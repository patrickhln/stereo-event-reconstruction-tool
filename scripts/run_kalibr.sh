#!/bin/bash

# wrapper to run Kalibr inside docker
# usage: ./run_kalibr.sh <session_path> <capture_dir>

set -e

SESSION_PATH="$1"
CAPTURE_DIR="$2"

if [ -z "$SESSION_PATH" ] || [ -z "$CAPTURE_DIR" ]; then
	echo "Usage: $0 <session_path> <capture_dir>"
	exit 1
fi

# relative to absolute path
SESSION_PATH=$(realpath "$SESSION_PATH")
CAPTURE_DIR=$(realpath "$CAPTURE_DIR")

# Target config is in session/config/targets/
CONFIG_PATH="$SESSION_PATH/config/targets"

# Input/output are in the capture directory
INTERMEDIATE_DIR="$CAPTURE_DIR/intermediate"
OUTPUT_DIR="$CAPTURE_DIR"

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR"
fi

TARGET_FILE=""
TARGET_NAME=""
for t in "aprilgrid.yaml" "checkerboard.yaml" "circlegrid.yaml"; do
    if [ -f "$CONFIG_PATH/$t" ]; then
        TARGET_FILE="/session/config/targets/$t"
        TARGET_NAME="$t"
        break
    fi
done

if [ -z "$TARGET_FILE" ]; then
    echo "Error: No calibration target file (aprilgrid, checkerboard, or circlegrid) found in $CONFIG_PATH"
    exit 1
fi

echo "Using target config: $CONFIG_PATH/$TARGET_NAME"
echo "Input bag: $INTERMEDIATE_DIR/stereo_frames.bag"
echo "Output directory: $OUTPUT_DIR"

# local user ID and Group ID to fix permissions later
USER_ID=$(id -u)
GROUP_ID=$(id -g)

# Mount session for config and capture for data
docker run --rm \
	-e HOME=/tmp \
	-e MPLBACKEND=Agg \
	-v "$SESSION_PATH:/session:ro" \
	-v "$CAPTURE_DIR:/capture" \
	-w /capture \
	sert-esvo-kalibr:latest \
	/bin/bash -c "
	rosrun kalibr kalibr_calibrate_cameras \
		--target $TARGET_FILE \
		--bag /capture/intermediate/stereo_frames.bag \
		--models pinhole-radtan pinhole-radtan \
		--topics /cam0/image_raw /cam1/image_raw \
		--approx-sync 0.02 \
		--dont-show-report || exit 1
	
	echo 'Moving results...';
    mv /capture/intermediate/stereo_frames-camchain.yaml /capture/ 2>/dev/null || true;
    mv /capture/intermediate/stereo_frames-report-cam.pdf /capture/ 2>/dev/null || true;
    mv /capture/intermediate/stereo_frames-results-cam.txt /capture/ 2>/dev/null || true;

    echo 'Fixing permissions...';
    chown -R $USER_ID:$GROUP_ID /capture;
	
	echo 'Done! Calibration results are in: /capture/'
	"

# -e HOME=/tmp: ROS tries to create a cache

# -e MPLBACKEND=Agg: Even with --dont-show-report, Kalibr uses matplotlib to draw PDF, 
# MPLBACKEND=Agg forces Anti-Grain Gemotry backend which is purely for saving files (headless)

# --approx-sync 0.02 default as of docker run --rm sert-esvo-kalibr:latest rosrun kalibr kalibr_calibrate_cameras (returns help message)
