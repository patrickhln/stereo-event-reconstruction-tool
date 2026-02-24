#!/bin/bash
set -e

# ESVO2 Runner Script (Local Data)
# Usage: ./run_esvo2.sh <session_path> <scene_name> [OPTIONS]
#
# Options:
#   --no-viz        Run without visualization (headless)
#   --rate <r>      Bag playback rate (default: 0.2)
#   --save-pc       Save final pointcloud to file
#   --gpu <mode>    GPU mode: auto|intel|amd|nvidia|cpu (default: auto)
#   --use-imu       Enable IMU integration (requires bag with /davis/left/imu)

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <session_path> <scene_name> [OPTIONS]"
    echo "Example: $0 ./session scene_test"
    echo ""
    echo "Options:"
    echo "  --no-viz      Run without visualization"
    echo "  --rate <r>    Bag playback rate (default: 0.2)"
    echo "  --save-pc     Save final pointcloud"
    echo "  --use-imu     Enable IMU integration"
    echo "  --gpu <mode>  GPU mode: auto|intel|amd|nvidia|cpu"
    exit 1
fi

SESSION_PATH=$(realpath "$1")
SCENE_ARG="$2"
shift 2

# Handle scene argument (name or path)
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
ESVO2_IMAGE="sert-esvo2:latest"
ESVO2_LAUNCH_FILE="$SCRIPT_DIR/launch/esvo2/offline_system.launch"

# Defaults
VISUALIZE=true
PLAYBACK_RATE=0.2
SAVE_PC=false
GPU_MODE=auto
USE_IMU=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-viz) VISUALIZE=false; shift ;;
        --rate) PLAYBACK_RATE="$2"; shift 2 ;;
        --save-pc) SAVE_PC=true; shift ;;
        --gpu) GPU_MODE="$2"; shift 2 ;;
        --use-imu) USE_IMU=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== ESVO2 Runner ==="
echo "Session: $SESSION_PATH"
echo "Scene:   $SCENE_DIR"
echo "IMU:     $USE_IMU"

# Docker sanity checks
if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker command not found."
    exit 1
fi

if ! docker image inspect "$ESVO2_IMAGE" >/dev/null 2>&1; then
    echo "Error: Docker image '$ESVO2_IMAGE' not found."
    echo "Build it first with: ./scripts/docker_build_esvo2.sh"
    exit 1
fi

if [[ ! -f "$ESVO2_LAUNCH_FILE" ]]; then
    echo "Error: Launch file not found: $ESVO2_LAUNCH_FILE"
    exit 1
fi

# Try to source conda if available to use sert-python for config generation
if command -v conda >/dev/null 2>&1; then
    eval "$(conda shell.bash hook)"
    if conda env list | grep -q "sert-python"; then
        conda activate sert-python
    else
        echo "Warning: 'sert-python' env not found. Using system python."
    fi
fi

ESVO2_CONFIG_DIR="$SESSION_PATH/config/esvo2"
BAG_FILE="$SCENE_DIR/intermediate/scene_events.bag"

if [[ ! -f "$BAG_FILE" ]]; then
    echo "Error: Bag file not found: $BAG_FILE"
    echo "Please ensure the dataset is processed (aedat4_to_bag) before running ESVO2."
    if [[ "$USE_IMU" == "true" ]]; then
        echo "For IMU mode, rerun conversion with:"
        echo "  python3 src/python/aedat4_to_bag.py --path <scene> --with-imu"
    fi
    exit 1
fi

# IMU topic validation (fast fail before launch)
if [[ "$USE_IMU" == "true" ]]; then
    echo "Checking bag for IMU topic /davis/left/imu ..."
    if ! docker run --rm \
        -v "$BAG_FILE:/data/input.bag:ro" \
        "$ESVO2_IMAGE" \
        /bin/bash -lc "rosbag info /data/input.bag | grep -q '/davis/left/imu'"; then
        echo "Error: --use-imu was requested but /davis/left/imu is missing in:"
        echo "  $BAG_FILE"
        echo "Rerun conversion with:"
        echo "  python3 src/python/aedat4_to_bag.py --path <scene> --with-imu"
        exit 1
    fi

    echo "Warning: IMU calibration is still pending (see notes/imu_calibration.md)."
    echo "         Visual-inertial accuracy may be limited for now."
fi

mkdir -p "$ESVO2_CONFIG_DIR"

# Generate calibration files only if missing
if [[ ! -f "$ESVO2_CONFIG_DIR/left.yaml" ]] || [[ ! -f "$ESVO2_CONFIG_DIR/right.yaml" ]]; then
    echo "Generating ESVO2 calibration files (left.yaml, right.yaml)..."

    CAMERA_META="$SCENE_DIR/raw/camera_metadata.txt"

    if [[ ! -f "$CAMERA_META" ]]; then
        echo "Error: No camera_metadata.txt found in $SCENE_DIR/raw/"
        exit 1
    fi

    CALIB_ARGS=(
        "$SESSION_PATH/calibrations"
        --raw "$(dirname "$CAMERA_META")"
    )

    python3 "$SRC_PYTHON/camchain_to_esvo2.py" "${CALIB_ARGS[@]}"
fi

# Always regenerate runtime configs for deterministic behavior
echo "Generating ESVO2 runtime configs (mapping/tracking/image_representation)..."
RUNTIME_ARGS=(
    --session "$SESSION_PATH"
    --min-depth 0.5
    --max-depth 10.0
)
if [[ "$USE_IMU" == "true" ]]; then
    RUNTIME_ARGS+=(--use-imu)
fi
python3 "$SRC_PYTHON/generate_esvo2_config.py" "${RUNTIME_ARGS[@]}"

OUTPUT_DIR="$SCENE_DIR/reconstruction/esvo2"
LOGS_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$OUTPUT_DIR"

# Keep logs local to this run and clear previous logs.
rm -rf "$LOGS_DIR"
mkdir -p "$LOGS_DIR"

# Remove stale trajectory artifacts before each run.
rm -f "$OUTPUT_DIR/stamped_traj_estimate.txt"
rm -f "$OUTPUT_DIR/stamped_traj_estimate_ours.txt"
rm -f "$OUTPUT_DIR/result.txt"
rm -f "$OUTPUT_DIR/trajectory_tum.txt"
rm -f "$OUTPUT_DIR/traj_ours_old.txt"
rm -rf "$OUTPUT_DIR/pcd_tmp"
if [[ "$SAVE_PC" == "true" ]]; then
    rm -f "$OUTPUT_DIR/pointcloud.pcd"
fi

# Create runner file mapped into container
RUNNER_SCRIPT=$(mktemp /tmp/esvo2_runner_XXXXXX.sh)

cleanup_tmp_files() {
    rm -f "$RUNNER_SCRIPT"
}
trap cleanup_tmp_files EXIT

IMU_DATA_TOPIC="/imu/data"
if [[ "$USE_IMU" == "true" ]]; then
    IMU_DATA_TOPIC="/davis/left/imu"
fi

cat > "$RUNNER_SCRIPT" <<EOF
#!/bin/bash
set -e
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash

PID_PCD=""

echo "Starting ROSCore..."
roscore &
PID_CORE=\$!
sleep 2

echo "Publishing Camera Info..."
python3 /scripts/publish_camera_info.py /esvo2_config/left.yaml /esvo2_config/right.yaml &
PID_CAM=\$!
sleep 1

echo "Launching ESVO2..."
roslaunch /esvo2_launch.launch enable_viz:=$VISUALIZE imu_data_topic:=$IMU_DATA_TOPIC &
PID_LAUNCH=\$!
sleep 8

echo "Waiting for ESVO2 nodes to initialize..."
sleep 2

if [ "$SAVE_PC" = "true" ]; then
    echo "Listening for pointcloud on /esvo2_mapping/pointcloud_global2 ..."
    mkdir -p /output/pcd_tmp
    rm -f /output/pcd_tmp/*.pcd
    rosrun pcl_ros pointcloud_to_pcd input:=/esvo2_mapping/pointcloud_global2 _prefix:="/output/pcd_tmp/pc_" &
    PID_PCD=\$!
fi

echo "Playing bag at rate $PLAYBACK_RATE..."
rosbag play /data/input.bag --clock -r $PLAYBACK_RATE --delay=2

echo "Bag finished. Terminating..."
rosparam set /ESVO2_SYSTEM_STATUS 'TERMINATE'
sleep 2

if [ -n "\$PID_PCD" ]; then
    kill "\$PID_PCD" || true
fi
kill "\$PID_LAUNCH" || true
kill "\$PID_CAM" || true
kill "\$PID_CORE" || true

if [ "$SAVE_PC" = "true" ]; then
    echo "Saving final pointcloud..."
    python3 -c "import glob, os, shutil; files = sorted(glob.glob('/output/pcd_tmp/*.pcd'), key=os.path.getmtime); shutil.copy(files[-1], '/output/pointcloud.pcd') if files else print('No PCD found')"
fi
EOF

chmod +x "$RUNNER_SCRIPT"

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

echo "Running ESVO2 in Docker..."
docker run --rm -it \
    --cpus="$DOCKER_CPUS" \
    --memory="8g" \
    $GPU_ARGS \
    $VIZ_ARGS \
    -v "$ESVO2_CONFIG_DIR:/esvo2_config:ro" \
    -v "$BAG_FILE:/data/input.bag:ro" \
    -v "$OUTPUT_DIR:/output" \
    -v "$LOGS_DIR:/root/.ros/log" \
    -v "$ESVO2_LAUNCH_FILE:/esvo2_launch.launch:ro" \
    -v "$RUNNER_SCRIPT:/esvo2_runner.sh:ro" \
    -v "$SRC_PYTHON/publish_camera_info.py:/scripts/publish_camera_info.py:ro" \
    "$ESVO2_IMAGE" \
    bash /esvo2_runner.sh

echo "Done. Results in $OUTPUT_DIR"
