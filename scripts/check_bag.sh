#!/bin/bash
# Usage: ./check_bag.sh <bag_file_path>
BAG_PATH=$(realpath "$1")
BAG_DIR=$(dirname "$BAG_PATH")
BAG_NAME=$(basename "$BAG_PATH")
docker run --rm \
    -v "$BAG_DIR:/data:ro" \
    sert-ros:latest \
    rosbag info "/data/$BAG_NAME"
