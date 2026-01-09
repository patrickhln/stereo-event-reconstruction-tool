#!/bin/bash

set -e
docker build -t sert-ros:latest -f Dockerfile ../docker/
