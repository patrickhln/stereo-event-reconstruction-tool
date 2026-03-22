#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/lib/path_utils.sh"

# ESVO2 Runner Script
# Usage: ./run_esvo2.sh <scene_branch_root> <calibration_branch_root> [OPTIONS]
#
# Options:
#   --model <m>     Calibration model to load
#   --no-viz        Run without visualization (headless)
#   --rate <r>      Bag playback rate (default: 0.2)
#   --min-depth <m> Minimum expected scene depth in meters (default: 0.5)
#   --max-depth <m> Maximum expected scene depth in meters (default: 10.0)
#   --save-pc       Save final pointcloud to file
#   --gpu <mode>    GPU mode: auto|intel|amd|nvidia|cpu (default: auto)
#   --use-imu       Enable IMU integration (requires bag with /davis/left/imu)

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <scene_branch_root> <calibration_branch_root> [OPTIONS]"
    echo "Example: $0 lab/scenes/scene_01/unfiltered lab/calibrations/calib_01/unfiltered --model e2vid"
    echo ""
    echo "Options:"
    echo "  --model <m>   Calibration model to load"
    echo "  --no-viz      Run without visualization"
    echo "  --rate <r>    Bag playback rate (default: 0.2)"
    echo "  --min-depth   Minimum expected scene depth in meters (default: 0.5)"
    echo "  --max-depth   Maximum expected scene depth in meters (default: 10.0)"
    echo "  --save-pc     Save final pointcloud"
    echo "  --use-imu     Enable IMU integration"
    echo "  --gpu <mode>  GPU mode: auto|intel|amd|nvidia|cpu"
    exit 1
fi

SCENE_ARG="$1"
CALIB_ARG="$2"
shift 2

SCENE_DIR=$(require_branch_root "$SCENE_ARG") || exit 1
SESSION_PATH=$(find_session_root "$SCENE_DIR") || exit 1
SCENE_DIR=$(require_branch_in_session_subdir "$SCENE_DIR" "$SESSION_PATH" scenes) || exit 1
CALIB_DIR=$(require_branch_root "$CALIB_ARG") || exit 1
CALIB_DIR=$(require_branch_in_session_subdir "$CALIB_DIR" "$SESSION_PATH" calibrations) || exit 1

SRC_PYTHON="$PROJECT_ROOT/src/python"
ESVO2_IMAGE="sert-esvo2:latest"
ESVO2_LAUNCH_FILE="$SCRIPT_DIR/launch/esvo2/offline_system.launch"

# Defaults
VISUALIZE=true
PLAYBACK_RATE=0.2
MIN_DEPTH=0.5
MAX_DEPTH=10.0
SAVE_PC=false
GPU_MODE=auto
USE_IMU=false
MODEL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --model) MODEL="$2"; shift 2 ;;
        --no-viz) VISUALIZE=false; shift ;;
        --rate) PLAYBACK_RATE="$2"; shift 2 ;;
        --min-depth) MIN_DEPTH="$2"; shift 2 ;;
        --max-depth) MAX_DEPTH="$2"; shift 2 ;;
        --save-pc) SAVE_PC=true; shift ;;
        --gpu) GPU_MODE="$2"; shift 2 ;;
        --use-imu) USE_IMU=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$MODEL" ]]; then
    echo "Error: --model is required."
    exit 1
fi

echo "=== ESVO2 Runner ==="
echo "Session:      $SESSION_PATH"
echo "Scene branch: $SCENE_DIR"
echo "Calibration:  $CALIB_DIR"
echo "Calib model:  $MODEL"
echo "Depth:        ${MIN_DEPTH}m - ${MAX_DEPTH}m"
echo "IMU:          $USE_IMU"

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
mkdir -p "$ESVO2_CONFIG_DIR"

echo "Generating ESVO2 calibration files (left.yaml, right.yaml)..."
python3 "$SRC_PYTHON/camchain_to_esvo2.py" "$CALIB_DIR" "$ESVO2_CONFIG_DIR" --model "$MODEL"

BAG_FILE="$SCENE_DIR/intermediate/scene_events_with_caminfo_${MODEL}.bag"

echo "Regenerating scene event bag with calibration for model '$MODEL'..."
AEDAT4_ARGS=(
    --path "$SCENE_DIR"
    --calibration "$ESVO2_CONFIG_DIR"
    --model "$MODEL"
)
if [[ "$USE_IMU" == "true" ]]; then
    AEDAT4_ARGS+=(--with-imu)
fi
python3 "$SRC_PYTHON/aedat4_to_bag.py" "${AEDAT4_ARGS[@]}"

echo "Bag file: $BAG_FILE"

echo "Checking bag for camera_info topics /davis/left/camera_info and /davis/right/camera_info ..."
if ! docker run --rm \
    -v "$BAG_FILE:/data/input.bag:ro" \
    "$ESVO2_IMAGE" \
    /bin/bash -lc "rosbag info /data/input.bag | grep -q '/davis/left/camera_info' && rosbag info /data/input.bag | grep -q '/davis/right/camera_info'"; then
    echo "Error: ESVO2 requires /davis/left/camera_info and /davis/right/camera_info in:"
    echo "  $BAG_FILE"
    echo "Regenerate the bag with calibration embedded, for example:"
    echo "  python3 src/python/aedat4_to_bag.py --path $SCENE_DIR --calibration $ESVO2_CONFIG_DIR --model $MODEL"
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
        echo "  python3 src/python/aedat4_to_bag.py --path $SCENE_DIR --with-imu"
        exit 1
    fi

    IMU_CAMCHAIN_FILE="$CALIB_DIR/calibration/$MODEL/stereo_frames-camchain-imucam.yaml"
    if [[ ! -f "$IMU_CAMCHAIN_FILE" ]]; then
        echo "WARNING: No dedicated IMU-camera calibration found at: $IMU_CAMCHAIN_FILE"
        echo "WARNING: EXPLORATORY ABLATION ONLY: --use-imu without IMU-camera calibration risks rotation misalignment and wrong IMU noise/bias parameters."
        echo "WARNING: Do not treat this as a calibrated visual-inertial result."
    fi
fi

# Always regenerate runtime configs for deterministic behavior
echo "Generating ESVO2 runtime configs (mapping/tracking/image_representation)..."
RUNTIME_ARGS=(
    --session "$SESSION_PATH"
    --min-depth "$MIN_DEPTH"
    --max-depth "$MAX_DEPTH"
)
if [[ "$USE_IMU" == "true" ]]; then
    RUNTIME_ARGS+=(--use-imu)
fi
python3 "$SRC_PYTHON/generate_esvo2_config.py" "${RUNTIME_ARGS[@]}"

GENERATION_RATE_HZ=$(python3 - <<PY
import yaml
with open("$ESVO2_CONFIG_DIR/image_representation.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}
rate = cfg.get("generation_rate_hz", 100)
try:
    rate = int(rate)
except Exception:
    rate = 100
print(max(rate, 1))
PY
)

echo "Playback rate: $PLAYBACK_RATE"
echo "Image representation rate (sim time): $GENERATION_RATE_HZ"

OUTPUT_DIR="$SCENE_DIR/reconstruction/esvo2"
LOGS_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$OUTPUT_DIR"

echo "Output dir: $OUTPUT_DIR"

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
    "$ESVO2_IMAGE" \
    bash /esvo2_runner.sh

echo "Done. Results in $OUTPUT_DIR"
