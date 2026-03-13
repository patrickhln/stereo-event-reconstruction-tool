#!/bin/bash
set -e

# ESVO Runner Script (Minimal & Local Data)
# Usage: ./run_esvo.sh <session_path> <scene_name> [OPTIONS]
#
# Options:
#   --no-viz        Run without visualization (headless)
#   --rate <r>      Bag playback rate (default: 0.2)
#   --min-depth <m> Minimum expected scene depth in meters (default: 0.5)
#   --max-depth <m> Maximum expected scene depth in meters (default: 10.0)
#   --save-pc       Save final pointcloud to file
#   --gpu <mode>    GPU mode: auto|intel|amd|nvidia|cpu (default: auto)

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <session_path> <scene_name> [OPTIONS]"
    echo "Example: $0 ./session scene_test"
    echo ""
    echo "Options:"
    echo "  --no-viz      Run without visualization"
    echo "  --rate <r>    Bag playback rate (default: 0.2)"
    echo "  --min-depth   Minimum expected scene depth in meters (default: 0.5)"
    echo "  --max-depth   Maximum expected scene depth in meters (default: 10.0)"
    echo "  --save-pc     Save final pointcloud"
    echo "  --gpu <mode>  GPU mode: auto|intel|amd|nvidia|cpu"
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
ESVO_LAUNCH_FILE="$SCRIPT_DIR/launch/esvo/offline_system.launch"
ESVO_IMAGE="sert-esvo-kalibr:latest"

# Defaults
VISUALIZE=true
PLAYBACK_RATE=0.2
MIN_DEPTH=0.5
MAX_DEPTH=10.0
SAVE_PC=false
GPU_MODE=auto
TARGET_SIM_TS_RATE_HZ=100

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-viz) VISUALIZE=false; shift ;;
        --rate) PLAYBACK_RATE="$2"; shift 2 ;;
        --min-depth) MIN_DEPTH="$2"; shift 2 ;;
        --max-depth) MAX_DEPTH="$2"; shift 2 ;;
        --save-pc) SAVE_PC=true; shift ;;
        --gpu) GPU_MODE="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== ESVO Runner ==="
echo "Session: $SESSION_PATH"
echo "Scene:   $SCENE_DIR"
echo "Depth:   ${MIN_DEPTH}m - ${MAX_DEPTH}m"

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

echo "Checking bag for camera_info topics ..."
if ! docker run --rm \
    -v "$BAG_FILE:/data/input.bag:ro" \
    "$ESVO_IMAGE" \
    /bin/bash -lc "rosbag info /data/input.bag | grep -q '/davis/left/camera_info' && rosbag info /data/input.bag | grep -q '/davis/right/camera_info'"; then
    echo "Error: ESVO requires /davis/left/camera_info and /davis/right/camera_info in:"
    echo "  $BAG_FILE"
    echo "Regenerate the bag with calibration embedded, for example:"
    echo "  python3 src/python/aedat4_to_bag.py --path <scene> --calibration <session>/config/esvo"
    exit 1
fi

if [[ ! -f "$ESVO_LAUNCH_FILE" ]]; then
    echo "Error: Launch file not found: $ESVO_LAUNCH_FILE"
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
    --min-depth "$MIN_DEPTH" \
    --max-depth "$MAX_DEPTH"


OUTPUT_DIR="$SCENE_DIR/reconstruction/esvo"
mkdir -p "$OUTPUT_DIR"

# Official offline behavior: keep time-surface generation at 100 Hz in
# simulation time and slow only wall-clock playback for weak hardware.
SYNC_RATE=$(python3 - <<PY
import math
playback_rate = float("$PLAYBACK_RATE")
target_rate = int("$TARGET_SIM_TS_RATE_HZ")
print(max(1, int(math.ceil(playback_rate * target_rate))))
PY
)

echo "Playback rate: $PLAYBACK_RATE"
echo "Time-surface rate (sim time): $TARGET_SIM_TS_RATE_HZ"
echo "Sync rate: $SYNC_RATE"

# Create Runner Script (for inside Docker)
RUNNER_SCRIPT=$(mktemp /tmp/esvo_runner_XXXXXX.sh)

cleanup_tmp_files() {
    rm -f "$RUNNER_SCRIPT"
}
trap cleanup_tmp_files EXIT

cat > "$RUNNER_SCRIPT" <<EOF
#!/bin/bash
set -e
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash

echo "Starting ROSCore..."
roscore &
PID_CORE=\$!
sleep 2

echo "Launching ESVO..."
roslaunch /esvo_launch.launch enable_viz:=$VISUALIZE sync_rate:=$SYNC_RATE &
PID_LAUNCH=\$!
sleep 8

# Give TF buffer time to initialize before bag playback
echo "Waiting for ESVO nodes to initialize..."
sleep 2

# Optional: Pointcloud Saving
if [ "$SAVE_PC" = "true" ]; then
    echo "Listening for Pointcloud..."
    mkdir -p /output/pcd_tmp
    rm -f /output/pcd_tmp/*.pcd
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
# kill \$PID_CORE || true

# Graceful shutdown without forcing a huge /clock jump
rosparam set /ESVO_SYSTEM_STATUS 'TERMINATE'
sleep 2

[ ! -z "\$PID_PCD" ] && kill \$PID_PCD || true
kill \$PID_LAUNCH || true
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
#     "$ESVO_IMAGE" \
#     bash /esvo_runner.sh

docker run --rm -it \
    --cpus="$DOCKER_CPUS" \
    --memory="8g" \
    $GPU_ARGS \
    $VIZ_ARGS \
    -v "$ESVO_CONFIG_DIR:/esvo_config:ro" \
    -v "$BAG_FILE:/data/input.bag:ro" \
    -v "$OUTPUT_DIR:/output" \
    -v "$ESVO_LAUNCH_FILE:/esvo_launch.launch:ro" \
    -v "$RUNNER_SCRIPT:/esvo_runner.sh:ro" \
    "$ESVO_IMAGE" \
    bash /esvo_runner.sh

echo "Done. Results in $OUTPUT_DIR"
