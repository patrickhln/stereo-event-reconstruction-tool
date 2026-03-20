#!/bin/bash

# wrapper to run Kalibr IMU-Camera calibration inside docker
# usage: ./run_kalibr_imucam.sh <calibration_branch_root>
#
# calibration_branch_root is an explicit branch directory
# (e.g. lab/calibrations/calib_01/unfiltered) containing raw/, intermediate/,
# frames/, and the stereo camera calibration output from run_kalibr.sh.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/path_utils.sh"

BRANCH_ROOT="$1"

if [ -z "$BRANCH_ROOT" ]; then
	echo "Usage: $0 <calibration_branch_root>"
	echo "Example: $0 lab/calibrations/calib_01/unfiltered"
	exit 1
fi

BRANCH_ROOT=$(require_branch_root "$BRANCH_ROOT") || exit 1

SESSION_PATH=$(find_session_root "$BRANCH_ROOT") || exit 1
BRANCH_ROOT=$(require_branch_in_session_subdir "$BRANCH_ROOT" "$SESSION_PATH" calibrations) || exit 1

# Target config is in session/config/targets/
CONFIG_PATH="$SESSION_PATH/config/targets"

# Input/output are in the branch directory
INTERMEDIATE_DIR="$BRANCH_ROOT/intermediate"
OUTPUT_DIR="$BRANCH_ROOT"

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
echo "Input bag: $INTERMEDIATE_DIR/stereo_frames.bag"
echo "Input camchain: $BRANCH_ROOT/stereo_frames-camchain.yaml"
echo "Input imu config: $INTERMEDIATE_DIR/imu.yaml"
echo "Output directory: $OUTPUT_DIR"

if [ ! -f "$BRANCH_ROOT/stereo_frames-camchain.yaml" ]; then
    echo "Error: Camera calibration (stereo_frames-camchain.yaml) not found. Run run_kalibr.sh first."
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
		--bag /capture/intermediate/stereo_frames.bag \
		--cam /capture/stereo_frames-camchain.yaml \
		--imu /capture/intermediate/imu.yaml \
		--target $TARGET_FILE \
		--dont-show-report || exit 1
	
	echo 'Moving results...';
    mv /capture/intermediate/stereo_frames-camchain-imucam.yaml /capture/ 2>/dev/null || true;
    mv /capture/intermediate/stereo_frames-report-imucam.pdf /capture/ 2>/dev/null || true;
    mv /capture/intermediate/stereo_frames-results-imucam.txt /capture/ 2>/dev/null || true;

    echo 'Fixing permissions...';
    chown -R $USER_ID:$GROUP_ID /capture;
	
	echo 'Done! IMU-Camera calibration results are in: /capture/'
	"
