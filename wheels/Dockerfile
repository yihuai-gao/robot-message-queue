FROM quay.io/pypa/manylinux_2_28_x86_64:latest

WORKDIR /root

RUN git clone https://github.com/jedisct1/libsodium.git && \
    cd libsodium && git checkout 1.0.20-RELEASE && \
    ./autogen.sh && \
    ./configure && \
    make -j && \
    make check && \
    make install

RUN git clone https://github.com/zeromq/libzmq.git && \
    cd libzmq && git checkout v4.3.5 && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make -j && \
    make install

RUN git clone https://github.com/zeromq/cppzmq.git && \
    cd cppzmq && git checkout v4.10.0 && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make -j && \
    make install

# This version is buggy. Will use the one installed in a python virtual environment.
# RUN git clone https://github.com/pybind/pybind11.git && \
#     cd pybind11 && git checkout v2.13.6 && \
#     mkdir build && \
#     cd build && \
#     cmake .. && \
#     make -j && \
#     make install

RUN git clone https://github.com/gabime/spdlog.git && \
    cd spdlog && git checkout v1.15.1 && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make -j && \
    make install

RUN git clone https://github.com/yihuai-gao/robot-message-queue.git && \
    cd robot-message-queue

COPY CMakeLists.txt robot-message-queue/CMakeLists.txt

RUN yum install -y tmux

RUN cd robot-message-queue && \
    set -e && \
    # There are unknown bugs in cp312 (core dump)
    for PYTHON_VERSION in cp37-cp37m cp38-cp38 cp39-cp39 cp310-cp310 cp311-cp311 cp313-cp313; do \
    /opt/python/${PYTHON_VERSION}/bin/python -m venv ${PYTHON_VERSION} && \
    source ${PYTHON_VERSION}/bin/activate && \
    pip install pybind11 && \
    pip install -e . && \
    pip wheel . && \
    PACKAGE_VERSION=$(grep "version = " pyproject.toml | sed 's/version = "\(.*\)"/\1/') && \
    auditwheel repair robotmq-${PACKAGE_VERSION}-${PYTHON_VERSION}-linux_x86_64.whl; \
    done

# RUN cd robot-message-queue && \
#     set -e && \
#     # Install GNU Parallel
#     yum install -y parallel && \
#     # Create a function to build wheel for a single Python version
#     echo 'build_wheel() { \
#     PYTHON_VERSION=$1; \
#     /opt/python/${PYTHON_VERSION}/bin/python -m venv ${PYTHON_VERSION} && \
#     source ${PYTHON_VERSION}/bin/activate && \
#     pip install pybind11 && \
#     pip install -e . && \
#     pip wheel . && \
#     auditwheel repair robotmq-0.1.0-${PYTHON_VERSION}-linux_x86_64.whl; \
#     }' > build_wheel.sh && \
#     # Export the function and make script executable
#     chmod +x build_wheel.sh && \
#     source build_wheel.sh && \
#     export -f build_wheel && \
#     # Run builds in parallel
#     echo "cp38-cp38 cp39-cp39 cp310-cp310 cp311-cp311 cp312-cp312 cp313-cp313" | \
#     tr ' ' '\n' | parallel build_wheel