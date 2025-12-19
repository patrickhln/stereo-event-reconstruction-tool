#!/bin/bash -l

# -l stands for login (load user profile before running commands)

ENV_NAME="E2VID"

# standard conda installation path
CONDA_PATH="$HOME/anaconda3/etc/profile.d/conda.sh"

if [ -f "$CONDA_PATH" ]; then
    source "$CONDA_PATH"
else
    # Fallback: try sourcing bashrc if the specific conda file isn't found
    source "$HOME/.bashrc"
fi

# 2. Check if conda is available now
if ! command -v conda &> /dev/null
then
    echo "Conda could not be found. Please check the path in the script."
    exit 2
fi

eval "$(conda shell.bash hook)"

if conda env list | grep -q "^$ENV_NAME "; then
    echo "Environment '$ENV_NAME' is already installed."
    exit 0 
else
    echo "Environment '$ENV_NAME' was not found."
    exit 1 
fi
