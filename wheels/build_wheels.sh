#! /bin/bash

root_dir=$(dirname $(dirname $(realpath $0)))

cd $root_dir
ROBOTMQ_COMMIT=$(git rev-parse HEAD)
docker build -t robotmq wheels --build-arg ROBOTMQ_COMMIT=$ROBOTMQ_COMMIT
docker create --name robotmq-container robotmq
docker cp robotmq-container:/root/robot-message-queue/wheelhouse wheels/
docker rm robotmq-container

