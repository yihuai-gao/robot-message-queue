#include "common.h"

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

std::string end_type_to_str(EndType end_type)
{
    if (end_type == EndType::EARLIEST)
    {
        return "earliest";
    }
    else if (end_type == EndType::LATEST)
    {
        return "latest";
    }
    throw std::invalid_argument("Invalid end type");
}

EndType str_to_end_type(const std::string &end_type)
{
    if (end_type == "earliest")
    {
        return EndType::EARLIEST;
    }
    else if (end_type == "latest")
    {
        return EndType::LATEST;
    }
    throw std::invalid_argument("Invalid end type: " + end_type);
}
