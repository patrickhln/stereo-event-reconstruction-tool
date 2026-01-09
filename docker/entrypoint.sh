#!/bin/bash

# if any command fails, stop the script
set -e
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash
exec "$@"
