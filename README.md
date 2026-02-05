# SERT - Stereo Event Reconstruction Tool

**Tested on:** Ubuntu 24.04 LTS
**Hardware:** DVXplorer

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
cmake -S . -B build/ -DCMAKE_BUILD_TYPE=Release
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
sudo usermod -aG video,render $USER  # Needed for GPU OpenGL in Docker
# For NVIDIA GPUs: install nvidia-container-toolkit on the host, then, for the run_esvo.sh use: --gpu nvidia
# To be integrated into cli
cd scripts
./docker_build.sh  # This might take a while! (~20min) 
```

# Usage

## Quick Start

```bash
# 1. Record calibration data
./build/Debug/sert record -p ./data -s lab -t calib

# 2. Convert events to frames using E2VID
./build/Debug/sert render -s ./data/session_lab -c calib_01

# 3. Run Kalibr calibration (with target config)
./build/Debug/sert calibrate -s ./data/session_lab -c calib_01 \
    -t checkerboard --config 7 5 0.043 0.043

# 4. Record a scene
./build/Debug/sert record -p ./data -s lab -t scene -n desk_test
```

Notes:
- `record` uses `-p` for the parent directory and optional `-s` for the session name (prefix `session_` is always added).
- Example: `-s lab` creates `session_lab/`.
- If no session name is provided, a `session_<timestamp>` folder is created.
- Other commands (`render`, `calibrate`) require a session directory path.

For more info on calibration targets, see: https://github.com/ethz-asl/kalibr/wiki/calibration-targets

## Session Structure

```text
<session>/
├── session.yaml                            # Session metadata + active calibration
├── config/
│   ├── targets/                            # Calibration target definitions
│   │   └── checkerboard.yaml
│   └── esvo/                               # ESVO configuration
│       ├── left.yaml                       # Left camera calibration (from camchain)
│       ├── right.yaml                      # Right camera calibration (from camchain)
│       ├── mapping.yaml                    # ESVO mapping parameters
│       ├── tracking.yaml                   # ESVO tracking parameters
│       └── ts_parameters.yaml              # Time surface parameters
├── calibrations/
│   ├── calib_01/                           # Calibration capture (auto)
│   │   ├── raw/
│   │   ├── intermediate/
│   │   ├── frames/
│   │   ├── stereo_frames-camchain.yaml     # Kalibr output
│   │   ├── stereo_frames-report-cam.pdf
│   │   └── stereo_frames-results-cam.txt
│   └── test/                               # Custom-named calibration capture
├── scenes/
│   ├── scene_2024-01-26_10-30-00/           # Auto-named scene
│   │   ├── raw/
│   │   ├── intermediate/
│   │   ├── frames/
│   │   └── reconstruction/esvo/
│   └── scene_desk_test/                    # Custom-named scene
└── logs/                                   # (planned) Session logs
```

## View Frames

```bash
ffplay -framerate 20 -pattern_type glob -i './data/session_lab/calibrations/calib_01/frames/left/*.png'
```

# Third-party Components

This project integrates the following third-party tools:

- **E2VID**: Event-to-video reconstruction - https://github.com/uzh-rpg/rpg_e2vid
  - Included as git submodule using a [fork](https://github.com/patrickhln/rpg_e2vid)
  - Requires `git clone --recursive` to initialize
- **Kalibr**: Camera calibration toolbox - https://github.com/ethz-asl/kalibr
- **ESVO**: Event-based Stereo Visual Odometry - https://github.com/HKUST-Aerial-Robotics/ESVO

All components are automatically set up by the installation scripts. Original licenses and attributions are preserved.

# ESVO Compatibility Note

The Docker environment provided in this project automatically handles a specific compatibility version for ESVO:
- **Commit**: `538b576` (Oct 2021)
- **Reason**: Newer commits of ESVO were found to produce degenerate results on small-scale datasets (like RPG/Indoor).
