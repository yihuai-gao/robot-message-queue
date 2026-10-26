/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "rmq_client.h"
#include "common.h"
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <pthread.h>
#include <random>
#include <sstream>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace
{
// The random token in a segment name: 8 bytes rendered as 16 lowercase hex characters.
constexpr size_t SEGMENT_TOKEN_BYTES = 8;
// How many names are tried when the token collides before the exchange gives up.
constexpr int MAX_NAME_ATTEMPTS = 16;

// A shared memory segment this client writes for one exchange with the server. Its name carries a random token and
// it is created with O_EXCL, so a client in another PID namespace that shares /dev/shm (same user, pid, client name
// and topic) can never truncate or unlink this client's segment. It is unlinked when it goes out of scope, also when
// the exchange throws, so a failed request leaves nothing behind in /dev/shm.
class OwnedSegment
{
  public:
    // The segment is named <base_name>_<16 lowercase hex characters><suffix>; a taken name gets a fresh token.
    OwnedSegment(const std::string &base_name, const char *suffix, const char *data, size_t length)
    {
        std::random_device random_device;
        std::string token(SEGMENT_TOKEN_BYTES, '\0');
        for (int attempt = 0; attempt < MAX_NAME_ATTEMPTS && fd_ == -1; attempt++)
        {
            for (char &byte : token)
            {
                byte = static_cast<char>(random_device() & 0xFF);
            }
            name_ = base_name + "_" + bytes_to_hex(token) + suffix;
            fd_ = shm_open(name_.c_str(), O_CREAT | O_EXCL | O_RDWR, 0666);
            if (fd_ == -1 && errno != EEXIST)
            {
                throw std::runtime_error("Failed to create shared memory /dev/shm/" + name_ + ": " + strerror(errno));
            }
        }
        if (fd_ == -1)
        {
            throw std::runtime_error("Failed to create shared memory /dev/shm/" + name_ + ": the name was taken " +
                                     std::to_string(MAX_NAME_ATTEMPTS) + " times in a row");
        }
        // posix_fallocate reserves the pages, so a full /dev/shm is an error here instead of a SIGBUS in memcpy.
        int fallocate_error = posix_fallocate(fd_, 0, length);
        if (fallocate_error != 0)
        {
            release_();
            throw std::runtime_error("Failed to reserve " + std::to_string(length) + " bytes of shared memory /dev/shm/" +
                                     name_ + ": " + strerror(fallocate_error));
        }
        void *ptr = mmap(0, length, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, 0);
        if (ptr == MAP_FAILED)
        {
            std::string reason = strerror(errno);
            release_();
            throw std::runtime_error("Failed to map shared memory /dev/shm/" + name_ + ": " + reason);
        }
        memcpy(ptr, data, length);
        munmap(ptr, length);
    }
    ~OwnedSegment()
    {
        release_();
    }
    OwnedSegment(const OwnedSegment &) = delete;
    OwnedSegment &operator=(const OwnedSegment &) = delete;
    const std::string &name() const
    {
        return name_;
    }

  private:
    void release_()
    {
        if (fd_ != -1)
        {
            close(fd_);
            fd_ = -1;
            shm_unlink(name_.c_str());
        }
    }
    std::string name_;
    int fd_ = -1;
};

constexpr size_t PROBE_BYTES = 16;
static_assert(PROBE_BYTES <= SHM_MAX_PROBE_BYTES, "the server reads back at most SHM_MAX_PROBE_BYTES");

// Thrown by RMQClient::exchange_ when the server did not reply in time, as opposed to a socket error or a malformed
// reply. It stays a std::runtime_error so pybind11 keeps mapping it to a Python RuntimeError.
struct NoReplyError : std::runtime_error
{
    using std::runtime_error::runtime_error;
};
} // namespace

RMQClient::RMQClient(const std::string &client_name, const std::string &server_endpoint)
    : RMQClient(client_name, server_endpoint, spdlog::level::info)
{
}

RMQClient::RMQClient(const std::string &client_name, const std::string &server_endpoint, spdlog::level::level_enum log_level)
    : client_name_(client_name), context_(1), socket_(context_, zmq::socket_type::req),
      steady_clock_start_time_us_(steady_clock_us()), last_retrieved_ptrs_()
{
    logger_ = spdlog::get(client_name);
    if (!logger_)
    {
        logger_ = spdlog::stdout_color_mt(client_name);
    }
    logger_->set_level(log_level);
    logger_->set_pattern("[%H:%M:%S %n %^%l%$] %v");
    int linger_value = 100;
    socket_.setsockopt(ZMQ_LINGER, &linger_value, sizeof(linger_value));
    socket_.connect(server_endpoint);
}

RMQClient::~RMQClient()
{
    socket_.close();
    context_.close();
}

int RMQClient::get_topic_status(const std::string &topic, double timeout_s)
{
    RMQMessage message(topic, CmdType::GET_TOPIC_STATUS, get_timestamp(), "Get topic status");

    std::string serialized = message.serialize();
    zmq::message_t request(serialized.data(), serialized.size());
    socket_.send(request, zmq::send_flags::none);

    zmq::pollitem_t items[] = {{socket_, 0, ZMQ_POLLIN, 0}};
    if (timeout_s >= 0)
    {
        zmq::poll(&items[0], 1, timeout_s * 1000);
    }
    else
    {
        // Wait forever until the server is connected
        zmq::poll(&items[0], 1, default_timeout_s_ * 1000000);
    }
    if (items[0].revents & ZMQ_POLLIN)
    {
        zmq::message_t reply;
        socket_.recv(reply);
        RMQMessage reply_message(std::string(reply.data<char>(), reply.data<char>() + reply.size()));
        if (reply_message.cmd() == CmdType::GET_TOPIC_STATUS)
        {
            std::string data_str = reply_message.data_str();
            int32_t size = bytes_to_int32(data_str.substr(0, 4));
            if (data_str.size() == 8)
            {
                topic_using_shared_memory_[topic] = bytes_to_int32(data_str.substr(4, 4));
            }
            return size;
        }
        else if (reply_message.cmd() == CmdType::ERROR)
        {
            throw std::runtime_error("Server returned error: " + reply_message.data_str());
        }
        else
        {
            throw std::runtime_error(
                "Invalid command type: " + std::to_string(static_cast<int>(reply_message.cmd())) +
                " for get_topic_status on topic: " + topic);
        }
    }

    std::string endpoint = socket_.get(zmq::sockopt::last_endpoint);
    socket_.close();
    socket_ = zmq::socket_t(context_, zmq::socket_type::req);
    int linger_value = 100;
    socket_.setsockopt(ZMQ_LINGER, &linger_value, sizeof(linger_value));
    socket_.connect(endpoint);
    retries_++;
    if (retries_ > MAX_RETRIES_)
    {
        throw std::runtime_error("No reply from server after " + std::to_string(MAX_RETRIES_) + " retries. " +
                                    "Please check whether the server is running.");
    }

    logger_->warn("Not connected to server after {} retries. Retrying...", retries_);
    return -2;
}

pybind11::tuple RMQClient::peek_data(const std::string &topic, int32_t n, double timeout_s, bool automatic_resend)
{
    std::string data_str = int32_to_bytes(n);
    RMQMessage message(topic, CmdType::PEEK_DATA, get_timestamp(), data_str);
    std::vector<TimedPtr> reply_ptrs = send_request_(message, timeout_s, automatic_resend);
    if (reply_ptrs.empty())
    {
        logger_->debug("No data available for topic: {}", topic);
    }
    return ptrs_to_tuple_(reply_ptrs);
}

pybind11::tuple RMQClient::pop_data(const std::string &topic, int32_t n, double timeout_s, bool automatic_resend)
{
    std::string data_str = int32_to_bytes(n);
    RMQMessage message(topic, CmdType::POP_DATA, get_timestamp(), data_str);
    std::vector<TimedPtr> reply_ptrs = send_request_(message, timeout_s, automatic_resend);
    if (reply_ptrs.empty())
    {
        logger_->debug("No data available for topic: {}", topic);
    }
    return ptrs_to_tuple_(reply_ptrs);
}

void RMQClient::put_data(const std::string &topic, const pybind11::bytes &data, double timeout_s, bool automatic_resend)
{
    if (pybind11::len(data) == 0)
    {
        throw std::invalid_argument("Cannot pass empty bytes string");
    }
    std::vector<TimedPtr> timed_ptrs;
    BytesPtr data_ptr = std::make_shared<Bytes>(data);
    TimedPtr timed_ptr = std::make_tuple(data_ptr, get_timestamp());
    timed_ptrs.push_back(timed_ptr);
    RMQMessage message(topic, CmdType::PUT_DATA, get_timestamp(), timed_ptrs);
    std::vector<TimedPtr> reply_ptrs = send_request_(message, timeout_s, automatic_resend);
}

pybind11::bytes RMQClient::request_with_data(const std::string &topic, const pybind11::bytes &data, double timeout_s, bool automatic_resend)
{
    if (pybind11::len(data) == 0)
    {
        throw std::invalid_argument("Cannot pass empty bytes string");
    }

    auto shm_status = topic_using_shared_memory_.find(topic);
    if (shm_status == topic_using_shared_memory_.end())
    {
        get_topic_status(topic, timeout_s);
        // Still absent when the status call got no reply or the topic does not exist.
        shm_status = topic_using_shared_memory_.find(topic);
    }
    bool use_shared_memory = shm_status != topic_using_shared_memory_.end() && shm_status->second;
    double timestamp = get_timestamp();
    std::vector<TimedPtr> reply_ptrs;

    if (use_shared_memory)
    {
        // Extract the raw bytes and size from py::bytes
        char *new_data_buffer;
        ssize_t length;
        PYBIND11_BYTES_AS_STRING_AND_SIZE(data.ptr(), &new_data_buffer, &length);

        const std::string request_base_name =
            "rmq_" + get_user_name() + "_" + get_pid() + "_" + client_name_ + "_" + topic;
        OwnedSegment request_segment(request_base_name, "_request", new_data_buffer, length); // unlinked on every exit
        SharedMemoryDataInfo data_info(request_segment.name(), length, 0, length);
        BytesPtr data_ptr = std::make_shared<Bytes>(data_info.serialize());

        TimedPtr timed_ptr = std::make_tuple(data_ptr, timestamp);
        std::vector<TimedPtr> timed_ptrs;
        timed_ptrs.push_back(timed_ptr);

        RMQMessage message(topic, CmdType::REQUEST_WITH_DATA, get_timestamp(), timed_ptrs);
        reply_ptrs = send_request_(message, timeout_s, automatic_resend);
    }

    else
    {
        std::vector<TimedPtr> timed_ptrs;
        BytesPtr data_ptr = std::make_shared<Bytes>(data);
        TimedPtr timed_ptr = std::make_tuple(data_ptr, timestamp);
        timed_ptrs.push_back(timed_ptr);

        RMQMessage message(topic, CmdType::REQUEST_WITH_DATA, get_timestamp(), timed_ptrs);
        reply_ptrs = send_request_(message, timeout_s, automatic_resend);
    }

    if (reply_ptrs.empty())
    {
        logger_->error("No response from server for request with data on topic: {}", topic);
    }
    if (reply_ptrs.size() != 1)
    {
        throw std::runtime_error("Expected 1 reply pointer, but received " + std::to_string(reply_ptrs.size()));
    }
    BytesPtr reply_data_ptr = std::get<0>(reply_ptrs[0]);
    if (SharedMemoryDataInfo::is_shm_data_info(*reply_data_ptr))
    {
        SharedMemoryDataInfo data_info(*reply_data_ptr);
        return data_info.get_shm_data_with_mutex();
    }
    else
    {
        return pybind11::bytes(*reply_data_ptr);
    }
}

pybind11::tuple RMQClient::get_last_retrieved_data()
{
    return ptrs_to_tuple_(last_retrieved_ptrs_);
}

pybind11::tuple RMQClient::ptrs_to_tuple_(const std::vector<TimedPtr> &ptrs)
{
    pybind11::list data;
    pybind11::list timestamps;
    for (const TimedPtr ptr : ptrs)
    {
        if (SharedMemoryDataInfo::is_shm_data_info(*std::get<0>(ptr)))
        {
            SharedMemoryDataInfo data_info(*std::get<0>(ptr));
            data.append(data_info.get_shm_data_with_mutex());
        }
        else
        {
            data.append(pybind11::bytes(*std::get<0>(ptr)));
        }
        timestamps.append(std::get<1>(ptr));
    }
    return pybind11::make_tuple(data, timestamps);
}

double RMQClient::get_timestamp()
{
    return static_cast<double>(steady_clock_us() - steady_clock_start_time_us_) / 1e6;
}

void RMQClient::reset_start_time(int64_t system_time_us)
{
    logger_->info("Resetting start time. Will clear all data retrieved before this time");
    last_retrieved_ptrs_.clear();
    steady_clock_start_time_us_ = steady_clock_us() + (system_time_us - system_clock_us());
}

std::tuple<bool, std::string> RMQClient::check_shared_memory(const std::string &topic, double timeout_s)
{
    // A negative timeout would poll forever, which this method must never do: it answers (false, reason) instead.
    if (timeout_s < 0)
    {
        std::ostringstream reason;
        reason << "timeout_s must be non-negative, got " << timeout_s;
        return {false, reason.str()};
    }

    // 1. The server's direction: write a random probe and let the server read it back.
    std::random_device random_device;
    std::string nonce(PROBE_BYTES, '\0');
    for (char &byte : nonce)
    {
        byte = static_cast<char>(random_device() & 0xFF);
    }
    const std::string probe_base_name = "rmq_" + get_user_name() + "_" + get_pid() + "_" + client_name_ + "_" + topic;
    std::unique_ptr<OwnedSegment> probe;
    try
    {
        probe = std::make_unique<OwnedSegment>(probe_base_name, SHM_PROBE_SUFFIX, nonce.data(), nonce.size());
    }
    catch (const std::exception &e)
    {
        return {false, std::string("this client cannot create shared memory: ") + e.what()};
    }
    // The generated name outlives the probe: the messages below still name it after probe.reset().
    const std::string probe_name = probe->name();
    RMQMessage message(topic, CmdType::CHECK_SHARED_MEMORY, get_timestamp(),
                       SharedMemoryDataInfo(probe_name, nonce.size(), 0, nonce.size()).serialize());
    std::unique_ptr<RMQMessage> reply;
    try
    {
        reply = std::make_unique<RMQMessage>(exchange_(message, timeout_s, false));
    }
    catch (const NoReplyError &)
    {
        std::ostringstream reason;
        reason << "no reply from the server within " << timeout_s << " s";
        return {false, reason.str()};
    }
    catch (const std::exception &e)
    {
        return {false, std::string("the exchange with the server failed: ") + e.what()};
    }
    probe.reset();

    if (reply->cmd() == CmdType::ERROR)
    {
        std::string text = reply->data_str();
        if (text.rfind("Received unknown command", 0) == 0)
        {
            return {false, "the server's robotmq does not support check_shared_memory (it predates it): " + text};
        }
        if (text.rfind("Topic `", 0) == 0 && text.find("not found") != std::string::npos)
        {
            return {false, "`" + topic + "` is not a topic of the server"};
        }
        return {false, "the server returned an error: " + text};
    }
    if (reply->cmd() != CmdType::CHECK_SHARED_MEMORY)
    {
        return {false, "unexpected reply command " + std::to_string(static_cast<int>(reply->cmd()))};
    }
    int32_t status;
    uint64_t device, inode, size;
    std::string echo, segment_name, error;
    try
    {
        std::string payload = reply->data_str();
        constexpr size_t fixed_size = sizeof(int32_t) + 3 * sizeof(uint64_t);
        if (payload.size() < fixed_size)
        {
            throw std::invalid_argument("payload of " + std::to_string(payload.size()) + " bytes");
        }
        status = bytes_to_int32(payload.substr(0, sizeof(int32_t)));
        size_t pos = sizeof(int32_t);
        device = bytes_to_uint64(payload.substr(pos, sizeof(uint64_t)));
        inode = bytes_to_uint64(payload.substr(pos + sizeof(uint64_t), sizeof(uint64_t)));
        size = bytes_to_uint64(payload.substr(pos + 2 * sizeof(uint64_t), sizeof(uint64_t)));
        pos = fixed_size;
        echo = read_length_prefixed(payload, pos);
        segment_name = read_length_prefixed(payload, pos);
        error = read_length_prefixed(payload, pos);
    }
    catch (const std::exception &e)
    {
        return {false, std::string("malformed check_shared_memory reply: ") + e.what()};
    }
    if (status == 1)
    {
        return {false, "`" + topic + "` is not a shared memory topic on the server"};
    }
    if (status == 2)
    {
        return {false, "the server cannot read this client's shared memory (" + error +
                           "): the client and the server must share /dev/shm (the same host and IPC namespace), and "
                           "the server's user must be allowed to open this client's segments"};
    }
    if (status != 0)
    {
        return {false, "unknown check_shared_memory status " + std::to_string(status)};
    }
    if (echo != nonce)
    {
        return {false, "the server read a different /dev/shm/" + probe_name +
                           " than this client wrote: the client and the server do not share /dev/shm"};
    }

    // 2. The reply direction: this client must open the server's segment (read) and its mutex (read-write).
    int segment_fd = shm_open(segment_name.c_str(), O_RDONLY, 0);
    if (segment_fd == -1)
    {
        return {false, "this client cannot open the server's shared memory segment /dev/shm/" + segment_name + " (" +
                           strerror(errno) + ")"};
    }
    struct stat segment_stat;
    int stat_result = fstat(segment_fd, &segment_stat);
    int stat_errno = errno;
    close(segment_fd);
    if (stat_result == -1)
    {
        return {false, "this client cannot stat the server's shared memory segment /dev/shm/" + segment_name + " (" +
                           strerror(stat_errno) + ")"};
    }
    if (static_cast<uint64_t>(segment_stat.st_dev) != device || static_cast<uint64_t>(segment_stat.st_ino) != inode)
    {
        return {false, "/dev/shm/" + segment_name +
                           " on this client is not the server's segment: the client and the server do not share /dev/shm"};
    }
    if (static_cast<uint64_t>(segment_stat.st_size) < size)
    {
        return {false, "the server's shared memory segment /dev/shm/" + segment_name + " holds " +
                           std::to_string(segment_stat.st_size) + " bytes, fewer than its " + std::to_string(size)};
    }
    const std::string mutex_name = segment_name + "_mutex";
    int mutex_fd = shm_open(mutex_name.c_str(), O_RDWR, 0);
    if (mutex_fd == -1)
    {
        return {false, "this client cannot open the server's shared memory mutex /dev/shm/" + mutex_name + " (" +
                           strerror(errno) + ")"};
    }
    void *mutex_ptr = mmap(0, sizeof(pthread_mutex_t), PROT_READ | PROT_WRITE, MAP_SHARED, mutex_fd, 0);
    int map_errno = errno;
    close(mutex_fd);
    if (mutex_ptr == MAP_FAILED)
    {
        return {false, "this client cannot open the server's shared memory mutex /dev/shm/" + mutex_name +
                           " for writing (" + strerror(map_errno) + ")"};
    }
    munmap(mutex_ptr, sizeof(pthread_mutex_t));
    return {true, ""};
}

std::vector<TimedPtr> RMQClient::send_request_(RMQMessage &message, double timeout_s, bool automatic_resend)
{
    RMQMessage reply_message = exchange_(message, timeout_s, automatic_resend);
    if (reply_message.cmd() == CmdType::ERROR)
    {
        throw std::runtime_error("Server returned error: " + reply_message.data_str());
    }
    if (reply_message.cmd() != message.cmd())
    {
        throw std::runtime_error("Command type mismatch. Sent " + std::to_string(static_cast<int>(message.cmd())) +
                                 " but received " + std::to_string(static_cast<int>(reply_message.cmd())));
    }
    if (reply_message.topic() != message.topic())
    {
        throw std::runtime_error("Topic mismatch. Sent " + message.topic() + " but received " + reply_message.topic());
    }
    if (reply_message.cmd() == CmdType::PEEK_DATA || reply_message.cmd() == CmdType::POP_DATA ||
        reply_message.cmd() == CmdType::REQUEST_WITH_DATA || reply_message.cmd() == CmdType::PUT_DATA)
    {
        last_retrieved_ptrs_ = reply_message.data_ptrs();
        return reply_message.data_ptrs();
    }
    throw std::runtime_error("Invalid command type: " + std::to_string(static_cast<int>(reply_message.cmd())));
}

RMQMessage RMQClient::exchange_(RMQMessage &message, double timeout_s, bool automatic_resend)
{
    std::string serialized = message.serialize();
    zmq::message_t reply;

    // After a send, a REQ socket accepts nothing but the reply (every later send fails with EFSM), so whenever a
    // request is given up on, the socket is replaced by a fresh one connected to the same endpoint.
    auto recreate_socket = [this]()
    {
        std::string endpoint = socket_.get(zmq::sockopt::last_endpoint);
        socket_.close();
        socket_ = zmq::socket_t(context_, zmq::socket_type::req);
        int linger_value = 100;
        socket_.setsockopt(ZMQ_LINGER, &linger_value, sizeof(linger_value));
        socket_.connect(endpoint);
    };

    while (true)
    {
        zmq::message_t request(serialized.data(), serialized.size());
        socket_.send(request, zmq::send_flags::none);
        zmq::pollitem_t items[] = {{socket_, 0, ZMQ_POLLIN, 0}};
        int timeout_ms = timeout_s * 1000;
        try
        {
            zmq::poll(&items[0], 1, timeout_ms);
        }
        catch (const zmq::error_t &)
        {
            // zmq::poll throws on EINTR, e.g. when a Python signal handler interrupted the syscall. The request is
            // abandoned, so the socket must not stay in the awaiting-reply state.
            recreate_socket();
            throw;
        }
        if (items[0].revents & ZMQ_POLLIN)
        {
            socket_.recv(reply);
            break;
        }
        recreate_socket();
        if (!automatic_resend)
        {
            throw NoReplyError(
                "No reply from server. To automatically resend the request, please set automatic_resend to true.");
        }
        if (retries_ > MAX_RETRIES_)
        {
            throw NoReplyError("No reply from server after " + std::to_string(MAX_RETRIES_) + " retries");
        }
        retries_++;
        logger_->warn("No reply in timeout_s={} seconds after {} retries. If the message is too large, please increase the "
                      "timeout. Retrying...", timeout_s, retries_);
    }

    return RMQMessage(std::string(reply.data<char>(), reply.data<char>() + reply.size()));
}
