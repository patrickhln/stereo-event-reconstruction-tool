#!/bin/bash

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker build -t sert-rtabmap:latest -f "$SCRIPT_DIR/../docker/Dockerfile.rtabmap" "$SCRIPT_DIR/../docker"
