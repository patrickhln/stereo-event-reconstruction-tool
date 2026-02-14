#!/bin/bash
set -e

# ESVO Runner Script (Minimal & Local Data)
# Usage: ./run_esvo.sh <session_path> <scene_name> [OPTIONS]
#
# Options:
#   --no-viz        Run without visualization (headless)
#   --rate <r>      Bag playback rate (default: 0.06)
#   --save-pc       Save final pointcloud to file
#   --gpu <mode>    GPU mode: auto|intel|amd|nvidia|cpu (default: auto)

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <session_path> <scene_name> [OPTIONS]"
    echo "Example: $0 ./session scene_test"
    exit 1
fi

SESSION_PATH=$(realpath "$1")
SCENE_ARG="$2"
shift 2

# Handle Scene Argument (name or path)
if [[ -d "$SCENE_ARG" ]]; then
    SCENE_DIR=$(realpath "$SCENE_ARG")
elif [[ -d "$SESSION_PATH/scenes/$SCENE_ARG" ]]; then
    SCENE_DIR="$SESSION_PATH/scenes/$SCENE_ARG"
else
    echo "Error: Scene '$SCENE_ARG' not found."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SRC_PYTHON="$PROJECT_ROOT/src/python"

# Defaults
VISUALIZE=true
PLAYBACK_RATE=0.06  # DVXplorer-safe default on (my) laptop CPU
SAVE_PC=false
GPU_MODE=auto

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-viz) VISUALIZE=false; shift ;;
        --rate) PLAYBACK_RATE="$2"; shift 2 ;;
        --save-pc) SAVE_PC=true; shift ;;
        --gpu) GPU_MODE="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== ESVO Runner ==="
echo "Session: $SESSION_PATH"
echo "Scene:   $SCENE_DIR"

# try to source conda if available to use sert-python for config generation
if command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook)"
    if conda env list | grep -q "sert-python"; then
        conda activate sert-python
    else
        echo "Warning: 'sert-python' env not found. Using system python."
    fi
fi

ESVO_CONFIG_DIR="$SESSION_PATH/config/esvo"
BAG_FILE="$SCENE_DIR/intermediate/scene_events.bag"

if [[ ! -f "$BAG_FILE" ]]; then
    echo "Error: Bag file not found: $BAG_FILE"
    echo "Please ensure the dataset is processed (aedat4_to_bag) before running ESVO."
    exit 1
fi

mkdir -p "$ESVO_CONFIG_DIR"

# check if calibration files exist, if not, generate them
if [[ ! -f "$ESVO_CONFIG_DIR/left.yaml" ]] || [[ ! -f "$ESVO_CONFIG_DIR/right.yaml" ]]; then
    echo "Generating ESVO calibration files (left.yaml, right.yaml)..."
    
    # Helper to find camchain (assumes first one found in calibrations folder)
    CAMCHAIN_FILE=$(find "$SESSION_PATH/calibrations" -name "*camchain.yaml" 2>/dev/null | head -n 1)
    CAMERA_META="$SCENE_DIR/raw/camera_metadata.txt"
    
    if [[ -z "$CAMCHAIN_FILE" ]]; then
        echo "Error: No camchain file found in $SESSION_PATH/calibrations/"
        echo "Cannot generate ESVO calibration."
        exit 1
    fi
     if [[ ! -f "$CAMERA_META" ]]; then
        echo "Error: No camera_metadata.txt found in $SCENE_DIR/raw/"
        exit 1
    fi
    
    python3 "$SRC_PYTHON/camchain_to_esvo.py" \
        --camchain "$CAMCHAIN_FILE" \
        --raw "$(dirname "$CAMERA_META")" \
        --output "$ESVO_CONFIG_DIR"
fi

# always regenerate runtime configs so tuning changes in generate_esvo_config.py
# are applied without manually deleting old YAML files.
echo "Generating ESVO runtime configs (mapping.yaml, tracking.yaml, ts_parameters.yaml)..."
python3 "$SRC_PYTHON/generate_esvo_config.py" \
    --session "$SESSION_PATH" \
    --min-depth 0.5 \
    --max-depth 5.0

# Read tracking rate from generated tracking.yaml to keep /sync aligned.
TRACKING_RATE_HZ=$(python3 - <<PY
import yaml
with open("$ESVO_CONFIG_DIR/tracking.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}
rate = cfg.get("tracking_rate_hz", 50)
try:
    rate = int(rate)
except Exception:
    rate = 50
print(max(rate, 1))
PY
)


OUTPUT_DIR="$SCENE_DIR/reconstruction/esvo"
mkdir -p "$OUTPUT_DIR"

# Create Launch File (Mapped to container paths)
LAUNCH_FILE=$(mktemp /tmp/esvo_launch_XXXXXX.launch)
# Sync rate (wall-clock Hz) = ceil(playback_rate * tracking_rate_hz)
# Ceil avoids undersupplying time surfaces when the product is non-integer.
SYNC_RATE=$(python3 - <<PY
import math
playback_rate = float("$PLAYBACK_RATE")
tracking_rate = int("$TRACKING_RATE_HZ")
print(max(1, int(math.ceil(playback_rate * tracking_rate))))
PY
)

echo "Playback rate: $PLAYBACK_RATE"
echo "Tracking rate: $TRACKING_RATE_HZ"
echo "Sync rate: $SYNC_RATE"

VIZ_NODES=""
if [ "$VISUALIZE" = true ]; then
    VIZ_NODES='
    <node pkg="rqt_gui" type="rqt_gui" name="rqt_gui" args="--perspective-file $(find esvo_core)/esvo_system.perspective" />
    <node pkg="rviz" type="rviz" name="rviz" args="-d $(find esvo_core)/esvo_system.rviz" />'
fi

cat > "$LAUNCH_FILE" <<EOF
<launch>
  <rosparam param="/use_sim_time">true</rosparam>

  <!-- Node: TimeSurface Left -->
  <node name="TimeSurface_left" pkg="esvo_time_surface" type="esvo_time_surface">
    <remap from="events" to="/davis/left/events" />
    <remap from="camera_info" to="/davis/left/camera_info" />
    <remap from="time_surface" to="TS_left" />
    <rosparam command="load" file="/esvo_config/ts_parameters.yaml" />
  </node>

  <!-- Node: TimeSurface Right -->
  <node name="TimeSurface_right" pkg="esvo_time_surface" type="esvo_time_surface">
    <remap from="events" to="/davis/right/events" />
    <remap from="camera_info" to="/davis/right/camera_info" />
    <remap from="time_surface" to="TS_right" />
    <rosparam command="load" file="/esvo_config/ts_parameters.yaml" />
  </node>

  <!-- Node: Global Timer for Sync -->
  <node name="global_timer" pkg="rostopic" type="rostopic" 
        args="pub -s -r $SYNC_RATE /sync std_msgs/Time 'now' "/>

  <!-- Node: ESVO Mapping -->
  <node name="esvo_Mapping" pkg="esvo_core" type="esvo_Mapping" output="screen" required="true">
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

  <!-- Node: ESVO Tracking -->
  <node name="esvo_Tracking" pkg="esvo_core" type="esvo_Tracking" output="screen" required="true">
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
EOF

# Create Runner Script (for inside Docker)
RUNNER_SCRIPT=$(mktemp /tmp/esvo_runner_XXXXXX.sh)
cat > "$RUNNER_SCRIPT" <<EOF
#!/bin/bash
set -e
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash

echo "Starting ROSCore..."
roscore &
PID_CORE=\$!
sleep 2

# Essential: Publish Camera Info
# Even if bag has it, this ensures we use the exact calibration from the configs.
echo "Publishing Camera Info..."
python3 /scripts/publish_camera_info.py /esvo_config/left.yaml /esvo_config/right.yaml &
PID_CAM=\$!
sleep 1

echo "Launching ESVO..."
roslaunch /esvo_launch.launch &
PID_LAUNCH=\$!
sleep 8

# Give TF buffer time to initialize before bag playback
echo "Waiting for ESVO nodes to initialize..."
sleep 2

# Optional: Pointcloud Saving
if [ "$SAVE_PC" = "true" ]; then
    echo "Listening for Pointcloud..."
    mkdir -p /output/pcd_tmp
    rosrun pcl_ros pointcloud_to_pcd input:=/esvo_mapping/pointcloud_global _prefix:="/output/pcd_tmp/pc_" &
    PID_PCD=\$!
fi

echo "Playing Bag..."
rosbag play /data/input.bag --clock -r $PLAYBACK_RATE --delay=2

echo "Bag finished. Terminating..."
# Kick clock to forward time so nodes can process final bits and exit
# rostopic pub -r 10 /clock rosgraph_msgs/Clock "clock: {secs: 2147483647, nsecs: 0}" >/dev/null 2>&1 &
# PID_KICK=\$!
#
# rosparam set /ESVO_SYSTEM_STATUS 'TERMINATE'
# sleep 5
#
# kill \$PID_KICK || true
# [ ! -z "\$PID_PCD" ] && kill \$PID_PCD || true
# kill \$PID_LAUNCH || true
# kill \$PID_CAM || true
# kill \$PID_CORE || true

# Graceful shutdown without forcing a huge /clock jump
rosparam set /ESVO_SYSTEM_STATUS 'TERMINATE'
sleep 2

[ ! -z "\$PID_PCD" ] && kill \$PID_PCD || true
kill \$PID_LAUNCH || true
kill \$PID_CAM || true
kill \$PID_CORE || true

# Process PCD
if [ "$SAVE_PC" = "true" ]; then
    echo "Saving final pointcloud..."
    python3 -c "import shutil, glob, os; 
files = sorted(glob.glob('/output/pcd_tmp/*.pcd'), key=os.path.getmtime); 
shutil.copy(files[-1], '/output/pointcloud.pcd') if files else print('No PCD found')"
fi
EOF

chmod +x "$RUNNER_SCRIPT"

# run docker
VIZ_ARGS=""
if [ "$VISUALIZE" = true ]; then
    xhost +local:root 2>/dev/null || true
    VIZ_ARGS="-e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:rw"
fi

AVAILABLE_CPUS=$(nproc)
DOCKER_CPUS=$((AVAILABLE_CPUS > 2 ? AVAILABLE_CPUS - 2 : AVAILABLE_CPUS))

GPU_ARGS=""
case "$GPU_MODE" in
    auto)
        if [[ -e /dev/nvidia0 ]]; then
            GPU_ARGS="--gpus all -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute"
        elif [[ -d /dev/dri ]]; then
            GPU_ARGS="--device /dev/dri --group-add video --group-add render -e LIBGL_ALWAYS_SOFTWARE=0"
        else
            GPU_ARGS="-e LIBGL_ALWAYS_SOFTWARE=1"
        fi
        ;;
    intel|amd)
        GPU_ARGS="--device /dev/dri --group-add video --group-add render -e LIBGL_ALWAYS_SOFTWARE=0"
        ;;
    nvidia)
        GPU_ARGS="--gpus all -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute"
        ;;
    cpu|none)
        GPU_ARGS="-e LIBGL_ALWAYS_SOFTWARE=1"
        ;;
    *)
        echo "Unknown --gpu mode: $GPU_MODE"
        exit 1
        ;;
esac

echo "Running ESVO in Docker..."
# docker run --rm -it \
#     --cpus="$DOCKER_CPUS" \
#     --memory="8g" \
#     $VIZ_ARGS \
#     -v "$ESVO_CONFIG_DIR:/esvo_config:ro" \
#     -v "$BAG_FILE:/data/input.bag:ro" \
#     -v "$OUTPUT_DIR:/output" \
#     -v "$LAUNCH_FILE:/esvo_launch.launch:ro" \
#     -v "$RUNNER_SCRIPT:/esvo_runner.sh:ro" \
#     -v "$SRC_PYTHON/publish_camera_info.py:/scripts/publish_camera_info.py:ro" \
#     sert-esvo-kalibr:latest \
#     bash /esvo_runner.sh

docker run --rm -it \
    --cpus="$DOCKER_CPUS" \
    --memory="8g" \
    $GPU_ARGS \
    $VIZ_ARGS \
    -v "$ESVO_CONFIG_DIR:/esvo_config:ro" \
    -v "$BAG_FILE:/data/input.bag:ro" \
    -v "$OUTPUT_DIR:/output" \
    -v "$LAUNCH_FILE:/esvo_launch.launch:ro" \
    -v "$RUNNER_SCRIPT:/esvo_runner.sh:ro" \
    -v "$SRC_PYTHON/publish_camera_info.py:/scripts/publish_camera_info.py:ro" \
    sert-esvo-kalibr:latest \
    bash /esvo_runner.sh

# Cleanup
rm "$LAUNCH_FILE" "$RUNNER_SCRIPT"

echo "Done. Results in $OUTPUT_DIR"
