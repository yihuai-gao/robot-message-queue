#pragma once
#include "common.h"
#include <deque>
#include <string>
#include <vector>
class DataTopic
{
  public:
    DataTopic(const std::string &topic_name, double max_remaining_time);

    void add_data_ptr(const PyBytesPtr data_ptr, double timestamp);

    std::vector<TimedPtr> peek_data_ptrs(EndType end_type, int32_t n);
    std::vector<TimedPtr> pop_data_ptrs(EndType end_type, int32_t n);

    void clear_data();
    int size() const;

  private:
    std::string topic_name_;
    double max_remaining_time_;
    std::deque<TimedPtr> data_;
};