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
    cd robot-message-queue && \
    git checkout 09fdba7b16dee646e9e46936986a6cef0ec887f7

COPY CMakeLists.txt robot-message-queue/CMakeLists.txt


RUN cd robot-message-queue && \
    /opt/python/cp38-cp38/bin/python -m venv cp38 && \
    source cp38/bin/activate && \
    pip install pybind11 && \
    pip install -e . && \
    pip wheel . && \
    auditwheel repair robotmq-0.1.0-cp38-cp38-linux_x86_64.whl

RUN cd robot-message-queue && \
    /opt/python/cp39-cp39/bin/python -m venv cp39 && \
    source cp39/bin/activate && \
    pip install pybind11 && \
    pip install -e . && \
    pip wheel . && \
    auditwheel repair robotmq-0.1.0-cp39-cp39-linux_x86_64.whl

RUN cd robot-message-queue && \
    /opt/python/cp310-cp310/bin/python -m venv cp310 && \
    source cp310/bin/activate && \
    pip install pybind11 && \
    pip install -e . && \
    pip wheel . && \
    auditwheel repair robotmq-0.1.0-cp310-cp310-linux_x86_64.whl

RUN cd robot-message-queue && \
    /opt/python/cp311-cp311/bin/python -m venv cp311 && \
    source cp311/bin/activate && \
    pip install pybind11 && \
    pip install -e . && \
    pip wheel . && \
    auditwheel repair robotmq-0.1.0-cp311-cp311-linux_x86_64.whl


RUN cd robot-message-queue && \
    /opt/python/cp312-cp312/bin/python -m venv cp312 && \
    source cp312/bin/activate && \
    pip install pybind11 && \
    pip install -e . && \
    pip wheel . && \
    auditwheel repair robotmq-0.1.0-cp312-cp312-linux_x86_64.whl
