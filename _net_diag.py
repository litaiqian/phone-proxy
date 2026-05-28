import subprocess, os, time

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_net.txt')

with open(out, 'w', encoding='utf-8') as f:
    # 只查注册表，不联网
    for label, key, val in [
        ("代理开关", "ProxyEnable", ""),
        ("代理地址", "ProxyServer", ""),
        ("代理例外", "ProxyOverride", ""),
        ("PAC", "AutoConfigURL", ""),
    ]:
        r = subprocess.run(
            f'reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v {key}',
            shell=True, capture_output=True, text=True, timeout=5)
        f.write(f"=== {label} ===\n{r.stdout.strip() or r.stderr.strip() or 'not found'}\n\n")

    r = subprocess.run('netsh winhttp show proxy', shell=True, capture_output=True, text=True, timeout=5)
    f.write(f"=== WinHTTP ===\n{r.stdout.strip()}\n\n")

    r = subprocess.run('ipconfig /all', shell=True, capture_output=True, text=True, timeout=5)
    f.write(f"=== ipconfig ===\n{r.stdout.strip()}\n\n")

    f.write(f"HTTP_PROXY={os.environ.get('HTTP_PROXY','none')}\n")
    f.write(f"HTTPS_PROXY={os.environ.get('HTTPS_PROXY','none')}\n")
    f.write(f"NO_PROXY={os.environ.get('NO_PROXY','none')}\n")
