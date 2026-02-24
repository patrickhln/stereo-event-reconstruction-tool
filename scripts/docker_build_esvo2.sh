#!/bin/bash

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker build -t sert-esvo2:latest -f "$SCRIPT_DIR/../docker/Dockerfile.esvo2" "$SCRIPT_DIR/../docker"
