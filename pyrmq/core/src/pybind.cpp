#include "common.h"
#include "data_topic.h"
#include "rmq_client.h"
#include "rmq_message.h"
#include "rmq_server.h"
#include <pybind11/functional.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PyBytesPtr bytes_to_shared_string(py::bytes py_bytes)
{
    return std::make_shared<py::bytes>(py_bytes);
}

PYBIND11_MODULE(pyrmq, m)
{

    m.def("steady_clock_us", &steady_clock_us);
    m.def("system_clock_us", &system_clock_us);

    py::class_<RMQClient>(m, "RMQClient")
        .def(py::init<const std::string &, const std::string &>())
        .def("peek_data", &RMQClient::peek_data)
        .def("pop_data", &RMQClient::pop_data)
        .def("get_last_retrieved_data", &RMQClient::get_last_retrieved_data)
        .def("reset_start_time", &RMQClient::reset_start_time)
        .def("get_timestamp", &RMQClient::get_timestamp)
        .def("request_with_data", &RMQClient::request_with_data);

    py::class_<RMQServer>(m, "RMQServer")
        .def(py::init<const std::string &, const std::string &>())
        .def("add_topic", &RMQServer::add_topic)
        .def("put_data", &RMQServer::put_data)
        .def("peek_data", &RMQServer::peek_data)
        .def("pop_data", &RMQServer::pop_data)
        .def("get_topic_status", &RMQServer::get_topic_status)
        .def("reset_start_time", &RMQServer::reset_start_time)
        .def("wait_for_request", &RMQServer::wait_for_request)
        .def("reply_request", &RMQServer::reply_request)
        .def("get_timestamp", &RMQServer::get_timestamp);
}
