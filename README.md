# SERT - Stereo Event Reconstruction Tool

**Tested on:** Ubuntu 24.04 LTS
**Hardware:** DVXplorer

# Installation

## 1. System Dependencies
```bash
sudo apt update
sudo apt install -y build-essential cmake git wget pciutils ffmpeg pcl-tools
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
# For NVIDIA GPUs: install nvidia-container-toolkit on the host, then, for the run_esvo(2).sh use: --gpu nvidia
# To be integrated into cli
cd scripts
./docker_build_esvo_kalibr.sh  
./docker_build_esvo2.sh
# Building these images might take a while! 
```

# Usage

## Quick Start

```bash
# 1. Record calibration (creates 'lab/' session in current directory)
./sert record lab -t calib

# 2. Convert events to frames using E2VID
./sert render lab/calibrations/calib_01

# 3. Run Kalibr calibration (with target config)
./sert calibrate lab/calibrations/calib_01 \
    -t checkerboard --config 8 6 0.068 0.068

# 4. Record a scene
./sert record lab -t scene -n outdoor

# 5. Create a filtered sibling branch from the baseline capture
./sert filter lab/scenes/outdoor --config lab/config/filters/hot_then_ba.yaml
```

A path such as `lab/scenes/outdoor` is a capture group. It contains the baseline `unfiltered/` branch and optional sibling branches such as `filtered_hot_then_ba/`. Rendering, calibration, bag conversion, and downstream reconstruction operate on a chosen branch root.

For more info on calibration targets, see: https://github.com/ethz-asl/kalibr/wiki/calibration-targets

**Commands:**
```
record [<session>] -t calib|scene [-n <name>] [-v]
render <path>
filter <group_or_branch_path> --config <path/to/config.yaml>
calibrate <path> [-t <target> --config <args>]
set-calibration <path>
```

**Notes:**
- Session names are user-defined or automatically generated with timestamp suffix.
- If session not specified, `record` uses current directory
- Tool auto-detects session root by finding `session.yaml`
- Group-root paths resolve to the `unfiltered` branch where applicable; filtered branches are addressed explicitly
- Reconstruction runners use an explicit `--calibration` branch 
- Run `./build/Debug/sert` without arguments to see full help

## Filter chains (YAML)

- New sessions auto-create filter presets in `<session>/config/filters/`:
  - `hot_only.yaml`
  - `ba_only.yaml`
  - `hot_then_ba.yaml`
  - `ba_then_hot.yaml`

```bash
./sert filter <session>/scenes/<scene> --config <session>/config/filters/hot_then_ba.yaml
```

- Or pass any custom yaml path:

```bash
./sert filter <session>/scenes/<scene> --config /tmp/custom_chain.yaml
```

- Filtering creates a sibling branch named `filtered_<config_stem>/`
- Each branch keeps its own `raw/`, `intermediate/`, `frames/`, and scene `reconstruction/` outputs
- Chain order in YAML is the order applied at runtime.
- Full filter reference (all types + options): `docs/filter_chains.md`

## Session Structure

Capture groups live under `scenes/` and `calibrations/`; each group contains one baseline `unfiltered/` branch and optional `filtered_<config_stem>/` sibling branches.

```text
<session>/
├── session.yaml                            # Session metadata + active calibration
├── config/
│   ├── targets/                            # Calibration target definitions
│   │   └── checkerboard.yaml
│   ├── filters/                            # Event filter chains
│   │   ├── hot_only.yaml
│   │   ├── ba_only.yaml
│   │   ├── hot_then_ba.yaml
│   │   └── ba_then_hot.yaml
│   ├── esvo/                                  # ESVO configuration
│   │   ├── left.yaml                          # Left camera calibration (from camchain)
│   │   ├── right.yaml                         # Right camera calibration (from camchain)
│   │   ├── mapping.yaml                       # ESVO mapping parameters
│   │   ├── tracking.yaml                      # ESVO tracking parameters
│   │   └── ts_parameters.yaml                 # Time surface parameters
│   ├── esvo2/                                 # ESVO2 configuration
│       ├── left.yaml                          # Left camera + IMU calibration (from camchain)
│       ├── right.yaml                         # Right camera + IMU calibration (from camchain)
│       ├── mapping.yaml                       # ESVO2 mapping parameters
│       ├── tracking.yaml                      # ESVO2 tracking parameters
│       ├── image_representation.yaml          # Instead of Time surface parameters (left)
│       └── image_representation_right.yaml    # Instead of Time surface parameters (right)
├── calibrations/
│   ├── calib_01/                              # Calibration capture group (auto)
│   │   ├── unfiltered/
│   │   │   ├── raw/
│   │   │   ├── intermediate/
│   │   │   ├── frames/
│   │   │   ├── stereo_frames-camchain.yaml    # Kalibr output
│   │   │   ├── stereo_frames-report-cam.pdf
│   │   │   └── stereo_frames-results-cam.txt
│   │   └── filtered_hot_then_ba/
│   │       ├── raw/
│   │       ├── intermediate/
│   │       ├── frames/
│   │       ├── stereo_frames-camchain.yaml
│   │       ├── stereo_frames-report-cam.pdf
│   │       └── stereo_frames-results-cam.txt
│   └── test/                               # Custom-named calibration capture group
├── scenes/
│   ├── scene_2024-01-26_10-30-00/           # Auto-named scene capture group
│   │   ├── unfiltered/
│   │   │   ├── raw/
│   │   │   ├── intermediate/
│   │   │   ├── frames/
│   │   │   └── reconstruction/
│   │   ├── filtered_hot_only/
│   │   │   ├── raw/
│   │   │   ├── intermediate/
│   │   │   ├── frames/
│   │   │   └── reconstruction/
│   │   └── filtered_hot_then_ba/
│   │       ├── raw/
│   │       ├── intermediate/
│   │       ├── frames/
│   │       └── reconstruction/
│   └── scene_desk_test/                    # Custom-named scene capture group
└── logs/                                   # (planned) Session logs
```

## View Frames

```bash
ffplay -framerate 20 -pattern_type glob -i '*.png'
```

# Third-party Components

This project integrates the following third-party tools:

- **E2VID**: Event-to-video reconstruction - https://github.com/uzh-rpg/rpg_e2vid
  - Included as git submodule using a [fork](https://github.com/patrickhln/rpg_e2vid)
  - Requires `git clone --recursive` to initialize
- **event_cnn_minimal**: Minimal code for loading models trained for ECCV'20 
  - Included as git submodule using a [fork](https://github.com/patrickhln/event_cnn_minimal)
  - Requires `git clone --recursive` to initialize
- **Kalibr**: Camera calibration toolbox - https://github.com/ethz-asl/kalibr
- **ESVO**: Event-based Stereo Visual Odometry - https://github.com/HKUST-Aerial-Robotics/ESVO
- **ESVO2**: Direct Visual-Intertial Odometry with Stereo Event Cameras: https://github.com/NAIL-HNU/ESVO2
- **RTAB-Map**: Real-Time Appearance-Based Mapping - https://github.com/introlab/rtabmap

All components are automatically set up by the installation scripts. Original licenses and attributions are preserved.

# ESVO Compatibility Note

The Docker environment provided in this project automatically handles a specific compatibility version for ESVO:
- **Commit**: `538b576` 
- **Reason**: Newer commits of ESVO were found to produce degenerate results on small-scale datasets (like RPG/Indoor).
