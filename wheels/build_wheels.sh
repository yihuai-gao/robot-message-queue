#! /bin/bash

ARCH=$(uname -m)

if [ "$ARCH" == "x86_64" ]; then
    DOCKERFILE="wheels/Dockerfile.x86_64"
elif [ "$ARCH" == "arm64" ] || [ "$ARCH" == "aarch64" ]; then
    DOCKERFILE="wheels/Dockerfile.aarch64"
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi
set -e
root_dir=$(dirname $(dirname $(realpath $0)))

cd $root_dir
ROBOTMQ_COMMIT=$(git rev-parse HEAD)
docker build -t robotmq wheels --build-arg ROBOTMQ_COMMIT=$ROBOTMQ_COMMIT --file $DOCKERFILE
docker create --name robotmq-container robotmq
docker cp robotmq-container:/root/robot-message-queue/wheelhouse wheels/
docker rm robotmq-container

