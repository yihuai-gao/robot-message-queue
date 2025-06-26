/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#pragma once
#include <chrono>
#include <memory>
#include <pybind11/pybind11.h>
#include <string>
#include <tuple>
#include <vector>

#include <iomanip>
#include <sstream>
// using Bytes = pybind11::bytes;
// using BytesPtr = std::shared_ptr<pybind11::bytes>;
using Bytes = std::string;
using BytesPtr = std::shared_ptr<std::string>;
using TimedPtr = std::tuple<BytesPtr, double>;
int64_t steady_clock_us();
int64_t system_clock_us();

enum class Order : int8_t
{
    NONE = 0,
    EARLIEST = 1,
    LATEST = 2,
};

std::string uint32_to_bytes(uint32_t value);
uint32_t bytes_to_uint32(const std::string &bytes);
std::string int32_to_bytes(int32_t value);
int32_t bytes_to_int32(const std::string &bytes);
std::string double_to_bytes(double value);
double bytes_to_double(const std::string &bytes);
std::string bytes_to_hex(const std::string &bytes);
std::string order_to_str(Order order);
Order str_to_order(const std::string &order);

class SharedMemoryDataInfo
{
  public:
    SharedMemoryDataInfo(const std::string &server_name, const std::string &topic_name, uint64_t shm_size_bytes,
                         uint64_t shm_start_idx, uint64_t data_size_bytes);
    SharedMemoryDataInfo(const std::string &serialized_data_info);

    static bool is_shm_data_info(const std::string &serialized_data_info);

    std::string server_name() const;
    std::string topic_name() const;
    std::string shm_name() const;
    uint64_t shm_size_bytes() const;
    uint64_t shm_start_idx() const;
    uint64_t data_size_bytes() const;

    std::string serialize() const;

  private:
    static const std::string HEADER;
    std::string server_name_;
    std::string topic_name_;
    uint64_t shm_size_bytes_;
    uint64_t shm_start_idx_;
    uint64_t data_size_bytes_;
};