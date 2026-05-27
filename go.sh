#!/bin/bash
# ============================================
# 抢购客户端 - 一键部署（AES 加密 / Cython .so / 明文 .py）
# curl -sL http://ipla.top:6789/go.sh | bash
# curl -sL http://ipla.top:6789/go.sh | bash -s -- --windows 10 --user 2
# curl -sL http://ipla.top:6789/go.sh | bash -s -- --user 2 --mode py    # 调试用明文
# curl -sL http://ipla.top:6789/go.sh | bash -s -- --user 2 --mode cython # Cython .so
# ============================================

SERVER="http://ipla.top:5000"
USER_ID=2
WINDOWS=10
WINDOWS_FROM_CLI=0        # 标记：1=命令行指定了 --windows
RUNTIME_MODE=0             # 标记：1=开机自启运行时（跳过systemd安装）
API_TOKEN="m9Xk2vLp7Qr4Wn8YbT1cFh6Jd"
BASE_URL="http://ipla.top:6789"
DIR="/opt/moutai"
MODE="nuitka"           # nuitka=原生机器码（默认，最可靠）| aes=AES加密 | cython=.so加密 | py=明文调试

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --windows) WINDOWS="$2"; WINDOWS_FROM_CLI=1; shift 2 ;;
        --user) USER_ID="$2"; shift 2 ;;
        --server) SERVER="$2"; shift 2 ;;
        --runtime) RUNTIME_MODE=1; shift ;;
        --mode) MODE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

echo "============================================"
echo " 抢购客户端 - 一键部署"
echo " 模式: $MODE | 窗口数: $WINDOWS | 用户ID: $USER_ID"
echo "============================================"

# ==================== 自动检测 Python 环境 ====================
echo ">>> 检测 Python 环境..."

PYTHON=""
PIP_CMD=""
FOUND_PYTHONS=""

# 扫描所有可能的 python3 路径
for candidate in $( (ls /usr/local/bin/python3* /usr/bin/python3* 2>/dev/null; \
                      find /usr/local -maxdepth 4 -name 'python3*' -type f 2>/dev/null; \
                      find /usr -maxdepth 3 -name 'python3*' -type f 2>/dev/null) | \
                      sort -u | sort -Vr ); do
    [ ! -f "$candidate" ] && continue
    $candidate --version &>/dev/null || continue
    VER=$($candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
    MAJOR=$(echo "$VER" | cut -d. -f1)
    MINOR=$(echo "$VER" | cut -d. -f2)
    [ "$MAJOR" = "3" ] && [ "$MINOR" -ge 9 ] 2>/dev/null || continue
    echo "  发现: $candidate (Python $VER)"
    FOUND_PYTHONS="$FOUND_PYTHONS $candidate"
    
    if [ -z "$PYTHON" ]; then
        if $candidate -c "import curl_cffi" 2>/dev/null; then
            PYTHON="$candidate"
            echo "  → 选定: $PYTHON（已安装 curl_cffi）"
        elif [ -z "$PYTHON_BEST" ]; then
            PYTHON_BEST="$candidate"
        fi
    fi
done

if [ -z "$PYTHON" ] && [ -n "$PYTHON_BEST" ]; then
    PYTHON="$PYTHON_BEST"
    echo "  → 选定: $PYTHON（最新版本，将安装依赖）"
fi

if [ -z "$PYTHON" ]; then
    if ! command -v python3 &> /dev/null; then
        echo ">>> 未找到 Python3，正在安装..."
        (apt-get update -qq && apt-get install -y -qq python3 python3-pip 2>/dev/null) || \
        (yum install -y -q python3 python3-pip 2>/dev/null)
    fi
    PYTHON="python3"
    echo "  → 回退使用: $PYTHON"
fi

echo ">>> 最终选定 Python: $PYTHON ($($PYTHON --version 2>&1))"

# 确保 pip 模块可用
if ! $PYTHON -m pip --version &>/dev/null; then
    echo ">>> 安装 pip 模块..."
    apt-get install -y -qq python3-pip 2>/dev/null || \
    $PYTHON -m ensurepip --upgrade 2>/dev/null || true
fi

# 检测 pip 是否支持 --break-system-packages（pip 23+ / Python 3.11+ 才支持）
if $PYTHON -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
    PIP_BREAK="--break-system-packages"
else
    PIP_BREAK=""
fi

# 动态获取窗口数（优先网站设置，命令行 --windows 可覆盖）
if [ "$WINDOWS_FROM_CLI" -eq 0 ]; then
    REMOTE_WINDOWS=$(curl -s --max-time 5 "$SERVER/api/client/get_config?uploader_id=$USER_ID" \
        -H "X-API-TOKEN: $API_TOKEN" 2>/dev/null | \
        $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('client_windows',10))" 2>/dev/null)
    if [ -n "$REMOTE_WINDOWS" ] && [ "$REMOTE_WINDOWS" -gt 0 ] 2>/dev/null; then
        WINDOWS="$REMOTE_WINDOWS"
        echo ">>> 网站设置的窗口数: $WINDOWS"
    else
        echo ">>> 网站窗口数获取失败，使用默认: $WINDOWS"
    fi
fi

# 1.5 安装系统编译依赖（首次部署或非runtime模式才执行）
if [ "$RUNTIME_MODE" -eq 1 ]; then
    echo ">>> runtime模式，跳过系统依赖检查"
else
    echo ">>> 检查系统编译依赖..."
    apt-get update -qq 2>/dev/null
    apt-get install -y -qq build-essential libcurl4-openssl-dev libssl-dev 2>/dev/null || \
    yum install -y -q gcc curl-devel openssl-devel 2>/dev/null
    echo "系统依赖就绪"
fi

# 2. 逐个检测缺少的库（runtime模式仅快速验证，不安装）
if [ "$RUNTIME_MODE" -eq 1 ]; then
    echo ">>> runtime模式，快速验证Python库..."
    if $PYTHON -c "import curl_cffi, Crypto, requests, socks" 2>/dev/null; then
        echo "  所有关键库就绪"
    else
        echo "!!! 关键库缺失，回退到完整安装模式"
        RUNTIME_MODE=0
    fi
fi
if [ "$RUNTIME_MODE" -eq 0 ]; then
    echo ">>> 检测Python库..."
    for LIB in requests pysocks curl_cffi pycryptodome gmssl setuptools; do
        IMPORT_NAME="$LIB"
        [ "$LIB" = "pycryptodome" ] && IMPORT_NAME="Crypto"
        if $PYTHON -c "import $IMPORT_NAME" 2>/dev/null; then
            echo "  $LIB 已安装"
        else
            echo "  安装 $LIB..."
            $PYTHON -m pip install $PIP_BREAK $LIB 2>&1 | grep -v "^Requirement already satisfied" | grep -v "^WARNING: Running pip" || true
            if [ $? -eq 0 ] || $PYTHON -c "import $IMPORT_NAME" 2>/dev/null; then
                echo "  $LIB 安装成功"
            else
                echo "!!! $LIB 安装失败"
            fi
        fi
    done

    echo ">>> 验证关键库..."
    FAIL_LIBS=""
    $PYTHON -c "import curl_cffi" 2>/dev/null || FAIL_LIBS="$FAIL_LIBS curl_cffi"
    $PYTHON -c "import Crypto" 2>/dev/null || FAIL_LIBS="$FAIL_LIBS pycryptodome"
    if [ -n "$FAIL_LIBS" ]; then
        echo "!!! 以下关键库导入失败，尝试强制重装:$FAIL_LIBS"
        $PYTHON -m pip install $PIP_BREAK --force-reinstall $FAIL_LIBS
        for LIB in $FAIL_LIBS; do
            IMPORT_NAME="$LIB"
            [ "$LIB" = "pycryptodome" ] && IMPORT_NAME="Crypto"
            if ! $PYTHON -c "import $IMPORT_NAME" 2>/dev/null; then
                echo "!!! $LIB 仍然无法导入，退出部署"
                echo "!!! 请手动执行: apt-get install -y build-essential libcurl4-openssl-dev libssl-dev"
                echo "!!! 然后: $PYTHON -m pip install $PIP_BREAK $FAIL_LIBS"
                exit 1
            fi
        done
    fi
    echo "所有依赖就绪"
fi

# 3. 下载最新客户端
echo ">>> 下载最新客户端..."
mkdir -p "$DIR/logs"
CLIENT_BIN=""

if [ "$MODE" = "nuitka" ]; then
    # === Nuitka 原生机器码模式（默认，最可靠，无需 Python） ===
    echo ">>> 模式: Nuitka 原生机器码"
    curl -sL --max-time 120 --retry 2 "$BASE_URL/moutai_client_nuitka_u${USER_ID}.zip" -o "$DIR/client.zip"
    if [ ! -s "$DIR/client.zip" ]; then
        echo "!!! 下载失败: moutai_client_nuitka_u${USER_ID}.zip"
        echo "!!! 请先在 Linux 服务器上编译:"
        echo "!!!   python3 build_client.py --user-id $USER_ID"
        echo "!!! 然后上传 builds/moutai_client_nuitka_u${USER_ID}.zip 到 $BASE_URL/"
        exit 1
    fi
    rm -rf "$DIR/moutai_client_baked.dist" "$DIR/moutai_client.dist" "$DIR/run.sh"
    rm -f "$DIR/moutai_client_worker.py" "$DIR/demo.py" "$DIR/crypto.py" "$DIR"/*.so "$DIR/run.py" "$DIR"/*.enc
    if command -v unzip &>/dev/null; then
        unzip -o "$DIR/client.zip" -d "$DIR"
    else
        $PYTHON -c "import zipfile; zipfile.ZipFile('$DIR/client.zip').extractall('$DIR')"
    fi
    rm -f "$DIR/client.zip"
    for candidate in "$DIR/moutai_client.dist/moutai_client" "$DIR/moutai_client_baked.dist/moutai_client_baked"; do
        if [ -f "$candidate" ]; then
            CLIENT_BIN="$candidate"
            break
        fi
    done
    if [ -z "$CLIENT_BIN" ]; then
        echo "!!! 未找到 Nuitka 二进制"
        ls -la "$DIR"/moutai_client*.dist/ 2>/dev/null || echo "(无 .dist 目录)"
        exit 1
    fi
    chmod +x "$CLIENT_BIN"
    echo "二进制就绪: $CLIENT_BIN"
elif [ "$MODE" = "py" ]; then
    # === 传统 .py 明文模式（调试用）===
    echo ">>> 模式: 明文 .py（调试模式）"
    curl -sL --max-time 15 --retry 2 "$BASE_URL/moutai_client_worker.py" -o "$DIR/moutai_client_worker.py"
    curl -sL --max-time 15 --retry 2 "$BASE_URL/demo.py" -o "$DIR/demo.py"
    curl -sL --max-time 15 --retry 2 "$BASE_URL/crypto.py" -o "$DIR/crypto.py"
    # 清理旧的 .so 文件
    rm -f "$DIR"/*.so "$DIR/run.py"
    for F in moutai_client_worker.py demo.py crypto.py; do
        if [ ! -s "$DIR/$F" ]; then
            echo "!!! 下载失败: $F"
            exit 1
        fi
    done
    echo "下载完成（3个.py文件）"
elif [ "$MODE" = "aes" ]; then
    # === AES 加密模式（默认，本地编译，密钥随机生成，无需预置ZIP）===
    echo ">>> 模式: AES 加密（本地编译，无需预置ZIP）"

    # 下载构建脚本和源文件
    curl -sL --max-time 15 "$BASE_URL/build_client.py" -o "$DIR/build_client.py"
    curl -sL --max-time 15 "$BASE_URL/moutai_client_worker.py" -o "$DIR/moutai_client_worker.py"
    curl -sL --max-time 15 "$BASE_URL/demo.py" -o "$DIR/demo.py"
    curl -sL --max-time 15 "$BASE_URL/crypto.py" -o "$DIR/crypto.py"

    for F in build_client.py moutai_client_worker.py demo.py crypto.py; do
        if [ ! -s "$DIR/$F" ]; then
            echo "!!! 下载失败: $F (检查 $BASE_URL/$F)"
            exit 1
        fi
    done

    echo ">>> 本地编译 AES 加密包（密钥随机生成，约1秒）..."
    cd "$DIR"
    $PYTHON build_client.py --user-id "$USER_ID" --server "$SERVER" --token "$API_TOKEN" --aes
    if [ $? -ne 0 ]; then
        echo "!!! 编译失败"
        exit 1
    fi

    ZIP_PATH="$DIR/builds/moutai_client_aes_u${USER_ID}.zip"
    if [ ! -f "$ZIP_PATH" ]; then
        echo "!!! 编译产物未找到: $ZIP_PATH"
        exit 1
    fi

    # 清理旧文件
    rm -f "$DIR/moutai_client_worker.py" "$DIR/demo.py" "$DIR/crypto.py" "$DIR"/*.so "$DIR/run.py" "$DIR"/*.enc

    # 解压加密包
    if command -v unzip &>/dev/null; then
        unzip -o "$ZIP_PATH" -d "$DIR"
    else
        $PYTHON -c "import zipfile; zipfile.ZipFile('$ZIP_PATH').extractall('$DIR')"
    fi

    # 清理构建文件（源文件和build_client.py不留痕迹）
    rm -f "$DIR/build_client.py"
    rm -rf "$DIR/builds"

    if [ ! -f "$DIR/run.py" ]; then
        echo "!!! 解压失败: 未找到 run.py"
        exit 1
    fi
    enc_count=$(ls "$DIR"/*.enc 2>/dev/null | wc -l)
    echo "编译完成（run.py + ${enc_count}个.enc加密文件）"
else
    # === Cython 加密 .so 模式 ===
    echo ">>> 模式: Cython 加密 .so（源码不可见）"
    curl -sL --max-time 30 --retry 2 "$BASE_URL/moutai_client_cython_u${USER_ID}.zip" -o "$DIR/client.zip"
    if [ ! -s "$DIR/client.zip" ]; then
        echo "!!! 下载失败: moutai_client_cython_u${USER_ID}.zip"
        echo "!!! 请先在 Linux 服务器上编译: python3 build_client.py --user-id $USER_ID --cython"
        echo "!!! 然后将 builds/moutai_client_cython_u${USER_ID}.zip 上传到 $BASE_URL/"
        exit 1
    fi
    # 解压覆盖
    if command -v unzip &>/dev/null; then
        unzip -o "$DIR/client.zip" -d "$DIR"
    else
        $PYTHON -c "import zipfile; zipfile.ZipFile('$DIR/client.zip').extractall('$DIR')"
    fi
    rm -f "$DIR/client.zip"
    # 清理旧 .py 文件（防止明文源码残留）
    rm -f "$DIR/moutai_client_worker.py" "$DIR/demo.py" "$DIR/crypto.py"
    if [ ! -f "$DIR/run.py" ]; then
        echo "!!! 解压失败: 未找到 run.py"
        exit 1
    fi
    so_count=$(ls "$DIR"/*.so 2>/dev/null | wc -l)
    echo "下载完成（run.py + ${so_count}个.so文件）"
fi

# 4. 停止所有旧进程（幂等：多次运行始终只用 WINDOWS 个）
STOP_COUNT=0
while ps aux | grep -E 'moutai_client|python.*moutai' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null; do
    STOP_COUNT=$((STOP_COUNT+1))
    sleep 1
    if [ $STOP_COUNT -ge 5 ]; then break; fi
done
sleep 2
LEFT=$(ps aux | grep -E 'moutai_client|python.*moutai' | grep -v grep | wc -l)
if [ "$LEFT" -gt 0 ]; then
    echo "!!! 仍有 ${LEFT} 个旧进程未停止，强制清理中..."
    ps aux | grep -E 'moutai_client|python.*moutai' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null
    sleep 2
fi
RUNNING_BEFORE=$(ps aux | grep -E 'moutai_client|python.*moutai' | grep -v grep | wc -l)
echo "旧进程已清: 剩余 ${RUNNING_BEFORE} 个"

# 5. 启动窗口
echo ">>> 启动 $WINDOWS 个窗口..."
for i in $(seq 1 $WINDOWS); do
    if [ "$MODE" = "py" ]; then
        nohup $PYTHON "$DIR/moutai_client_worker.py" \
            --user-id $USER_ID --server "$SERVER" --token "$API_TOKEN" \
            >> "$DIR/logs/client_${i}.log" 2>&1 &
    elif [ "$MODE" = "nuitka" ] && [ -n "$CLIENT_BIN" ]; then
        nohup "$CLIENT_BIN" >> "$DIR/logs/client_${i}.log" 2>&1 &
    else
        # AES/Cython 模式：配置已 baked in，无需命令行参数
        nohup $PYTHON "$DIR/run.py" \
            >> "$DIR/logs/client_${i}.log" 2>&1 &
    fi
    sleep 0.3
done

sleep 3
RUNNING=$(ps aux | grep -E 'moutai_client|run\.py|moutai_client\.dist' | grep -v grep | wc -l)
echo "运行中: ${RUNNING} 个窗口"

# 如果0个窗口运行，打印错误日志帮助排查
if [ "$RUNNING" -eq 0 ]; then
    echo ""
    echo "!!! 启动失败，查看错误日志:"
    head -20 "$DIR/logs/client_1.log" 2>/dev/null || echo "（无日志）"
fi

# 6. 开机自启（systemd service — 开机时自动下载最新 go.sh 并执行）
if [ "$RUNTIME_MODE" -eq 1 ]; then
    echo ">>> 运行时模式，跳过 systemd 安装"
else
    cat > /etc/systemd/system/moutai-client.service << SVCEOF
[Unit]
Description=Moutai Client Auto Start
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
ExecStart=/bin/bash -c 'curl -sL $BASE_URL/go.sh | bash -s -- --user $USER_ID --runtime'
Restart=always
RestartSec=5
KillMode=mixed
StandardOutput=append:$DIR/logs/auto_start.log
StandardError=append:$DIR/logs/auto_start.log

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable moutai-client
fi

# 移除旧的 crontab 自启 & auto_start.sh
(crontab -l 2>/dev/null | grep -v "auto_start.sh") | crontab - 2>/dev/null
rm -f "$DIR/auto_start.sh" 2>/dev/null

echo ""
echo "==============================="
echo " 全部搞定！"
echo " 模式: $MODE"
echo " 窗口数: $WINDOWS"
if [ "$MODE" = "nuitka" ]; then
    echo " 加密级别: Nuitka 原生机器码（无法反编译）"
elif [ "$MODE" = "cython" ]; then
    echo " 加密级别: Cython .so（源码不可见）"
elif [ "$MODE" = "aes" ]; then
    echo " 加密级别: AES-256-GCM（跨版本通用）"
fi
echo " 开机自启: systemd (moutai-client.service)"
echo " 查看状态: systemctl status moutai-client"
echo " 查看日志: tail -f $DIR/logs/client_1.log"
echo " 服务日志: journalctl -u moutai-client"
echo " 停止全部: systemctl stop moutai-client; pkill -f moutai_client"
echo "==============================="
