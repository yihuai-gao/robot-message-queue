#pragma once

#include "common.h"
#include <pybind11/pybind11.h>
#include <vector>
#include <zmq.hpp>
enum class CmdType : int8_t
{
    PEEK_DATA = 1,
    POP_DATA = 2,
    REQUEST_WITH_DATA = 3,
    SYNCHRONIZE_TIME = 4,
    ERROR = -1,
    UNKNOWN = 0,
};

class RMQMessage
{
  public:
    RMQMessage(const std::string &topic, CmdType cmd, EndType end_type, double timestamp,
               const std::vector<TimedPtr> &data_ptrs);
    RMQMessage(const std::string &topic, CmdType cmd, EndType end_type, double timestamp, const std::string &data_str);
    RMQMessage(const std::string &serialized);

    std::string topic() const;
    CmdType cmd() const;
    EndType end_type() const;
    double timestamp() const;
    std::vector<TimedPtr> data_ptrs();
    std::string data_str(); // Should avoid using because it may copy a large amount of data
    std::string serialize();

  private:
    void encode_data_blocks_();
    void decode_data_blocks_();
    void check_input_validity_();
    std::string topic_;
    CmdType cmd_;
    EndType end_type_;
    double timestamp_;
    std::vector<TimedPtr> data_ptrs_;
    std::string data_str_;
};
