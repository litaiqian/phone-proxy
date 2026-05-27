#!/bin/bash
# ==========================================
# 茅台客户端 - 一键部署（systemd 开机自启 + 自动拉取最新）
# ==========================================
set -e

INSTALL_DIR="/opt/moutai"
SERVICE_NAME="moutai-client"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
DOWNLOAD_URL="http://ipla.top:6789/moutai_client_aes_u2.zip"

echo ">>> 检查 Python 环境..."
PYTHON=$(which python3 2>/dev/null || which python 2>/dev/null)
if [ -z "$PYTHON" ]; then
    echo "未找到 Python，正在安装..."
    apt update -qq && apt install -y python3 python3-pip
    PYTHON=$(which python3)
fi
$PYTHON --version

echo ""
echo ">>> 逐项检测依赖包（跳过已安装）..."

PACKAGES=(
    "requests|requests"
    "Crypto|pycryptodome"
    "curl_cffi|curl_cffi"
    "gmssl|gmssl"
    "socks|PySocks"
)

for entry in "${PACKAGES[@]}"; do
    IMP="${entry%%|*}"
    PKG="${entry##*|}"
    if $PYTHON -c "import $IMP" 2>/dev/null; then
        echo "  [OK] $PKG 已安装"
    else
        echo "  [安装] $PKG ..."
        $PYTHON -m pip install -q "$PKG" -i "$MIRROR" --trusted-host pypi.tuna.tsinghua.edu.cn
        if [ $? -ne 0 ]; then
            echo "  [重试] $PKG (默认源)..."
            $PYTHON -m pip install -q "$PKG" --break-system-packages 2>/dev/null || $PYTHON -m pip install -q "$PKG"
        fi
    fi
done

echo ""
echo ">>> 检查 Linux 系统依赖 (curl_cffi 需要)..."
for LIB in libcurl4 libssl3 ca-certificates; do
    if ! dpkg -s "$LIB" >/dev/null 2>&1; then
        echo "  [安装] $LIB ..."
        apt install -y -qq "$LIB" 2>/dev/null || true
    fi
done

echo ""
echo ">>> 安装到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
systemctl stop $SERVICE_NAME 2>/dev/null || true
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"

echo ">>> 生成开机启动脚本（每次开机自动从网盘拉取最新包）..."
cat > "$INSTALL_DIR/start.sh" << 'START_EOF'
#!/bin/bash
# 每次开机自动从网盘拉取最新并启动
set -e

INSTALL_DIR="__INSTALL_DIR__"
DOWNLOAD_URL="__DOWNLOAD_URL__"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

echo "[$(date)] 开机启动 - 从网盘拉取最新包..."

# 下载最新 zip
cd /tmp
rm -f moutai_latest.zip
if wget -q -O moutai_latest.zip "$DOWNLOAD_URL" 2>/dev/null; then
    echo "[$(date)] 下载成功"
    # 用 Python 解压（兼容无 unzip 环境）
    python3 -c "
import zipfile, shutil, os
z = zipfile.ZipFile('/tmp/moutai_latest.zip')
z.extractall('$INSTALL_DIR')
z.close()
"
    rm -f /tmp/moutai_latest.zip
else
    echo "[$(date)] 下载失败，使用本地缓存"
fi

# 检查依赖（缺失才装）
for entry in "requests|requests" "Crypto|pycryptodome" "curl_cffi|curl_cffi" "gmssl|gmssl" "socks|PySocks"; do
    IMP="${entry%%|*}"
    PKG="${entry##*|}"
    if ! python3 -c "import $IMP" 2>/dev/null; then
        echo "[$(date)] 安装缺失依赖: $PKG"
        python3 -m pip install -q "$PKG" -i "$MIRROR" --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null ||         python3 -m pip install -q "$PKG" 2>/dev/null || true
    fi
done

mkdir -p "$INSTALL_DIR/logs"
echo "[$(date)] 启动客户端..."
cd "$INSTALL_DIR"
exec /usr/bin/python3 "$INSTALL_DIR/run.py"
START_EOF

# 写入实际路径和下载地址
sed -i "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$INSTALL_DIR/start.sh"
sed -i "s|__DOWNLOAD_URL__|$DOWNLOAD_URL|g" "$INSTALL_DIR/start.sh"
chmod +x "$INSTALL_DIR/start.sh"

echo ">>> 创建 systemd 服务（指向 start.sh）..."
cat > /etc/systemd/system/$SERVICE_NAME.service << SERVICE_EOF
[Unit]
Description=Moutai Client Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/moutai
ExecStart=/bin/bash /opt/moutai/start.sh
Restart=always
RestartSec=10
StandardOutput=append:/opt/moutai/logs/stdout.log
StandardError=append:/opt/moutai/logs/stderr.log

[Install]
WantedBy=multi-user.target
SERVICE_EOF

mkdir -p "$INSTALL_DIR/logs"

echo ">>> 启用开机自启..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME
sleep 2
STATUS=$(systemctl is-active $SERVICE_NAME)

echo ""
echo "========================================="
echo " 部署状态: $STATUS"
echo " 网盘地址: $DOWNLOAD_URL"
echo ""
echo " 管理命令:"
echo "  状态: systemctl status $SERVICE_NAME"
echo "  日志: tail -f $INSTALL_DIR/logs/stdout.log"
echo "  停止: systemctl stop $SERVICE_NAME"
echo "  启动: systemctl start $SERVICE_NAME"
echo "  重启: systemctl restart $SERVICE_NAME"
echo ""
echo " 更新方式: 替换网盘上的 zip，然后 reboot 或 systemctl restart"
echo "========================================="
