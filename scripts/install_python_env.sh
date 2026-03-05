#!/bin/bash

# if any command fails, stop the script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# check if conda is available
if ! command -v conda &> /dev/null
then
	echo "Conda could not be found. Please install Anaconda3."
	exit 1
fi


# conda activate non-interactively
eval "$(conda shell.bash hook)"

ENV_NAME="sert-python"

# check if env already exists
if ./check_env.sh; then
    read -p "Do you want to remove it? [y/N]: " reinstall_ans
    if [[ "$reinstall_ans" =~ ^[Yy]$ ]]; then
        conda env remove -n "$ENV_NAME"
    else
        echo "Exiting..."
        exit 0
    fi
fi

read -p "Do you want to install the sert-python environment? [Y/n]: " answer
if [[ "$answer" == "n" || "$answer" == "N" ]]; then
    echo "Exiting..."
    exit 0
fi

echo "Creating sert-python environment..."

conda create -y -n sert-python python=3.10
conda activate sert-python

echo "Installing E2VID dependencies..."
conda install -y -c conda-forge pandas scipy opencv protobuf libprotobuf absl-py numpy=1.23.5

echo "Installing ROS specific tools..."
pip install rosbags 

echo "Installing dv-processing, PyYAML..."
pip install dv-processing PyYAML

echo "Installing others..."
pip install gdown matplotlib opencv-python

# adding event_cnn_minimal dependencies
pip install tqdm h5py scikit-image thop

echo "Checking Graphics Card Vendor (requires \`pciutils\`)..."

# Default to CPU
INSTALL_TYPE="cpu"
E2VID_BRANCH="master"

if command -v lspci &> /dev/null; then
    gpu_info=$(lspci | grep -Ei "vga|3d|display")
    if echo "$gpu_info" | grep -qi nvidia; then
        INSTALL_TYPE="cuda"
    elif echo "$gpu_info" | grep -qi intel; then
        INSTALL_TYPE="xpu"
    fi
else
    echo "Warning: 'lspci' command not found. Unable to auto-detect GPU."
    echo "Assuming CPU-only installation to be safe."
fi

if [[ "$INSTALL_TYPE" == "cuda" ]]; then
    echo "NVIDIA GPU found -> installing PyTorch with CUDA"
    pip install torch torchvision
elif [[ "$INSTALL_TYPE" == "xpu" ]]; then
    echo "Intel GPU found -> installing PyTorch XPU + IPEX"
	pip install torch==2.8.0+xpu torchvision==0.23.0+xpu --index-url https://download.pytorch.org/whl/xpu
	pip install intel-extension-for-pytorch==2.8.0
else
    echo "No NVIDIA GPU found (or lspci missing) -> installing CPU-only PyTorch"
	pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi

echo
echo "Switching rpg_e2vid submodule to '$E2VID_BRANCH' branch..."
cd ../rpg_e2vid
git fetch origin
git checkout "$E2VID_BRANCH"
cd ../scripts

echo

echo "Checking E2VID pretrained model..."
mkdir -p ../data/models/e2vid
if [ -f ../data/models/e2vid/E2VID_lightweight.pth.tar ]; then
    echo "E2VID pretrained model already exists. Skipping download."
else
    echo "Downloading E2VID pretrained model..."
    wget -q --show-progress "http://rpg.ifi.uzh.ch/data/E2VID/models/E2VID_lightweight.pth.tar" -O ../data/models/e2vid/E2VID_lightweight.pth.tar
fi

echo "Checking event_cnn_minimal pretrained models..."
mkdir -p ../data/models/event_cnn_minimal
if [ -f ../data/models/event_cnn_minimal/firenet/firenet_all_cts.pth ] && \
   [ -f ../data/models/event_cnn_minimal/flow/flow_model.pth ] && \
   [ -f ../data/models/event_cnn_minimal/reconstruction/reconstruction_model.pth ]; then
    echo "event_cnn_minimal pretrained models already exist. Skipping download."
else
    echo "Downloading event_cnn_minimal pretrained models..."
    gdown --folder "https://drive.google.com/drive/folders/1J6PbqYPOGlyspYsdH4fgg5pZpc_l-BOD?usp=drive_link" -O ../data/models/event_cnn_minimal
fi

echo "Installation Complete!"
