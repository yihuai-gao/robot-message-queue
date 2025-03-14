/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "data_topic.h"

DataTopic::DataTopic(const std::string &topic_name, double message_remaining_time_s)
    : message_remaining_time_s_(message_remaining_time_s), topic_name_(topic_name)
{
    data_.clear();
}

void DataTopic::add_data_ptr(const PyBytesPtr data_ptr, double timestamp)
{
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
