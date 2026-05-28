#!/bin/bash
# ============================================
# 茅台抢购一键启动脚本
# 用法: bash start_all.sh
# 开机自启: 见底部说明
# ============================================

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

# Python 路径（按实际修改）
PYTHON="/usr/bin/python3"
# 如果用虚拟环境，改为: PYTHON="$BASE_DIR/../venv/bin/python"

# ==================== 1. 启动服务端 ====================
echo ">>> 启动桥接服务 (端口8000)..."
nohup $PYTHON "$BASE_DIR/main.py" > "$LOG_DIR/bridge.log" 2>&1 &
echo "桥接PID: $!"

sleep 2  # 等桥接先启动

echo ">>> 启动调度服务 (端口5000)..."
nohup $PYTHON "$BASE_DIR/moutai_automation.py" > "$LOG_DIR/scheduler.log" 2>&1 &
echo "调度PID: $!"

sleep 3  # 等服务端就绪

# ==================== 2. 启动客户端窗口 ====================
WINDOW_COUNT=${1:-10}  # 默认10个窗口，可传参: bash start_all.sh 5

echo ">>> 启动 $WINDOW_COUNT 个客户端窗口..."
for i in $(seq 1 $WINDOW_COUNT); do
    nohup $PYTHON "$BASE_DIR/moutai_client_worker.py" \
        --user-id 2 \
        --server http://127.0.0.1:5000 \
        --bridge http://127.0.0.1:8000 \
        > "$LOG_DIR/client_${i}.log" 2>&1 &
    echo "窗口${i} PID: $!"
    sleep 0.5  # 错开0.5秒注册，避免并发
done

echo ""
echo "==============================="
echo " 全部启动完成！"
echo " 桥接服务: http://127.0.0.1:8000"
echo " 调度服务: http://127.0.0.1:5000"
echo " 客户端: ${WINDOW_COUNT}个窗口"
echo " 日志目录: $LOG_DIR/"
echo "==============================="
echo ""
echo " 查看状态: bash $BASE_DIR/status.sh"
echo " 停止全部: bash $BASE_DIR/stop_all.sh"
