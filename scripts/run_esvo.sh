#!/bin/bash

# Wrapper to run ESVO inside docker
# Usage: ./run_esvo.sh <session_path> [playback_rate]
#
# Prerequisites:
#   1. Session must have: /intermediate/scene_events.bag (with stereo events)
#   2. Session must have: /config/esvo/system_custom.launch (custom launch file)
#   3. Session must have: /config/esvo/calib/left.yaml and right.yaml (ESVO format calibration)
#
# The launch file and calibration must be generated from Kalibr output.
# See ESVO_Guide.md for the required file formats.

SESSION_PATH="$1"
PLAYBACK_RATE="${2:-0.5}"  # Default to 0.5x speed

if [ -z "$SESSION_PATH" ]; then
	echo "Usage: $0 <session_path> [playback_rate]"
	echo ""
	echo "Arguments:"
	echo "  session_path   - Path to session directory"
	echo "  playback_rate  - Rosbag playback rate (default: 0.5)"
	echo ""
	echo "Required session structure:"
	echo "  session_path/"
	echo "    ├── intermediate/scene_events.bag"
	echo "    └── config/esvo/"
	echo "        ├── system_custom.launch"
	echo "        ├── mapping.yaml"
	echo "        ├── tracking.yaml"
	echo "        ├── ts_parameters.yaml"
	echo "        └── calib/"
	echo "            ├── left.yaml"
	echo "            └── right.yaml"
	exit 1
fi

# Relative to absolute path
SESSION_PATH=$(realpath "$SESSION_PATH")

# Validate required files exist
if [ ! -f "$SESSION_PATH/intermediate/scene_events.bag" ]; then
	echo "ERROR: scene_events.bag not found at $SESSION_PATH/intermediate/"
	exit 1
fi

if [ ! -f "$SESSION_PATH/config/esvo/system_custom.launch" ]; then
	echo "ERROR: system_custom.launch not found at $SESSION_PATH/config/esvo/"
	echo "Generate it using 'sert calibrate' or create manually. See ESVO_Guide.md"
	exit 1
fi

if [ ! -f "$SESSION_PATH/config/esvo/calib/left.yaml" ] || [ ! -f "$SESSION_PATH/config/esvo/calib/right.yaml" ]; then
	echo "ERROR: Calibration files (left.yaml, right.yaml) not found at $SESSION_PATH/config/esvo/calib/"
	echo "Convert from Kalibr output. See ESVO_Guide.md"
	exit 1
fi

# Calculate global timer rate based on playback speed
# ESVO time surfaces need to update at 100Hz in simulation time
# timer_rate = 100 * playback_rate
TIMER_RATE=$(echo "$PLAYBACK_RATE * 100" | bc)
echo "Playback rate: ${PLAYBACK_RATE}x -> Global timer: ${TIMER_RATE}Hz"

# Enable X11 forwarding for RViz visualization
xhost +local:root 2>/dev/null || true

echo "Starting ESVO with session: $SESSION_PATH"
echo "Press Ctrl+C to stop"

docker run --rm -it \
	-e DISPLAY \
	-v /tmp/.X11-unix:/tmp/.X11-unix:rw \
	-v "$SESSION_PATH:/data" \
	sert-ros:latest \
	bash -c "
		# Source ROS setup
		source /catkin_ws/devel/setup.bash

		# Set simulation time (required for offline processing)
		rosparam set /use_sim_time true

		# Launch ESVO system (runs in background)
		roslaunch /data/config/esvo/system_custom.launch \
			playback_rate:=$PLAYBACK_RATE \
			timer_rate:=$TIMER_RATE &

		ESVO_PID=\$!

		# Wait for nodes to initialize
		echo 'Waiting for ESVO nodes to initialize...'
		sleep 8

		# Check if time surfaces are publishing
		echo 'Checking time surface topics...'
		rostopic hz /TS_left --window=5 &
		sleep 3
		kill %2 2>/dev/null

		# Play the event bag
		echo 'Playing event bag at ${PLAYBACK_RATE}x speed...'
		rosbag play /data/intermediate/scene_events.bag --clock -r $PLAYBACK_RATE

		# After bag finishes, give time for final processing
		echo 'Bag playback complete. Waiting for final processing...'
		sleep 5

		# Signal ESVO to save trajectory and terminate
		echo 'Saving trajectory and terminating...'
		rosparam set /ESVO_SYSTEM_STATUS 'TERMINATE'
		sleep 3

		# Cleanup
		kill \$ESVO_PID 2>/dev/null
		echo 'ESVO processing complete.'
		echo 'Check /data/reconstruction/ for outputs.'
	"
