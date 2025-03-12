/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#pragma once

#include <zmq.hpp>

#include "common.h"
#include "rmq_message.h"
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>
#include <string>
#include <vector>

class RMQClient
{
  public:
    RMQClient(const std::string &client_name, const std::string &server_endpoint);
    ~RMQClient();

    int get_topic_status(const std::string &topic, double timeout_s);
    // -1 if the server or topic does not exist: get no reply after timeout_s seconds
    // 0 if the topic exists but has no data
    // positive number means the number of data in the topic
    pybind11::tuple peek_data(const std::string &topic, std::string order, int32_t n);
    pybind11::tuple pop_data(const std::string &topic, std::string order, int32_t n);
    void put_data(const std::string &topic, const PyBytes &data);
    pybind11::tuple get_last_retrieved_data();
    PyBytes request_with_data(const std::string &topic, const PyBytes &data);

    double get_timestamp();
    void reset_start_time(int64_t system_time_us);

  private:
    std::vector<TimedPtr> deserialize_multiple_data_(const std::string &data);
    std::vector<TimedPtr> send_request_(RMQMessage &message);
    pybind11::tuple ptrs_to_tuple_(const std::vector<TimedPtr> &ptrs);
    std::string client_name_;
    std::shared_ptr<spdlog::logger> logger_;
    zmq::context_t context_;
    zmq::socket_t socket_;
    std::vector<TimedPtr> last_retrieved_ptrs_;
    int64_t steady_clock_start_time_us_;
};
