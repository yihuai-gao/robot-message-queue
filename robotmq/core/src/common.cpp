/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

#include "common.h"
#include <algorithm>
#include <cstring>
#include <fcntl.h>
#include <pybind11/functional.h>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/pytypes.h>
#include <pybind11/stl.h>
#include <pybind11/stl_bind.h>
#include <sstream>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <pwd.h>
#include <sys/types.h>

namespace py = pybind11;

void interruptible_sleep(double seconds)
{
    py::gil_scoped_release release; // Release the GIL for C++ execution

    auto start_time = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> elapsed_seconds;

    // Sleep in small increments and check for interrupts
    while (true)
    {
        elapsed_seconds = std::chrono::high_resolution_clock::now() - start_time;
        if (elapsed_seconds.count() >= seconds)
        {
            break; // Target sleep duration reached
        }

        // Calculate remaining time or a small chunk
        double remaining_seconds = seconds - elapsed_seconds.count();
        double sleep_chunk = std::min(remaining_seconds, 0.001); // Sleep for 1ms at a time

        std::this_thread::sleep_for(std::chrono::duration<double>(sleep_chunk));

        // Reacquire GIL temporarily to check for Python signals
        py::gil_scoped_acquire acquire;
        if (PyErr_CheckSignals() != 0)
        {
            // A Python error (like KeyboardInterrupt) is pending
            throw py::error_already_set(); // Re-raise the Python exception
        }
    }
}

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

std::string get_user_name()
{
    char *user_name = getlogin();
    if (user_name == nullptr)
    {
        uid_t uid = getuid();
        struct passwd *pw = getpwuid(uid);
        if (pw == nullptr)
        {
            printf("Failed to get user_name. Using uid: %d\n", uid);
            return std::to_string(uid);
        }
        return std::string(pw->pw_name);
    }
    return std::string(user_name);
}

std::string get_pid()
{
    pid_t pid = getpid();
    return std::to_string(pid);
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
        printf("serialized_data_info: first 10 bytes: %s, total size: %zu, HEADER: %s\n",
               bytes_to_hex(serialized_data_info.substr(0, 10)).c_str(), serialized_data_info.size(),
               bytes_to_hex(HEADER).c_str());
        throw std::invalid_argument("Invalid serialized data info (beginning doesn't match with HEADER)");
    }
    current_byte_idx += HEADER.size();

    uint64_t shm_name_size = bytes_to_uint64(serialized_data_info.substr(current_byte_idx, sizeof(uint64_t)));
    current_byte_idx += sizeof(uint64_t);

    shm_name_ = serialized_data_info.substr(current_byte_idx, shm_name_size);
    current_byte_idx += shm_name_size;
    // shm_open stops at a NUL, so a name with one embedded would pass any check on the std::string (such as the
    // server's probe suffix check) yet open a different segment; glibc rejects a '/' inside a name anyway.
    if (shm_name_.empty() || shm_name_.find('\0') != std::string::npos || shm_name_.find('/') != std::string::npos)
    {
        throw std::invalid_argument("Invalid shared memory name in data info (contains NUL or '/')");
    }

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

namespace
{
// Opens `shm_name` with `flags` and rejects a segment that is already smaller than the `min_size` bytes described.
// A segment shrunk after this check still faults on a mapped read (SIGBUS), which is why every read of a segment
// another process owns (read_bytes and get_shm_data) goes through SharedMemoryDataInfo::read_into_ and pread.
// Returns the fd, or -1 with the reason in `error`.
int open_shm_at_least(const std::string &shm_name, int flags, uint64_t min_size, std::string &error)
{
    int fd = shm_open(shm_name.c_str(), flags, 0);
    if (fd == -1)
    {
        error = strerror(errno);
        return -1;
    }
    struct stat shm_stat;
    if (fstat(fd, &shm_stat) == -1)
    {
        error = strerror(errno);
        close(fd);
        return -1;
    }
    if (static_cast<uint64_t>(shm_stat.st_size) < min_size)
    {
        error = "the segment holds " + std::to_string(shm_stat.st_size) + " bytes, fewer than the " +
                std::to_string(min_size) + " bytes described";
        close(fd);
        return -1;
    }
    return fd;
}

// Reads exactly `count` bytes at `offset` of `fd` into `buf`. Returns false with the reason in `error` on a failed
// read or a short one (the segment shrank below the size checked when it was opened).
bool pread_exactly(int fd, char *buf, uint64_t count, uint64_t offset, std::string &error)
{
    uint64_t done = 0;
    while (done < count)
    {
        ssize_t n = pread(fd, buf + done, count - done, static_cast<off_t>(offset + done));
        if (n == -1)
        {
            if (errno == EINTR)
            {
                continue;
            }
            error = strerror(errno);
            return false;
        }
        if (n == 0)
        {
            error = "the segment shrank while it was read";
            return false;
        }
        done += static_cast<uint64_t>(n);
    }
    return true;
}
} // namespace

bool SharedMemoryDataInfo::in_bounds_(std::string &error) const
{
    if (shm_size_bytes_ == 0 || shm_start_idx_ > shm_size_bytes_ || data_size_bytes_ > shm_size_bytes_)
    {
        error = "descriptor out of bounds (segment " + std::to_string(shm_size_bytes_) + " bytes, start " +
                std::to_string(shm_start_idx_) + ", data " + std::to_string(data_size_bytes_) + " bytes)";
        return false;
    }
    return true;
}

// pread rather than mmap: another process owns the segment and may shrink it after the size check, which faults a
// mapped read (SIGBUS) but only shortens a pread.
bool SharedMemoryDataInfo::read_into_(int fd, char *dst, std::string &error) const
{
    uint64_t first_part = std::min(data_size_bytes_, shm_size_bytes_ - shm_start_idx_);
    return pread_exactly(fd, dst, first_part, shm_start_idx_, error) &&
           pread_exactly(fd, dst + first_part, data_size_bytes_ - first_part, 0, error); // the ring-buffer wrap
}

bool SharedMemoryDataInfo::check_readable(std::string &error) const
{
    if (!in_bounds_(error))
    {
        return false;
    }
    int fd = open_shm_at_least(shm_name_, O_RDONLY, shm_size_bytes_, error);
    if (fd == -1)
    {
        return false;
    }
    close(fd);
    return true;
}

bool SharedMemoryDataInfo::read_bytes(std::string &out, std::string &error) const
{
    if (!in_bounds_(error))
    {
        return false;
    }
    int fd = open_shm_at_least(shm_name_, O_RDONLY, shm_size_bytes_, error);
    if (fd == -1)
    {
        return false;
    }
    out.resize(data_size_bytes_);
    bool complete = read_into_(fd, out.data(), error);
    close(fd);
    if (!complete)
    {
        out.clear();
    }
    return complete;
}

pybind11::bytes SharedMemoryDataInfo::get_shm_data() const
{
    std::string error;
    if (!in_bounds_(error))
    {
        throw std::runtime_error("Failed to open shared memory: " + shm_name_ + " " + error);
    }
    int shm_fd = open_shm_at_least(shm_name_, O_RDONLY, shm_size_bytes_, error);
    if (shm_fd == -1)
    {
        throw std::runtime_error("Failed to open shared memory: " + shm_name_ + " " + error);
    }

    // Allocate the bytes object first and read straight into its buffer, so the data is copied exactly once.
    PyObject *raw = PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(data_size_bytes_));
    if (!raw)
    {
        close(shm_fd);
        throw std::runtime_error("Failed to allocate Python bytes");
    }
    pybind11::bytes data = pybind11::reinterpret_steal<pybind11::bytes>(raw); // released on any exception below
    bool complete = read_into_(shm_fd, PyBytes_AS_STRING(raw), error);
    close(shm_fd);
    if (!complete)
    {
        throw std::runtime_error("Failed to read shared memory: " + shm_name_ + " " + error);
    }
    return data;
}

pybind11::bytes SharedMemoryDataInfo::get_shm_data_with_mutex() const
{

    // Lock the mutex
    int shm_mutex_fd = shm_open((shm_name_ + "_mutex").c_str(), O_RDWR, 0666);
    if (shm_mutex_fd == -1)
    {
        throw std::runtime_error("Failed to open shared memory mutex: " + shm_name_ + "_mutex " +
                                 std::string(strerror(errno)));
    }
    pthread_mutex_t *shm_mutex_ptr =
        (pthread_mutex_t *)mmap(0, sizeof(pthread_mutex_t), PROT_READ | PROT_WRITE, MAP_SHARED, shm_mutex_fd, 0);
    if (shm_mutex_ptr == MAP_FAILED)
    {
        std::string reason = strerror(errno);
        close(shm_mutex_fd);
        throw std::runtime_error("Failed to map shared memory mutex: " + shm_name_ + "_mutex " + reason);
    }
    pthread_mutex_lock(shm_mutex_ptr);

    // Get data; the mutex is released also when the read fails
    pybind11::bytes data;
    try
    {
        data = get_shm_data();
    }
    catch (...)
    {
        pthread_mutex_unlock(shm_mutex_ptr);
        munmap(shm_mutex_ptr, sizeof(pthread_mutex_t));
        close(shm_mutex_fd);
        throw;
    }

    // Unlock the mutex
    pthread_mutex_unlock(shm_mutex_ptr);
    munmap(shm_mutex_ptr, sizeof(pthread_mutex_t));
    close(shm_mutex_fd);

    return data;
}

void append_length_prefixed(std::string &out, const std::string &field)
{
    out.append(uint32_to_bytes(static_cast<uint32_t>(field.size())));
    out.append(field);
}

std::string read_length_prefixed(const std::string &in, size_t &pos)
{
    if (pos + sizeof(uint32_t) > in.size())
    {
        throw std::invalid_argument("Length-prefixed field truncated at byte " + std::to_string(pos));
    }
    uint32_t length = bytes_to_uint32(in.substr(pos, sizeof(uint32_t)));
    pos += sizeof(uint32_t);
    if (pos + length > in.size())
    {
        throw std::invalid_argument("Length-prefixed field of " + std::to_string(length) + " bytes truncated at byte " +
                                    std::to_string(pos));
    }
    std::string field = in.substr(pos, length);
    pos += length;
    return field;
}
