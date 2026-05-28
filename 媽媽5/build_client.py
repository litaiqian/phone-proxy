#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
客户端打包工具 (Nuitka standalone / Cython 双模式)
用法:
  python build_client.py --user-id 2 --cython      # Linux 部署用 Cython .so
  python build_client.py --user-id 2                # Windows 部署用 Nuitka EXE
  python build_client.py --user-id 2 --server http://...

原理:
  Nuitka: 编译核心代码为原生机器码（standalone 目录模式）→ Windows EXE
  Cython: .py → .c → .so 共享库（Linux 部署，源码不可见，体积极小）
"""

import os, sys, shutil, subprocess, tempfile, re, time, zipfile
from typing import Optional

BASEDIR = os.path.dirname(os.path.abspath(__file__))
BUILDS_DIR = os.path.join(BASEDIR, 'builds')
SOURCE_FILE = os.path.join(BASEDIR, 'moutai_client_worker.py')
DEMO_FILE = os.path.join(BASEDIR, 'demo.py')
CRYPTO_FILE = os.path.join(BASEDIR, 'crypto.py')


def _find_package_path(pkg_name):
    """找到包的安装路径（目录或单文件）"""
    try:
        mod = __import__(pkg_name)
        return getattr(mod, '__path__', [None])[0] or mod.__file__
    except ImportError:
        # 尝试单文件模块
        import importlib.util
        spec = importlib.util.find_spec(pkg_name)
        if spec and spec.origin:
            return spec.origin
        return None


def build_exe(user_id: int, server: str = 'http://ipla.top:5000',
              bridge: str = 'http://ipla.top:5000',
              token: str = 'your-secure-token-change-me') -> Optional[str]:
    """
    为指定用户构建客户端（standalone + ZIP）
    返回: 生成的 zip 文件路径，失败返回 None
    """
    os.makedirs(BUILDS_DIR, exist_ok=True)

    exe_name = f'moutai_client_u{user_id}'
    # Nuitka standalone 会创建 {源码名}.dist 目录
    dist_dir = os.path.join(BUILDS_DIR, 'moutai_client_baked.dist')
    zip_path = os.path.join(BUILDS_DIR, f'{exe_name}.zip')

    # 1. 读取源码
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        source = f.read()

    # 2. 注入用户配置
    source = re.sub(r'BAKED_USER_ID\s*=\s*0', f'BAKED_USER_ID = {user_id}', source)
    source = source.replace('SERVER_BASE_URL = "http://ipla.top:5000"', f'SERVER_BASE_URL = "{server}"')
    source = source.replace('BRIDGE_BASE_URL = "http://ipla.top:5000"', f'BRIDGE_BASE_URL = "{bridge}"')
    source = source.replace('API_TOKEN = "your-secure-token-change-me"', f'API_TOKEN = "{token}"')

    # 3. 写入临时文件
    tmp_dir = tempfile.mkdtemp(prefix='moutai_build_')
    tmp_source = os.path.join(tmp_dir, 'moutai_client_baked.py')
    with open(tmp_source, 'w', encoding='utf-8') as f:
        f.write(source)
    print(f'[打包] 用户ID={user_id}  源码已注入')

    shutil.copy2(DEMO_FILE, os.path.join(tmp_dir, 'demo.py'))
    shutil.copy2(CRYPTO_FILE, os.path.join(tmp_dir, 'crypto.py'))

    # 4. 清理旧构建
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    # 5. Nuitka 编译（standalone + 跳过 curl_cffi 编译）
    cmd = [
        sys.executable, '-m', 'nuitka',
        '--standalone',
        '--remove-output',
        f'--output-filename={exe_name}.exe',
        f'--output-dir={BUILDS_DIR}',
        '--lto=yes',
        '--jobs=4',
        '--assume-yes-for-downloads',
        '--include-module=demo',
        '--include-module=crypto',
        '--include-package=gmssl',
        # Crypto/pycryptodome 和 curl_cffi 的 C 扩展导致 Nuitka 崩溃，跳过编译后手动复制
        '--nofollow-import-to=Crypto',
        '--nofollow-import-to=Crypto.Cipher',
        '--nofollow-import-to=Crypto.PublicKey',
        '--nofollow-import-to=Crypto.Util',
        '--nofollow-import-to=Crypto.IO',
        '--nofollow-import-to=Crypto.Hash',
        '--nofollow-import-to=Crypto.Random',
        '--nofollow-import-to=curl_cffi',
        '--nofollow-import-to=curl_cffi.requests',
        '--nofollow-import-to=curl_cffi.const',
        '--nofollow-import-to=curl_cffi.curl',
        '--nofollow-import-to=curl_cffi.aio',
        '--nofollow-import-to=curl_cffi.utils',
        '--nofollow-import-to=curl_cffi.__version__',
        tmp_source
    ]

    print(f'[打包] Nuitka C编译中 -> {exe_name}.exe...')
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    except subprocess.TimeoutExpired:
        print('[打包] 超时(>600s)')
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    elapsed = time.time() - start

    if result.returncode != 0:
        err = result.stderr or result.stdout
        print(f'[打包] 失败 (耗时{elapsed:.0f}s):')
        err_text = err[:3000] if err else '(no output)'
        for l in err_text.split('\n'):
            if l.strip():
                print(f'  {l.strip()}')
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    shutil.rmtree(tmp_dir, ignore_errors=True)

    # 6. 检查 EXE
    built_exe = os.path.join(dist_dir, f'{exe_name}.exe')
    if not os.path.exists(built_exe):
        print('[打包] 失败: EXE未生成')
        return None

    # 7. 复制 curl_cffi + _cffi_backend 到 dist 目录
    print('[打包] 复制 C 扩展包...')
    for pkg_name in ['Crypto', 'curl_cffi', '_cffi_backend']:
        pkg_path = _find_package_path(pkg_name)
        if not pkg_path:
            print(f'  [警告] 未找到 {pkg_name}，跳过')
            continue
        if os.path.isdir(pkg_path):
            dest = os.path.join(dist_dir, os.path.basename(pkg_path))
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(pkg_path, dest)
            print(f'  {pkg_name}/ -> OK')
        elif os.path.isfile(pkg_path):
            dest = os.path.join(dist_dir, os.path.basename(pkg_path))
            shutil.copy2(pkg_path, dest)
            print(f'  {os.path.basename(pkg_path)} -> OK')

    # 8. ZIP 打包
    print('[打包] ZIP打包中...')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(dist_dir):
            for f in files:
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, dist_dir)
                zf.write(full, arcname)
    zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f'[打包] 成功: {exe_name}.zip ({zip_mb:.1f}MB, 耗时{elapsed:.0f}s)')

    # 9. 清理 dist 目录
    shutil.rmtree(dist_dir, ignore_errors=True)

    return zip_path


def build_nuitka_linux(user_id: int, server: str = 'http://ipla.top:5000',
                       bridge: str = 'http://ipla.top:5000',
                       token: str = 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd') -> Optional[str]:
    """
    Nuitka standalone 编译（Linux）→ 原生机器码，无需 Python 即可运行
    返回: 生成的 zip 文件路径，失败返回 None

    产物结构（ZIP内）:
      moutai_client.dist/    ← Nuitka standalone 目录（含所有 .so + 二进制）
        moutai_client        ← 可执行文件
        Crypto/               ← C 扩展（手动复制）
        curl_cffi/            ← C 扩展（手动复制）
      run.sh                  ← 启动脚本
    """
    if sys.platform != 'linux':
        print('[Nuitka] 错误: 必须在 Linux 上编译')
        return None

    os.makedirs(BUILDS_DIR, exist_ok=True)

    zip_name = f'moutai_client_nuitka_u{user_id}'
    zip_path = os.path.join(BUILDS_DIR, f'{zip_name}.zip')
    dist_dir = os.path.join(BUILDS_DIR, 'moutai_client_baked.dist')

    # 1. 检查 Nuitka
    try:
        __import__('nuitka')
    except ImportError:
        print('[Nuitka] Nuitka 未安装，正在安装...')
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'nuitka'], check=True)

    # 2. 读取并注入配置
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        source = f.read()
    source = re.sub(r'BAKED_USER_ID\s*=\s*0', f'BAKED_USER_ID = {user_id}', source)
    source = source.replace('SERVER_BASE_URL = "http://ipla.top:5000"', f'SERVER_BASE_URL = "{server}"')
    source = source.replace('BRIDGE_BASE_URL = "http://ipla.top:5000"', f'BRIDGE_BASE_URL = "{bridge}"')
    source = source.replace('API_TOKEN = "your-secure-token-change-me"', f'API_TOKEN = "{token}"')

    tmp_dir = tempfile.mkdtemp(prefix='moutai_nuitka_')
    tmp_source = os.path.join(tmp_dir, 'moutai_client_baked.py')
    with open(tmp_source, 'w', encoding='utf-8') as f:
        f.write(source)
    shutil.copy2(DEMO_FILE, os.path.join(tmp_dir, 'demo.py'))
    shutil.copy2(CRYPTO_FILE, os.path.join(tmp_dir, 'crypto.py'))
    print(f'[Nuitka] 用户ID={user_id}  源码已注入')

    # 3. 清理旧构建
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    # 4. Nuitka 编译
    cmd = [
        sys.executable, '-m', 'nuitka',
        '--standalone',
        '--remove-output',
        '--output-filename=moutai_client',
        f'--output-dir={BUILDS_DIR}',
        '--lto=yes',
        '--jobs=4',
        '--assume-yes-for-downloads',
        '--include-module=demo',
        '--include-module=crypto',
        '--include-package=gmssl',
        '--nofollow-import-to=Crypto',
        '--nofollow-import-to=Crypto.Cipher',
        '--nofollow-import-to=Crypto.PublicKey',
        '--nofollow-import-to=Crypto.Util',
        '--nofollow-import-to=Crypto.IO',
        '--nofollow-import-to=Crypto.Hash',
        '--nofollow-import-to=Crypto.Random',
        '--nofollow-import-to=curl_cffi',
        '--nofollow-import-to=curl_cffi.requests',
        '--nofollow-import-to=curl_cffi.const',
        '--nofollow-import-to=curl_cffi.curl',
        '--nofollow-import-to=curl_cffi.aio',
        '--nofollow-import-to=curl_cffi.utils',
        '--nofollow-import-to=curl_cffi.__version__',
        tmp_source
    ]

    print('[Nuitka] C 编译中（约3-5分钟）...')
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=600)
    except subprocess.TimeoutExpired:
        print('[Nuitka] 超时(>600s)')
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    elapsed = time.time() - start

    if result.returncode != 0:
        err = result.stderr or result.stdout
        print(f'[Nuitka] 失败 (耗时{elapsed:.0f}s):')
        for l in (err or '(no output)').split('\n')[-20:]:
            if l.strip():
                print(f'  {l.strip()}')
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f'[Nuitka] C 编译成功 (耗时{elapsed:.0f}s)')

    # 5. 检查二进制
    built_bin = os.path.join(dist_dir, 'moutai_client')
    if not os.path.exists(built_bin):
        print('[Nuitka] 失败: 二进制未生成')
        return None

    # 6. 复制 C 扩展（Nuitka 跳过了这些，手动补）
    print('[Nuitka] 复制 C 扩展包...')
    for pkg_name in ['Crypto', 'curl_cffi', '_cffi_backend']:
        pkg_path = _find_package_path(pkg_name)
        if not pkg_path:
            print(f'  [警告] 未找到 {pkg_name}')
            continue
        if os.path.isdir(pkg_path):
            dest = os.path.join(dist_dir, os.path.basename(pkg_path))
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(pkg_path, dest)
            print(f'  {pkg_name}/ -> OK')
        elif os.path.isfile(pkg_path):
            dest = os.path.join(dist_dir, os.path.basename(pkg_path))
            shutil.copy2(pkg_path, dest)
            print(f'  {os.path.basename(pkg_path)} -> OK')

    # 7. 创建 run.sh 启动脚本
    run_sh = os.path.join(BUILDS_DIR, 'run.sh')
    with open(run_sh, 'w') as f:
        f.write('#!/bin/bash\n')
        f.write('DIR="$(cd "$(dirname "$0")" && pwd)"\n')
        f.write('exec "$DIR/moutai_client.dist/moutai_client"\n')
    os.chmod(run_sh, 0o755)

    # 8. ZIP 打包
    print('[Nuitka] ZIP打包中...')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 打包 .dist 目录
        for root, dirs, files in os.walk(dist_dir):
            for f in files:
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, BUILDS_DIR)
                zf.write(full, arcname)
        # 打包 run.sh
        zf.write(run_sh, 'run.sh')
    zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f'[Nuitka] 成功: {zip_name}.zip ({zip_mb:.1f}MB, 耗时{elapsed:.0f}s)')

    # 9. 清理
    shutil.rmtree(dist_dir, ignore_errors=True)
    os.remove(run_sh)

    return zip_path


def build_cython(user_id: int, server: str = 'http://ipla.top:5000',
                 bridge: str = 'http://ipla.top:5000',
                 token: str = 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd') -> Optional[str]:
    """
    Cython 编译模式：将 Python 源码编译为 .so 共享库（Linux 部署用）
    返回: 生成的 zip 文件路径，失败返回 None

    产物结构（ZIP内）:
      moutai_client_worker.cpython-*.so
      demo.cpython-*.so
      crypto.cpython-*.so
      run.py                        ← 启动器
    """
    os.makedirs(BUILDS_DIR, exist_ok=True)

    zip_name = f'moutai_client_cython_u{user_id}'
    zip_path = os.path.join(BUILDS_DIR, f'{zip_name}.zip')

    # 检查 Cython 是否已安装
    try:
        __import__('Cython')
    except ImportError:
        print('[Cython] Cython 未安装，正在安装...')
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'cython'], check=True)
        __import__('Cython')  # 重新导入

    build_dir = tempfile.mkdtemp(prefix='moutai_cython_')

    try:
        # 1. 复制源码到构建目录
        for src_file, dst_name in [(SOURCE_FILE, 'moutai_client_worker.py'),
                                    (DEMO_FILE, 'demo.py'),
                                    (CRYPTO_FILE, 'crypto.py')]:
            shutil.copy2(src_file, os.path.join(build_dir, dst_name))

        # 2. 注入用户配置到 moutai_client_worker.py
        worker_path = os.path.join(build_dir, 'moutai_client_worker.py')
        with open(worker_path, 'r', encoding='utf-8') as f:
            source = f.read()
        source = re.sub(r'BAKED_USER_ID\s*=\s*0', f'BAKED_USER_ID = {user_id}', source)
        source = source.replace(
            'SERVER_BASE_URL = "http://ipla.top:5000"',
            f'SERVER_BASE_URL = "{server}"')
        source = source.replace(
            'BRIDGE_BASE_URL = "http://ipla.top:5000"',
            f'BRIDGE_BASE_URL = "{bridge}"')
        source = source.replace(
            'API_TOKEN = "your-secure-token-change-me"',
            f'API_TOKEN = "{token}"')
        with open(worker_path, 'w', encoding='utf-8') as f:
            f.write(source)
        print(f'[Cython] 用户ID={user_id}  源码已注入（server={server}）')

        # 3. 生成 setup.py 并编译
        setup_py = os.path.join(build_dir, 'setup.py')
        with open(setup_py, 'w', encoding='utf-8') as f:
            f.write('''from setuptools import setup
from Cython.Build import cythonize

setup(
    name="moutai_client",
    ext_modules=cythonize(
        ["moutai_client_worker.py", "demo.py", "crypto.py"],
        compiler_directives={'language_level': "3"},
        nthreads=4,
    ),
    script_args=["build_ext", "--inplace"],
)
''')

        print('[Cython] 编译中（.py → .c → .so）...')
        start = time.time()
        result = subprocess.run(
            [sys.executable, 'setup.py'],
            cwd=build_dir, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=300
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            err = (result.stderr or result.stdout or '(no output)')
            print(f'[Cython] 编译失败 (耗时{elapsed:.0f}s):')
            for l in err.split('\n')[-30:]:
                if l.strip():
                    print(f'  {l.strip()}')
            return None

        print(f'[Cython] 编译成功 (耗时{elapsed:.0f}s)')

        # 4. 创建 run.py 启动器
        run_py = os.path.join(build_dir, 'run.py')
        with open(run_py, 'w', encoding='utf-8') as f:
            f.write('''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import moutai_client_worker
if __name__ == '__main__':
    moutai_client_worker.main()
''')

        # 5. 收集产物：.so 文件 + run.py
        artifacts = []
        for f in sorted(os.listdir(build_dir)):
            if f.endswith('.so') or f == 'run.py':
                artifacts.append(f)

        if not any(f.endswith('.so') for f in artifacts):
            print('[Cython] 失败: 未生成 .so 文件')
            return None

        print(f'[Cython] 产物: {artifacts}')

        # 6. 清理旧的 ZIP
        if os.path.exists(zip_path):
            os.remove(zip_path)

        # 7. ZIP 打包
        print('[Cython] ZIP打包中...')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in artifacts:
                full = os.path.join(build_dir, f)
                zf.write(full, f)
        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f'[Cython] 成功: {zip_name}.zip ({zip_mb:.1f}MB, 耗时{elapsed:.0f}s)')

        return zip_path

    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def build_plain(user_id: int, server: str = 'http://ipla.top:5000',
               bridge: str = 'http://ipla.top:5000',
               token: str = 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd') -> Optional[str]:
    """
    纯源码打包模式：不加密，直接打包 .py 文件
    返回: 生成的 zip 文件路径，失败返回 None
    """
    os.makedirs(BUILDS_DIR, exist_ok=True)

    zip_name = f'moutai_client_plain_u{user_id}'
    zip_path = os.path.join(BUILDS_DIR, f'{zip_name}.zip')

    build_dir = tempfile.mkdtemp(prefix='moutai_plain_')

    try:
        # 1. 复制所有源码
        for src_file, dst_name in [(SOURCE_FILE, 'moutai_client_worker.py'),
                                    (DEMO_FILE, 'demo.py'),
                                    (CRYPTO_FILE, 'crypto.py'),
                                    (os.path.join(BASEDIR, 'nurture_account.py'), 'nurture_account.py'),
                                    (os.path.join(BASEDIR, '_security_bodies.py'), '_security_bodies.py')]:
            shutil.copy2(src_file, os.path.join(build_dir, dst_name))

        # 2. 注入配置
        worker_path = os.path.join(build_dir, 'moutai_client_worker.py')
        with open(worker_path, 'r', encoding='utf-8') as f:
            source = f.read()
        source = re.sub(r'BAKED_USER_ID\s*=\s*0', f'BAKED_USER_ID = {user_id}', source)
        source = source.replace('SERVER_BASE_URL = "http://ipla.top:5000"', f'SERVER_BASE_URL = "{server}"')
        source = source.replace('BRIDGE_BASE_URL = "http://ipla.top:5000"', f'BRIDGE_BASE_URL = "{bridge}"')
        source = source.replace(
            'API_TOKEN = "your-secure-token-change-me"',
            f'API_TOKEN = "{token}"')
        with open(worker_path, 'w', encoding='utf-8') as f:
            f.write(source)
        print(f'[Plain] 用户ID={user_id}  源码已注入（server={server}）')

        # 3. 复制 services/
        svc_src = os.path.join(BASEDIR, 'services')
        svc_dst = os.path.join(build_dir, 'services')
        if os.path.isdir(svc_src):
            if os.path.exists(svc_dst):
                shutil.rmtree(svc_dst)
            shutil.copytree(svc_src, svc_dst,
                           ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            print('[Plain] services/ 已复制')

        # 4. 生成 setup.sh
        download_url = f'http://ipla.top:6789/moutai_client_plain_u{user_id}.zip'
        setup_sh = f'''#!/bin/bash
set -e

INSTALL_DIR="/opt/moutai"
SERVICE_NAME="moutai-client"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
DOWNLOAD_URL="{download_url}"

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

for entry in "${{PACKAGES[@]}}"; do
    IMP="${{entry%%|*}}"
    PKG="${{entry##*|}}"
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
echo ">>> 安装到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
systemctl stop $SERVICE_NAME 2>/dev/null || true
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"

echo ">>> 生成开机启动脚本..."
cat > "$INSTALL_DIR/start.sh" << 'START_EOF'
#!/bin/bash
set -e

INSTALL_DIR="__INSTALL_DIR__"
DOWNLOAD_URL="__DOWNLOAD_URL__"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

echo "[$(date)] 开机启动 - 从网盘拉取最新包..."
cd /tmp
rm -f moutai_latest.zip
if wget -q -O moutai_latest.zip "$DOWNLOAD_URL" 2>/dev/null; then
    echo "[$(date)] 下载成功"
    python3 -c "
import zipfile
z = zipfile.ZipFile('/tmp/moutai_latest.zip')
z.extractall('$INSTALL_DIR')
z.close()
"
    rm -f /tmp/moutai_latest.zip
else
    echo "[$(date)] 下载失败，使用本地缓存"
fi

for entry in "requests|requests" "Crypto|pycryptodome" "curl_cffi|curl_cffi" "gmssl|gmssl" "socks|PySocks"; do
    IMP="${{entry%%|*}}"
    PKG="${{entry##*|}}"
    if ! python3 -c "import $IMP" 2>/dev/null; then
        python3 -m pip install -q "$PKG" -i "$MIRROR" --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null || true
    fi
done

mkdir -p "$INSTALL_DIR/logs"
echo "[$(date)] 启动客户端..."
cd "$INSTALL_DIR"
exec /usr/bin/python3 "$INSTALL_DIR/moutai_client_worker.py"
START_EOF

sed -i "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$INSTALL_DIR/start.sh"
sed -i "s|__DOWNLOAD_URL__|$DOWNLOAD_URL|g" "$INSTALL_DIR/start.sh"
chmod +x "$INSTALL_DIR/start.sh"

echo ">>> 创建 systemd 服务..."
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

echo ">>> 启用开机自启..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME
sleep 3

echo ""
echo "========================================="
echo " 部署状态: $(systemctl is-active $SERVICE_NAME)"
echo " 网盘地址: $DOWNLOAD_URL"
echo ""
echo " 管理命令:"
echo "  状态: systemctl status $SERVICE_NAME"
echo "  日志: tail -f $INSTALL_DIR/logs/stdout.log"
echo "  停止: systemctl stop $SERVICE_NAME"
echo "  重启: systemctl restart $SERVICE_NAME"
echo " 客户端日志: ls $INSTALL_DIR/logs/"
echo "========================================="
'''
        setup_path = os.path.join(build_dir, 'setup.sh')
        with open(setup_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(setup_sh)
        print('[Plain] setup.sh 已生成')

        # 5. ZIP 打包
        print('[Plain] ZIP打包中...')
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fname in ['moutai_client_worker.py', 'demo.py', 'crypto.py', 'nurture_account.py', '_security_bodies.py', 'setup.sh']:
                fpath = os.path.join(build_dir, fname)
                if os.path.exists(fpath):
                    zf.write(fpath, fname)
            svc_dir = os.path.join(build_dir, 'services')
            if os.path.isdir(svc_dir):
                for root, dirs, files in os.walk(svc_dir):
                    for fn in files:
                        full = os.path.join(root, fn)
                        arc = os.path.relpath(full, build_dir)
                        zf.write(full, arc)
        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f'[Plain] 成功: {zip_name}.zip ({zip_mb:.1f}MB)')

        return zip_path

    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def build_aes(user_id: int, server: str = 'http://ipla.top:5000',
              bridge: str = 'http://ipla.top:5000',
              token: str = 'm9Xk2vLp7Qr4Wn8YbT1cFh6Jd') -> Optional[str]:
    """
    AES-256-GCM 加密模式：Python 源码加密为 .enc 文件（跨版本通用，秒级编译）
    返回: 生成的 zip 文件路径，失败返回 None

    产物结构（ZIP内）:
      run.py              ← 启动器（密钥拆分嵌入，无明文密钥）
      worker.enc          ← moutai_client_worker.py  AES-256-GCM 加密
      demo.enc
      crypto.enc
    """
    os.makedirs(BUILDS_DIR, exist_ok=True)

    zip_name = f'moutai_client_aes_u{user_id}'
    zip_path = os.path.join(BUILDS_DIR, f'{zip_name}.zip')

    build_dir = tempfile.mkdtemp(prefix='moutai_aes_')

    try:
        # 1. 读取源码并注入配置
        for src_file, dst_name in [(SOURCE_FILE, 'moutai_client_worker.py'),
                                    (DEMO_FILE, 'demo.py'),
                                    (CRYPTO_FILE, 'crypto.py'),
                                    (os.path.join(BASEDIR, 'nurture_account.py'), 'nurture_account.py'),
                                    (os.path.join(BASEDIR, '_security_bodies.py'), '_security_bodies.py')]:
            shutil.copy2(src_file, os.path.join(build_dir, dst_name))

        worker_path = os.path.join(build_dir, 'moutai_client_worker.py')
        with open(worker_path, 'r', encoding='utf-8') as f:
            source = f.read()
        source = re.sub(r'BAKED_USER_ID\s*=\s*0', f'BAKED_USER_ID = {user_id}', source)
        source = source.replace('SERVER_BASE_URL = "http://ipla.top:5000"', f'SERVER_BASE_URL = "{server}"')
        source = source.replace('BRIDGE_BASE_URL = "http://ipla.top:5000"', f'BRIDGE_BASE_URL = "{bridge}"')
        source = source.replace(
            'API_TOKEN = "your-secure-token-change-me"',
            f'API_TOKEN = "{token}"')
        with open(worker_path, 'w', encoding='utf-8') as f:
            f.write(source)
        print(f'[AES] 用户ID={user_id}  源码已注入（server={server}）')

        # 2. 生成随机 AES-256 密钥（hex 编码存入 run.py，杜绝转义问题）
        key = os.urandom(32)
        key_hex = key.hex()

        # 3. 加密各 .py 文件为 .enc
        from Crypto.Cipher import AES as AESCipher
        enc_map = {'moutai_client_worker.py': 'worker.enc',
                    'demo.py': 'demo.enc',
                    'crypto.py': 'crypto.enc',
                    'nurture_account.py': 'nurture.enc',
                    '_security_bodies.py': 'security.enc'}
        for src_name, enc_name in enc_map.items():
            src_path = os.path.join(build_dir, src_name)
            with open(src_path, 'rb') as f:
                plain = f.read()
            cipher = AESCipher.new(key, AESCipher.MODE_GCM, nonce=os.urandom(12))
            ciphertext, tag = cipher.encrypt_and_digest(plain)
            enc_path = os.path.join(build_dir, enc_name)
            with open(enc_path, 'wb') as f:
                f.write(cipher.nonce)   # 12 bytes (explicit)
                f.write(tag)            # 16 bytes
                f.write(ciphertext)
            os.remove(src_path)  # 删除明文
            print(f'[AES] {src_name} → {enc_name} 已加密')

        # 4. 生成 run.py 启动器（hex 密钥嵌入）
        run_py = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AES 加密启动器 — 运行时解密并执行"""
import sys, os, types

_DIR = os.path.dirname(os.path.abspath(__file__))
_KEY_HEX = "{key_hex}"

def _key():
    return bytes.fromhex(_KEY_HEX)

def _load(mod_name, enc_name):
    from Crypto.Cipher import AES
    with open(f'{{_DIR}}/{{enc_name}}', 'rb') as f:
        nonce = f.read(12)          # AES-GCM recommended nonce length
        tag = f.read(16)            # GCM tag is always 16 bytes
        ct = f.read()
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    plain = cipher.decrypt_and_verify(ct, tag)
    code = compile(plain, f'<{{mod_name}}>', 'exec')
    mod = types.ModuleType(mod_name)
    mod.__file__ = f'{{_DIR}}/{{enc_name}}'
    sys.modules[mod_name] = mod
    exec(code, mod.__dict__)
    return mod

_ = _load('crypto', 'crypto.enc')
_ = _load('demo', 'demo.enc')
_ = _load('_security_bodies', 'security.enc')
_ = _load('nurture_account', 'nurture.enc')
worker = _load('moutai_client_worker', 'worker.enc')

if __name__ == '__main__' and hasattr(worker, 'main'):
    worker.main()
'''
        run_path = os.path.join(build_dir, 'run.py')
        with open(run_path, 'w', encoding='utf-8') as f:
            f.write(run_py)
        print('[AES] run.py 启动器已生成（密钥分片嵌入）')

        # 4.5 生成 setup.sh（自动检测+国内镜像+开机自动拉取最新包）
        download_url = f'http://ipla.top:6789/moutai_client_aes_u{user_id}.zip'
        setup_sh = f'''#!/bin/bash
# ==========================================
# 茅台客户端 - 一键部署（systemd 开机自启 + 自动拉取最新）
# ==========================================
set -e

INSTALL_DIR="/opt/moutai"
SERVICE_NAME="moutai-client"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
DOWNLOAD_URL="{download_url}"

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

for entry in "${{PACKAGES[@]}}"; do
    IMP="${{entry%%|*}}"
    PKG="${{entry##*|}}"
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
    IMP="${{entry%%|*}}"
    PKG="${{entry##*|}}"
    if ! python3 -c "import $IMP" 2>/dev/null; then
        echo "[$(date)] 安装缺失依赖: $PKG"
        python3 -m pip install -q "$PKG" -i "$MIRROR" --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null || \
        python3 -m pip install -q "$PKG" 2>/dev/null || true
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
'''
        setup_path = os.path.join(build_dir, 'setup.sh')
        with open(setup_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(setup_sh)
        os.chmod(setup_path, 0o755)
        print('[AES] setup.sh 已生成（自动检测依赖 + 清华镜像 + systemd 开机自启）')

        # 4.6 复制 services/ 目录（非敏感模块，不加密）
        svc_src = os.path.join(BASEDIR, 'services')
        svc_dst = os.path.join(build_dir, 'services')
        if os.path.isdir(svc_src):
            if os.path.exists(svc_dst):
                shutil.rmtree(svc_dst)
            shutil.copytree(svc_src, svc_dst,
                           ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            print('[AES] services/ 已复制')

        # 5. ZIP 打包
        print('[AES] ZIP打包中...')
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fname in ['run.py', 'worker.enc', 'demo.enc', 'crypto.enc', 'nurture.enc', 'security.enc', 'setup.sh']:
                fpath = os.path.join(build_dir, fname)
                if os.path.exists(fpath):
                    zf.write(fpath, fname)
            # 打包 services/ 目录
            svc_dir = os.path.join(build_dir, 'services')
            if os.path.isdir(svc_dir):
                for root, dirs, files in os.walk(svc_dir):
                    for fn in files:
                        full = os.path.join(root, fn)
                        arc = os.path.relpath(full, build_dir)
                        zf.write(full, arc)
        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f'[AES] 成功: {zip_name}.zip ({zip_mb:.1f}MB)')

        return zip_path

    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def build_for_all_users(db_session=None, mode='exe'):
    """为所有用户批量打包"""
    if db_session is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        engine = create_engine(
            'mysql+pymysql://maomama:aQ9SnwTx6i4QzRhx@ipla.top:3306/maomama?charset=utf8mb4',
            connect_args={"connect_timeout": 5}
        )
        Session = sessionmaker(bind=engine)
        db = Session()
    else:
        db = db_session

    try:
        from moutai_automation import User
        users = db.query(User).all()
        results = {}
        for u in users:
            print(f'\n{"="*50}')
            print(f'[批量打包] 用户: {u.username} (ID={u.id})')
            if mode == 'nuitka':
                path = build_nuitka_linux(u.id)
            elif mode == 'aes':
                path = build_aes(u.id)
            elif mode == 'plain':
                path = build_plain(u.id)
            elif mode == 'cython':
                path = build_cython(u.id)
            else:
                path = build_exe(u.id)
            results[u.id] = path
        return results
    finally:
        if db_session is None:
            db.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='客户端打包工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python build_client.py --user-id 2
  python build_client.py --user-id 3 --server http://mydomain.com:5000
  python build_client.py --all
        '''
    )
    parser.add_argument('--user-id', type=int, help='用户ID')
    parser.add_argument('--server', default='http://ipla.top:5000', help='服务端地址')
    parser.add_argument('--bridge', default='http://ipla.top:5000', help='桥接地址')
    parser.add_argument('--token', default='your-secure-token-change-me', help='API Token')
    parser.add_argument('--all', action='store_true', help='为所有用户打包')
    parser.add_argument('--cython', action='store_true', help='Cython 模式（编译为 .so，适用于 Linux 部署）')
    parser.add_argument('--aes', action='store_true', help='AES 加密模式（跨版本通用，秒级编译）')
    parser.add_argument('--plain', action='store_true', help='纯源码模式（不加密，直接打包 .py）')
    parser.add_argument('--nuitka', action='store_true', help='Nuitka 模式（原生机器码，最安全，需在 Linux 上编译）')
    parser.add_argument('--exe', action='store_true', help='Nuitka EXE 模式（Windows）')

    args = parser.parse_args()

    if args.cython:
        mode = 'cython'
    elif args.plain:
        mode = 'plain'
    elif args.aes:
        mode = 'aes'
    elif args.exe:
        mode = 'exe'
    elif args.nuitka:
        mode = 'nuitka'
    else:
        mode = 'nuitka'  # 默认 Nuitka（最可靠）

    if args.all:
        print(f'[批量打包] 为所有用户构建客户端（{mode}模式）...')
        results = build_for_all_users(mode=mode)
        success = sum(1 for v in results.values() if v)
        print(f'\n[批量打包] 完成: {success}/{len(results)} 成功')
    elif args.user_id:
        if mode == 'nuitka':
            path = build_nuitka_linux(args.user_id, args.server, args.bridge, args.token)
        elif mode == 'aes':
            path = build_aes(args.user_id, args.server, args.bridge, args.token)
        elif mode == 'plain':
            path = build_plain(args.user_id, args.server, args.bridge, args.token)
        elif mode == 'cython':
            path = build_cython(args.user_id, args.server, args.bridge, args.token)
        elif mode == 'exe':
            path = build_exe(args.user_id, args.server, args.bridge, args.token)
        else:
            path = build_exe(args.user_id, args.server, args.bridge, args.token)
        if path:
            print(f'\n[OK] 下载路径: {path}')
        else:
            print('\n[FAIL] 打包失败，请检查日志')
            sys.exit(1)
    else:
        parser.print_help()
