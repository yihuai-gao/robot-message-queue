/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "rmq_client.h"

RMQClient::RMQClient(const std::string &client_name, const std::string &server_endpoint)
    : context_(1), socket_(context_, zmq::socket_type::req), steady_clock_start_time_us_(steady_clock_us()),
      last_retrieved_ptrs_()
{
    logger_ = spdlog::get(client_name);
    if (!logger_)
    {
        logger_ = spdlog::stdout_color_mt(client_name);
    }
    logger_->set_pattern("[%H:%M:%S %n %^%l%$] %v");
    socket_.connect(server_endpoint);
}

RMQClient::~RMQClient()
{
    socket_.close();
    context_.close();
}

int RMQClient::get_topic_status(const std::string &topic, double timeout_s)
{
    RMQMessage message(topic, CmdType::GET_TOPIC_STATUS, Order::NONE, get_timestamp(), "");
    std::string serialized = message.serialize();
    zmq::message_t request(serialized.data(), serialized.size());
    socket_.send(request, zmq::send_flags::none);

    zmq::pollitem_t items[] = {{socket_, 0, ZMQ_POLLIN, 0}};
    zmq::poll(&items[0], 1, timeout_s * 1000);
    if (items[0].revents & ZMQ_POLLIN)
    {
        zmq::message_t reply;
        socket_.recv(reply);
        RMQMessage reply_message(std::string(reply.data<char>(), reply.data<char>() + reply.size()));
        if (reply_message.cmd() == CmdType::GET_TOPIC_STATUS)
        {
            return std::stoi(reply_message.data_str());
        }
        else if (reply_message.cmd() == CmdType::ERROR)
        {
            throw std::runtime_error("Server returned error: " + reply_message.data_str());
        }
        else
        {
            throw std::runtime_error("Invalid command type: " + std::to_string(static_cast<int>(reply_message.cmd())) +
                                     " for get_topic_status on topic: " + topic);
        }
    }

    std::string endpoint = socket_.get(zmq::sockopt::last_endpoint);
    socket_.close();
    socket_ = zmq::socket_t(context_, zmq::socket_type::req);
    socket_.connect(endpoint);

    return -2;
}

pybind11::tuple RMQClient::peek_data(const std::string &topic, std::string order, int32_t n)
{
    std::string data_str = int32_to_bytes(n);
    RMQMessage message(topic, CmdType::PEEK_DATA, str_to_order(order), get_timestamp(), data_str);
    std::vector<TimedPtr> reply_ptrs = send_request_(message);
    if (reply_ptrs.empty())
    {
        logger_->debug("No data available for topic: {}", topic);
    }
    return ptrs_to_tuple_(reply_ptrs);
}

pybind11::tuple RMQClient::pop_data(const std::string &topic, std::string order, int32_t n)
{
    std::string data_str = int32_to_bytes(n);
    RMQMessage message(topic, CmdType::POP_DATA, str_to_order(order), get_timestamp(), data_str);
    std::vector<TimedPtr> reply_ptrs = send_request_(message);
    if (reply_ptrs.empty())
    {
        logger_->debug("No data available for topic: {}", topic);
    }
    return ptrs_to_tuple_(reply_ptrs);
}

void RMQClient::put_data(const std::string &topic, const Bytes &data)
{
    if (data.empty())
    {
        throw std::invalid_argument("Cannot pass empty bytes string");
    }
    std::vector<TimedPtr> timed_ptrs;
    BytesPtr data_ptr = std::make_shared<Bytes>(data);
    TimedPtr timed_ptr = std::make_tuple(data_ptr, get_timestamp());
    timed_ptrs.push_back(timed_ptr);
    RMQMessage message(topic, CmdType::PUT_DATA, Order::NONE, get_timestamp(), timed_ptrs);
    std::vector<TimedPtr> reply_ptrs = send_request_(message);
}

pybind11::bytes RMQClient::request_with_data(const std::string &topic, const Bytes &data)
{
    if (data.empty())
    {
        throw std::invalid_argument("Cannot pass empty bytes string");
    }
    std::vector<TimedPtr> timed_ptrs;

    BytesPtr data_ptr = std::make_shared<Bytes>(data);
    TimedPtr timed_ptr = std::make_tuple(data_ptr, get_timestamp());
    timed_ptrs.push_back(timed_ptr);

    RMQMessage message(topic, CmdType::REQUEST_WITH_DATA, Order::NONE, get_timestamp(), timed_ptrs);
    std::vector<TimedPtr> reply_ptrs = send_request_(message);
    if (reply_ptrs.empty())
    {
        logger_->error("No response from server for request with data on topic: {}", topic);
    }
    if (reply_ptrs.size() != 1)
    {
        throw std::runtime_error("Expected 1 reply pointer, but received " + std::to_string(reply_ptrs.size()));
    }
    BytesPtr reply_data_ptr = std::get<0>(reply_ptrs[0]);
    return pybind11::bytes(*reply_data_ptr);
}

pybind11::tuple RMQClient::get_last_retrieved_data()
{
    return ptrs_to_tuple_(last_retrieved_ptrs_);
}

pybind11::tuple RMQClient::ptrs_to_tuple_(const std::vector<TimedPtr> &ptrs)
{
    pybind11::list data;
    pybind11::list timestamps;
    for (const TimedPtr ptr : ptrs)
    {
        data.append(pybind11::bytes(*std::get<0>(ptr)));
        timestamps.append(std::get<1>(ptr));
    }
    return pybind11::make_tuple(data, timestamps);
}

double RMQClient::get_timestamp()
{
    return static_cast<double>(steady_clock_us() - steady_clock_start_time_us_) / 1e6;
}

void RMQClient::reset_start_time(int64_t system_time_us)
{
    logger_->info("Resetting start time. Will clear all data retrieved before this time");
    last_retrieved_ptrs_.clear();
    steady_clock_start_time_us_ = steady_clock_us() + (system_time_us - system_clock_us());
}

std::vector<TimedPtr> RMQClient::send_request_(RMQMessage &message)
{
    std::string serialized = message.serialize();
    zmq::message_t request(serialized.data(), serialized.size());
    socket_.send(request, zmq::send_flags::none);
    zmq::message_t reply;
    socket_.recv(reply);
    RMQMessage reply_message(std::string(reply.data<char>(), reply.data<char>() + reply.size()));
    if (reply_message.cmd() == CmdType::ERROR)
    {
        throw std::runtime_error("Server returned error: " + reply_message.data_str());
    }
    if (reply_message.cmd() != message.cmd())
    {
        throw std::runtime_error("Command type mismatch. Sent " + std::to_string(static_cast<int>(message.cmd())) +
                                 " but received " + std::to_string(static_cast<int>(reply_message.cmd())));
    }
    if (reply_message.topic() != message.topic())
    {
        throw std::runtime_error("Topic mismatch. Sent " + message.topic() + " but received " + reply_message.topic());
    }
    if (reply_message.cmd() == CmdType::PEEK_DATA || reply_message.cmd() == CmdType::POP_DATA ||
        reply_message.cmd() == CmdType::REQUEST_WITH_DATA || reply_message.cmd() == CmdType::PUT_DATA)
    {
        last_retrieved_ptrs_ = reply_message.data_ptrs();
        return reply_message.data_ptrs();
    }
    throw std::runtime_error("Invalid command type: " + std::to_string(static_cast<int>(reply_message.cmd())));
}
