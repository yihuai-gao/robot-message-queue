/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "rmq_server.h"
#include <filesystem>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>
RMQServer::RMQServer(const std::string &server_name, const std::string &server_endpoint)
    : server_name_(server_name), context_(1), socket_(context_, zmq::socket_type::rep), running_(false),
      steady_clock_start_time_us_(steady_clock_us()), poller_timeout_ms_(1000)
{
    logger_ = spdlog::get(server_name);
    if (!logger_)
    {
        logger_ = spdlog::stdout_color_mt(server_name);
    }
    logger_->set_pattern("[%H:%M:%S %n %^%l%$] %v");

    // Only accept tcp and ipc endpoints
    if (server_endpoint.find("tcp://") != 0 && server_endpoint.find("ipc://") != 0)
    {
        throw std::invalid_argument("Server endpoint must start with tcp:// or ipc://");
    }
    if (server_endpoint.find("ipc://") == 0)
    {
        // Create the directory if it does not exist
        std::string directory = server_endpoint.substr(6, server_endpoint.find_last_of('/') - 6);
        if (!directory.empty())
        {
            std::filesystem::create_directories(directory);
        }
    }
    socket_.bind(server_endpoint);
    running_ = true;
    poller_item_ = {socket_, 0, ZMQ_POLLIN, 0};
    background_thread_ = std::thread(&RMQServer::background_loop_, this);
    data_topics_ = std::unordered_map<std::string, DataTopic>();
}

RMQServer::~RMQServer()
{
    running_ = false;
    background_thread_.join();
    socket_.close();
    context_.close();
}

void RMQServer::add_topic(const std::string &topic, double message_remaining_time_s)
{
    std::lock_guard<std::mutex> lock(data_topic_mutex_);
    auto it = data_topics_.find(topic);
    if (it != data_topics_.end())
    {
        logger_->warn("Topic `{}` already exists. Ignoring the request to add it again.", topic);
        return;
    }
    data_topics_.insert({topic, DataTopic(topic, message_remaining_time_s)});
    logger_->info("Added topic `{}` with max remaining time {}s.", topic, message_remaining_time_s);
}

void RMQServer::put_data(const std::string &topic, const PyBytes &data)
{
    if (data.equal(PyBytes("")))
    {
        throw std::invalid_argument("Cannot pass empty bytes string");
    }
    std::lock_guard<std::mutex> lock(data_topic_mutex_);
    auto it = data_topics_.find(topic);
    if (it == data_topics_.end())
    {
        logger_->warn(
            "Received data for unknown topic {}. Please first call add_topic to add it into the recorded topics.",
            topic);
        return;
    }
    PyBytesPtr data_ptr = std::make_shared<PyBytes>(data);

    it->second.add_data_ptr(data_ptr, get_timestamp());
}

pybind11::tuple RMQServer::peek_data(const std::string &topic, std::string order_str, int n)
{
    Order order = str_to_order(order_str);
    std::vector<TimedPtr> ptrs = peek_data_ptrs_(topic, order, n);
    pybind11::list data;
    pybind11::list timestamps;
    for (const TimedPtr ptr : ptrs)
    {
        data.append(*std::get<0>(ptr));
        timestamps.append(std::get<1>(ptr));
    }
    return pybind11::make_tuple(data, timestamps);
}

pybind11::tuple RMQServer::pop_data(const std::string &topic, std::string order_str, int n)
{
    Order order = str_to_order(order_str);
    std::vector<TimedPtr> ptrs = pop_data_ptrs_(topic, order, n);
    pybind11::list data;
    pybind11::list timestamps;
    for (const TimedPtr ptr : ptrs)
    {
        data.append(*std::get<0>(ptr));
        timestamps.append(std::get<1>(ptr));
    }
    return pybind11::make_tuple(data, timestamps);
}

pybind11::tuple RMQServer::wait_for_request(double timeout_s)
{
    double start_time = get_timestamp();
    if (timeout_s < 0)
    {
        timeout_s = std::numeric_limits<double>::max();
    }
    while (get_timestamp() - start_time < timeout_s)
    {
        std::this_thread::sleep_for(std::chrono::microseconds(100));
        {
            std::lock_guard<std::mutex> lock(get_new_request_mutex_);
            if (get_new_request_ != "")
            {
                std::string topic = get_new_request_;
                get_new_request_ = "";
                std::vector<TimedPtr> ptrs = pop_data_ptrs_(topic, Order::LATEST, -1);
                if (ptrs.size() == 0)
                {
                    logger_->error("Failed to pop data from topic {}. Please check if the topic is added.", topic);
                    return pybind11::make_tuple(PyBytes(), pybind11::str(topic));
                }
                else if (ptrs.size() > 1)
                {
                    logger_->error("Received more than one data from topic {}. Will only return the latest data.",
                                   topic);
                }
                // Clear the queue and return the latest data
                PyBytes data = *std::get<0>(ptrs[0]);
                ptrs.clear();
                return pybind11::make_tuple(data, pybind11::str(topic));
            }
        }
    }
    logger_->debug("Timeout when waiting for request ");
    return pybind11::make_tuple(pybind11::bytes(), pybind11::str(""));
}

void RMQServer::reply_request(const std::string &topic, const pybind11::bytes &data)
{
    put_data(topic, data);
    {
        std::lock_guard<std::mutex> lock(reply_mutex_);
        reply_topic_ = topic;
    }
}

std::unordered_map<std::string, int> RMQServer::get_all_topic_status()
{
    std::unordered_map<std::string, int> result;
    std::lock_guard<std::mutex> lock(data_topic_mutex_);
    for (auto &pair : data_topics_)
    {
        result[pair.first] = pair.second.size();
    }
    return result;
}

double RMQServer::get_timestamp()
{
    return static_cast<double>(steady_clock_us() - steady_clock_start_time_us_) / 1e6;
}

void RMQServer::reset_start_time(int64_t system_time_us)
{
    std::lock_guard<std::mutex> lock(data_topic_mutex_);
    logger_->info("Resetting start time. Will clear all data stored before this time");
    for (auto &pair : data_topics_)
    {
        pair.second.clear_data();
    }
    // Use system time to make sure different servers and clients are synchronized
    steady_clock_start_time_us_ = steady_clock_us() + (system_time_us - system_clock_us());
}

std::vector<TimedPtr> RMQServer::peek_data_ptrs_(const std::string &topic, Order order, int32_t n)
{
    std::lock_guard<std::mutex> lock(data_topic_mutex_);
    auto it = data_topics_.find(topic);
    if (it == data_topics_.end())
    {
        logger_->warn("Requested last k data for unknown topic {}. Please first call add_topic to add it into the "
                      "recorded topics.",
                      topic);
        return {};
    }
    return it->second.peek_data_ptrs(order, n);
}

void RMQServer::add_data_ptrs_(const std::string &topic, const std::vector<TimedPtr> &data_ptrs)
{
    std::lock_guard<std::mutex> lock(data_topic_mutex_);

    auto it = data_topics_.find(topic);
    if (it == data_topics_.end())
    {
        logger_->warn("Received data for unknown topic {}. Please first call add_topic to add it into the recorded "
                      "topics.",
                      topic);
        return;
    }
    for (const TimedPtr ptr : data_ptrs)
    {
        it->second.add_data_ptr(std::get<0>(ptr), std::get<1>(ptr));
    }
}

std::vector<TimedPtr> RMQServer::pop_data_ptrs_(const std::string &topic, Order order, int32_t n)
{
    std::lock_guard<std::mutex> lock(data_topic_mutex_);
    auto it = data_topics_.find(topic);
    if (it == data_topics_.end())
    {
        logger_->warn(
            "Requested data for unknown topic {}. Please first call add_topic to add it into the server topics.",
            topic);
        return {};
    }
    return it->second.pop_data_ptrs(order, n);
}

bool RMQServer::exists_topic_(const std::string &topic)
{
    std::lock_guard<std::mutex> lock(data_topic_mutex_);
    return data_topics_.find(topic) != data_topics_.end();
}

void RMQServer::process_request_(RMQMessage &message)
{
    // Check if the topic is already in the data_topics_
    if (!exists_topic_(message.topic()) && message.cmd() != CmdType::GET_TOPIC_STATUS)
    {
        std::string error_message =
            "Topic `" + message.topic() + "` not found. Please first call add_topic to add it into the server topics.";
        RMQMessage reply(message.topic(), CmdType::ERROR, Order::NONE, get_timestamp(), error_message);
        std::string reply_data = reply.serialize();
        logger_->error(error_message);
        socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
        return;
    }
    switch (message.cmd())
    {
    case CmdType::PEEK_DATA:
    case CmdType::POP_DATA: {
        std::string error_message = "";
        if (message.order() == Order::NONE)
        {
            error_message.append("Order type cannot be NONE for PEEK_DATA and POP_DATA commands. ");
        }
        if (message.data_str().length() != sizeof(int32_t))
        {
            error_message.append("Data length should be the same as an integer, but got ");
            error_message.append(std::to_string(message.data_str().length()));
            error_message.append(" bytes.");
        }
        if (!error_message.empty())
        {
            logger_->error(error_message);
            RMQMessage reply(message.topic(), CmdType::ERROR, Order::NONE, get_timestamp(), error_message);
            std::string reply_data = reply.serialize();
            socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
            break;
        }

        int32_t n = bytes_to_int32(message.data_str());
        std::vector<TimedPtr> ptrs = message.cmd() == CmdType::PEEK_DATA
                                         ? peek_data_ptrs_(message.topic(), message.order(), n)
                                         : pop_data_ptrs_(message.topic(), message.order(), n);
        RMQMessage reply(message.topic(), message.cmd(), message.order(), get_timestamp(), ptrs);
        std::string reply_data = reply.serialize();
        socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
        break;
    }

    case CmdType::REQUEST_WITH_DATA: {
        add_data_ptrs_(message.topic(), message.data_ptrs());
        {
            std::lock_guard<std::mutex> lock(get_new_request_mutex_);
            get_new_request_ = message.topic();
        }
        while (true)
        {
            std::this_thread::sleep_for(std::chrono::microseconds(100));
            {
                std::lock_guard<std::mutex> lock(reply_mutex_);
                if (reply_topic_ != "") // Wait until the request is processed by the main thread
                {
                    assert(reply_topic_ == message.topic());
                    reply_topic_ = "";
                    std::vector<TimedPtr> reply_ptrs = pop_data_ptrs_(message.topic(), Order::EARLIEST, -1);
                    RMQMessage reply(message.topic(), CmdType::REQUEST_WITH_DATA, Order::EARLIEST, get_timestamp(),
                                     reply_ptrs);
                    std::string reply_data = reply.serialize();
                    socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
                    break;
                }
            }
        }
        break;
    }

    case CmdType::PUT_DATA: {
        auto it = data_topics_.find(message.topic());
        if (it == data_topics_.end())
        {
            logger_->error("Received data for unknown topic {}. Please first call add_topic to add it into the "
                           "recorded topics.",
                           message.topic());
            RMQMessage reply(message.topic(), CmdType::ERROR, Order::NONE, get_timestamp(),
                             "Topic `" + message.topic() +
                                 "` not found. Please first call add_topic to add it into the "
                                 "recorded topics.");
            std::string reply_data = reply.serialize();
            socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
            break;
        }
        add_data_ptrs_(message.topic(), message.data_ptrs());
        std::vector<TimedPtr> reply_ptrs;
        RMQMessage reply(message.topic(), CmdType::PUT_DATA, Order::NONE, get_timestamp(), reply_ptrs);
        std::string reply_data = reply.serialize();
        socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
        break;
    }

    case CmdType::GET_TOPIC_STATUS: {
        auto it = data_topics_.find(message.topic());
        std::string status_str;
        if (it == data_topics_.end())
        {
            status_str = std::string("-1");
        }
        else
        {
            status_str = std::to_string(it->second.size());
        }
        RMQMessage reply(message.topic(), CmdType::GET_TOPIC_STATUS, Order::NONE, get_timestamp(), status_str);
        std::string reply_data = reply.serialize();
        socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
        break;
    }

    default: {
        std::string error_message = "Received unknown command: " + std::to_string(static_cast<int>(message.cmd()));
        logger_->error(error_message);
        RMQMessage reply(message.topic(), CmdType::ERROR, Order::NONE, get_timestamp(), error_message);
        std::string reply_data = reply.serialize();
        socket_.send(zmq::message_t(reply_data.data(), reply_data.size()), zmq::send_flags::none);
        break;
    }
    }
}

void RMQServer::background_loop_()
{
    while (running_)
    {

        zmq::poll(&poller_item_, 1, poller_timeout_ms_.count());

        zmq::message_t request;
        if (poller_item_.revents & ZMQ_POLLIN)
        {
            socket_.recv(request);
            RMQMessage message(std::string(request.data<char>(), request.data<char>() + request.size()));
            process_request_(message);
        }
    }
}
