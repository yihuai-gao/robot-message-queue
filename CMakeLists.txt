# Copyright (c) 2024 Yihuai Gao
# 
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

cmake_minimum_required(VERSION 3.10)
project(robotmq)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(DEFINED ENV{CONDA_PREFIX})
    set(Python_ROOT_DIR $ENV{CONDA_PREFIX})
    set(Python_EXECUTABLE $ENV{CONDA_PREFIX}/bin/python)
endif()

find_package(Python COMPONENTS Interpreter Development REQUIRED)
find_package(pybind11 CONFIG REQUIRED)
find_package(ZeroMQ REQUIRED)
find_package(Boost REQUIRED COMPONENTS system)
find_package(Threads REQUIRED)
find_package(fmt REQUIRED)
find_package(spdlog REQUIRED)
find_package(cppzmq REQUIRED)

find_path(CPPZMQ_INCLUDE_DIR zmq.hpp)

# Set output directories
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# Add source files with new directory structure
set(SOURCES
    robotmq/core/src/rmq_client.cpp
    robotmq/core/src/rmq_message.cpp
    robotmq/core/src/rmq_server.cpp
    robotmq/core/src/data_topic.cpp
    robotmq/core/src/common.cpp
    robotmq/core/src/pybind.cpp
)

# Create the pybind11 module with the new target name
pybind11_add_module(robotmq_core ${SOURCES})

add_compile_options(-pthread)

target_link_libraries(robotmq_core PRIVATE
    libzmq
    spdlog::spdlog
    Threads::Threads
    pthread
)

# Update include directories for new structure
target_include_directories(robotmq_core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/robotmq/core/include
)


# Update the output location and name
set_target_properties(robotmq_core PROPERTIES 
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/robotmq/core"
    PREFIX ""
    OUTPUT_NAME "robotmq"
)

message(STATUS "Python_EXECUTABLE: ${Python_EXECUTABLE}")