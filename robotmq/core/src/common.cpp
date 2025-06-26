/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "common.h"
#include <cstring>
#include <fcntl.h>
#include <sstream>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

int64_t steady_clock_us()
{
    return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}
int64_t system_clock_us()
{
    return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::system_clock::now().time_since_epoch())
        .count();
}

std::string uint32_to_bytes(uint32_t value)
{
    return std::string(reinterpret_cast<const char *>(&value), sizeof(uint32_t));
}

uint32_t bytes_to_uint32(const std::string &bytes)
{
    if (bytes.size() != sizeof(uint32_t))
    {
        throw std::invalid_argument("Input bytes must have the same size as an unsigned integer");
    }
    return *reinterpret_cast<const uint32_t *>(bytes.data());
}

std::string int32_to_bytes(int32_t value)
{
    return std::string(reinterpret_cast<const char *>(&value), sizeof(int32_t));
}

int32_t bytes_to_int32(const std::string &bytes)
{
    if (bytes.size() != sizeof(int32_t))
    {
        throw std::invalid_argument("Input bytes must have the same size as an integer");
    }
    return *reinterpret_cast<const int32_t *>(bytes.data());
}

std::string uint64_to_bytes(uint64_t value)
{
    return std::string(reinterpret_cast<const char *>(&value), sizeof(uint64_t));
}

uint64_t bytes_to_uint64(const std::string &bytes)
{
    if (bytes.size() != sizeof(uint64_t))
    {
        throw std::invalid_argument("Input bytes must have the same size as an unsigned integer");
    }
    return *reinterpret_cast<const uint64_t *>(bytes.data());
}
std::string double_to_bytes(double value)
{
    return std::string(reinterpret_cast<const char *>(&value), sizeof(double));
}

double bytes_to_double(const std::string &bytes)
{
    if (bytes.size() != sizeof(double))
    {
        throw std::invalid_argument("Input bytes must have the same size as a double");
    }
    return *reinterpret_cast<const double *>(bytes.data());
}

std::string bytes_to_hex(const std::string &bytes)
{
    std::ostringstream hex_stream;
    hex_stream << std::hex << std::setfill('0');
    for (unsigned char byte : bytes)
    {
        hex_stream << std::setw(2) << static_cast<int>(byte);
    }
    return hex_stream.str();
}

std::string order_to_str(Order order)
{
    if (order == Order::EARLIEST)
    {
        return "earliest";
    }
    else if (order == Order::LATEST)
    {
        return "latest";
    }
    throw std::invalid_argument("Invalid end type");
}

Order str_to_order(const std::string &order)
{
    if (order == "earliest" || order == "EARLIEST")
    {
        return Order::EARLIEST;
    }
    else if (order == "latest" || order == "LATEST")
    {
        return Order::LATEST;
    }
    throw std::invalid_argument("Invalid end type: " + order);
}

SharedMemoryDataInfo::SharedMemoryDataInfo(const std::string &server_name, const std::string &topic_name,
                                           uint64_t shm_size_bytes, uint64_t shm_start_idx, uint64_t data_size_bytes)
    : server_name_(server_name), topic_name_(topic_name), shm_size_bytes_(shm_size_bytes),
      shm_start_idx_(shm_start_idx), data_size_bytes_(data_size_bytes)
{
}

SharedMemoryDataInfo::SharedMemoryDataInfo(const std::string &serialized_data_info)
{
    uint64_t current_byte_idx = 0;
    if (serialized_data_info.substr(0, HEADER.size()) != HEADER)
    {
        throw std::invalid_argument("Invalid serialized data info: " + serialized_data_info);
    }
    current_byte_idx += HEADER.size();

    uint64_t server_name_size = bytes_to_uint64(serialized_data_info.substr(current_byte_idx, sizeof(uint64_t)));
    current_byte_idx += sizeof(uint64_t);

    uint64_t topic_name_size = bytes_to_uint64(serialized_data_info.substr(current_byte_idx, sizeof(uint64_t)));
    current_byte_idx += sizeof(uint64_t);

    server_name_ = serialized_data_info.substr(current_byte_idx, server_name_size);
    current_byte_idx += server_name_size;

    topic_name_ = serialized_data_info.substr(current_byte_idx, topic_name_size);
    current_byte_idx += topic_name_size;

    shm_size_bytes_ = bytes_to_uint64(serialized_data_info.substr(current_byte_idx, sizeof(uint64_t)));
    current_byte_idx += sizeof(uint64_t);

    shm_start_idx_ = bytes_to_uint64(serialized_data_info.substr(current_byte_idx, sizeof(uint64_t)));
    current_byte_idx += sizeof(uint64_t);

    data_size_bytes_ = bytes_to_uint64(serialized_data_info.substr(current_byte_idx, sizeof(uint64_t)));
    current_byte_idx += sizeof(uint64_t);

    if (current_byte_idx != serialized_data_info.size())
    {
        throw std::runtime_error("Shared memory data info is not complete");
    }
}

const std::string SharedMemoryDataInfo::HEADER = "\x0d\x0b";

bool SharedMemoryDataInfo::is_shm_data_info(const std::string &serialized_data_info)
{
    return serialized_data_info.substr(0, HEADER.size()) == HEADER;
}

std::string SharedMemoryDataInfo::serialize() const
{
    std::string serialized;
    serialized.append(HEADER);
    uint64_t server_name_size = server_name_.size();
    serialized.append(uint64_to_bytes(server_name_size));
    uint64_t topic_name_size = topic_name_.size();
    serialized.append(uint64_to_bytes(topic_name_size));
    serialized.append(server_name_);
    serialized.append(topic_name_);
    serialized.append(uint64_to_bytes(shm_size_bytes_));
    serialized.append(uint64_to_bytes(shm_start_idx_));
    serialized.append(uint64_to_bytes(data_size_bytes_));
    return serialized;
}

std::string SharedMemoryDataInfo::shm_name() const
{
    return server_name_ + "_" + topic_name_;
}

std::string SharedMemoryDataInfo::server_name() const
{
    return server_name_;
}

std::string SharedMemoryDataInfo::topic_name() const
{
    return topic_name_;
}

uint64_t SharedMemoryDataInfo::shm_size_bytes() const
{
    return shm_size_bytes_;
}

uint64_t SharedMemoryDataInfo::shm_start_idx() const
{
    return shm_start_idx_;
}

uint64_t SharedMemoryDataInfo::data_size_bytes() const
{
    return data_size_bytes_;
}
