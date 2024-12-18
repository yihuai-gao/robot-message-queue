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


# if(DEFINED ENV{PYTHON_EXECUTABLE})
#     set(Python_EXECUTABLE $ENV{PYTHON_EXECUTABLE})
# endif()


# set(Python_EXECUTABLE /opt/python/cp310-cp310/bin/python)
# set(Python_INCLUDE_DIRS /opt/python/cp310-cp310/include/python3.10)
# set(Python_LIBRARIES /opt/python/cp310-cp310/lib/libpython3.10.so)

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

# set_target_properties(robotmq_core PROPERTIES SUFFIX "${PYTHON_ABI}${CMAKE_SHARED_LIBRARY_SUFFIX}")


message(STATUS "Python_EXECUTABLE: ${Python_EXECUTABLE}")

# 'cmake', '/io', '-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=/io/build/lib.linux-x86_64-cpython-310/robotmq/core', '-DPYTHON_EXECUTABLE=/opt/python/cp310-cp310/bin/python', '-DPYTHON_INCLUDE_DIR=/opt/python/cp310-cp310/include/python3.10', '-DPYTHON_LIBRARY=/opt/python/cp310-cp310/lib/libpython3.10.so', '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DCMAKE_BUILD_TYPE=Release'

# CIBW_BEFORE_BUILD_LINUX="apt-get update && apt-get install -y libspdlog-dev libboost-all-dev libfmt-dev libzmq3-dev libczmq-dev"