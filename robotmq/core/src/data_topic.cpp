/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "data_topic.h"
#include "common.h"
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
DataTopic::DataTopic(const std::string &topic_name, double message_remaining_time_s)
    : message_remaining_time_s_(message_remaining_time_s), topic_name_(topic_name), is_shm_topic_(false),
      shm_size_gb_(0)
{
    data_.clear();
}

DataTopic::DataTopic(const std::string &topic_name, double message_remaining_time_s, const std::string server_name,
                     double shared_memory_size_gb)
    : message_remaining_time_s_(message_remaining_time_s), topic_name_(topic_name), server_name_(server_name),
      is_shm_topic_(true), shm_size_gb_(shared_memory_size_gb)
{
    data_.clear();

    shm_size_ = shm_size_gb_ * 1024 * 1024 * 1024;
    occupied_shm_size_ = 0;
    current_shm_offset_ = 0;

    // Remove existing shared memory and mutex

    char *user_name = getlogin();
    if (user_name == nullptr)
    {
        throw std::runtime_error("Failed to get user_name.");
    }

    shm_fd_ = shm_open(get_shm_name_().c_str(), O_CREAT | O_RDWR, 0666);
    if (shm_fd_ == -1)
    {
        std::string full_shm_path = "/dev/shm/" + get_shm_name_();
        throw std::runtime_error("Failed to create shared memory at " + full_shm_path +
                                 ". Please check if the user has permission to create shared memory.");
    }
    ftruncate(shm_fd_, shm_size_);
    shm_ptr_ = mmap(0, shm_size_, PROT_WRITE, MAP_SHARED, shm_fd_, 0);

    // Create shared memory mutex
    shm_mutex_fd_ = shm_open(get_shm_mutex_name_().c_str(), O_CREAT | O_RDWR, 0666);
    if (shm_mutex_fd_ == -1)
    {
        std::string full_shm_mutex_path = "/dev/shm/" + get_shm_mutex_name_();
        throw std::runtime_error("Failed to create shared memory mutex at " + full_shm_mutex_path +
                                 ". Please check if the user has permission to create shared memory mutex.");
    }
    ftruncate(shm_mutex_fd_, sizeof(pthread_mutex_t));
    shm_mutex_ptr_ = (pthread_mutex_t *)mmap(0, sizeof(pthread_mutex_t), PROT_WRITE, MAP_SHARED, shm_mutex_fd_, 0);

    pthread_mutexattr_t attr;
    pthread_mutexattr_init(&attr);
    pthread_mutexattr_setpshared(&attr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(shm_mutex_ptr_, &attr);
}

std::string DataTopic::get_shm_name_() const
{
    return "rmq_" + std::string(getlogin()) + "_" + server_name_ + "_" + topic_name_;
}

std::string DataTopic::get_shm_mutex_name_() const
{
    return "rmq_" + std::string(getlogin()) + "_" + server_name_ + "_" + topic_name_ + "_mutex";
}

void DataTopic::copy_data_to_shm(const pybind11::bytes &data, double timestamp)
{

    // Extract the raw bytes and size from py::bytes
    char *new_data_buffer;
    ssize_t length;
    // This gives you a pointer to the underlying buffer and the size
    PYBIND11_BYTES_AS_STRING_AND_SIZE(data.ptr(), &new_data_buffer, &length);

    // Store the original data into shared memory and the shm_data_info into data_
    int64_t data_size = length;
    if (data_size > shm_size_)
    {
        printf("Data size %ld is larger than shared memory size %ld. New data will be ignored\n", data_size, shm_size_);
        return;
    }
    BytesPtr info_ptr = std::make_shared<Bytes>(
        SharedMemoryDataInfo(get_shm_name_(), shm_size_, current_shm_offset_, data_size).serialize());
    data_.push_back({info_ptr, timestamp});
    occupied_shm_size_ += data_size;
    while (occupied_shm_size_ > shm_size_)
    {
        BytesPtr old_info_ptr = std::get<0>(data_.front());
        SharedMemoryDataInfo old_info(*old_info_ptr);
        if (old_info.shm_name() == get_shm_name_())
            occupied_shm_size_ -= old_info.data_size_bytes();
        data_.pop_front();
    }

    // Copy data to shared memory: 76MB takes 0.02s

    pthread_mutex_lock(shm_mutex_ptr_);
    if (current_shm_offset_ + data_size > shm_size_)
    {
        uint64_t shm_remaining_size = shm_size_ - current_shm_offset_;
        memcpy(shm_ptr_ + current_shm_offset_, new_data_buffer, shm_remaining_size);
        current_shm_offset_ = data_size - shm_remaining_size;
        memcpy(shm_ptr_, new_data_buffer + shm_remaining_size, current_shm_offset_);
    }
    else
    {
        memcpy(shm_ptr_ + current_shm_offset_, new_data_buffer, data_size);
        current_shm_offset_ += data_size;
    }
    pthread_mutex_unlock(shm_mutex_ptr_);

    while (!data_.empty() && timestamp - std::get<1>(data_.front()) > message_remaining_time_s_)
    {
        BytesPtr old_info_ptr = std::get<0>(data_.front());
        SharedMemoryDataInfo old_info(*old_info_ptr);
        if (old_info.shm_name() == get_shm_name_())
            occupied_shm_size_ -= old_info.data_size_bytes();
        data_.pop_front();
    }
}

void DataTopic::add_data_ptr(const BytesPtr data_ptr, double timestamp)
{
    data_.push_back({data_ptr, timestamp});
    while (!data_.empty() && timestamp - std::get<1>(data_.front()) > message_remaining_time_s_)
    {
        data_.pop_front();
    }
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
            if (is_shm_topic_)
            {
                BytesPtr old_info_ptr = std::get<0>(data_.back());
                SharedMemoryDataInfo old_info(*old_info_ptr);
                if (old_info.shm_name() == get_shm_name_())
                    occupied_shm_size_ -= old_info.data_size_bytes();
            }
            data_.pop_back();
        }
    }
    else // n > 0
    {
        for (int i = 0; i < n; i++)
        {
            if (is_shm_topic_)
            {
                BytesPtr old_info_ptr = std::get<0>(data_.front());
                SharedMemoryDataInfo old_info(*old_info_ptr);
                if (old_info.shm_name() == get_shm_name_())
                    occupied_shm_size_ -= old_info.data_size_bytes();
            }
            data_.pop_front();
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

bool DataTopic::is_shm_topic() const
{
    return is_shm_topic_;
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