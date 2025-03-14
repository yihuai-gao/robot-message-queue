/**
 * Copyright (c) 2024 Yihuai Gao
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 */

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

PYBIND11_MODULE(robotmq_core, m)
{

    m.def("steady_clock_us", &steady_clock_us);
    m.def("system_clock_us", &system_clock_us);

    py::class_<RMQClient>(m, "RMQClient")
        .def(py::init<const std::string &, const std::string &>(), py::arg("client_name"), py::arg("server_endpoint"))
        .def("get_topic_status", &RMQClient::get_topic_status, py::arg("topic"), py::arg("timeout_s"))
        .def("peek_data", &RMQClient::peek_data, py::arg("topic"), py::arg("order"), py::arg("n"))
        .def("pop_data", &RMQClient::pop_data, py::arg("topic"), py::arg("order"), py::arg("n"))
        .def("put_data", &RMQClient::put_data, py::arg("topic"), py::arg("data"))
        .def("get_last_retrieved_data", &RMQClient::get_last_retrieved_data)
        .def("reset_start_time", &RMQClient::reset_start_time, py::arg("system_time_us"))
        .def("get_timestamp", &RMQClient::get_timestamp)
        .def("request_with_data", &RMQClient::request_with_data, py::arg("topic"), py::arg("data"));

    py::class_<RMQServer>(m, "RMQServer")
        .def(py::init<const std::string &, const std::string &>(), py::arg("server_name"), py::arg("server_endpoint"))
        .def("add_topic", &RMQServer::add_topic, py::arg("topic"), py::arg("message_remaining_time_s"))
        .def("put_data", &RMQServer::put_data, py::arg("topic"), py::arg("data"))
        .def("peek_data", &RMQServer::peek_data, py::arg("topic"), py::arg("order"), py::arg("n"))
        .def("pop_data", &RMQServer::pop_data, py::arg("topic"), py::arg("order"), py::arg("n"))
        .def("get_all_topic_status", &RMQServer::get_all_topic_status)
        .def("reset_start_time", &RMQServer::reset_start_time, py::arg("system_time_us"))
        .def("wait_for_request", &RMQServer::wait_for_request, py::arg("timeout_s"))
        .def("reply_request", &RMQServer::reply_request, py::arg("topic"), py::arg("data"))
        .def("get_timestamp", &RMQServer::get_timestamp);
}
