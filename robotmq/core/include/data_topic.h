/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#pragma once
#include "common.h"
#include <deque>
#include <pthread.h>
#include <string>
#include <vector>
class DataTopic
{
  public:
    DataTopic(const std::string &topic_name, double message_remaining_time_s);

    DataTopic(const std::string &topic_name, double message_remaining_time_s, const std::string server_name,
              double shared_memory_size_gb);

    void add_data_ptr(const BytesPtr data_ptr, double timestamp);

    std::vector<TimedPtr> peek_data_ptrs(int32_t n);
    std::vector<TimedPtr> pop_data_ptrs(int32_t n);

    void clear_data();
    int size() const;

    void copy_data_to_shm(const pybind11::bytes &data, double timestamp);
    pybind11::bytes get_shared_memory_data(const SharedMemoryDataInfo &shm_data_info);
    bool is_shm_topic() const;
    void delete_shm();

  private:
    std::string topic_name_;
    double message_remaining_time_s_;
    std::deque<TimedPtr> data_;

    // Shared memory related
    std::string server_name_;
    uint64_t shm_size_;
    uint64_t occupied_shm_size_;
    uint64_t current_shm_offset_;
    bool is_shm_topic_;
    double shm_size_gb_;
    void *shm_ptr_;
    int shm_fd_;
    pthread_mutex_t *shm_mutex_ptr_;
    int shm_mutex_fd_;
};