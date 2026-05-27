#!/bin/bash
# 停止所有茅台抢购进程
echo ">>> 停止客户端..."
pkill -f "moutai_client_worker.py" 2>/dev/null
sleep 1
echo ">>> 停止调度服务..."
pkill -f "moutai_automation.py" 2>/dev/null
sleep 1
echo ">>> 停止桥接服务..."
pkill -f "main.py" 2>/dev/null
echo "全部已停止"
