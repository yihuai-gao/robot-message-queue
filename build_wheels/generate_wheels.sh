#! /bin/bash

root_dir=$(dirname $(dirname $(realpath $0)))

cd $root_dir
docker build -t robotmq build_wheels
docker create --name robotmq-container robotmq
docker cp robotmq-container:/root/robot-message-queue/wheelhouse build_wheels/
docker rm robotmq-container

