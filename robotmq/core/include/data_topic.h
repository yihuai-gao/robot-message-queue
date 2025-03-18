/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#pragma once
#include "common.h"
#include <deque>
#include <string>
#include <vector>
class DataTopic
{
  public:
    DataTopic(const std::string &topic_name, double message_remaining_time_s);

    void add_data_ptr(const BytesPtr data_ptr, double timestamp);

    std::vector<TimedPtr> peek_data_ptrs(Order order, int32_t n);
    std::vector<TimedPtr> pop_data_ptrs(Order order, int32_t n);

    void clear_data();
    int size() const;

  private:
    std::string topic_name_;
    double message_remaining_time_s_;
    std::deque<TimedPtr> data_;
};