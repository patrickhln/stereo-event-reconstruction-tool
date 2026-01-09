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
./sert record -p ./data -v
```
Creates `./data/session_YYYY-MM-DD_HH-MM-SS/`.

**Rendering (Events → Frames)**
```bash
./sert render -s ./data/session_YYYY-MM-DD_HH-MM-SS
```
Uses the `sert-python` conda environment to run E2VID.

**Calibration**
```bash
./sert calibrate -s ./data/session_YYYY-MM-DD_HH-MM-SS
```

## Session Structure

```text
session_YYYY-MM-DD_HH-MM-SS/
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

# Install E2VID (Reference / Manual Setup) [Optional]

> [!IMPORTANT]
> **Automated Installation**
>
> E2VID is included in this repository as a git submodule (`rpg_e2vid/`), pointing to a [fork](https://github.com/patrickhln/rpg_e2vid/tree/cpu-support) of [E2VID](https://github.com/uzh-rpg/rpg_e2vid).
>
> The steps below are handled **automatically** by `scripts/install_python_env.sh` (which sets up the E2VID environment) and **not required** for normal usage.
>
> The instructions here are provided primarily for reference and to document the underlying process.

The installation requires [Anaconda3](https://www.anaconda.com/download).
Minor adjustments were made to the code and installation requirements compared to the [original README](https://github.com/uzh-rpg/rpg_e2vid/blob/master/README.md) to ensure CPU compatibility.

## 1. Create the environment

```bash
conda create -n E2VID python=3.8
conda activate E2VID
```

## 2. Install Dependencies


```bash
conda install -y -c conda-forge pandas scipy opencv protobuf libprotobuf absl-py numpy=1.23.5
```

Since E2VID uses `np.int` which was deprecated in 1.20 and removed in 1.24 we
need to set numpy version explicitly

Now, for the pytorch installation, choose based on your hardware:

```bash
# NVIDIA GPU (CUDA 12.1)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# CPU only
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

## 3. Download model

Download the pretrained model:

```bash 
mkdir -p rpg_e2vid/pretrained
wget "http://rpg.ifi.uzh.ch/data/E2VID/models/E2VID_lightweight.pth.tar" -O rpg_e2vid/pretrained/E2VID_lightweight.pth.tar
```


# Third-party components

- **E2VID**: https://github.com/uzh-rpg/rpg_e2vid
    - Used via a fork (branch `cpu-support`) and included as a git submodule.
    - Fork: https://github.com/patrickhln/rpg_e2vid/tree/cpu-support
    - All original license information is preserved.
