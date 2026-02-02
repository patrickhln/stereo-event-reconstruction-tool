#!/bin/bash
set -e

# Test ESVO with Official Bags
# 
# Script to run ESVO completely inside Docker using downloaded
# datasets.
#
# Usage: ./scripts/test_esvo_official.sh <profile> [OPTIONS]
#
# Arguments:
#   <profile>       Result profile name: hkust, rpg, dsec, upenn
#
# Options:
#   --no-viz        Run without visualization (headless)
#   --rate <r>      Bag playback rate (default: 0.5)
#   --bag <path>    Override auto-download and use specific local bag

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <profile> [OPTIONS]"
    echo "Profiles: hkust, rpg, dsec, upenn"
    echo "  (Dataset will be downloaded automatically if --bag is not provided)"
    exit 1
fi

PROFILE="$1"
shift 1

BAG_INPUT=""
VISUALIZE=true
PLAYBACK_RATE=0.5

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-viz)
            VISUALIZE=false
            shift
            ;;
        --rate)
            PLAYBACK_RATE="$2"
            shift 2
            ;;
        --bag)
            BAG_INPUT="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done


if [[ -z "$BAG_INPUT" ]]; then
    echo "Autodetecting dataset for profile: $PROFILE..."
    DATASET_DIR="$PROJECT_ROOT/data/datasets/$PROFILE"
    python3 "$PROJECT_ROOT/src/python/download_esvo_dataset.py" "$PROFILE" "$DATASET_DIR"
    
    # find the first .bag file
    FOUND_BAG=$(find "$DATASET_DIR" -maxdepth 2 -name "*.bag" -type f -printf "%s %p\n" | sort -nr | head -n1 | awk '{$1=""; print $0}' | xargs)
    
    if [[ -z "$FOUND_BAG" ]]; then
        echo "Error: No .bag file found in $DATASET_DIR after download."
        exit 1
    fi
    BAG_INPUT="$FOUND_BAG"
    echo "Using bag: $BAG_INPUT"
fi

if [[ ! -f "$BAG_INPUT" ]]; then
    echo "Error: Bag file '$BAG_INPUT' not found."
    exit 1
fi
REAL_BAG_PATH=$(readlink -f "$BAG_INPUT")


TEST_DIR="$PROJECT_ROOT/build/esvo_test_${PROFILE}"
CONFIG_DIR="$TEST_DIR/config"
OUTPUT_DIR="$TEST_DIR/output"
LOGS_DIR="$TEST_DIR/ros_logs"

echo "ESVO Docker Test Runner"
echo "Profile:   $PROFILE"
echo "Bag:       $REAL_BAG_PATH"
echo "Work Dir:  $TEST_DIR"
echo "Visualize: $VISUALIZE"

mkdir -p "$CONFIG_DIR"
mkdir -p "$OUTPUT_DIR/pcd_tmp"
mkdir -p "$LOGS_DIR"

rm -rf "$OUTPUT_DIR"/*
mkdir -p "$OUTPUT_DIR/pcd_tmp"

echo "Extracting configuration for profile '$PROFILE' from Docker image..."

# Create a temporary container to copy files from
CONTAINER_ID=$(docker create sert-ros:latest)

# Function to clean up on error found during config extraction
cleanup_container() {
    docker rm -v "$CONTAINER_ID" >/dev/null 2>&1 || true
}
trap cleanup_container EXIT

# 1. Copy Calibration (left.yaml, right.yaml)
if ! docker cp "$CONTAINER_ID:/catkin_ws/src/ESVO/esvo_core/calib/$PROFILE/." "$CONFIG_DIR/"; then
    echo "Error: Could not extract calibration for profile '$PROFILE' from Docker image."
    echo "Please ensure the profile exists in the Docker image."
    exit 1
fi

# 2. Copy Mapping Config
if ! docker cp "$CONTAINER_ID:/catkin_ws/src/ESVO/esvo_core/cfg/mapping/mapping_${PROFILE}.yaml" "$CONFIG_DIR/mapping.yaml"; then
    echo "Error: mapping_${PROFILE}.yaml not found in Docker image."
    exit 1
fi

# 3. Copy Tracking Config
if ! docker cp "$CONTAINER_ID:/catkin_ws/src/ESVO/esvo_core/cfg/tracking/tracking_${PROFILE}.yaml" "$CONFIG_DIR/tracking.yaml"; then
    echo "Error: tracking_${PROFILE}.yaml not found in Docker image."
    exit 1
fi

# 4. Copy TimeSurface Config (Generic)
docker cp "$CONTAINER_ID:/catkin_ws/src/ESVO/esvo_core/cfg/time_surface/ts_parameters.yaml" "$CONFIG_DIR/"

# Remove container
docker rm -v "$CONTAINER_ID"
trap - EXIT

# --- Patch Configs ---

# Enable Trajectory Saving
TRACKING_CONFIG="$CONFIG_DIR/tracking.yaml"
if grep -q "SAVE_TRAJECTORY: False" "$TRACKING_CONFIG" 2>/dev/null; then
    sed -i 's/SAVE_TRAJECTORY: False/SAVE_TRAJECTORY: True/' "$TRACKING_CONFIG"
    sed -i 's|PATH_TO_SAVE_TRAJECTORY:.*|PATH_TO_SAVE_TRAJECTORY: "/output/"|' "$TRACKING_CONFIG"
fi

# --- Generate Launch File ---

SYNC_RATE=$(echo "$PLAYBACK_RATE * 100" | bc)
LAUNCH_FILE=$(mktemp /tmp/esvo_launch_XXXXXX.launch)

# Visualization
VIZ_NODES=""
if [ "$VISUALIZE" = true ]; then
    VIZ_NODES='
  <node pkg="rqt_gui" type="rqt_gui" name="rqt_gui"
    args="--perspective-file $(find esvo_core)/esvo_system.perspective" />
  <node pkg="rviz" type="rviz" name="rviz"
    args="-d $(find esvo_core)/esvo_system.rviz" />'
fi

cat > "$LAUNCH_FILE" << LAUNCH_EOF
<launch>
  <rosparam param="/use_sim_time">true</rosparam>

  <!-- ESVO Nodes -->
  <node name="TimeSurface_left" pkg="esvo_time_surface" type="esvo_time_surface">
    <remap from="events" to="/davis/left/events" />
    <remap from="camera_info" to="/davis/left/camera_info" />
    <remap from="time_surface" to="TS_left" />
    <rosparam command="load" file="/esvo_config/ts_parameters.yaml" />
  </node>

  <node name="TimeSurface_right" pkg="esvo_time_surface" type="esvo_time_surface">
    <remap from="events" to="/davis/right/events" />
    <remap from="camera_info" to="/davis/right/camera_info" />
    <remap from="time_surface" to="TS_right" />
    <rosparam command="load" file="/esvo_config/ts_parameters.yaml" />
  </node>

  <node name="global_timer" pkg="rostopic" type="rostopic" 
        args="pub -s -r $SYNC_RATE /sync std_msgs/Time 'now' "/>

  <node name="esvo_Mapping" pkg="esvo_core" type="esvo_Mapping" 
        output="screen" required="true">
    <remap from="time_surface_left" to="/TS_left" />
    <remap from="time_surface_right" to="/TS_right" />
    <remap from="stamped_pose" to="/esvo_tracking/pose_pub" />
    <remap from="events_left" to="/davis/left/events" />
    <remap from="events_right" to="/davis/right/events" />
    <rosparam param="dvs_frame_id">"dvs"</rosparam>
    <rosparam param="world_frame_id">"map"</rosparam>
    <rosparam param="calibInfoDir">/esvo_config</rosparam>
    <rosparam command="load" file="/esvo_config/mapping.yaml" />
  </node>

  <node name="esvo_Tracking" pkg="esvo_core" type="esvo_Tracking" 
        output="screen" required="true">
    <remap from="time_surface_left" to="/TS_left" />
    <remap from="time_surface_right" to="/TS_right" />
    <remap from="stamped_pose" to="/esvo_tracking/pose_pub" />
    <remap from="events_left" to="/davis/left/events" />
    <remap from="pointcloud" to="/esvo_mapping/pointcloud_local" />
    <rosparam param="dvs_frame_id">"dvs"</rosparam>
    <rosparam param="world_frame_id">"map"</rosparam>
    <rosparam param="calibInfoDir">/esvo_config</rosparam>
    <rosparam param="resultPath">/output</rosparam>
    <rosparam command="load" file="/esvo_config/tracking.yaml" />
  </node>

  $VIZ_NODES
</launch>
LAUNCH_EOF

# generate runner script (Docker internal)

RUNNER_SCRIPT=$(mktemp /tmp/esvo_runner_XXXXXX.sh)
cat > "$RUNNER_SCRIPT" << 'RUNNER_EOF'
#!/bin/bash
set -e

PLAYBACK_RATE=$1
# No rebuild needed - using pre-built image

source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash

echo 'Starting ROS Core...'
roscore &
ROSCORE_PID=$!
sleep 2

echo 'Starting Camera Info Publisher (1000 Hz)...'
python3 /scripts/publish_camera_info.py /esvo_config/left.yaml /esvo_config/right.yaml &
CAMINFO_PID=$!
sleep 1

echo 'Launching ESVO (Pre-built)...'
roslaunch /esvo_launch.launch &
LAUNCH_PID=$!
sleep 5

echo 'Starting Pointcloud Saver...'
rosrun pcl_ros pointcloud_to_pcd input:=/esvo_mapping/pointcloud_global _prefix:="/output/pcd_tmp/pc_" &
PCD_PID=$!

echo "Playing Bag at rate $PLAYBACK_RATE..."
rosbag play /data/input.bag --clock -r "$PLAYBACK_RATE"

echo 'Bag Finished. Finalizing...'
# Kick clock
rostopic pub -r 10 /clock rosgraph_msgs/Clock "clock: {secs: 2147483647, nsecs: 0}" >/dev/null 2>&1 &
KICKER_PID=$!

# Terminate
rosparam set /ESVO_SYSTEM_STATUS 'TERMINATE'
sleep 10
kill $KICKER_PID 2>/dev/null || true
sleep 2
kill "$PCD_PID" 2>/dev/null || true

# Save Final PCD
python3 << 'PYSCRIPT'
from pathlib import Path
from shutil import copy2
import os

pcd_dir = Path("/output/pcd_tmp")
pcd_files = sorted(pcd_dir.glob("*.pcd"), key=lambda p: p.stat().st_mtime)
if pcd_files:
    target = Path("/output/pointcloud.pcd")
    copy2(pcd_files[-1], target)
    print(f"Saved final pointcloud to {target}")
    print(f"Total frames: {len(pcd_files)}")
else:
    print("Warning: No pointcloud files generated.")
PYSCRIPT

# Cleanup
kill $CAMINFO_PID 2>/dev/null || true
kill $LAUNCH_PID 2>/dev/null || true
kill $ROSCORE_PID 2>/dev/null || true
RUNNER_EOF

chmod +x "$RUNNER_SCRIPT"

# run docker

if [ "$VISUALIZE" = true ]; then
    xhost +local:root 2>/dev/null || true
    X11_ARGS="-e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:rw"
else
    X11_ARGS=""
fi

AVAILABLE_CPUS=$(nproc)
DOCKER_CPUS=$((AVAILABLE_CPUS > 2 ? AVAILABLE_CPUS - 2 : AVAILABLE_CPUS))

docker run --rm -it \
    --cpus="$DOCKER_CPUS" \
    --memory="8g" \
    $X11_ARGS \
    -v "$CONFIG_DIR:/esvo_config:ro" \
    -v "$REAL_BAG_PATH:/data/input.bag:ro" \
    -v "$OUTPUT_DIR:/output" \
    -v "$LOGS_DIR:/root/.ros/log" \
    -v "$LAUNCH_FILE:/esvo_launch.launch:ro" \
    -v "$RUNNER_SCRIPT:/esvo_runner.sh:ro" \
    -v "$PROJECT_ROOT/src/python/publish_camera_info.py:/scripts/publish_camera_info.py:ro" \
    sert-ros:latest \
    bash /esvo_runner.sh "$PLAYBACK_RATE"

rm -f "$LAUNCH_FILE" "$RUNNER_SCRIPT"
