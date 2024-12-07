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
    void add_topic(const std::string &topic, double max_remaining_time);
    void put_data(const std::string &topic, const PyBytes &data);
    pybind11::tuple peek_data(const std::string &topic, std::string end_type_str, int n);
    pybind11::tuple pop_data(const std::string &topic, std::string end_type_str, int n);
    pybind11::tuple wait_for_request(const std::string &topic, double timeout);
    void reply_request(const std::string &topic, const pybind11::list &data);
    double get_timestamp();
    void reset_start_time(int64_t system_time_us);

    // void set_request_with_data_handler(std::function<PyBytes(const PyBytes)> handler);
    std::unordered_map<std::string, int> get_topic_status();

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
    bool get_new_request_ = false;
    std::mutex get_new_request_mutex_;
    bool reply_ready_ = false;
    std::mutex reply_ready_mutex_;

    std::unordered_map<std::string, DataTopic> data_topics_;
    std::shared_ptr<spdlog::logger> logger_;

    void process_request_(RMQMessage &message);

    std::vector<TimedPtr> peek_data_ptrs_(const std::string &topic, EndType end_type, int32_t n);
    std::vector<TimedPtr> pop_data_ptrs_(const std::string &topic, EndType end_type, int32_t n);
    void add_data_ptrs_(const std::string &topic, const std::vector<TimedPtr> &data_ptrs);
    std::function<TimedPtr(const TimedPtr)> request_with_data_handler_;

    void background_loop_();
};
