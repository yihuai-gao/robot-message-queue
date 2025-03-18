/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#pragma once

#include <zmq.hpp>

#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "common.h"
#include "data_topic.h"
#include "rmq_message.h"
#include "spdlog/spdlog.h"
class RMQServer
{
  public:
    RMQServer(const std::string &server_name, const std::string &server_endpoint);
    ~RMQServer();
    void add_topic(const std::string &topic, double message_remaining_time_s);
    void put_data(const std::string &topic, const Bytes &data);
    pybind11::tuple peek_data(const std::string &topic, std::string order_str, int n);
    pybind11::tuple pop_data(const std::string &topic, std::string order_str, int n);
    pybind11::tuple wait_for_request(double timeout_s);
    void reply_request(const std::string &topic, const Bytes &data);
    double get_timestamp();
    void reset_start_time(int64_t system_time_us);

    std::unordered_map<std::string, int> get_all_topic_status();

  private:
    const std::string server_name_;
    bool running_;
    int64_t steady_clock_start_time_us_;
    zmq::context_t context_;
    zmq::socket_t socket_;
    zmq::pollitem_t poller_item_;
    const std::chrono::milliseconds poller_timeout_ms_;
    std::thread background_thread_;
    std::mutex data_topic_mutex_;
    std::string get_new_request_ = "";
    std::mutex get_new_request_mutex_;
    std::string reply_topic_ = "";
    std::mutex reply_mutex_;

    std::unordered_map<std::string, DataTopic> data_topics_;
    std::shared_ptr<spdlog::logger> logger_;

    void process_request_(RMQMessage &message);

    std::vector<TimedPtr> peek_data_ptrs_(const std::string &topic, Order order, int32_t n);
    std::vector<TimedPtr> pop_data_ptrs_(const std::string &topic, Order order, int32_t n);
    void add_data_ptrs_(const std::string &topic, const std::vector<TimedPtr> &data_ptrs);
    bool exists_topic_(const std::string &topic);
    std::function<TimedPtr(const TimedPtr)> request_with_data_handler_;

    void background_loop_();
};
