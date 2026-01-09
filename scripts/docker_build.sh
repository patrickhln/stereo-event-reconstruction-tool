#!/bin/bash

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker build -t sert-ros:latest -f "$SCRIPT_DIR/../docker/Dockerfile" "$SCRIPT_DIR/../docker"
