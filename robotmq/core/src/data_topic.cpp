/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "data_topic.h"
#include "common.h"
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
DataTopic::DataTopic(const std::string &topic_name, double message_remaining_time_s)
    : message_remaining_time_s_(message_remaining_time_s), topic_name_(topic_name), shm_size_(0),
      occupied_shm_size_(0), current_shm_offset_(0), is_shm_topic_(false), shm_size_gb_(0), shm_ptr_(nullptr),
      shm_fd_(-1), shm_mutex_ptr_(nullptr), shm_mutex_fd_(-1), shm_device_(0), shm_inode_(0)
{
    data_.clear();
}

DataTopic::DataTopic(const std::string &topic_name, double message_remaining_time_s, const std::string server_name,
                     double shared_memory_size_gb)
    : message_remaining_time_s_(message_remaining_time_s), topic_name_(topic_name), server_name_(server_name),
      is_shm_topic_(true), shm_size_gb_(shared_memory_size_gb), shm_ptr_(nullptr), shm_fd_(-1),
      shm_mutex_ptr_(nullptr), shm_mutex_fd_(-1), shm_device_(0), shm_inode_(0)
{
    data_.clear();

    if (!(shared_memory_size_gb > 0))
    {
        throw std::invalid_argument("shared_memory_size_gb of topic `" + topic_name +
                                    "` must be positive, got " + std::to_string(shared_memory_size_gb));
    }
    shm_size_ = static_cast<uint64_t>(shm_size_gb_ * 1024 * 1024 * 1024);
    occupied_shm_size_ = 0;
    current_shm_offset_ = 0;
    shm_name_cache_ = "rmq_" + get_user_name() + "_" + get_pid() + "_" + server_name_ + "_" + topic_name_;
    shm_mutex_name_cache_ = shm_name_cache_ + "_mutex";

    const std::string full_shm_path = "/dev/shm/" + get_shm_name_();
    shm_fd_ = shm_open(get_shm_name_().c_str(), O_CREAT | O_RDWR, 0666);
    if (shm_fd_ == -1)
    {
        throw std::runtime_error("Failed to create shared memory at " + full_shm_path +
                                 ". Please check if the user has permission to create shared memory.");
    }
    if (ftruncate(shm_fd_, shm_size_) == -1)
    {
        std::string reason = strerror(errno);
        close(shm_fd_);
        shm_unlink(get_shm_name_().c_str());
        throw std::runtime_error("Failed to size the shared memory at " + full_shm_path + " to " +
                                 std::to_string(shm_size_) + " bytes: " + reason);
    }
    shm_ptr_ = mmap(0, shm_size_, PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd_, 0);
    if (shm_ptr_ == MAP_FAILED)
    {
        std::string reason = strerror(errno);
        close(shm_fd_);
        shm_unlink(get_shm_name_().c_str());
        throw std::runtime_error("Failed to map the shared memory at " + full_shm_path + ": " + reason);
    }
    struct stat shm_stat;
    if (fstat(shm_fd_, &shm_stat) == 0)
    {
        shm_device_ = static_cast<uint64_t>(shm_stat.st_dev);
        shm_inode_ = static_cast<uint64_t>(shm_stat.st_ino);
    }

    // Create shared memory mutex. When that fails, the data segment created above (and the mutex segment once it
    // exists) is released as well, so a topic that is never constructed leaves no mapping, fd or /dev/shm file.
    auto release_segments = [this](bool mutex_created)
    {
        if (mutex_created)
        {
            close(shm_mutex_fd_);
            shm_unlink(get_shm_mutex_name_().c_str());
        }
        munmap(shm_ptr_, shm_size_);
        close(shm_fd_);
        shm_unlink(get_shm_name_().c_str());
    };
    const std::string full_shm_mutex_path = "/dev/shm/" + get_shm_mutex_name_();
    shm_mutex_fd_ = shm_open(get_shm_mutex_name_().c_str(), O_CREAT | O_RDWR, 0666);
    if (shm_mutex_fd_ == -1)
    {
        release_segments(false);
        throw std::runtime_error("Failed to create shared memory mutex at " + full_shm_mutex_path +
                                 ". Please check if the user has permission to create shared memory mutex.");
    }
    if (ftruncate(shm_mutex_fd_, sizeof(pthread_mutex_t)) == -1)
    {
        std::string reason = strerror(errno);
        release_segments(true);
        throw std::runtime_error("Failed to size the shared memory mutex at " + full_shm_mutex_path + ": " + reason);
    }
    shm_mutex_ptr_ = (pthread_mutex_t *)mmap(0, sizeof(pthread_mutex_t), PROT_READ | PROT_WRITE, MAP_SHARED,
                                             shm_mutex_fd_, 0);
    if (shm_mutex_ptr_ == MAP_FAILED)
    {
        std::string reason = strerror(errno);
        release_segments(true);
        throw std::runtime_error("Failed to map the shared memory mutex at " + full_shm_mutex_path + ": " + reason);
    }

    pthread_mutexattr_t attr;
    pthread_mutexattr_init(&attr);
    pthread_mutexattr_setpshared(&attr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(shm_mutex_ptr_, &attr);
}

std::string DataTopic::get_shm_name_() const
{
    return shm_name_cache_;
}

std::string DataTopic::get_shm_mutex_name_() const
{
    return shm_mutex_name_cache_;
}

std::optional<SharedMemoryDataInfo> DataTopic::parse_descriptor_(const BytesPtr &entry) const
{
    if (!is_shm_topic_ || !SharedMemoryDataInfo::is_shm_data_info(*entry))
    {
        return std::nullopt;
    }
    try
    {
        return SharedMemoryDataInfo(*entry);
    }
    catch (const std::exception &)
    {
        return std::nullopt; // inline bytes that merely start like a descriptor
    }
}

bool DataTopic::is_own_descriptor_(const SharedMemoryDataInfo &info) const
{
    return is_shm_topic_ && info.shm_name() == shm_name_cache_ && info.shm_size_bytes() == shm_size_ &&
           info.shm_start_idx() <= shm_size_ && info.data_size_bytes() <= shm_size_;
}

uint64_t DataTopic::own_shm_bytes_(const BytesPtr &entry) const
{
    std::optional<SharedMemoryDataInfo> info = parse_descriptor_(entry);
    return info && is_own_descriptor_(*info) ? info->data_size_bytes() : 0;
}

void DataTopic::pop_front_entry_()
{
    uint64_t own_bytes = own_shm_bytes_(std::get<0>(data_.front()));
    occupied_shm_size_ -= std::min(own_bytes, occupied_shm_size_);
    data_.pop_front();
}

void DataTopic::pop_back_entry_()
{
    std::optional<SharedMemoryDataInfo> info = parse_descriptor_(std::get<0>(data_.back()));
    if (info && is_own_descriptor_(*info))
    {
        occupied_shm_size_ -= std::min(info->data_size_bytes(), occupied_shm_size_);
        // The newest entry ends where the next write would begin, so the write offset moves back to its start.
        // Left where it was, the next write would skip the freed bytes and wrap onto live entries.
        current_shm_offset_ = info->shm_start_idx();
    }
    data_.pop_back();
}

void DataTopic::evict_expired_(double timestamp)
{
    while (!data_.empty() && timestamp - std::get<1>(data_.front()) > message_remaining_time_s_)
    {
        pop_front_entry_();
    }
}

void DataTopic::copy_data_to_shm(const pybind11::bytes &data, double timestamp)
{

    // Extract the raw bytes and size from py::bytes
    char *new_data_buffer;
    ssize_t length;
    // This gives you a pointer to the underlying buffer and the size
    PYBIND11_BYTES_AS_STRING_AND_SIZE(data.ptr(), &new_data_buffer, &length);

    uint64_t data_size = static_cast<uint64_t>(length);
    if (data_size > shm_size_)
    {
        // Refused before anything is stored: the ring can never hold it, and sending it another way would hide a
        // topic sized too small for its data.
        throw std::invalid_argument("Data of " + std::to_string(data_size) + " bytes does not fit the " +
                                    std::to_string(shm_size_) + "-byte shared memory segment of topic `" +
                                    topic_name_ +
                                    "`: give add_shared_memory_topic a larger shared_memory_size_gb or use a plain "
                                    "topic (add_topic) for data this large.");
    }
    // Store the original data into shared memory and the shm_data_info into data_
    BytesPtr info_ptr = std::make_shared<Bytes>(
        SharedMemoryDataInfo(get_shm_name_(), shm_size_, current_shm_offset_, data_size).serialize());
    data_.push_back({info_ptr, timestamp});
    occupied_shm_size_ += data_size;
    while (occupied_shm_size_ > shm_size_ && !data_.empty())
    {
        pop_front_entry_();
    }

    // Copy data to shared memory: 76MB takes 0.02s

    pthread_mutex_lock(shm_mutex_ptr_);
    if (current_shm_offset_ + data_size > shm_size_)
    {
        uint64_t shm_remaining_size = shm_size_ - current_shm_offset_;
        memcpy(static_cast<char *>(shm_ptr_) + current_shm_offset_, new_data_buffer, shm_remaining_size);
        current_shm_offset_ = data_size - shm_remaining_size;
        memcpy(shm_ptr_, new_data_buffer + shm_remaining_size, current_shm_offset_);
    }
    else
    {
        memcpy(static_cast<char *>(shm_ptr_) + current_shm_offset_, new_data_buffer, data_size);
        current_shm_offset_ += data_size;
    }
    pthread_mutex_unlock(shm_mutex_ptr_);

    evict_expired_(timestamp);
}

void DataTopic::add_data_ptr(const BytesPtr data_ptr, double timestamp)
{
    data_.push_back({data_ptr, timestamp});
    evict_expired_(timestamp);
}

std::vector<TimedPtr> DataTopic::peek_data_ptrs(int32_t n)
{
    if (data_.empty())
    {
        return std::vector<TimedPtr>();
    }
    if (n == 0)
    {
        n = data_.size();
    }
    if (n < 0)
    {
        if (n < -data_.size())
        {
            n = -data_.size();
        }
        std::vector<TimedPtr> result(data_.end() + n, data_.end());
        return result;
    }
    else // n > 0
    {
        if (n > data_.size())
        {
            n = data_.size();
        }
        return std::vector<TimedPtr>(data_.begin(), data_.begin() + n);
    }
}

std::vector<TimedPtr> DataTopic::pop_data_ptrs(int32_t n)
{
    if (data_.empty())
    {
        return std::vector<TimedPtr>();
    }
    if (n == 0)
    {
        n = data_.size();
    }
    else if (n > data_.size())
    {
        n = data_.size();
    }
    else if (n < -data_.size())
    {
        n = -data_.size();
    }
    std::vector<TimedPtr> ret = peek_data_ptrs(n);

    if (n < 0)
    {
        n = -n;
        for (int i = 0; i < n; i++)
        {
            pop_back_entry_();
        }
    }
    else // n > 0
    {
        for (int i = 0; i < n; i++)
        {
            pop_front_entry_();
        }
    }
    return ret;
}

void DataTopic::clear_data()
{
    data_.clear();
    if (is_shm_topic_)
    {
        occupied_shm_size_ = 0;
        current_shm_offset_ = 0;
    }
}

int DataTopic::size() const
{
    return data_.size();
}

pybind11::bytes DataTopic::get_shared_memory_data(const SharedMemoryDataInfo &shm_data_info)
{
    // read_entry only passes descriptors that is_own_descriptor_ accepted; this guards any other caller, since a
    // start past the ring would wrap the first-part length below and copy from far outside the mapping.
    if (shm_data_info.shm_start_idx() > shm_size_ || shm_data_info.data_size_bytes() > shm_size_)
    {
        throw std::out_of_range("Shared memory descriptor of topic `" + topic_name_ + "` lies outside its " +
                                std::to_string(shm_size_) + "-byte ring (start " +
                                std::to_string(shm_data_info.shm_start_idx()) + ", data " +
                                std::to_string(shm_data_info.data_size_bytes()) + " bytes)");
    }
    pybind11::bytes data;
    pthread_mutex_lock(shm_mutex_ptr_);
    if (shm_data_info.shm_start_idx() + shm_data_info.data_size_bytes() > shm_size_)
    {
        char *a = reinterpret_cast<char *>(shm_ptr_) + shm_data_info.shm_start_idx();
        size_t a_len = shm_size_ - shm_data_info.shm_start_idx();
        char *b = reinterpret_cast<char *>(shm_ptr_);
        size_t b_len = shm_data_info.data_size_bytes() - a_len;
        data = concat_to_pybytes(a, a_len, b, b_len);
    }
    else
    {
        data = pybind11::bytes(reinterpret_cast<char *>(shm_ptr_) + shm_data_info.shm_start_idx(),
                               shm_data_info.data_size_bytes());
    }
    pthread_mutex_unlock(shm_mutex_ptr_);
    return data;
}

pybind11::bytes DataTopic::read_entry(const BytesPtr &entry)
{
    std::optional<SharedMemoryDataInfo> info = parse_descriptor_(entry);
    if (!info)
    {
        return pybind11::bytes(*entry); // inline bytes
    }
    if (is_own_descriptor_(*info))
    {
        return get_shared_memory_data(*info);
    }
    if (info->shm_name() != shm_name_cache_)
    {
        return info->get_shm_data(); // a client's request segment; when it cannot be read, that is an error
    }
    // A descriptor of this topic's segment that does not fit its ring (a forged or corrupted entry) is never read
    // through; its bytes are handed back as they are.
    return pybind11::bytes(*entry);
}

bool DataTopic::is_shm_topic() const
{
    return is_shm_topic_;
}

std::string DataTopic::shm_name() const
{
    return is_shm_topic_ ? get_shm_name_() : "";
}

uint64_t DataTopic::shm_size_bytes() const
{
    return shm_size_;
}

uint64_t DataTopic::shm_device() const
{
    return shm_device_;
}

uint64_t DataTopic::shm_inode() const
{
    return shm_inode_;
}

void DataTopic::delete_shm()
{
    if (is_shm_topic_)
    {
        printf("deleting shared memory: %s\n", get_shm_name_().c_str());
        munmap(shm_ptr_, shm_size_);
        munmap(shm_mutex_ptr_, sizeof(pthread_mutex_t));
        shm_unlink(get_shm_name_().c_str());
        shm_unlink(get_shm_mutex_name_().c_str());
        close(shm_fd_);
        close(shm_mutex_fd_);
    }
}
