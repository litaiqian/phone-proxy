#!/bin/bash
# 查看茅台抢购运行状态
echo "========== 桥接服务 (8000) =========="
ps aux | grep "main.py" | grep -v grep || echo "未运行"
echo ""
echo "========== 调度服务 (5000) =========="
ps aux | grep "moutai_automation.py" | grep -v grep || echo "未运行"
echo ""
echo "========== 客户端窗口 =========="
count=$(ps aux | grep "moutai_client_worker.py" | grep -v grep | wc -l)
echo "运行中: ${count} 个窗口"
ps aux | grep "moutai_client_worker.py" | grep -v grep | awk '{print "  PID="$2, $NF}'
echo ""
echo "========== 内存使用 =========="
free -h | head -2
