#!/bin/bash

# wrapper to run ESVO insider docker
# usage: ./run_esvo.sh <session_path>

SESSION_PATH="$1"

if [ -z "$SESSION_PATH" ]; then
	echo "Usage: $0 <session_path>"
	exit 1
fi

# relative to absolute path
SESSION_PATH=$(realpath "$SESSION_PATH")

# enable x11 forwarding for visualization
xhost +local:root 2>/dev/null || true

docker run --rm -it \
	-e DISPLAY \
	-v /tmp/.X11-unix:/tmp/.X11-unix:rw \
	-v "$SESSION_PATH:/data" \
	sert-ros:latest \
	bash -c "
		roslaunch esvo_core system.launch config:=/data/config/esvo_stereo.yaml &
		sleep 5
		rosbag play /data/intermediate/scene_events.bag --clock -r 0.5
	"
