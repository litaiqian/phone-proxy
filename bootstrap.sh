#!/bin/bash
# ============================================
# 茅台抢购 - 一键部署启动脚本
# 在任意Linux服务器上执行一句命令即可：
# curl -sL http://你的域名/moutai/bootstrap.sh | bash -s -- --user 1 --windows 6 --server http://你的域名:5000 --bridge http://你的域名:8000
# ============================================

# 默认参数（可通过命令行覆盖）
USER_ID=1
WINDOWS=6
SERVER_URL=""
BRIDGE_URL=""
DOWNLOAD_URL=""  # 程序包下载地址，如 http://你的域名/moutai/moutai.tar.gz
INSTALL_DIR="/opt/moutai"

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --user) USER_ID="$2"; shift 2 ;;
        --windows) WINDOWS="$2"; shift 2 ;;
        --server) SERVER_URL="$2"; shift 2 ;;
        --bridge) BRIDGE_URL="$2"; shift 2 ;;
        --url) DOWNLOAD_URL="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        *) echo "未知参数: $1"; shift ;;
    esac
done

echo "============================================"
echo " 茅台抢购 - 一键部署"
echo " 用户ID: $USER_ID"
echo " 窗口数: $WINDOWS"
echo " 调度服务: $SERVER_URL"
echo " 桥接服务: $BRIDGE_URL"
echo " 安装目录: $INSTALL_DIR"
echo "============================================"

# ==================== 1. 安装依赖 ====================
echo ">>> 检查Python环境..."
if ! command -v python3 &> /dev/null; then
    echo "安装Python3..."
    if command -v apt-get &> /dev/null; then
        apt-get update -qq && apt-get install -y -qq python3 python3-pip > /dev/null 2>&1
    elif command -v yum &> /dev/null; then
        yum install -y -q python3 python3-pip > /dev/null 2>&1
    fi
fi

echo ">>> 检查Python库，缺少的自动安装..."
for LIB in fastapi uvicorn sqlalchemy pymysql requests httpx pysocks; do
    python3 -c "import $LIB" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "  缺少 $LIB，安装中..."
        pip3 install -q $LIB 2>/dev/null
    fi
done
echo "所有依赖就绪"

# ==================== 2. 下载最新程序 ====================
echo ">>> 下载最新程序..."
mkdir -p "$INSTALL_DIR"

if [ -n "$DOWNLOAD_URL" ]; then
    # 从服务器下载压缩包
    cd /tmp
    rm -f moutai.tar.gz 2>/dev/null
    curl -sL "$DOWNLOAD_URL" -o moutai.tar.gz
    if [ -f moutai.tar.gz ]; then
        tar -xzf moutai.tar.gz -C "$INSTALL_DIR" --strip-components=1 2>/dev/null || \
        cp moutai.tar.gz "$INSTALL_DIR/" 2>/dev/null
        rm -f moutai.tar.gz
        echo "下载完成"
    else
        echo "下载失败，使用本地已有文件"
    fi
fi

cd "$INSTALL_DIR"

# ==================== 3. 停止旧进程 ====================
echo ">>> 停止旧进程..."
pkill -f "moutai_client_worker.py" 2>/dev/null
pkill -f "moutai_automation.py" 2>/dev/null
pkill -f "main.py" 2>/dev/null
sleep 2

# ==================== 4. 启动客户端窗口 ====================
LOG_DIR="$INSTALL_DIR/logs"
mkdir -p "$LOG_DIR"

echo ">>> 启动 $WINDOWS 个客户端窗口..."
for i in $(seq 1 $WINDOWS); do
    nohup python3 "$INSTALL_DIR/moutai_client_worker.py" \
        --user-id $USER_ID \
        --server "${SERVER_URL}" \
        --bridge "${BRIDGE_URL}" \
        >> "$LOG_DIR/client_${i}.log" 2>&1 &
    echo "窗口${i} PID: $!"
    sleep 0.5
done

sleep 2
RUNNING=$(ps aux | grep "moutai_client_worker.py" | grep -v grep | wc -l)
echo ""
echo "==============================="
echo " 启动完成！运行中: ${RUNNING} 个窗口"
echo " 日志目录: $LOG_DIR/"
echo "==============================="

# ==================== 5. 设置开机自启 ====================
echo ">>> 设置开机自启..."

# 生成自启脚本（每次开机先下载最新再启动）
cat > "$INSTALL_DIR/auto_start.sh" << AUTOSTART_EOF
#!/bin/bash
# 开机自动下载最新程序并启动
sleep 10  # 等网络就绪

USER_ID=$USER_ID
WINDOWS=$WINDOWS
SERVER_URL="$SERVER_URL"
BRIDGE_URL="$BRIDGE_URL"
DOWNLOAD_URL="$DOWNLOAD_URL"
INSTALL_DIR="$INSTALL_DIR"
LOG_DIR="$INSTALL_DIR/logs"
mkdir -p "\$LOG_DIR"

# 下载最新
if [ -n "\$DOWNLOAD_URL" ]; then
    cd /tmp
    rm -f moutai.tar.gz 2>/dev/null
    curl -sL "\$DOWNLOAD_URL" -o moutai.tar.gz
    if [ -f moutai.tar.gz ]; then
        tar -xzf moutai.tar.gz -C "\$INSTALL_DIR" --strip-components=1 2>/dev/null
        rm -f moutai.tar.gz
        echo "[\$(date)] 程序更新完成" >> "\$LOG_DIR/auto_start.log"
    fi
fi

cd "\$INSTALL_DIR"

# 检查缺少的库
for LIB in fastapi uvicorn sqlalchemy pymysql requests httpx pysocks; do
    python3 -c "import \$LIB" 2>/dev/null || pip3 install -q \$LIB 2>/dev/null
done

# 启动
for i in \$(seq 1 \$WINDOWS); do
    nohup python3 "\$INSTALL_DIR/moutai_client_worker.py" \\
        --user-id \$USER_ID \\
        --server "\$SERVER_URL" \\
        --bridge "\$BRIDGE_URL" \\
        >> "\$LOG_DIR/client_\${i}.log" 2>&1 &
    sleep 0.5
done
echo "[\$(date)] 启动 \${WINDOWS} 个窗口" >> "\$LOG_DIR/auto_start.log"
AUTOSTART_EOF

chmod +x "$INSTALL_DIR/auto_start.sh"

# 写入crontab（不覆盖已有的）
CRON_LINE="@reboot bash $INSTALL_DIR/auto_start.sh"
(crontab -l 2>/dev/null | grep -v "auto_start.sh"; echo "$CRON_LINE") | crontab -

echo "开机自启已设置！"
echo ""
echo "====================================="
echo " 管理命令："
echo " 查看状态: ps aux | grep moutai"
echo " 查看日志: tail -f $LOG_DIR/client_1.log"
echo " 停止全部: pkill -f moutai_client_worker"
echo "====================================="
