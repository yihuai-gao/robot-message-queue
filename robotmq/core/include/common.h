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
void interruptible_sleep(double seconds);
std::string uint32_to_bytes(uint32_t value);
uint32_t bytes_to_uint32(const std::string &bytes);
std::string int32_to_bytes(int32_t value);
int32_t bytes_to_int32(const std::string &bytes);
std::string double_to_bytes(double value);
double bytes_to_double(const std::string &bytes);
std::string bytes_to_hex(const std::string &bytes);

std::string uint64_to_bytes(uint64_t value);
uint64_t bytes_to_uint64(const std::string &bytes);

// Length-prefixed (uint32) byte strings, for messages that carry several fields.
void append_length_prefixed(std::string &out, const std::string &field);
// Reads the field at `pos` and advances `pos`; throws std::invalid_argument when `in` is too short.
std::string read_length_prefixed(const std::string &in, size_t &pos);

std::string get_user_name();
std::string get_pid();

// The probe segment of RMQClient::check_shared_memory: its name ends in SHM_PROBE_SUFFIX and its actual size is at
// most SHM_MAX_PROBE_BYTES. The server compares its contents locally and only echoes a verified client nonce.
constexpr const char *SHM_PROBE_SUFFIX = "_probe";
constexpr uint64_t SHM_MAX_PROBE_BYTES = 64;

class SharedMemoryDataInfo
{
  public:
    SharedMemoryDataInfo(const std::string &shm_name, uint64_t shm_size_bytes, uint64_t shm_start_idx,
                         uint64_t data_size_bytes);
    SharedMemoryDataInfo(const std::string &serialized_data_info);

    static bool is_shm_data_info(const std::string &serialized_data_info);

    std::string shm_name() const;
    std::string shm_mutex_name() const;
    uint64_t shm_size_bytes() const;
    uint64_t shm_start_idx() const;
    uint64_t data_size_bytes() const;

    std::string serialize() const;

    // The described bytes as a Python bytes object; throws std::runtime_error when the segment cannot be opened or
    // read. get_shm_data_with_mutex also holds the segment's process-shared mutex for the read.
    pybind11::bytes get_shm_data() const;
    pybind11::bytes get_shm_data_with_mutex() const;

    // Whether this process can open the segment read-only and it holds the bytes the descriptor names. Uses no
    // Python objects, so it is safe on the server's background thread (no GIL). The reason goes to `error`.
    bool check_readable(std::string &error) const;
    // Copies the described bytes into `out`, leaving it empty on failure. An optional nonzero size limit is checked
    // against the actual segment using the same open fd as the read, so replacing the name cannot bypass it.
    bool read_bytes(std::string &out, std::string &error, uint64_t max_segment_size_bytes = 0) const;

  private:
    // The descriptor's own consistency: a non-empty segment, a start inside it or equal to its size (an entry that
    // begins at the wrap point, whose bytes all lie at the front of the ring), data no larger than it.
    bool in_bounds_(std::string &error) const;
    // Reads the described bytes (following the ring-buffer wrap) from the open segment `fd` into `dst`, which holds
    // at least data_size_bytes_ bytes. Returns false with the reason in `error`.
    bool read_into_(int fd, char *dst, std::string &error) const;
    static const std::string HEADER;
    std::string shm_name_;
    uint64_t shm_size_bytes_;
    uint64_t shm_start_idx_;
    uint64_t data_size_bytes_;
};

pybind11::bytes concat_to_pybytes(const char *a, size_t a_len, const char *b, size_t b_len);
