#!/bin/bash
set -e

# RTAB-Map Runner (offline stereo frame bag)
# Usage: ./run_rtabmap.sh <session_path> <scene_name_or_scene_path> [OPTIONS]
#
# Options:
#   --no-viz        Run without RViz
#   --rate <r>      Bag playback rate (default: 0.2)
#   --save-pc       Save final pointcloud to reconstruction folder
#   --gpu <mode>    GPU mode: auto|intel|amd|nvidia|cpu (default: auto)

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <session_path> <scene_name_or_scene_path> [OPTIONS]"
    exit 1
fi

SESSION_PATH=$(realpath "$1")
SCENE_ARG="$2"
shift 2

# scene arg can be a name or path
if [[ -d "$SCENE_ARG" ]]; then
    SCENE_DIR=$(realpath "$SCENE_ARG")
elif [[ -d "$SESSION_PATH/scenes/$SCENE_ARG" ]]; then
    SCENE_DIR="$SESSION_PATH/scenes/$SCENE_ARG"
else
    echo "Error: Scene '$SCENE_ARG' not found."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RTABMAP_IMAGE="sert-rtabmap:latest"
RTABMAP_LAUNCH_FILE="$SCRIPT_DIR/launch/rtabmap/offline_stereo.launch"

# defaults
VISUALIZE=true
PLAYBACK_RATE=0.2
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

echo "=== RTAB-Map Runner ==="
echo "Session: $SESSION_PATH"
echo "Scene:   $SCENE_DIR"

if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker command not found."
    exit 1
fi

if ! docker image inspect "$RTABMAP_IMAGE" >/dev/null 2>&1; then
    echo "Error: Docker image '$RTABMAP_IMAGE' not found."
    echo "Build it first with: ./scripts/docker_build_rtabmap.sh"
    exit 1
fi

if [[ ! -f "$RTABMAP_LAUNCH_FILE" ]]; then
    echo "Error: Launch file not found: $RTABMAP_LAUNCH_FILE"
    exit 1
fi

BAG_FILE="$SCENE_DIR/intermediate/stereo_frames.bag"
if [[ ! -f "$BAG_FILE" ]]; then
    echo "Error: Bag file not found: $BAG_FILE"
    exit 1
fi

OUTPUT_DIR="$SCENE_DIR/reconstruction/rtabmap"
mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_DIR/rtabmap.db"
if [[ "$SAVE_PC" == "true" ]]; then
    rm -f "$OUTPUT_DIR/pointcloud.pcd"
    rm -f "$OUTPUT_DIR/pointcloud_cloud.ply"
fi
rm -f "$OUTPUT_DIR/rtabmap_odom.txt" "$OUTPUT_DIR/rtabmap_slam.txt" "$OUTPUT_DIR/report.csv"

echo "Input bag:      $BAG_FILE"
echo "Output dir:     $OUTPUT_DIR"
echo "Playback rate:  $PLAYBACK_RATE"
echo "Visualization:  $VISUALIZE"
echo "Save pointcloud:$SAVE_PC"

RUNNER_SCRIPT=$(mktemp /tmp/rtabmap_runner_XXXXXX.sh)

cleanup_tmp_files() {
    rm -f "$RUNNER_SCRIPT"
}
trap cleanup_tmp_files EXIT

cat > "$RUNNER_SCRIPT" <<EOF
#!/bin/bash
set -e
source /opt/ros/noetic/setup.bash

echo "Starting ROS core..."
roscore &
PID_CORE=\$!
sleep 2

echo "Launching stereo_image_proc + RTAB-Map..."
roslaunch /rtabmap.launch enable_viz:=$VISUALIZE &
PID_LAUNCH=\$!
sleep 8

echo "Playing bag..."
rosbag play /data/input.bag --clock -r $PLAYBACK_RATE --delay=2

echo "Bag finished. Letting RTAB-Map flush pending work..."
sleep 5

echo "Stopping launched RTAB-Map nodes cleanly..."
for node in /rtabmapviz /rtabmap /stereo_odometry /stereo/stereo_image_proc; do
    rosnode kill "\$node" >/dev/null 2>&1 || true
done

for _ in \$(seq 1 10); do
    if ! kill -0 "\$PID_LAUNCH" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

kill "\$PID_LAUNCH" >/dev/null 2>&1 || true

if [[ -f /output/rtabmap.db ]]; then
    echo "Waiting for database writes to settle..."
    prev_size=-1
    stable_count=0
    for _ in \$(seq 1 10); do
        current_size=\$(stat -c%s /output/rtabmap.db 2>/dev/null || echo 0)
        if [[ "\$current_size" -gt 0 && "\$current_size" -eq "\$prev_size" ]]; then
            stable_count=\$((stable_count + 1))
            if [[ "\$stable_count" -ge 2 ]]; then
                break
            fi
        else
            stable_count=0
        fi
        prev_size=\$current_size
        sleep 1
    done
fi

if [[ -f /output/rtabmap.db ]]; then
    # quick text outputs from db
    export QT_QPA_PLATFORM=offscreen
    rtabmap-report --poses /output/rtabmap.db >/tmp/rtabmap_report.log 2>&1 || true
    (cd /output && rtabmap-report --report /output/rtabmap.db >/tmp/rtabmap_report_summary.log 2>&1 || true)

    if [[ "$SAVE_PC" == "true" ]]; then
        # rtabmap exports merged cloud as ply
        rtabmap-export --cloud --ascii --output_dir /output --output pointcloud /output/rtabmap.db >/tmp/rtabmap_export.log 2>&1 || true
    fi
fi

kill "\$PID_CORE" >/dev/null 2>&1 || true
EOF

chmod +x "$RUNNER_SCRIPT"

VIZ_ARGS=""
if [[ "$VISUALIZE" == "true" ]]; then
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

echo "Running RTAB-Map in Docker..."
DOCKER_TTY_ARGS="-i"
if [[ -t 1 ]]; then
    DOCKER_TTY_ARGS="-it"
fi

docker run --rm $DOCKER_TTY_ARGS \
    --cpus="$DOCKER_CPUS" \
    --memory="8g" \
    $GPU_ARGS \
    $VIZ_ARGS \
    -v "$BAG_FILE:/data/input.bag:ro" \
    -v "$OUTPUT_DIR:/output" \
    -v "$RTABMAP_LAUNCH_FILE:/rtabmap.launch:ro" \
    -v "$RUNNER_SCRIPT:/rtabmap_runner.sh:ro" \
    "$RTABMAP_IMAGE" \
    bash /rtabmap_runner.sh

# fallback: convert ply -> pcd if docker didnt produce one directly
if [[ "$SAVE_PC" == "true" && ! -f "$OUTPUT_DIR/pointcloud.pcd" && -f "$OUTPUT_DIR/pointcloud_cloud.ply" ]]; then
    if command -v pcl_ply2pcd >/dev/null 2>&1; then
        pcl_ply2pcd "$OUTPUT_DIR/pointcloud_cloud.ply" "$OUTPUT_DIR/pointcloud.pcd" || true
    else
        echo "Warning: pcl_ply2pcd not found. Install pcl-tools: sudo apt install pcl-tools"
    fi
fi

echo "Done. Results in $OUTPUT_DIR"
if [[ -f "$OUTPUT_DIR/rtabmap.db" ]]; then
    echo "DB:  $OUTPUT_DIR/rtabmap.db"
fi
if [[ -f "$OUTPUT_DIR/pointcloud.pcd" ]]; then
    echo "PCD: $OUTPUT_DIR/pointcloud.pcd"
fi
if [[ -f "$OUTPUT_DIR/pointcloud_cloud.ply" ]]; then
    echo "PLY: $OUTPUT_DIR/pointcloud_cloud.ply"
fi
if [[ -f "$OUTPUT_DIR/rtabmap_odom.txt" ]]; then
    echo "VO:  $OUTPUT_DIR/rtabmap_odom.txt"
fi
if [[ -f "$OUTPUT_DIR/rtabmap_slam.txt" ]]; then
    echo "SLAM:$OUTPUT_DIR/rtabmap_slam.txt"
fi
if [[ -f "$OUTPUT_DIR/report.csv" ]]; then
    echo "REP: $OUTPUT_DIR/report.csv"
fi
