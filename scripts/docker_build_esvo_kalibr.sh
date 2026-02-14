#!/bin/bash

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker build --no-cache -t sert-esvo-kalibr:latest -f "$SCRIPT_DIR/../docker/Dockerfile.esvo-kalibr" "$SCRIPT_DIR/../docker"
