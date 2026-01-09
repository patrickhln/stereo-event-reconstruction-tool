#!/bin/bash

# if any command fails, stop the script
set -e

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

conda create -y -n sert-python python=3.8
conda activate sert-python

echo "Installing E2VID dependencies..."
conda install -y -c conda-forge pandas scipy opencv protobuf libprotobuf absl-py numpy=1.23.5

echo "Installing ROS bag tools..."
pip install rosbags

echo "Checking Graphics Card Vendor (requires \`pciutils\`)..."

# Default to CPU
INSTALL_TYPE="cpu"

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
    echo "NVIDIA GPU found -> installing PyTorch with CUDA 10.0"
    conda install -y pytorch torchvision cudatoolkit=10.0 -c pytorch
    E2VID_BRANCH="master"
elif [[ "$INSTALL_TYPE" == "xpu" ]]; then
    echo "Intel GPU detected, but XPU support has complex dependencies"
    echo "Falling back to CPU-only installation"
    conda install -y pytorch torchvision cpuonly -c pytorch
    E2VID_BRANCH="cpu-support"
else
    echo "No NVIDIA GPU found (or lspci missing) -> installing CPU-only PyTorch"
    conda install -y pytorch torchvision cpuonly -c pytorch
    E2VID_BRANCH="cpu-support"
fi

echo
echo "Switching rpg_e2vid submodule to '$E2VID_BRANCH' branch..."
cd ../rpg_e2vid
git fetch origin
git checkout "$E2VID_BRANCH"
cd ../scripts

echo

echo "Downloading pretrained model..."
mkdir -p ../rpg_e2vid/pretrained
wget -q --show-progress "http://rpg.ifi.uzh.ch/data/E2VID/models/E2VID_lightweight.pth.tar" -O ../rpg_e2vid/pretrained/E2VID_lightweight.pth.tar
# wget "http://rpg.ifi.uzh.ch/data/E2VID/models/E2VID_lightweight.pth.tar" -O ../rpg_e2vid/pretrained/E2VID_lightweight.pth.tar

echo "Installation Complete!"

