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
        throw std::invalid_argument("Input bytes must have the same size as a 32-bit unsigned integer, but got " +
                                    std::to_string(bytes.size()));
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
        throw std::invalid_argument("Input bytes must have the same size as a 32-bit integer, but got " +
                                    std::to_string(bytes.size()));
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
        throw std::invalid_argument("Input bytes must have the same size as a 64-bit unsigned integer, but got " +
                                    std::to_string(bytes.size()));
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
        throw std::invalid_argument("Input bytes must have the same size as a double, but got " +
                                    std::to_string(bytes.size()));
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

SharedMemoryDataInfo::SharedMemoryDataInfo(const std::string &shm_name, uint64_t shm_size_bytes, uint64_t shm_start_idx,
                                           uint64_t data_size_bytes)
    : shm_name_(shm_name), shm_size_bytes_(shm_size_bytes), shm_start_idx_(shm_start_idx),
      data_size_bytes_(data_size_bytes)
{
}

SharedMemoryDataInfo::SharedMemoryDataInfo(const std::string &serialized_data_info)
{
    uint64_t current_byte_idx = 0;
    if (serialized_data_info.substr(0, HEADER.size()) != HEADER)
    {
        printf("serialized_data_info: %s, HEADER: %s\n", serialized_data_info.c_str(), HEADER.c_str());
        printf("result: %d\n", serialized_data_info.substr(0, HEADER.size()) == HEADER);
        throw std::invalid_argument("Invalid serialized data info (beginning doesn't match with HEADER)");
    }
    current_byte_idx += HEADER.size();

    uint64_t shm_name_size = bytes_to_uint64(serialized_data_info.substr(current_byte_idx, sizeof(uint64_t)));
    current_byte_idx += sizeof(uint64_t);

    shm_name_ = serialized_data_info.substr(current_byte_idx, shm_name_size);
    current_byte_idx += shm_name_size;

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

const std::string SharedMemoryDataInfo::HEADER = "\x0d\x0a\x0d\x0b";

bool SharedMemoryDataInfo::is_shm_data_info(const std::string &serialized_data_info)
{
    return serialized_data_info.substr(0, HEADER.size()) == HEADER;
}

std::string SharedMemoryDataInfo::serialize() const
{
    std::string serialized;
    serialized.append(HEADER);
    serialized.append(uint64_to_bytes(shm_name_.size()));
    serialized.append(shm_name_);
    serialized.append(uint64_to_bytes(shm_size_bytes_));
    serialized.append(uint64_to_bytes(shm_start_idx_));
    serialized.append(uint64_to_bytes(data_size_bytes_));
    return serialized;
}

std::string SharedMemoryDataInfo::shm_name() const
{
    return shm_name_;
}

std::string SharedMemoryDataInfo::shm_mutex_name() const
{
    return shm_name_ + "_mutex";
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

pybind11::bytes concat_to_pybytes(const char *a, size_t a_len, const char *b, size_t b_len)
{
    size_t total_len = a_len + b_len;

    // Allocate Python bytes object with uninitialized buffer
    PyObject *py_bytes = PyBytes_FromStringAndSize(nullptr, total_len);
    if (!py_bytes)
        throw std::runtime_error("Failed to allocate Python bytes");

    // Get pointer to internal buffer
    char *buffer = PyBytes_AS_STRING(py_bytes);

    // Copy both arrays into the buffer
    std::memcpy(buffer, a, a_len);
    std::memcpy(buffer + a_len, b, b_len);

    // Return py::bytes without extra copy
    return pybind11::reinterpret_steal<pybind11::bytes>(py_bytes);
}

pybind11::bytes SharedMemoryDataInfo::get_shm_data() const
{

    int shm_fd = shm_open(("rmq_" + shm_name()).c_str(), O_RDONLY, 0666);
    if (shm_fd == -1)
    {
        throw std::runtime_error("Failed to open shared memory: " + std::string(strerror(errno)));
    }

    void *shm_ptr = mmap(0, shm_size_bytes_, PROT_READ, MAP_SHARED, shm_fd, 0);
    if (shm_ptr == MAP_FAILED)
    {
        throw std::runtime_error("Failed to map shared memory: " + std::string(strerror(errno)));
    }
    pybind11::bytes data;
    if (shm_start_idx_ + data_size_bytes_ < shm_size_bytes_)
    {
        data = pybind11::bytes(static_cast<char *>(shm_ptr) + shm_start_idx_, data_size_bytes_);
    }
    else
    {
        char *a = static_cast<char *>(shm_ptr) + shm_start_idx_;
        size_t a_len = shm_size_bytes_ - shm_start_idx_;
        char *b = static_cast<char *>(shm_ptr);
        size_t b_len = data_size_bytes_ - a_len;
        data = concat_to_pybytes(a, a_len, b, b_len);
    }
    munmap(shm_ptr, shm_size_bytes_);
    close(shm_fd);

    return data;
}

pybind11::bytes SharedMemoryDataInfo::get_shm_data_with_mutex() const
{

    // Lock the mutex
    int shm_mutex_fd = shm_open(("rmq_" + shm_mutex_name()).c_str(), O_RDWR, 0666);
    if (shm_mutex_fd == -1)
    {
        throw std::runtime_error("Failed to open shared memory mutex: " + std::string(strerror(errno)));
    }
    pthread_mutex_t *shm_mutex_ptr =
        (pthread_mutex_t *)mmap(0, sizeof(pthread_mutex_t), PROT_READ | PROT_WRITE, MAP_SHARED, shm_mutex_fd, 0);
    pthread_mutex_lock(shm_mutex_ptr);

    // Get data
    pybind11::bytes data = get_shm_data();

    // Unlock the mutex
    pthread_mutex_unlock(shm_mutex_ptr);
    munmap(shm_mutex_ptr, sizeof(pthread_mutex_t));
    close(shm_mutex_fd);

    return data;
}
