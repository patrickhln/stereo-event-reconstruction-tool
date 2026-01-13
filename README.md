# SERT - Stereo Event Reconstruction Tool

**Tested on:** Ubuntu 24.04 LTS

# Installation

## 1. System Dependencies
```bash
sudo apt update
sudo apt install -y build-essential cmake git wget pciutils ffmpeg
```

## 2. DV-Processing
```bash
sudo add-apt-repository ppa:ubuntu-toolchain-r/test
sudo add-apt-repository ppa:inivation-ppa/inivation
sudo apt update
sudo apt install dv-processing
```
Please refer to the official docs for other platforms: (https://dv-processing.inivation.com/master/installation.html)

**OpenCV** 
```bash
sudo apt install -y libopencv-dev
```

## 3. Build SERT
```bash
git clone --recursive git@github.com:patrickhln/stereo-event-reconstruction-tool.git
cd stereo-event-reconstruction-tool
mkdir -p build 
cmake -S . -B build/ -DCMAKE_BUILD_TYPE=Debug
cmake --build build
```

## 4. Python Environment (for E2VID)
Install [Anaconda](https://www.anaconda.com/download) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html), then:
```bash
cd scripts
./install_python_env.sh
```

## 5. Docker (for Kalibr/ESVO)
```bash
sudo apt install -y docker.io
sudo usermod -aG docker $USER  # Log out and back in after this
cd scripts
./docker_build.sh  # This might take a while! (~20min) 
```

# Usage

**Recording**
```bash
./sert record -p <path> -v
```
Creates `<path>/session_YYYY-MM-DD_HH-MM-SS/` (default timestamp-based name) or `<path>/session_<name>/` if using `-n <name>` option.

**Rendering (Events → Frames)**
```bash
./sert render -s <path>/session_<name>
```
Uses the `sert-python` conda environment to run E2VID.

**Calibration**

If a calibration config already exists in `<session>/config/`:
```bash
./sert calibrate -s <path>/session_<name>
```

Or create a new calibration config and run calibration:
```bash
# Checkerboard example: 7x5 inner corners, 4.3cm spacing
./sert calibrate -s <path>/session_<name> -t checkerboard -c 7 5 0.043 0.043

# Aprilgrid example: 6x6 tags, 88mm tag size, 30% spacing
./sert calibrate -s <path>/session_<name> -t aprilgrid -c 6 6 0.088 0.3

# Circlegrid example: 7x6 circles, 3.2cm spacing, asymmetric
./sert calibrate -s <path>/session_<name> -t circlegrid -c 7 6 0.032 1
```

For more info on calibration targets, see: https://github.com/ethz-asl/kalibr/wiki/calibration-targets

## Session Structure

```text
session_<name>/
├── config/
│   ├── checkerboard.yaml             # Calibration target (user edits)
│   ├── esvo_stereo.yaml              # Auto-generated from Kalibr
│   └── esvo_custom.launch            # Auto-generated ROS launch file
├── raw/
│   ├── stereo_recording.aedat4       # Raw event data
│   └── camera_metadata.txt           # Camera info (left and right)
├── intermediate/
│   ├── leftEvents.txt                # E2VID input
│   ├── rightEvents.txt               # E2VID input
│   ├── stereo_frames.bag             # ROS bag for Kalibr
│   └── scene_events.bag              # ROS bag for ESVO
├── reconstruction/
│   ├── left/                         # E2VID output frames
│   └── right/                        # E2VID output frames
├── calibration/
│   ├── camchain-stereo_frames.yaml   # Kalibr output (intrinsics + extrinsics)
│   └── report-stereo_frames.pdf      # Kalibr calibration report
└── esvo/
    ├── trajectory.txt                # Estimated camera poses
    └── pointcloud.pcd                # 3D reconstruction result
```

**View the created Frames**
```bash
ffplay -framerate 20 -pattern_type glob -i '<session>/reconstruction/{left/right}/*.png'
```

# Third-party Components

This project integrates the following third-party tools:

- **E2VID**: Event-to-video reconstruction - https://github.com/uzh-rpg/rpg_e2vid
  - Included as git submodule using a [fork](https://github.com/patrickhln/rpg_e2vid)
  - Requires `git clone --recursive` to initialize
- **Kalibr**: Camera calibration toolbox - https://github.com/ethz-asl/kalibr
- **ESVO**: Event-based Stereo Visual Odometry - https://github.com/HKUST-Aerial-Robotics/ESVO

All components are automatically set up by the installation scripts. Original licenses and attributions are preserved.

