#!/bin/bash

# wrapper to run Kalibr IMU-Camera calibration inside docker
# usage: ./run_kalibr_imucam.sh <calibration_branch_root> <model>
#
# calibration_branch_root is an explicit branch directory
# (e.g. lab/calibrations/calib_01/unfiltered) containing raw/, intermediate/,
# frames/<model>/, and the stereo camera calibration output from run_kalibr.sh.

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
CAMCHAIN_PATH="$OUTPUT_DIR/stereo_frames-camchain.yaml"
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
echo "Input camchain: $CAMCHAIN_PATH"
echo "Input imu config: $INTERMEDIATE_DIR/imu.yaml"
echo "Output directory: $OUTPUT_DIR"

if [ ! -f "$BAG_FILE" ]; then
    echo "Error: Input bag not found: $BAG_FILE"
    echo "Run stereo_frames_to_rosbag.py first:"
    echo "  python3 src/python/stereo_frames_to_rosbag.py --path $BRANCH_ROOT --model $MODEL"
    exit 1
fi

if [ ! -f "$CAMCHAIN_PATH" ]; then
    echo "Error: Camera calibration not found: $CAMCHAIN_PATH"
    echo "Run run_kalibr.sh first for model '$MODEL'."
    exit 1
fi

if [ ! -f "$INTERMEDIATE_DIR/imu.yaml" ]; then
    echo "Error: IMU parameters (imu.yaml) not found. Need to generate it during aedat4_to_bag conversion."
    exit 1
fi

# local user ID and Group ID to fix permissions later
USER_ID=$(id -u)
GROUP_ID=$(id -g)

# Mount session for config and branch root for data
docker run --rm \
	-e HOME=/tmp -e MPLBACKEND=Agg \
	-v "$SESSION_PATH:/session:ro" \
	-v "$BRANCH_ROOT:/capture" \
	-w /capture \
	sert-esvo-kalibr:latest \
	/bin/bash -c "
	rosrun kalibr kalibr_calibrate_imu_camera \
		--bag /capture/intermediate/stereo_frames_${MODEL}.bag \
		--cam /capture/calibration/$MODEL/stereo_frames-camchain.yaml \
		--imu /capture/intermediate/imu.yaml \
		--target $TARGET_FILE \
		--dont-show-report || exit 1
	
	echo 'Moving results...';
	    mkdir -p /capture/calibration/$MODEL;
	    mv /capture/intermediate/stereo_frames-camchain-imucam.yaml /capture/calibration/$MODEL/ 2>/dev/null || true;
	    mv /capture/intermediate/stereo_frames-report-imucam.pdf /capture/calibration/$MODEL/ 2>/dev/null || true;
	    mv /capture/intermediate/stereo_frames-results-imucam.txt /capture/calibration/$MODEL/ 2>/dev/null || true;

    echo 'Fixing permissions...';
    chown -R $USER_ID:$GROUP_ID /capture;
	
	echo 'Done! IMU-Camera calibration results are in: /capture/calibration/$MODEL/'
	"
