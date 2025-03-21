# Copyright (c) 2024 Yihuai Gao
# 
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

# For building python wheels
cmake_minimum_required(VERSION 3.10)
project(robotmq)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

execute_process(
    COMMAND ${Python_EXECUTABLE} -c "import sysconfig; print(sysconfig.get_path('purelib'))"
    OUTPUT_VARIABLE PYTHON_SITE_PACKAGES
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

find_package(pybind11 REQUIRED PATHS ${PYTHON_SITE_PACKAGES}/pybind11/share/cmake/pybind11)
find_package(ZeroMQ REQUIRED)
find_package(Threads REQUIRED)
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
    spdlog
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
)

# Add this to ensure the wheel is built with the correct ABI flags
if(DEFINED ENV{CONDA_PREFIX})
    set(PYTHON_ABI ".cp${Python_VERSION_MAJOR}${Python_VERSION_MINOR}-cp${Python_VERSION_MAJOR}${Python_VERSION_MINOR}")
else()
    execute_process(
        COMMAND ${Python_EXECUTABLE} -c "import sysconfig; print(sysconfig.get_config_var('SOABI'))"
        OUTPUT_VARIABLE PYTHON_ABI
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
endif()