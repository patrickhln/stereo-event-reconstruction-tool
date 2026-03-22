#!/bin/bash

# wrapper to run Kalibr inside docker
# usage: ./run_kalibr.sh <calibration_branch_root> <model>
#
# calibration_branch_root is an explicit branch directory
# (e.g. lab/calibrations/calib_01/unfiltered) containing raw/, intermediate/,
# frames/<model>/, and where calibration output goes.
# "It is recommended to lower the frequency of the camera streams to around 4 Hz while capturing the calibration data. This reduces redundant information in the dataset and thus lowering the runtime of the calibration."

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/path_utils.sh"

BRANCH_ROOT="$1"
MODEL="$2"

if [ -z "$BRANCH_ROOT" ] || [ -z "$MODEL" ]; then
	echo "Usage: $0 <calibration_branch_root> <model>"
	echo "Example: $0 lab/calibrations/calib_01/unfiltered e2vid"
	exit 1
fi

BRANCH_ROOT=$(require_branch_root "$BRANCH_ROOT") || exit 1

SESSION_PATH=$(find_session_root "$BRANCH_ROOT") || exit 1
BRANCH_ROOT=$(require_branch_in_session_subdir "$BRANCH_ROOT" "$SESSION_PATH" calibrations) || exit 1

# Target config is in session/config/targets/
CONFIG_PATH="$SESSION_PATH/config/targets"

# Input/output are in the branch directory
INTERMEDIATE_DIR="$BRANCH_ROOT/intermediate"
OUTPUT_DIR="$BRANCH_ROOT/calibration/$MODEL"
BAG_FILE="$INTERMEDIATE_DIR/stereo_frames_${MODEL}.bag"

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
echo "Branch root: $BRANCH_ROOT"
echo "Model: $MODEL"
echo "Input bag: $BAG_FILE"
echo "Output directory: $OUTPUT_DIR"

if [ ! -f "$BAG_FILE" ]; then
    echo "Error: Input bag not found: $BAG_FILE"
    echo "Run stereo_frames_to_rosbag.py first:"
    echo "  python3 src/python/stereo_frames_to_rosbag.py --path $BRANCH_ROOT --model $MODEL"
    exit 1
fi

# local user ID and Group ID to fix permissions later
USER_ID=$(id -u)
GROUP_ID=$(id -g)

xhost +local:root 2>/dev/null || true
VIZ_ARGS="-e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:rw"

# Mount session for config and branch root for data
docker run --rm \
	$VIZ_ARGS \
	-e HOME=/tmp \
	-e MPLBACKEND=Agg \
	-v "$SESSION_PATH:/session:ro" \
	-v "$BRANCH_ROOT:/capture" \
	-w /capture \
	sert-esvo-kalibr:latest \
	/bin/bash -c "
	rosrun kalibr kalibr_calibrate_cameras \
		--target $TARGET_FILE \
		--bag /capture/intermediate/stereo_frames_${MODEL}.bag \
		--models pinhole-radtan pinhole-radtan \
		--topics /cam0/image_raw /cam1/image_raw \
		--approx-sync 0.02 \
		--dont-show-report \
		--bag-freq 6 \
		--no-shuffle \
		--use-blakezisserman || exit 1

	echo 'Moving results...';
    mkdir -p /capture/calibration/$MODEL;
    mv /capture/intermediate/stereo_frames_${MODEL}-camchain.yaml /capture/calibration/$MODEL/stereo_frames-camchain.yaml 2>/dev/null || true;
    mv /capture/intermediate/stereo_frames_${MODEL}-report-cam.pdf /capture/calibration/$MODEL/stereo_frames-report-cam.pdf 2>/dev/null || true;
    mv /capture/intermediate/stereo_frames_${MODEL}-results-cam.txt /capture/calibration/$MODEL/stereo_frames-results-cam.txt 2>/dev/null || true;

	echo 'Fixing permissions...';
    chown -R $USER_ID:$GROUP_ID /capture;

	echo 'Done! Calibration results are in: /capture/calibration/$MODEL/'
	"

# -e HOME=/tmp: ROS tries to create a cache

# -e MPLBACKEND=Agg: Even with --dont-show-report, Kalibr uses matplotlib to draw PDF, 
# MPLBACKEND=Agg forces Anti-Grain Gemotry backend which is purely for saving files (headless)

# --approx-sync 0.02 default as of docker run --rm sert-esvo-kalibr:latest rosrun kalibr kalibr_calibrate_cameras (returns help message)
