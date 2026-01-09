#!/bin/bash

# wrapper to run Kalibr insider docker
# usage: ./run_kalibr.sh <session_path>

set -e

SESSION_PATH="$1"

if [ -z "$SESSION_PATH" ]; then
	echo "Usage: $0 <session_path>"
	exit 1
fi

# relative to absolute path
SESSION_PATH=$(realpath "$SESSION_PATH")

OUTPUT_DIR="$SESSION_PATH/calibration"

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR"
fi

# local user ID and Group ID to fix permissions later
USER_ID=$(id -u)
GROUP_ID=$(id -g)


docker run --rm \
	-e HOME=/tmp \
	-e MPLBACKEND=Agg \
	-v "$SESSION_PATH:/data" \
	-w /data/calibration \
	sert-ros:latest \
	/bin/bash -c "
	rosrun kalibr kalibr_calibrate_cameras \
		--target /data/config/checkerboard.yaml \
		--bag /data/intermediate/stereo_frames.bag \
		--models pinhole-radtan pinhole-radtan \
		--topics /cam0/image_raw /cam1/image_raw \
		--approx-sync 0.02 \
		--dont-show-report \
	
	echo 'Moving results...';
    mv /data/intermediate/stereo_frames-camchain.yaml /data/calibration/ 2>/dev/null || true;
    mv /data/intermediate/stereo_frames-report-cam.pdf /data/calibration/ 2>/dev/null || true;
    mv /data/intermediate/stereo_frames-results-cam.txt /data/calibration/ 2>/dev/null || true;

    echo 'Fixing permissions...';
    chown -R $USER_ID:$GROUP_ID /data/calibration;
	
	echo "Done! All files are in: $OUTPUT_DIR"
	"

# -e HOME=/tmp: ROS tries to create a cache

# -e MPLBACKEND=Agg: Even with --dont-show-report, Kalibr uses matplotlib to draw PDF, 
# MPLBACKEND=Agg forces Anti-Grain Gemotry backend which is purely for saving files (headless)

# --approx-sync 0.02 default as of docker run --rm sert-ros:latest rosrun kalibr kalibr_calibrate_cameras (returns help message)
