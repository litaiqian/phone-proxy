#!/bin/bash
# ===================================================
# 猫妈妈手机代理 APK 一键编译脚本
# 需要在 Linux 环境运行 (Ubuntu 20.04+)
#
# 快速开始:
#   1. chmod +x build_apk.sh
#   2. ./build_apk.sh
#
# 产物: bin/phone_proxy-1.0.0-arm64-v8a-debug.apk
# ===================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  猫妈妈手机代理 APK 编译"
echo "=========================================="

# ---- 1. 安装系统依赖 ----
echo "[1/5] 安装系统依赖..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        python3 python3-pip python3-dev \
        git zip unzip openjdk-17-jdk \
        autoconf libtool pkg-config \
        zlib1g-dev libncurses-dev cmake libffi-dev libssl-dev \
        libltdl-dev
elif command -v yum &>/dev/null; then
    sudo yum install -y python3 python3-pip python3-devel \
        git zip unzip java-17-openjdk-devel
fi

# ---- 2. 安装 Buildozer ----
echo "[2/5] 安装 Buildozer..."
pip3 install --break-system-packages buildozer cython
export PATH="$HOME/.local/bin:$PATH"

# ---- 3. 注入配置 ----
echo "[3/5] 注入服务端配置..."
# 从环境变量读取，或使用默认值
SERVER="${MT_SERVER:-http://ipla.top:5000}"
TOKEN="${MT_TOKEN:-m9Xk2vLp7Qr4Wn8YbT1cFh6Jd}"
PORT="${MT_PROXY_PORT:-10808}"

# 替换 main.py 中的配置
sed -i "s|SERVER_HOST = 'ipla.top'|SERVER_HOST = '$(echo $SERVER | sed "s|http://||;s|:.*||")'|" main.py
sed -i "s|SERVER_PORT = 5000|SERVER_PORT = $(echo $SERVER | grep -oP ':\d+' | tr -d ':' || echo 5000)|" main.py

echo "  服务端: ${SERVER}"
echo "  代理端口: ${PORT}"

# ---- 4. 编译 APK ----
echo "[4/5] 编译 APK (首次约15-30分钟，后续约3-5分钟)..."
buildozer -v android debug

# ---- 5. 收集产物 ----
echo "[5/5] 收集 APK..."
mkdir -p bin
APK_PATH=$(find . -name "*.apk" -type f | head -1)
if [ -f "$APK_PATH" ]; then
    cp "$APK_PATH" bin/
    APK_SIZE=$(du -h "$APK_PATH" | cut -f1)
    echo ""
    echo "=========================================="
    echo "  ✅ 编译成功!"
    echo "  APK: $(realpath bin/$(basename "$APK_PATH"))"
    echo "  大小: ${APK_SIZE}"
    echo "=========================================="
    echo ""
    echo "部署到手机:"
    echo "  方式1: adb install bin/*.apk"
    echo "  方式2: 上传 bin/*.apk 到手机，点击安装"
    echo ""
    echo "手机端操作:"
    echo "  1. 安装此 APK"
    echo "  2. 打开「猫妈妈代理」App"
    echo "  3. 允许后台运行权限"
    echo "  4. 完成！无需任何配置"
    echo ""
else
    echo "❌ APK 未生成，请检查日志"
    exit 1
fi
