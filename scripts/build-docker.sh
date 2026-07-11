#!/bin/bash

# Build and Run Script for PALWorld Save Pal

# Exit immediately if a command exits with a non-zero status
set -e

# Navigate to the script's directory
cd "$(dirname "$0")/.."

# 确定 PUBLIC_WS_URL：优先使用环境变量显式覆盖，否则自动探测本机 IP
if [[ -n "${PUBLIC_WS_URL}" ]]; then
    echo "Using PUBLIC_WS_URL from environment: ${PUBLIC_WS_URL}"
else
    # 自动探测本机 IP（Linux / macOS）
    IP_ADDRESS=""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS：尝试获取 en0 接口 IP，失败则留空
        IP_ADDRESS=$(ipconfig getifaddr en0 2>/dev/null || true)
    else
        # Linux：尝试 hostname -I，不支持时安全回退
        IP_ADDRESS=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    fi

    # 探测失败则回退到 localhost（适合本机访问）
    if [[ -z "${IP_ADDRESS}" ]]; then
        echo "Could not detect local IP, falling back to localhost"
        IP_ADDRESS="localhost"
    fi

    PUBLIC_WS_URL="${IP_ADDRESS}:5174/ws"
    echo "Using IP Address: ${PUBLIC_WS_URL}"
fi

# Build and run docker compose
docker compose build --build-arg "PUBLIC_WS_URL=${PUBLIC_WS_URL}"
docker compose up -d

echo "Build and deployment completed successfully."
