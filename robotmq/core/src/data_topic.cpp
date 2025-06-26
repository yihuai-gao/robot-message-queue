/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "data_topic.h"
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

    shm_name_ = server_name + "_" + topic_name;

    // Remove shared memory if already exists
    if (shm_unlink(shm_name_.c_str()) == -1)
    {
        if (errno == ENOENT)
        {
        }
        else
        {
            perror("shm_unlink");
        }
    }

    // Create shared memory
    shm_size_ = shm_size_gb_ * 1024 * 1024 * 1024;
    occupied_shm_size_ = 0;
    int shm_fd = shm_open(shm_name_.c_str(), O_CREAT | O_RDWR, 0666);
    ftruncate(shm_fd, shm_size_);
    shm_ptr_ = mmap(0, shm_size_, PROT_WRITE, MAP_SHARED, shm_fd, 0);
}

void DataTopic::add_data_ptr(const BytesPtr data_ptr, double timestamp)
{
    if (is_shm_topic_)
    {
        occupied_shm_size_ += data_ptr->size();
    }
    data_.push_back({data_ptr, timestamp});
    while (!data_.empty() && timestamp - std::get<1>(data_.front()) > message_remaining_time_s_)
    {
        data_.pop_front();
    }
}

std::vector<TimedPtr> DataTopic::peek_data_ptrs(Order order, int32_t n)
{
    if (data_.empty())
    {
        return std::vector<TimedPtr>();
    }
    if (n < 0 || n > data_.size())
    {
        n = data_.size();
    }
    if (order == Order::LATEST)
    {
        std::vector<TimedPtr> result(data_.end() - n, data_.end());
        std::reverse(result.begin(), result.end());
        return result;
    }
    else if (order == Order::EARLIEST)
    {
        return std::vector<TimedPtr>(data_.begin(), data_.begin() + n);
    }
    else
    {
        throw std::runtime_error("Invalid end type");
    }
}

std::vector<TimedPtr> DataTopic::pop_data_ptrs(Order order, int32_t n)
{
    if (data_.empty())
    {
        return std::vector<TimedPtr>();
    }
    if (n < 0 || n > data_.size())
    {
        n = data_.size();
    }
    std::vector<TimedPtr> ret = peek_data_ptrs(order, n);

    if (order == Order::LATEST)
    {
        for (int i = 0; i < n; i++)
        {
            data_.pop_back();
        }
    }
    else if (order == Order::EARLIEST)
    {
        for (int i = 0; i < n; i++)
        {
            data_.pop_front();
        }
    }
    else
    {
        throw std::runtime_error("Invalid end type");
    }
    return ret;
}

void DataTopic::clear_data()
{
    data_.clear();
}

int DataTopic::size() const
{
    return data_.size();
}
