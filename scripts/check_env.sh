#!/bin/bash -l

# -l stands for login (load user profile before running commands)

ENV_NAME="sert-python"

# Try multiple conda paths
for path in "$HOME/anaconda3" "$HOME/miniconda3" "$HOME/.conda" "/opt/conda"; do
    if [ -f "$path/etc/profile.d/conda.sh" ]; then
        source "$path/etc/profile.d/conda.sh"
        break
    fi
done

# Fallback
if ! command -v conda &> /dev/null; then
    source "$HOME/.bashrc" 2>/dev/null || true
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
