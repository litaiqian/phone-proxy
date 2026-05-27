#!/bin/bash
# ============================================
# 抢购客户端 - 明文 .py 直运版
# curl -sL http://ipla.top:6789/go_py.sh | bash
# curl -sL http://ipla.top:6789/go_py.sh | bash -s -- 2   # 指定用户ID
# ============================================

USER_ID="${1:-2}"
SERVER="http://ipla.top:5000"
API_TOKEN="m9Xk2vLp7Qr4Wn8YbT1cFh6Jd"
BASE_URL="http://ipla.top:6789"
DIR="/opt/moutai"
WINDOWS=10

echo "============================================"
echo " 抢购客户端 - 明文直运"
echo " 用户ID: $USER_ID | 窗口数: $WINDOWS"
echo "============================================"

# 1. 找 Python
echo ">>> 检测 Python..."
PYTHON=""
for p in python3.11 python3.10 python3.9 python3; do
    if command -v $p &>/dev/null && $p --version &>/dev/null; then
        PYTHON="$p"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    apt-get update -qq && apt-get install -y -qq python3 python3-pip 2>/dev/null
    PYTHON="python3"
fi
echo "  Python: $PYTHON ($($PYTHON --version 2>&1))"

# 确保 pip 可用（Debian 的 python3.11 不自动带 pip）
if ! $PYTHON -m pip --version &>/dev/null; then
    echo "  安装 pip..."
    apt-get install -y -qq python3-pip 2>/dev/null || {
        # 如果系统包不行，用 ensurepip 引导
        $PYTHON -m ensurepip --upgrade 2>/dev/null || true
    }
fi

# 2. pip 参数兼容
if $PYTHON -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
    PIP_BREAK="--break-system-packages"
else
    PIP_BREAK=""
fi

# 3. 装依赖
echo ">>> 安装依赖..."
for LIB in requests pysocks curl_cffi pycryptodome gmssl; do
    IMPORT="$LIB"
    [ "$LIB" = "pycryptodome" ] && IMPORT="Crypto"
    if ! $PYTHON -c "import $IMPORT" 2>/dev/null; then
        echo "  安装 $LIB..."
        $PYTHON -m pip install $PIP_BREAK $LIB -q 2>/dev/null
    fi
done

# 验证
$PYTHON -c "import curl_cffi, Crypto" 2>/dev/null || {
    echo "!!! 依赖安装失败"
    apt-get install -y -qq build-essential libcurl4-openssl-dev libssl-dev 2>/dev/null
    $PYTHON -m pip install $PIP_BREAK curl_cffi pycryptodome
}
echo "  依赖就绪"

# 4. 拉取源文件（带重试，开机自动获取最新）
echo ">>> 下载源文件..."
mkdir -p "$DIR/logs" "$DIR/data/nurture/har_learned" "$DIR/services"
for F in moutai_client_worker.py demo.py crypto.py nurture_account.py _security_bodies.py; do
    curl -sL --max-time 30 --retry 3 "$BASE_URL/$F" -o "$DIR/$F"
    [ -s "$DIR/$F" ] || { echo "!!! 下载失败: $F"; exit 1; }
done
# 下载 services 子模块
for F in services/__init__.py services/local_ip_pool.py; do
    curl -sL --max-time 30 --retry 3 "$BASE_URL/$F" -o "$DIR/$F"
    [ -s "$DIR/$F" ] || { echo "!!! 下载失败: $F"; exit 1; }
done
echo "  下载完成"

# 5. 停旧进程
pkill -f moutai_client 2>/dev/null || true
sleep 2
echo "  旧进程已清"

# 6. 动态获取窗口数（从网站配置）
echo ">>> 获取网站窗口配置..."
API_RAW=$(curl -s --max-time 10 "$SERVER/api/client/get_config?uploader_id=$USER_ID" \
    -H "X-API-TOKEN: $API_TOKEN" 2>&1)
REMOTE=$(echo "$API_RAW" | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('client_windows',10))" 2>&1)
if [ -n "$REMOTE" ] && [ "$REMOTE" -gt 0 ] 2>/dev/null; then
    WINDOWS="$REMOTE"
    echo "  网站窗口数: $WINDOWS"
else
    echo "  API未返回有效窗口数，使用默认: $WINDOWS"
    echo "  API原始响应: ${API_RAW:-无响应}"
fi

# 7. 启动
echo ">>> 启动 $WINDOWS 个窗口..."
for i in $(seq 1 $WINDOWS); do
    nohup $PYTHON "$DIR/moutai_client_worker.py" \
        --user-id $USER_ID --server "$SERVER" --token "$API_TOKEN" \
        >> "$DIR/logs/client_${i}.log" 2>&1 &
    sleep 0.3
done

sleep 3
RUNNING=$(ps aux | grep moutai_client | grep -v grep | wc -l)
echo "  运行中: ${RUNNING} 个窗口"

# 8. 开机自启（每次开机自动 curl 拉取最新脚本 + 自动安装新库）
cat > /etc/systemd/system/moutai-client.service << EOF
[Unit]
Description=Moutai Client
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'curl -sL --retry 3 --max-time 30 $BASE_URL/go_py.sh | bash -s -- $USER_ID'
ExecStop=/bin/bash -c 'pkill -f moutai_client 2>/dev/null; echo "stopped"'
TimeoutStartSec=600
StandardOutput=append:$DIR/logs/auto_start.log
StandardError=append:$DIR/logs/auto_start.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable moutai-client

echo ""
echo "==============================="
echo " 全部搞定！"
echo " 窗口数: $WINDOWS"
echo " 模式: 明文 .py 直运"
echo " 查看日志: tail -f $DIR/logs/client_1.log"
echo " 服务日志: tail -f $DIR/logs/auto_start.log"
echo " 停止: systemctl stop moutai-client; pkill -f moutai"
echo "==============================="
