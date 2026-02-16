#!/bin/sh
# Git askpass helper that returns GITHUB_TOKEN from environment.
# Set GIT_ASKPASS to this script's path to authenticate git operations.
echo "${GITHUB_TOKEN}"
