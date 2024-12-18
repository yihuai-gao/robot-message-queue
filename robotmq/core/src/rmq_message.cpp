/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "rmq_message.h"

RMQMessage::RMQMessage(const std::string &topic, CmdType cmd, Order order, double timestamp,
                       const std::vector<TimedPtr> &data_ptrs)
    : topic_(topic), cmd_(cmd), order_(order), timestamp_(timestamp), data_ptrs_(data_ptrs)
{
    check_input_validity_();
}

RMQMessage::RMQMessage(const std::string &topic, CmdType cmd, Order order, double timestamp,
                       const std::string &data_str)
    : topic_(topic), cmd_(cmd), order_(order), timestamp_(timestamp), data_str_(data_str)
{
    check_input_validity_();
}

RMQMessage::RMQMessage(const std::string &serialized)
{
    uint8_t topic_length = static_cast<uint8_t>(serialized[0]);
    if (serialized.size() < sizeof(uint8_t) + topic_length)
    {
        throw std::invalid_argument("Serialized message is too short");
    }
    int decode_start_index = sizeof(uint8_t);
    topic_ =
        std::string(serialized.begin() + decode_start_index, serialized.begin() + decode_start_index + topic_length);
    decode_start_index += topic_length;
    cmd_ = static_cast<CmdType>(serialized[decode_start_index]);
    decode_start_index += sizeof(CmdType);
    order_ = static_cast<Order>(serialized[decode_start_index]);
    decode_start_index += sizeof(Order);
    timestamp_ = bytes_to_double(
        std::string(serialized.begin() + decode_start_index, serialized.begin() + decode_start_index + sizeof(double)));
    decode_start_index += sizeof(double);
    data_str_ = std::string(serialized.begin() + decode_start_index, serialized.end());
}

std::string RMQMessage::topic() const
{
    return topic_;
}

CmdType RMQMessage::cmd() const
{
    return cmd_;
}

Order RMQMessage::order() const
{
    return order_;
}

double RMQMessage::timestamp() const
{
    return timestamp_;
}

std::vector<TimedPtr> RMQMessage::data_ptrs()
{
    if (data_ptrs_.empty())
    {
        if (data_str_.empty())
        {
            throw std::runtime_error("Data is empty");
        }

        decode_data_blocks_();
    }
    return data_ptrs_;
}

std::string RMQMessage::data_str()
{
    if (data_str_.empty())
    {
        encode_data_blocks_();
    }
    return data_str_;
}

std::string RMQMessage::serialize()
{
    std::string serialized;
    serialized.push_back(static_cast<char>(uint8_t(topic_.size())));
    serialized.append(topic_);
    serialized.push_back(static_cast<char>(cmd_));
    serialized.push_back(static_cast<char>(order_));
    serialized.append(double_to_bytes(timestamp_));
    serialized.append(data_str());
    return serialized;
}

void RMQMessage::encode_data_blocks_()
{
    uint32_t data_string_length = sizeof(uint32_t); // block_num
    uint32_t block_num = data_ptrs_.size();
    std::vector<uint32_t> data_lengths;
    std::vector<double> timestamps;
    for (const auto &data_ptr : data_ptrs_)
    {
        int data_length = pybind11::len(*std::get<0>(data_ptr));
        data_string_length += data_length + sizeof(uint32_t) + sizeof(double);
        data_lengths.push_back(data_length);
        timestamps.push_back(std::get<1>(data_ptr));
    }
    data_str_.clear();
    data_str_.reserve(data_string_length);
    data_str_.append(uint32_to_bytes(block_num));
    for (int i = 0; i < block_num; ++i)
    {
        data_str_.append(uint32_to_bytes(data_lengths[i]));
        data_str_.append(double_to_bytes(timestamps[i]));
    }
    int data_start_index = 1 + block_num;
    for (const auto &data_ptr : data_ptrs_)
    {
        std::string data_block_str = *std::get<0>(data_ptr);
        data_str_.append(data_block_str);
    }
    assert(data_str_.size() == data_string_length);
}

void RMQMessage::decode_data_blocks_()
{
    if (data_str_.size() < sizeof(uint32_t))
    {
        throw std::invalid_argument("Data string is too short");
    }
    data_ptrs_.clear();
    uint32_t block_num = bytes_to_uint32(std::string(data_str_.data(), sizeof(uint32_t)));
    int index_size = sizeof(uint32_t) + sizeof(double);
    int data_start_index = (1 + block_num) * sizeof(uint32_t) + block_num * sizeof(double);
    // printf("decode_data_blocks: %s\n", bytes_to_hex(data_str_).c_str());
    for (int i = 0; i < block_num; ++i)
    {
        std::string data_length_str(data_str_.data() + sizeof(uint32_t) + i * index_size, sizeof(uint32_t));

        uint32_t data_length = bytes_to_uint32(data_length_str);
        if (data_start_index + data_length > data_str_.size())
        {
            throw std::invalid_argument("Data block length invalid. Please check the data string");
        }
        if (data_length < 0)
        {
            throw std::invalid_argument("Data block length must be non-negative");
        }
        std::string data_timestamp_str(data_str_.data() + 2 * sizeof(uint32_t) + i * index_size, sizeof(double));
        double timestamp = bytes_to_double(data_timestamp_str);
        if (data_length == 0)
        {
            data_ptrs_.push_back(std::make_tuple(std::make_shared<PyBytes>(PyBytes("")), timestamp));
            continue;
        }
        data_ptrs_.push_back(std::make_tuple(
            std::make_shared<PyBytes>(PyBytes(data_str_.data() + data_start_index, data_length)), timestamp));
        data_start_index += data_length;
    }
}

void RMQMessage::check_input_validity_()
{
    if (topic_.size() > 255)
    {
        throw std::invalid_argument("Topic size must be less than 256 characters");
    }
    if (topic_.empty())
    {
        throw std::invalid_argument("Topic cannot be empty");
    }
    for (const auto &data_ptr : data_ptrs_)
    {
        if (std::get<0>(data_ptr) == nullptr)
        {
            throw std::invalid_argument("Data cannot be null. To pass empty data, use a pointer to an empty string.");
        }
    }
}
