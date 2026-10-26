/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#pragma once
#include "common.h"
#include <deque>
#include <optional>
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

    // Stores data in the topic's shared memory ring. Data larger than the whole segment is refused: it throws
    // std::invalid_argument (ValueError in Python) and stores nothing.
    void copy_data_to_shm(const pybind11::bytes &data, double timestamp);
    pybind11::bytes get_shared_memory_data(const SharedMemoryDataInfo &shm_data_info);
    // The bytes of one queue entry, whatever its form: inline bytes, a descriptor of this topic's segment, or a
    // descriptor of a client's request segment.
    pybind11::bytes read_entry(const BytesPtr &entry);
    bool is_shm_topic() const;
    void delete_shm();

    // Identity of this topic's segment, for clients that check they can open it (RMQClient::check_shared_memory).
    std::string shm_name() const;
    uint64_t shm_size_bytes() const;
    uint64_t shm_device() const;
    uint64_t shm_inode() const;

  private:
    std::string topic_name_;
    double message_remaining_time_s_;
    std::deque<TimedPtr> data_;

    std::string get_shm_name_() const;
    std::string get_shm_mutex_name_() const;
    // `entry` parsed as a shared memory descriptor, or nullopt when it is inline bytes: on a plain topic, data a
    // client put over zmq, or bytes that merely start like a descriptor (including one with a malformed name).
    std::optional<SharedMemoryDataInfo> parse_descriptor_(const BytesPtr &entry) const;
    // Whether `info` describes bytes inside this topic's own ring: its segment, its exact size, and a start and a
    // data size within it. A forged descriptor of the segment fails this and is never read through.
    bool is_own_descriptor_(const SharedMemoryDataInfo &info) const;
    // Bytes an entry occupies in this topic's ring: 0 for inline data and for descriptors of other segments.
    uint64_t own_shm_bytes_(const BytesPtr &entry) const;
    void pop_front_entry_();
    void pop_back_entry_();
    void evict_expired_(double timestamp);

    // Shared memory related
    std::string server_name_;
    // The segment and mutex names, computed once in the constructor: they need the user name and the pid, which
    // are system calls, and every entry of the queue is matched against them. Empty on a plain topic.
    std::string shm_name_cache_;
    std::string shm_mutex_name_cache_;
    uint64_t shm_size_;
    uint64_t occupied_shm_size_;
    uint64_t current_shm_offset_;
    bool is_shm_topic_;
    double shm_size_gb_;
    void *shm_ptr_;
    int shm_fd_;
    pthread_mutex_t *shm_mutex_ptr_;
    int shm_mutex_fd_;
    uint64_t shm_device_;
    uint64_t shm_inode_;
};
