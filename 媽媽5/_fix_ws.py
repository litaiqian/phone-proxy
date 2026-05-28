import subprocess, sys

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout + r.stderr

log = []

# 1. 卸载
log.append("=== 卸载 websocket 相关包 ===")
log.append(run(r'D:\采购管理\venv\Scripts\pip.exe uninstall websocket websocket-client -y'))

# 2. 安装 websocket-client
log.append("=== 安装 websocket-client ===")
log.append(run(r'D:\采购管理\venv\Scripts\pip.exe install websocket-client'))

# 3. 验证
log.append("=== 验证 import ===")
try:
    import websocket
    log.append(f"version: {getattr(websocket, '__version__', 'N/A')}")
    log.append(f"file: {websocket.__file__}")
    log.append(f"has WebSocket: {hasattr(websocket, 'WebSocket')}")
    log.append(f"has create_connection: {hasattr(websocket, 'create_connection')}")
    # 测试创建 WebSocket
    ws = websocket.WebSocket()
    log.append(f"WebSocket() OK: {type(ws).__name__}")
    ws.close()
except Exception as e:
    log.append(f"ERROR: {e}")

result = '\n'.join(log)
with open(r'D:\采购管理\媽媽5\_pip_result.txt', 'w', encoding='utf-8') as f:
    f.write(result)
print('DONE')
