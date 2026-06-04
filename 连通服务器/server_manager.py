# -*- coding: utf-8 -*-
"""
茅台抢购 — 阿里云服务器管理工具
纯 SSH/SFTP 直连，不走网盘中转
功能：上传代码 | 安装依赖 | 启动/停止/重启 | 实时日志 | 一键更新
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import os
import sys
import threading
import time
import webbrowser
import paramiko

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CLIENT_DEPLOY_FILE = os.path.join(BASE_DIR, "client_deploy.json")

# ============================================================
# 配置
# ============================================================
def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ============================================================
# SSH 客户端
# ============================================================
class SSH:
    def __init__(self, host, port, user, pwd):
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.c.connect(host, port, user, pwd, timeout=10)
        self.sftp = self.c.open_sftp()

    def close(self):
        try: self.sftp.close()
        except: pass
        try: self.c.close()
        except: pass

    def run(self, cmd, timeout=30):
        """执行命令，返回 (stdout, stderr, code)"""
        _, out, err = self.c.exec_command(cmd, timeout=timeout)
        return out.read().decode("utf-8", errors="replace"), err.read().decode("utf-8", errors="replace"), out.channel.recv_exit_status()

    def stream(self, cmd, on_line, timeout=None):
        """流式执行，每行回调 on_line(line) — 分配 PTY 强制行缓冲"""
        _, out, _ = self.c.exec_command(cmd, timeout=timeout, get_pty=True)
        for line in iter(out.readline, ""):
            on_line(line.rstrip("\n"))

    def upload(self, local, remote):
        """上传文件"""
        self.sftp.put(local, remote)

    def upload_dir(self, local_dir, remote_dir):
        """递归上传目录"""
        self.run(f"mkdir -p {remote_dir}")
        for root, dirs, files in os.walk(local_dir):
            for d in dirs:
                if d.startswith("__pycache__") or d in ("data", "client_logs", "builds", "uploads", ".github", ".idea"):
                    dirs.remove(d)
            rel = os.path.relpath(root, local_dir)
            if rel == ".":
                rdir = remote_dir
            else:
                rdir = f"{remote_dir}/{rel}".replace("\\", "/")
            self.run(f"mkdir -p {rdir}")
            for f in files:
                if f.endswith(".pyc"):
                    continue
                local_fp = os.path.join(root, f)
                remote_fp = f"{rdir}/{f}".replace("\\", "/")
                try:
                    self.sftp.put(local_fp, remote_fp)
                except Exception as e:
                    print(f"  [跳过] {f}: {e}")

# ============================================================
# 主窗口
# ============================================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("阿里云服务器管理工具")
        self.root.geometry("1050x680")
        self.root.minsize(800, 500)

        self.cfg = load_config()
        self.ssh: SSH | None = None
        self._log_active = False
        self._log_stop_flag = False
        self._busy = False

        self._build_ui()
        self._auto_connect()

    # =================== UI ===================
    def _build_ui(self):
        # 顶部状态栏
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=(8, 0))

        self._status_dot = tk.Label(top, text="⚫", font=("", 14), fg="gray")
        self._status_dot.pack(side=tk.LEFT)
        self._status_label = tk.Label(top, text="未连接", font=("", 10))
        self._status_label.pack(side=tk.LEFT, padx=(4, 20))

        self._open_web_btn = ttk.Button(top, text="🌐 打开网站", command=self._open_web)
        self._open_web_btn.pack(side=tk.RIGHT, padx=2)
        self._quick_update_btn = ttk.Button(top, text="⚡ 一键更新", command=self._one_click_update)
        self._quick_update_btn.pack(side=tk.RIGHT, padx=2)
        ttk.Button(top, text="⚙ 设置", command=self._settings_dialog).pack(side=tk.RIGHT, padx=2)

        # 日志区
        self._log = scrolledtext.ScrolledText(self.root, wrap=tk.WORD,
            font=("Consolas", 10), bg="#1a1a2e", fg="#e0e0e0",
            insertbackground="white", state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True, padx=8, pady=5)
        self._log.tag_config("green", foreground="#4ecca3")
        self._log.tag_config("red", foreground="#ff6b6b")
        self._log.tag_config("cyan", foreground="#00d4ff")
        self._log.tag_config("yellow", foreground="#ffd93d")
        self._log.tag_config("gray", foreground="#888888")

        # 底部操作栏
        bot = ttk.Frame(self.root)
        bot.pack(fill=tk.X, padx=8, pady=(0, 8))

        svc = ttk.LabelFrame(bot, text="服务控制", padding=4)
        svc.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(svc, text="▶ 启动", command=self._svc_start, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(svc, text="⏹ 停止", command=self._svc_stop, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(svc, text="🔄 重启", command=self._svc_restart, width=8).pack(side=tk.LEFT, padx=2)

        deploy = ttk.LabelFrame(bot, text="部署", padding=4)
        deploy.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(deploy, text="📤 上传代码", command=self._upload_code, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(deploy, text="📦 安装依赖", command=self._install_deps, width=10).pack(side=tk.LEFT, padx=2)

        logf = ttk.LabelFrame(bot, text="日志", padding=4)
        logf.pack(side=tk.LEFT, padx=(0, 8))
        self._log_btn_var = tk.StringVar(value="📋 实时日志")
        self._log_btn = ttk.Button(logf, textvariable=self._log_btn_var, command=self._toggle_log, width=10)
        self._log_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(logf, text="🗑 清屏", command=self._clear_log, width=8).pack(side=tk.LEFT, padx=2)

        danger = ttk.LabelFrame(bot, text="重部署", padding=4)
        danger.pack(side=tk.LEFT)
        ttk.Button(danger, text="🗑 清空", command=self._delete_all, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(danger, text="🔁 全重部署", command=self._full_redeploy, width=10).pack(side=tk.LEFT, padx=2)

        tools = ttk.LabelFrame(bot, text="工具", padding=4)
        tools.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(tools, text="🔍 诊断", command=self._diagnose, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools, text="🔧 修复环境", command=self._repair_venv, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools, text="📡 批量部署客户端", command=self._client_deploy_window, width=14).pack(side=tk.LEFT, padx=2)

        # 底部进度条
        self._progress = ttk.Progressbar(self.root, mode="indeterminate")

    # =================== 连接 ===================
    def _auto_connect(self):
        self._log_write("[系统] 正在连接服务器...\n", "gray")
        def run():
            try:
                self.ssh = SSH(self.cfg["host"], self.cfg["port"], self.cfg["username"], self.cfg["password"])
                self.root.after(0, self._on_connected)
            except Exception as e:
                self.root.after(0, lambda: self._on_connect_err(str(e)))
        threading.Thread(target=run, daemon=True).start()

    def _on_connected(self):
        self._status_dot.config(fg="#4ecca3", text="🟢")
        self._status_label.config(text=f"已连接 {self.cfg['host']}:5000")
        self._log_write("[系统] ✅ 连接成功\n", "green")
        self._check_service_status()

    def _on_connect_err(self, err):
        self._status_dot.config(fg="#ff6b6b", text="🔴")
        self._status_label.config(text=f"连接失败")
        self._log_write(f"[系统] ❌ 连接失败: {err}\n", "red")

    def _check_service_status(self):
        if not self.ssh: return
        def run():
            out, _, code = self.ssh.run("pgrep -f 'python.*moutai_automation' | wc -l")
            self.root.after(0, lambda: self._update_svc_status(out.strip() != "0"))
        threading.Thread(target=run, daemon=True).start()

    def _update_svc_status(self, running):
        if running:
            self._status_label.config(text=f"🟢 运行中 | {self.cfg['host']}:5000")
        else:
            self._status_label.config(text=f"🔴 已停止 | {self.cfg['host']}")

    def _open_web(self):
        """调用系统浏览器打开管理网站"""
        url = f"http://{self.cfg['host']}:5000"
        self._log_write(f"[系统] 🌐 打开浏览器: {url}\n", "cyan")
        webbrowser.open(url)

    # =================== 日志 ===================
    def _log_write(self, text, tag=None):
        self._log.config(state=tk.NORMAL)
        if tag:
            self._log.insert(tk.END, text, tag)
        else:
            self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _clear_log(self):
        self._log.config(state=tk.NORMAL)
        self._log.delete("1.0", tk.END)
        self._log.config(state=tk.DISABLED)

    def _toggle_log(self):
        if self._log_active:
            self._stop_log()
        else:
            self._start_log()

    def _start_log(self):
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        if self._log_active: return  # 已在运行
        self._log_active = True
        self._log_stop_flag = False
        self._log_btn_var.set("⏹ 停止日志")
        log_path = f"{self.cfg['project_remote']}/server.log"
        self._log_write(f"[系统] 📋 开始实时日志 ({log_path})...\n", "cyan")

        def run():
            while not self._log_stop_flag:
                try:
                    self.ssh.stream(f"tail -F -n 50 {log_path}",
                        on_line=lambda line: self.root.after(0, lambda l=line: self._log_write(l + "\n")),
                        timeout=None)
                except Exception as e:
                    if not self._log_stop_flag:
                        self.root.after(0, lambda: self._log_write(f"[日志] 断开，2秒后重连...\n", "yellow"))
                        time.sleep(2)
            self.root.after(0, self._on_log_stopped)
        threading.Thread(target=run, daemon=True).start()

    def _ensure_log_started(self):
        """部署完成后自动打开实时日志（如未开启）"""
        if not self._log_active:
            self._start_log()

    def _stop_log(self):
        self._log_stop_flag = True
        self._log_active = False
        self._log_btn_var.set("📋 实时日志")
        self._log_write("[系统] ⏹ 日志已停止\n", "gray")

    def _on_log_stopped(self):
        self._log_active = False
        self._log_btn_var.set("📋 实时日志")

    # =================== 操作 ===================
    def _run_ssh(self, label, cmd, on_done=None):
        """后台执行 SSH 命令，显示进度"""
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        self._log_write(f"[操作] {label}...\n", "yellow")
        self._set_busy(True)

        def run():
            try:
                out, err, code = self.ssh.run(cmd, timeout=60)
                self.root.after(0, lambda: self._on_done(label, out, err, code, on_done))
            except Exception as e:
                self.root.after(0, lambda: self._on_err(label, str(e)))
        threading.Thread(target=run, daemon=True).start()

    def _on_done(self, label, out, err, code, on_done):
        self._set_busy(False)
        if out.strip(): self._log_write(out)
        if err.strip(): self._log_write(err, "red")
        self._log_write(f"[完成] {label} (exit={code})\n", "green" if code == 0 else "red")
        self._check_service_status()
        if on_done: on_done(code == 0)

    def _on_err(self, label, err):
        self._set_busy(False)
        self._log_write(f"[错误] {label}: {err}\n", "red")

    def _set_busy(self, busy):
        self._busy = busy
        if busy:
            self._progress.pack(fill=tk.X, padx=8, pady=(0, 4))
            self._progress.start()
        else:
            self._progress.stop()
            self._progress.pack_forget()

    # -- 服务控制 --
    def _svc_start(self):
        """智能启动：先检测是否已运行"""
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        self._log_write("[启动] 检测服务状态...\n", "yellow")
        def run():
            out, _, _ = self.ssh.run("pgrep -f 'python.*moutai_automation' | wc -l")
            count = int(out.strip() or 0)
            if count > 0:
                self.root.after(0, lambda: self._log_write(f"[启动] 服务已在运行 ({count}个进程)，无需重复启动\n", "cyan"))
                self.root.after(0, self._check_service_status)
            else:
                self.root.after(0, lambda: self._do_svc_start())
        threading.Thread(target=run, daemon=True).start()

    def _smart_start(self, label, remote, on_done=None):
        """智能启动：启动后台进程 → 等3秒 → 检查PID → 死了就显示完整日志"""
        self._log_write(f"[{label}] 启动服务...\n", "yellow")
        self._set_busy(True)

        def run():
            try:
                # 1. 强杀旧进程 + 释放端口（lsof + fuser + pkill 三保险）
                self.ssh.run("pkill -9 -f 'python.*moutai_automation' 2>/dev/null; "
                             "ss -tlnp 'sport = :5000' 2>/dev/null | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | xargs -r kill -9; "
                             "sleep 2; "
                             "if ss -tlnp 'sport = :5000' 2>/dev/null | grep -q ':5000'; then "
                             "echo 'PORT_5000_STILL_BUSY'; else echo 'PORT_5000_FREE'; fi", timeout=10)
                # 2. 启动（自适应 Python 路径）
                cmd = (
                    f"cd {remote} && "
                    f"PYBIN=$(test -f venv/bin/python3 && echo venv/bin/python3 || echo python3); "
                    f"(nohup $PYBIN moutai_automation.py > server.log 2>&1 < /dev/null &) ; "
                    f"sleep 3; "
                    f"if pgrep -f 'python.*moutai_automation' > /dev/null && ss -tlnp 'sport = :5000' 2>/dev/null | grep -q ':5000'; then "
                    f"echo '===OK|服务运行中==='; tail -8 server.log; "
                    f"else echo '===FAIL|服务启动失败==='; cat server.log; fi"
                )
                out, err, code = self.ssh.run(cmd, timeout=15)
                self.root.after(0, lambda: self._on_start_result(label, out, err, on_done))
            except Exception as e:
                self.root.after(0, lambda: self._log_write(f"[{label}] ❌ {e}\n", "red"))
                self.root.after(0, lambda: self._set_busy(False))
        threading.Thread(target=run, daemon=True).start()

    def _on_start_result(self, label, out, err, on_done):
        self._set_busy(False)
        out = (out or "").strip()
        err = (err or "").strip()
        if err:
            self._log_write(err + "\n", "red")
        if not out:
            self._log_write(f"[{label}] ⚠ 无输出，请检查服务器\n", "red")
        elif "FAIL|" in out:
            self._log_write(f"[{label}] ❌ 启动失败！\n", "red")
            self._log_write(out + "\n", "red")
        else:
            self._log_write(out + "\n")
            self._log_write(f"[{label}] ✅ 启动成功\n", "green")
        self._check_service_status()
        if on_done:
            on_done("OK|" in out)

    def _do_svc_start(self):
        self._smart_start("启动", self.cfg["project_remote"])

    def _svc_stop(self):
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        self._log_write("[停止] 检测服务状态...\n", "yellow")
        def run():
            out, _, _ = self.ssh.run("pgrep -f 'python.*moutai_automation' | wc -l")
            count = int(out.strip() or 0)
            if count == 0:
                self.root.after(0, lambda: self._log_write("[停止] 服务未运行\n", "gray"))
                self.root.after(0, self._check_service_status)
            else:
                self.root.after(0, lambda: self._run_ssh("停止服务", "pkill -9 -f 'python.*moutai_automation' 2>/dev/null; ss -tlnp 'sport = :5000' 2>/dev/null | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | xargs -r kill -9; echo OK"))
        threading.Thread(target=run, daemon=True).start()

    def _svc_restart(self):
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        self._smart_start("重启", self.cfg["project_remote"])

    # -- 部署 --
    def _upload_code(self, on_done=None):
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        local = os.path.abspath(os.path.join(BASE_DIR, self.cfg["project_local"]))
        if not os.path.isdir(local):
            return messagebox.showerror("错误", f"本地项目目录不存在:\n{local}")

        self._log_write(f"[上传] 从 {local} → {self.cfg['project_remote']} ...\n", "yellow")
        self._set_busy(True)

        def run():
            total, failed = 0, []
            try:
                # 上传核心 py 文件
                for f in ("moutai_automation.py", "demo.py", "crypto.py", "requirements.txt"):
                    try:
                        self.ssh.upload(os.path.join(local, f), f"{self.cfg['project_remote']}/{f}")
                        total += 1
                    except Exception as e:
                        failed.append(f"{f}: {e}")
                # 上传 routes
                rd = os.path.join(local, "routes")
                if os.path.isdir(rd):
                    self.ssh.run(f"mkdir -p {self.cfg['project_remote']}/routes")
                    for f in os.listdir(rd):
                        if f.endswith(".py"):
                            try:
                                self.ssh.upload(os.path.join(rd, f), f"{self.cfg['project_remote']}/routes/{f}")
                                total += 1
                            except Exception as e:
                                failed.append(f"routes/{f}: {e}")
                # 上传 templates
                td = os.path.join(local, "templates")
                if os.path.isdir(td):
                    self.ssh.run(f"mkdir -p {self.cfg['project_remote']}/templates")
                    for f in os.listdir(td):
                        if f.endswith((".html", ".css")):
                            try:
                                self.ssh.upload(os.path.join(td, f), f"{self.cfg['project_remote']}/templates/{f}")
                                total += 1
                            except Exception as e:
                                failed.append(f"templates/{f}: {e}")
                # 上传 slider
                sd = os.path.join(local, "slider")
                if os.path.isdir(sd):
                    self.ssh.run(f"mkdir -p {self.cfg['project_remote']}/slider")
                    for f in os.listdir(sd):
                        try:
                            self.ssh.upload(os.path.join(sd, f), f"{self.cfg['project_remote']}/slider/{f}")
                            total += 1
                        except Exception as e:
                            failed.append(f"slider/{f}: {e}")
                if failed:
                    self.root.after(0, lambda: self._log_write(f"[上传] ⚠ 成功 {total}，失败 {len(failed)}: {', '.join(failed)}\n", "yellow"))
                else:
                    self.root.after(0, lambda: self._log_write(f"[上传] ✅ 完成，{total} 个文件\n", "green"))
            except Exception as e:
                self.root.after(0, lambda: self._log_write(f"[上传] ❌ {e}\n", "red"))
            finally:
                self.root.after(0, lambda: self._set_busy(False))
        threading.Thread(target=run, daemon=True).start()

    def _install_deps(self):
        remote = self.cfg["project_remote"]
        cmd = (f"cd {remote} && "
               f"if (python3 -m venv venv 2>/dev/null && venv/bin/pip install "
               f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
               f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
               f"-i https://mirrors.aliyun.com/pypi/simple/ -q); then echo 'VENV_OK'; else "
               f"python3 -m pip install --break-system-packages -q "
               f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
               f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
               f"-i https://mirrors.aliyun.com/pypi/simple/; fi")
        self._run_ssh("安装依赖", cmd)

    def _delete_all(self):
        if not messagebox.askyesno("确认", "确定要清空服务器项目代码？\n（保留 venv 虚拟环境）\n此操作不可恢复！"):
            return
        remote = self.cfg["project_remote"]
        self._run_ssh("清空项目", f"rm -f {remote}/*.py {remote}/*.txt {remote}/server.log; rm -rf {remote}/routes {remote}/templates {remote}/slider {remote}/__pycache__ {remote}/data {remote}/uploads")

    def _full_redeploy(self):
        if not messagebox.askyesno("确认", "完全重部署：\n1. 清理端口 → 2. 清空代码 → 3. 上传 → 4. 安装依赖 → 5. 启动\n\n确定？"):
            return
        self._log_write("[重部署] 开始...\n", "cyan")

        def run():
            remote = self.cfg["project_remote"]
            local = os.path.abspath(os.path.join(BASE_DIR, self.cfg["project_local"]))
            try:
                # 1. 清理端口（最先做，确保端口释放）
                self.root.after(0, lambda: self._log_write("[重部署] 1/5 清理端口...\n", "yellow"))
                kill_out, _, _ = self.ssh.run(
                    "pkill -9 -f 'python.*moutai_automation' 2>/dev/null; "
                    "ss -tlnp 'sport = :5000' 2>/dev/null | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | xargs -r kill -9; "
                    "sleep 2; "
                    "if ss -tlnp 'sport = :5000' 2>/dev/null | grep -q ':5000'; then "
                    "echo 'PORT_5000_STILL_BUSY'; else echo 'PORT_5000_FREE'; fi", timeout=10)
                self.root.after(0, lambda o=kill_out: self._log_write(
                    f"[重部署] 端口状态: {o.strip()}\n",
                    "red" if "STILL_BUSY" in o else "green"))

                # 2. 清空代码（保留 venv）
                self.root.after(0, lambda: self._log_write("[重部署] 2/5 清空代码...\n", "yellow"))
                self.ssh.run(f"rm -f {remote}/*.py {remote}/*.txt {remote}/server.log; rm -rf {remote}/routes {remote}/templates {remote}/slider {remote}/__pycache__ {remote}/data {remote}/uploads")
                self.ssh.run(f"mkdir -p {remote}/routes {remote}/templates {remote}/slider")

                # 3. 上传
                self.root.after(0, lambda: self._log_write("[重部署] 3/5 上传代码...\n", "yellow"))
                total = 0
                for f in ("moutai_automation.py", "demo.py", "crypto.py", "requirements.txt"):
                    try:
                        self.ssh.upload(os.path.join(local, f), f"{remote}/{f}")
                        total += 1
                    except: pass
                for d in ("routes", "templates", "slider"):
                    sd = os.path.join(local, d)
                    if os.path.isdir(sd):
                        for f in os.listdir(sd):
                            if d == "routes" and not f.endswith(".py"): continue
                            if d == "templates" and not f.endswith((".html", ".css")): continue
                            self.ssh.upload(os.path.join(sd, f), f"{remote}/{d}/{f}")
                            total += 1
                self.root.after(0, lambda: self._log_write(f"[重部署] 上传 {total} 个文件\n", "green"))

                # 4. 安装依赖（venv 优先，失败走 --break-system-packages）
                self.root.after(0, lambda: self._log_write("[重部署] 4/5 安装依赖...\n", "yellow"))
                install_cmd = (
                    f"cd {remote} && "
                    f"if (python3 -m venv venv 2>/dev/null && venv/bin/pip install "
                    f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
                    f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
                    f"-i https://mirrors.aliyun.com/pypi/simple/ -q 2>&1); then "
                    f"echo 'VENV_OK'; else "
                    f"echo 'VENV_FAIL, using --break-system-packages'; "
                    f"python3 -m pip install --break-system-packages -q "
                    f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
                    f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
                    f"-i https://mirrors.aliyun.com/pypi/simple/ 2>&1; fi"
                )
                out, err, code = self.ssh.run(install_cmd, timeout=120)
                self.root.after(0, lambda: self._log_write(f"[重部署] 依赖安装 exit={code}\n", "green" if code == 0 else "red"))

                # 5. 启动（自适应 Python 路径）
                self.root.after(0, lambda: self._log_write("[重部署] 5/5 启动服务...\n", "yellow"))
                # 启动前再杀一次（防止步骤3/4期间进程被 systemd 等重新拉起）
                self.ssh.run("pkill -9 -f 'python.*moutai_automation' 2>/dev/null; "
                             "ss -tlnp 'sport = :5000' 2>/dev/null | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | xargs -r kill -9; "
                             "sleep 1", timeout=8)
                cmd = (
                    f"cd {remote} && "
                    f"PYBIN=$(test -f venv/bin/python3 && echo venv/bin/python3 || echo python3); "
                    f"(nohup $PYBIN moutai_automation.py > server.log 2>&1 < /dev/null &) ; "
                    f"sleep 3; "
                    f"if pgrep -f 'python.*moutai_automation' > /dev/null && ss -tlnp 'sport = :5000' 2>/dev/null | grep -q ':5000'; then "
                    f"echo '===OK|服务运行中==='; tail -5 server.log; "
                    f"else echo '===FAIL|服务启动失败==='; cat server.log; fi"
                )
                out, err, code = self.ssh.run(cmd, timeout=15)
                self.root.after(0, lambda: self._log_write(out))
                if err.strip():
                    self.root.after(0, lambda: self._log_write(err, "red"))
                if "===FAIL|" in out:
                    self.root.after(0, lambda: self._log_write("[重部署] ❌ 启动失败\n", "red"))
                else:
                    self.root.after(0, lambda: self._log_write("[重部署] ✅ 完成\n", "green"))
                    self.root.after(0, self._ensure_log_started)
                self.root.after(0, self._check_service_status)
            except Exception as e:
                self.root.after(0, lambda: self._log_write(f"[重部署] ❌ {e}\n", "red"))
            finally:
                self.root.after(0, lambda: self._set_busy(False))
        self._set_busy(True)
        threading.Thread(target=run, daemon=True).start()

    def _one_click_update(self):
        """一键更新：清理端口 → 上传代码 → 装依赖 → 重启"""
        self._log_write("[一键更新] 开始...\n", "cyan")
        self._set_busy(True)
        remote = self.cfg["project_remote"]
        local = os.path.abspath(os.path.join(BASE_DIR, self.cfg["project_local"]))

        def run():
            try:
                # 1. 清理端口（最先做，确保端口释放）
                self.root.after(0, lambda: self._log_write("[一键更新] 1/4 清理端口...\n", "yellow"))
                kill_out, _, _ = self.ssh.run(
                    "pkill -9 -f 'python.*moutai_automation' 2>/dev/null; "
                    "ss -tlnp 'sport = :5000' 2>/dev/null | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | xargs -r kill -9; "
                    "sleep 2; "
                    "if ss -tlnp 'sport = :5000' 2>/dev/null | grep -q ':5000'; then "
                    "echo 'PORT_5000_STILL_BUSY'; else echo 'PORT_5000_FREE'; fi", timeout=10)
                self.root.after(0, lambda o=kill_out: self._log_write(
                    f"[一键更新] 端口状态: {o.strip()}\n",
                    "red" if "STILL_BUSY" in o else "green"))

                # 2. 上传代码
                self.root.after(0, lambda: self._log_write("[一键更新] 2/4 上传代码...\n", "yellow"))
                # 先确保远程子目录存在
                self.ssh.run(f"mkdir -p {remote}/routes {remote}/templates {remote}/slider")
                total, failed = 0, []
                for f in ("moutai_automation.py", "demo.py", "crypto.py", "requirements.txt"):
                    try:
                        self.ssh.upload(os.path.join(local, f), f"{remote}/{f}")
                        total += 1
                    except Exception as e:
                        failed.append(f)
                for d in ("routes", "templates", "slider"):
                    sd = os.path.join(local, d)
                    if os.path.isdir(sd):
                        for f in os.listdir(sd):
                            if d == "routes" and not f.endswith(".py"): continue
                            if d == "templates" and not f.endswith((".html", ".css")): continue
                            try:
                                self.ssh.upload(os.path.join(sd, f), f"{remote}/{d}/{f}")
                                total += 1
                            except Exception as e:
                                failed.append(f"{d}/{f}")
                if failed:
                    self.root.after(0, lambda: self._log_write(
                        f"[一键更新] 上传 {total} 个文件，⚠ 失败 {len(failed)}: {', '.join(failed)}\n", "yellow"))
                else:
                    self.root.after(0, lambda: self._log_write(f"[一键更新] 上传 {total} 个文件\n", "green"))

                # 3. 装依赖（venv 优先，失败走 --break-system-packages）
                self.root.after(0, lambda: self._log_write("[一键更新] 3/4 安装依赖...\n", "yellow"))
                install_cmd = (
                    f"cd {remote} && "
                    f"if (python3 -m venv venv 2>/dev/null && venv/bin/pip install "
                    f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
                    f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
                    f"-i https://mirrors.aliyun.com/pypi/simple/ -q 2>&1); then echo 'VENV_OK'; else "
                    f"echo 'VENV_FAIL, using --break-system-packages'; "
                    f"python3 -m pip install --break-system-packages -q "
                    f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
                    f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
                    f"-i https://mirrors.aliyun.com/pypi/simple/ 2>&1; fi"
                )
                out, err, code = self.ssh.run(install_cmd, timeout=120)

                # 4. 重启
                self.root.after(0, lambda: self._log_write("[一键更新] 4/4 重启服务...\n", "yellow"))
                self.ssh.run("pkill -9 -f 'python.*moutai_automation' 2>/dev/null; "
                             "ss -tlnp 'sport = :5000' 2>/dev/null | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | xargs -r kill -9; "
                             "sleep 2; "
                             "if ss -tlnp 'sport = :5000' 2>/dev/null | grep -q ':5000'; then "
                             "echo 'PORT_5000_STILL_BUSY'; else echo 'PORT_5000_FREE'; fi", timeout=10)
                cmd = (
                    f"cd {remote} && "
                    f"PYBIN=$(test -f venv/bin/python3 && echo venv/bin/python3 || echo python3); "
                    f"(nohup $PYBIN moutai_automation.py > server.log 2>&1 < /dev/null &) ; "
                    f"sleep 3; "
                    f"if pgrep -f 'python.*moutai_automation' > /dev/null && ss -tlnp 'sport = :5000' 2>/dev/null | grep -q ':5000'; then "
                    f"echo '===OK|服务运行中==='; tail -8 server.log; "
                    f"else echo '===FAIL|服务启动失败==='; cat server.log; fi"
                )
                out, err, code = self.ssh.run(cmd, timeout=15)
                out = (out or "").strip()
                err = (err or "").strip()
                if err:
                    self.root.after(0, lambda: self._log_write(err + "\n", "red"))
                if not out or out == "None":
                    self.root.after(0, lambda: self._log_write("[一键更新] 命令无输出，但服务可能已在运行\n", "yellow"))
                    self.root.after(0, self._check_service_status)
                elif "===FAIL|" in out:
                    self.root.after(0, lambda: self._log_write("[一键更新] ❌ 启动失败！\n", "red"))
                    self.root.after(0, lambda: self._log_write(out + "\n", "red"))
                else:
                    self.root.after(0, lambda: self._log_write(out + "\n"))
                    self.root.after(0, lambda: self._log_write("[一键更新] ✅ 完成\n", "green"))
                    self.root.after(0, self._ensure_log_started)
                self.root.after(0, self._check_service_status)
            except Exception as e:
                self.root.after(0, lambda: self._log_write(f"[一键更新] ❌ {e}\n", "red"))
            finally:
                self.root.after(0, lambda: self._set_busy(False))
        threading.Thread(target=run, daemon=True).start()

    # =================== 诊断 ===================
    def _repair_venv(self):
        """修复 venv：检测并重建虚拟环境 + 安装依赖（venv 优先，失败走 --break-system-packages）"""
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        self._log_write("[修复] 检查并重建虚拟环境...\n", "cyan")
        remote = self.cfg["project_remote"]
        cmd = (f"cd {remote} && "
               f"if (python3 -m venv venv 2>/dev/null && venv/bin/pip install "
               f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
               f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
               f"-i https://mirrors.aliyun.com/pypi/simple/ -q); then echo 'VENV_OK'; else "
               f"python3 -m pip install --break-system-packages -q "
               f"fastapi uvicorn sqlalchemy pymysql pandas werkzeug python-multipart "
               f"httpx pycryptodome gmssl tls_client curl_cffi itsdangerous aiofiles jinja2 wasmtime requests "
               f"-i https://mirrors.aliyun.com/pypi/simple/; fi")
        self._run_ssh("修复环境", cmd)

    def _diagnose(self):
        """一键诊断服务器常见问题"""
        if not self.ssh: return messagebox.showwarning("未连接", "请先连接服务器")
        self._log_write("\n" + "="*50 + "\n", "cyan")
        self._log_write("[诊断] 开始服务器健康检查...\n", "cyan")
        self._set_busy(True)

        def run():
            checks = []
            remote = self.cfg["project_remote"]
            try:
                # 1. Python 路径
                out, _, _ = self.ssh.run(f"ls {remote}/venv/bin/python* 2>/dev/null || echo 'MISSING'")
                python_ok = "python3" in out
                checks.append(("Python 解释器", python_ok, out.strip()[:80]))

                # 2. 项目文件
                out, _, _ = self.ssh.run(f"test -f {remote}/moutai_automation.py && echo OK || echo MISSING")
                file_ok = "OK" in out
                checks.append(("主程序文件", file_ok, out.strip()))

                # 3. 端口监听
                out, _, _ = self.ssh.run("netstat -tlnp 2>&1 | grep ':5000 ' || echo 'NOT_LISTENING'")
                port_ok = "5000" in out and "LISTEN" in out
                checks.append(("端口 5000", port_ok, out.strip()[:100] or "未监听"))

                # 4. 进程
                out, _, _ = self.ssh.run("pgrep -f 'python.*moutai_automation' | wc -l")
                proc_count = int(out.strip() or 0)
                checks.append(("服务进程", proc_count > 0, f"{proc_count} 个"))

                # 5. server.log 最后几行
                out, _, _ = self.ssh.run(f"tail -3 {remote}/server.log 2>/dev/null || echo 'NO_LOG'")
                checks.append(("最近日志", bool(out.strip()), out.strip()[:150]))

                # 6. TemplateResponse 修复检查
                out, _, _ = self.ssh.run(
                    f"grep -c '\"request\".*request' {remote}/moutai_automation.py 2>/dev/null || echo 0")
                req_count = int(out.strip() or 0)
                checks.append(("TemplateResponse 修复", req_count >= 6, f"{req_count} 处含 request"))

                self.root.after(0, lambda: self._show_diagnose(checks))
            except Exception as e:
                self.root.after(0, lambda: self._log_write(f"[诊断] ❌ {e}\n", "red"))
                self.root.after(0, lambda: self._set_busy(False))
        threading.Thread(target=run, daemon=True).start()

    def _show_diagnose(self, checks):
        self._set_busy(False)
        all_ok = True
        for name, ok, detail in checks:
            icon = "✅" if ok else "❌"
            tag = "green" if ok else "red"
            self._log_write(f"  {icon} {name}: {detail}\n", tag)
            if not ok:
                all_ok = False
        if all_ok:
            self._log_write("[诊断] 🎉 一切正常！\n", "green")
        else:
            self._log_write("[诊断] ⚠ 发现问题，请点击 🔁 全重部署 修复\n", "yellow")
        self._log_write("="*50 + "\n", "cyan")
        self._check_service_status()

    # =================== 设置 ===================
    def _settings_dialog(self):
        d = tk.Toplevel(self.root)
        d.title("服务器设置")
        d.geometry("350x280")
        d.resizable(False, False)
        d.transient(self.root)
        d.grab_set()

        f = ttk.Frame(d, padding=15)
        f.pack(fill=tk.BOTH, expand=True)

        fields = [
            ("IP 地址", "host"),
            ("SSH 端口", "port"),
            ("用户名", "username"),
            ("密码", "password"),
        ]
        vars = {}
        for i, (label, key) in enumerate(fields):
            ttk.Label(f, text=label + ":").grid(row=i, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=str(self.cfg.get(key, "")))
            vars[key] = v
            show = "*" if key == "password" else ""
            ttk.Entry(f, textvariable=v, show=show, width=28).grid(row=i, column=1, sticky="ew", pady=3, padx=(8, 0))

        def save():
            for key, v in vars.items():
                val = v.get().strip()
                self.cfg[key] = int(val) if key == "port" else val
            save_config(self.cfg)
            d.destroy()
            messagebox.showinfo("已保存", "设置已保存。下次连接生效。")

        ttk.Button(f, text="💾 保存", command=save).grid(row=len(fields), column=0, columnspan=2, pady=(15, 0), sticky="ew")

    # =================== 客户端批量部署 ===================
    _CLIENT_FILES = ["moutai_client_worker.py", "demo.py", "crypto.py", "requirements.txt"]
    _CLIENT_DIRS = ["slider"]
    _CLIENT_REMOTE = "/opt/moutai-client"
    _CLIENT_DEPS = "requests curl_cffi pycryptodome gmssl wasmtime"

    def _load_client_data(self):
        """从持久化文件恢复 IP 列表和客户端列表"""
        if not os.path.exists(CLIENT_DEPLOY_FILE):
            return
        try:
            with open(CLIENT_DEPLOY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 恢复 IP 输入框
            ip_text = data.get('ip_text', '')
            if ip_text:
                self._cd_ip.insert('1.0', ip_text)
            # 恢复默认窗口数
            def_wins = data.get('default_wins', '1')
            if hasattr(self, '_cd_def_wins'):
                self._cd_def_wins.set(str(def_wins))
            # 恢复客户端列表
            for item in data.get('clients', []):
                ip = item.get('ip', '')
                if ip:
                    self._cd_tree.insert('', tk.END, iid=ip,
                        values=(ip, item.get('uid', 0), item.get('wins', 1), item.get('status', '')))
        except Exception:
            pass

    def _save_client_data(self):
        """保存 IP 列表和客户端列表到持久化文件"""
        try:
            ip_text = self._cd_ip.get('1.0', tk.END).strip()
            def_wins = self._cd_def_wins.get() if hasattr(self, '_cd_def_wins') else '1'
            clients = []
            for iid in self._cd_tree.get_children():
                vals = self._cd_tree.item(iid, 'values')
                if vals:
                    clients.append({
                        'ip': vals[0],
                        'uid': int(vals[1]) if vals[1] else 0,
                        'wins': int(vals[2]) if len(vals) > 2 and str(vals[2]).isdigit() else 1,
                        'status': vals[3] if len(vals) > 3 else ''
                    })
            data = {'ip_text': ip_text, 'default_wins': def_wins, 'clients': clients}
            with open(CLIENT_DEPLOY_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _clear_client_data(self):
        """清空持久化的客户端数据"""
        self._cd_ip.delete('1.0', tk.END)
        self._cd_tree.delete(*self._cd_tree.get_children())
        try:
            if os.path.exists(CLIENT_DEPLOY_FILE):
                os.remove(CLIENT_DEPLOY_FILE)
        except Exception:
            pass

    def _client_deploy_window(self):
        d = tk.Toplevel(self.root)
        d.title("客户端批量部署")
        d.geometry("820x640")
        d.minsize(680, 480)
        d.transient(self.root)

        # 配置区
        cfg = ttk.LabelFrame(d, text="部署配置", padding=8)
        cfg.pack(fill=tk.X, padx=8, pady=(8, 4))
        r1 = ttk.Frame(cfg); r1.pack(fill=tk.X, pady=2)
        ttk.Label(r1, text="SSH用户:").pack(side=tk.LEFT)
        self._cd_user = tk.StringVar(value=self.cfg.get("username", "root"))
        ttk.Entry(r1, textvariable=self._cd_user, width=12).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(r1, text="SSH密码:").pack(side=tk.LEFT)
        self._cd_pwd = tk.StringVar(value=self.cfg.get("password", ""))
        ttk.Entry(r1, textvariable=self._cd_pwd, show="*", width=16).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(r1, text="默认窗口数:").pack(side=tk.LEFT)
        self._cd_def_wins = tk.StringVar(value="1")
        ttk.Spinbox(r1, from_=1, to=50, textvariable=self._cd_def_wins, width=4).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(r1, text="客户端默认连接 → http://8.137.86.132:5000", foreground="gray").pack(side=tk.LEFT, padx=4)

        # IP输入
        ipf = ttk.LabelFrame(d, text="服务器IP（每行: IP [user_id] [窗口数]，不填user_id递增，窗口数使用默认值）", padding=8)
        ipf.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._cd_ip = tk.Text(ipf, height=5, font=("Consolas", 10))
        self._cd_ip.pack(fill=tk.BOTH, expand=True)

        # 按钮
        bf = ttk.Frame(d); bf.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(bf, text="🚀 批量部署", command=self._batch_deploy_clients).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="📦 重新部署启动", command=self._redeploy_restart_client).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="📋 查看日志", command=self._client_view_log).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="🔄 重启所选", command=self._restart_selected_client).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="⏹ 停止所选", command=self._stop_selected_client).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="🗑 清空IP", command=self._clear_client_data).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bf, text="🔁 重试失败", command=self._retry_failed_clients).pack(side=tk.RIGHT, padx=2)

        # 状态表
        sf = ttk.LabelFrame(d, text="客户端列表（双击或右键操作）", padding=4)
        sf.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))
        cols = ("ip", "uid", "wins", "status")
        self._cd_tree = ttk.Treeview(sf, columns=cols, show="headings", height=10)
        self._cd_tree.heading("ip", text="IP"); self._cd_tree.column("ip", width=120)
        self._cd_tree.heading("uid", text="用户ID"); self._cd_tree.column("uid", width=55)
        self._cd_tree.heading("wins", text="窗口数"); self._cd_tree.column("wins", width=55)
        self._cd_tree.heading("status", text="状态"); self._cd_tree.column("status", width=500)
        sb = ttk.Scrollbar(sf, orient=tk.VERTICAL, command=self._cd_tree.yview)
        self._cd_tree.configure(yscrollcommand=sb.set)
        self._cd_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._cd_tree.bind("<Double-1>", lambda e: self._client_view_log())
        menu = tk.Menu(d, tearoff=0)
        menu.add_command(label="📋 查看日志", command=self._client_view_log)
        menu.add_command(label="📦 重新部署", command=self._redeploy_restart_client)
        menu.add_command(label="🔄 重启", command=self._restart_selected_client)
        menu.add_command(label="⏹ 停止", command=self._stop_selected_client)
        self._cd_tree.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))

        # 恢复上次保存的数据
        self.root.after(100, self._load_client_data)

        # 窗口关闭时自动保存
        d.protocol("WM_DELETE_WINDOW", lambda: (self._save_client_data(), d.destroy()))

    def _parse_ips(self):
        text = self._cd_ip.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("提示", "请输入至少一个IP地址")
            return []
        default_wins = self._cd_def_wins.get()
        default_wins = int(default_wins) if str(default_wins).isdigit() else 1
        result, auto_id = [], 1
        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"): continue
            parts = line.split()
            ip = parts[0]
            uid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else auto_id
            # ★ 第3字段 = 窗口数，不填则使用默认值
            wins = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else default_wins
            wins = max(1, min(wins, 50))  # 1~50 限制
            result.append((ip, uid, wins))
            auto_id = uid + 1
        return result

    def _batch_deploy_clients(self, retry_ips=None):
        """批量部署客户端。retry_ips: 仅重试指定IP列表[(ip, uid, wins), ...]，None=全部"""
        if retry_ips:
            ips = retry_ips
        else:
            ips = self._parse_ips()
            if not ips: return
            self._cd_tree.delete(*self._cd_tree.get_children())
            for ip, uid, wins in ips:
                self._cd_tree.insert("", tk.END, iid=ip, values=(ip, uid, wins, "⏳ 等待..."))

        # ★ 从服务器数据库读取每个用户的 client_windows 配置，覆盖默认值
        ips = self._apply_server_window_config(ips)

        failed = []
        total = len(ips)
        for ip, uid, wins in ips:
            self._cd_tree.set(ip, "status", "⏳ 部署中...")
        def deploy_next(idx=0):
            if idx >= total: 
                # ★ 全部完成 → 输出汇总
                self.root.after(0, lambda: self._print_deploy_summary(ips))
                return
            ip, uid, wins = ips[idx]
            def on_done(is_ok):
                if not is_ok:
                    failed.append((ip, uid, wins))
                deploy_next(idx + 1)
            self._deploy_one(ip, uid, wins, on_done)
        # 保存到持久化文件
        self._save_client_data()
        threading.Thread(target=lambda: deploy_next(0), daemon=True).start()

    def _print_deploy_summary(self, ips):
        """部署完成后输出汇总，标注失败IP"""
        success_count = 0
        fail_list = []
        for ip, uid, wins in ips:
            vals = self._cd_tree.item(ip, "values")
            status = vals[3] if vals and len(vals) > 3 else ""
            if "✅" in status:
                success_count += 1
            else:
                fail_list.append(ip)
        self._log_write(f"{'='*50}\n", "cyan")
        self._log_write(f"[部署汇总] ✅ {success_count}/{len(ips)} 成功", "green" if success_count == len(ips) else "yellow")
        if fail_list:
            self._log_write(f" | ❌ 失败: {', '.join(fail_list)}\n", "red")
            self._log_write(f"[提示] 可选中失败IP → 右键 → 📦 重新部署 逐个重试\n", "yellow")
        else:
            self._log_write(f"\n")
        self._log_write(f"{'='*50}\n", "cyan")
    
    def _apply_server_window_config(self, ips):
        """从服务器数据库读取每个用户的 client_windows 配置，覆盖 ips 中的 wins"""
        if not self.ssh:
            return ips
        uids = list(set(uid for _, uid, _ in ips))
        if not uids:
            return ips
        uid_list = ','.join(str(u) for u in uids)
        db_path = f"{self.cfg['project_remote']}/data/moutai.db"
        # ★ 查所有用户 + 所有配置（解决 uid 自动分配与 DB 实际 ID 不匹配的问题）
        py_cmd = (
            f"python3 -c \""
            f"import sqlite3; "
            f"c=sqlite3.connect('{db_path}'); "
            f"u_rows=c.execute('SELECT id,username FROM user').fetchall(); "
            f"c_rows=c.execute('SELECT user_id,COALESCE(client_windows,1) FROM user_config').fetchall(); "
            f"c_dict={{r[0]:r[1] for r in c_rows}}; "
            f"[print(f'{{r[0]}}|{{c_dict.get(r[0],1)}}|{{r[1]}}') for r in u_rows]\" 2>/dev/null"
        )
        out, _, _ = self.ssh.run(py_cmd, timeout=10)
        if not out.strip():
            self._log_write(f"[配置] ⚠ 读取服务器 client_windows 失败（DB查询为空），使用本地默认值\n", "yellow")
            return ips
        # 解析 uid→wins 映射（格式: uid|wins|username）
        uid_wins = {}
        uid_name = {}
        for line in out.strip().split('\n'):
            line = line.strip()
            if '|' not in line:
                continue
            parts = line.split('|')
            if len(parts) >= 2:
                try:
                    uid_wins[int(parts[0])] = max(1, int(parts[1]))
                    if len(parts) >= 3:
                        uid_name[int(parts[0])] = parts[2]
                except ValueError:
                    pass
        if not uid_wins:
            self._log_write(f"[配置] ⚠ 解析 client_windows 结果为空\n", "yellow")
            return ips
        self._log_write(f"[配置] 服务器用户: " + ", ".join(f"{n or uid}({uid}):{w}窗口" for uid, n, w in [(u, uid_name.get(u,''), uid_wins[u]) for u in uid_wins]) + "\n", "cyan")
        result = []
        for ip, uid, wins in ips:
            if uid in uid_wins:
                svr_wins = uid_wins[uid]
                if svr_wins != wins:
                    self._log_write(f"[配置] uid={uid}: 服务器 client_windows={svr_wins} (本地默认={wins}) → 使用服务器值\n", "cyan")
                result.append((ip, uid, svr_wins))
            else:
                self._log_write(f"[配置] uid={uid}: 服务器无配置记录，使用本地默认 {wins}\n", "yellow")
                result.append((ip, uid, wins))
        return result
    
    def _retry_failed_clients(self):
        """重试所有失败的客户端（状态不含✅的）"""
        retry_list = []
        for iid in self._cd_tree.get_children():
            vals = self._cd_tree.item(iid, "values")
            if not vals: continue
            status = vals[3] if len(vals) > 3 else ""
            if "✅" not in status and "⏳" not in status:
                retry_list.append((vals[0], int(vals[1]), int(vals[2]) if vals[2] else 1))
        if not retry_list:
            messagebox.showinfo("提示", "没有失败的客户端需要重试")
            return
        self._log_write(f"[重试] 🔁 重试 {len(retry_list)} 个失败客户端...\n", "yellow")
        self._batch_deploy_clients(retry_ips=retry_list)

    def _deploy_one(self, ip, uid, win_count=1, callback=None):
        user = self._cd_user.get(); pwd = self._cd_pwd.get()
        remote = self._CLIENT_REMOTE
        local = os.path.abspath(os.path.join(BASE_DIR, self.cfg["project_local"]))

        def log_st(msg, color="green"):
            self.root.after(0, lambda: self._cd_tree.set(ip, "status", msg))
            self.root.after(0, lambda: self._log_write(f"[客户端 {ip}] {msg}\n", color))

        def pip_install(ssh, pip_bin, mirror_url, mirror_name):
            """尝试用指定镜像安装，返回 (success, output)。同时捕获 stdout+stderr。
            pip_bin 已包含完整前缀如 'venv/bin/pip install' 或 'python3 -m pip install --break-system-packages'"""
            if mirror_url:
                cmd = f"cd {remote} && {pip_bin} {self._CLIENT_DEPS} -i {mirror_url} --timeout=90"
            else:
                cmd = f"cd {remote} && {pip_bin} {self._CLIENT_DEPS} --timeout=90"
            out, err, code = ssh.run(cmd, timeout=180)
            combined = (out + err).strip()
            return code == 0, combined
        
        def verify_imports(ssh, py_bin):
            """验证所有关键模块可导入（stdout+stderr合并检查）"""
            for mod in ["requests", "curl_cffi", "Crypto", "gmssl"]:
                vfy, verr, vcode = ssh.run(f"{py_bin} -c 'import {mod}; print(\"OK\")'")
                if vcode != 0 or "OK" not in (vfy + verr):
                    return False, mod, (vfy + verr)[:200]
            return True, None, ""
        
        def try_install_with_fallback(ssh, base_pip_cmd, py_bin, label):
            """用 base_pip_cmd 轮询所有镜像源，返回 (installed, final_py_bin)"""
            mirrors = [
                ("https://mirrors.aliyun.com/pypi/simple/", "阿里云"),
                ("https://pypi.tuna.tsinghua.edu.cn/simple/", "清华"),
                ("https://mirrors.cloud.tencent.com/pypi/simple/", "腾讯云"),
                ("https://mirrors.ustc.edu.cn/pypi/simple/", "中科大"),
                ("", "PyPI官方"),
            ]
            for mirror_url, mirror_name in mirrors:
                log_st(f"📦 [{label}] 尝试 {mirror_name} 源...", "cyan")
                success, pip_out = pip_install(ssh, base_pip_cmd, mirror_url, mirror_name)
                if success:
                    ok_all, fail_mod, err_detail = verify_imports(ssh, py_bin)
                    if ok_all:
                        log_st(f"✅ [{label}] {mirror_name}源 成功")
                        return True, py_bin
                    else:
                        self.root.after(0, lambda m=fail_mod, n=mirror_name, d=err_detail: self._log_write(
                            f"[客户端 {ip}] {n}源: pip=OK 但 import {m} 失败: {d}\n", "yellow"))
                else:
                    self.root.after(0, lambda o=pip_out, n=mirror_name: self._log_write(
                        f"[客户端 {ip}] {n}源失败: {o[-300:]}\n", "yellow"))
            return False, py_bin

        def run():
            ok = True
            try:
                ssh = SSH(ip, 22, user, pwd)
                # ── 1. 准备目录 & 清理 ──
                ssh.run(f"mkdir -p {remote}")
                ssh.run(f"pkill -9 -f 'moutai_client_worker' 2>/dev/null; rm -f {remote}/*.py {remote}/*.txt")

                # ── 2. SFTP 上传 ──
                log_st("📤 SFTP上传代码...")
                for f in self._CLIENT_FILES:
                    ssh.upload(os.path.join(local, f), f"{remote}/{f}")
                for d in self._CLIENT_DIRS:
                    sd = os.path.join(local, d)
                    if os.path.isdir(sd):
                        ssh.run(f"mkdir -p {remote}/{d}")
                        for f in os.listdir(sd):
                            ssh.upload(os.path.join(sd, f), f"{remote}/{d}/{f}")

                # ── 3. 诊断 Python 环境 ──
                log_st("🔍 检查Python环境...")
                py_ver, py_err, _ = ssh.run("python3 --version 2>&1 || echo 'NO_PYTHON3'")
                self.root.after(0, lambda v=py_ver+py_err: self._log_write(
                    f"[客户端 {ip}] Python: {(v).strip()}\n", "cyan"))

                pip_ver, _, _ = ssh.run("python3 -m pip --version 2>&1 || echo 'NO_PIP'")
                self.root.after(0, lambda v=pip_ver: self._log_write(
                    f"[客户端 {ip}] Pip: {v.strip()[:100]}\n", "cyan"))

                # ── 4. 确保 pip 可用 ──
                if "NO_PIP" in pip_ver:
                    log_st("📥 安装pip...")
                    out, err, _ = ssh.run(
                        "apt-get update -qq && apt-get install -y -qq python3-pip 2>&1 || "
                        "yum install -y -q python3-pip 2>&1 || echo 'INSTALL_PIP_FAIL'", timeout=60)
                    pip_ver2, _, _ = ssh.run("python3 -m pip --version 2>&1 || echo 'STILL_NO_PIP'")
                    if "STILL_NO_PIP" in pip_ver2:
                        self.root.after(0, lambda o=out+err: self._log_write(
                            f"[客户端 {ip}] 安装pip失败: {o[:300]}\n", "red"))
                        log_st("❌ 无法安装pip", "red")
                        ssh.close()
                        if callback: self.root.after(0, lambda: callback(False))
                        return

                # ── 5. 安装依赖：venv → --break-system-packages → --user ──
                log_st("🔧 配置环境...")
                # 安装 python3-venv（不隐藏错误）
                ssh.run("apt-get update -qq 2>&1; apt-get install -y -qq python3-venv 2>&1; "
                        "yum install -y -q python3-venv 2>&1; echo done", timeout=60)

                PYTHON_BIN = "python3"
                installed = False

                # 方案A: venv
                vout, verr, _ = ssh.run(
                    f"cd {remote} && rm -rf venv && python3 -m venv venv 2>&1 && echo 'VENV_OK' || echo 'VENV_FAIL'")
                if "VENV_OK" in (vout + verr):
                    PYTHON_BIN = f"{remote}/venv/bin/python3"
                    pip_cmd = f"{remote}/venv/bin/pip install"
                    log_st("✅ venv 创建成功")
                    installed, PYTHON_BIN = try_install_with_fallback(ssh, pip_cmd, PYTHON_BIN, "venv")

                if not installed:
                    # 方案B: --break-system-packages（Debian 12+ PEP 668）
                    log_st("📦 尝试 --break-system-packages...", "yellow")
                    pip_cmd = "python3 -m pip install --break-system-packages"
                    installed, PYTHON_BIN = try_install_with_fallback(ssh, pip_cmd, "python3", "sys-pkg")

                if not installed:
                    # 方案C: --user（旧版 Debian/Ubuntu）
                    log_st("📦 尝试 --user...", "yellow")
                    pip_cmd = "python3 -m pip install --user"
                    installed, PYTHON_BIN = try_install_with_fallback(ssh, pip_cmd, "python3", "user")

                if not installed:
                    log_st("❌ 三种安装方式全部失败", "red")
                    ssh.close()
                    if callback: self.root.after(0, lambda: callback(False))
                    return

                # ── 6. 启动客户端（N个窗口） ──
                ssh.run(f"pkill -9 -f 'moutai_client_worker' 2>/dev/null; sleep 1")
                log_st(f"🚀 启动 {win_count} 个窗口...")
                # 生成 N 个 nohup 启动命令，每个窗口独立日志 client_w1.log ... client_wN.log
                start_cmds = []
                for wi in range(1, win_count + 1):
                    start_cmds.append(
                        f"(nohup {PYTHON_BIN} moutai_client_worker.py "
                        f"--user-id {uid} "
                        f"> client_w{wi}.log 2>&1 < /dev/null &)"
                    )
                cmd = (
                    f"cd {remote} && {' ; '.join(start_cmds)} ; sleep 3; "
                    f"WCOUNT=$(pgrep -fc 'python.*moutai_client_worker'); "
                    f"if [ $WCOUNT -ge {win_count} ]; then "
                    f"echo 'OK|'$WCOUNT'/{win_count}窗口运行中'; tail -3 client_w1.log; "
                    f"else echo 'FAIL|'$WCOUNT'/{win_count}窗口'; tail -3 client_w1.log; fi"
                )
                out, _, _ = ssh.run(cmd, timeout=15)
                if "OK|" in out:
                    log_st(f"✅ {win_count}窗口运行中 (uid={uid})", "green")
                else:
                    log_st(f"❌ 启动失败: {out.strip()[-150:]}", "red")
                    ok = False
                ssh.close()
            except Exception as e:
                err_str = str(e).lower()
                if 'timed out' in err_str or 'timeout' in err_str:
                    log_st("❌ SSH连接超时—机器可能关机/断网/端口不通", "red")
                    self.root.after(0, lambda ip=ip: self._log_write(
                        f"[客户端 {ip}] SSH 22端口连接超时 → 请检查: ① 机器是否开机 ② IP是否正确 ③ 防火墙是否开放22端口\n", "red"))
                elif 'auth' in err_str or 'password' in err_str or 'permission' in err_str:
                    log_st("❌ SSH认证失败—密码错误或不允许密码登录", "red")
                elif 'refused' in err_str or 'connect' in err_str:
                    log_st("❌ SSH连接被拒绝—端口未开放或服务未启动", "red")
                else:
                    log_st(f"❌ {e}", "red")
                ok = False
            if callback:
                self.root.after(0, lambda: callback(ok))
        threading.Thread(target=run, daemon=True).start()

    def _get_selected_client_ip(self):
        sel = self._cd_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先在列表中选择一个客户端")
            return None
        return sel[0]

    def _client_view_log(self, win_num=1):
        ip = self._get_selected_client_ip()
        if not ip: return
        user = self._cd_user.get(); pwd = self._cd_pwd.get()
        remote = self._CLIENT_REMOTE
        # ★ 获取该IP的窗口数
        vals = self._cd_tree.item(ip, "values")
        total_wins = int(vals[2]) if vals and len(vals) > 2 and str(vals[2]).isdigit() else 1

        d = tk.Toplevel(self.root)
        d.title(f"客户端日志 - {ip} [窗口{win_num}/{total_wins}]")
        d.geometry("820x520")
        d.transient(self.root)

        # ★ 顶部窗口选择栏
        topf = ttk.Frame(d); topf.pack(fill=tk.X, padx=4, pady=(4, 0))
        ttk.Label(topf, text="选择窗口:").pack(side=tk.LEFT)
        win_var = tk.StringVar(value=str(win_num))
        win_combo = ttk.Combobox(topf, textvariable=win_var, values=[str(i) for i in range(1, total_wins + 1)],
                                  width=4, state="readonly")
        win_combo.pack(side=tk.LEFT, padx=4)
        ttk.Label(topf, text=f"(共{total_wins}个窗口，日志: client_wN.log)", foreground="gray").pack(side=tk.LEFT, padx=4)

        log_widget = scrolledtext.ScrolledText(d, wrap=tk.WORD, font=("Consolas", 10),
            bg="#1a1a2e", fg="#e0e0e0", state=tk.DISABLED)
        log_widget.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        def write(text):
            log_widget.config(state=tk.NORMAL)
            log_widget.insert(tk.END, text)
            log_widget.see(tk.END)
            log_widget.config(state=tk.DISABLED)

        write(f"📋 连接 {ip} 实时日志 [窗口{win_num}]...\n")
        stop_flag = [False]
        current_win = [win_num]  # mutable ref for lambda closure
        log_file = f"{remote}/client_w{win_num}.log"

        def on_win_change(*args):
            """切换窗口 → 重启 tail 线程"""
            try:
                new_win = int(win_var.get())
            except ValueError:
                return
            if new_win == current_win[0]:
                return
            current_win[0] = new_win
            nonlocal log_file
            log_file = f"{remote}/client_w{new_win}.log"
            d.title(f"客户端日志 - {ip} [窗口{new_win}/{total_wins}]")
            # 停止旧 tail，启动新的
            stop_flag[0] = True
            # 清屏
            log_widget.config(state=tk.NORMAL)
            log_widget.delete("1.0", tk.END)
            log_widget.config(state=tk.DISABLED)
            write(f"📋 切换至窗口{new_win} 日志...\n")
            stop_flag[0] = False
            threading.Thread(target=lambda: tail_log(log_file), daemon=True).start()

        win_var.trace_add("write", on_win_change)

        def tail_log(lf):
            try:
                ssh = SSH(ip, 22, user, pwd)
                d.after(0, lambda: write(f"✅ SSH已连接\n{'='*60}\n"))
                # ★ 检查日志文件是否存在，不存在则先创建
                check_out, _, _ = ssh.run(f"test -f {lf} && echo EXISTS || echo MISSING")
                if "MISSING" in check_out:
                    ssh.run(f"touch {lf}")
                    d.after(0, lambda: write("⚠️ 该窗口日志文件尚未创建（窗口可能未启动）\n"))
                    d.after(0, lambda: write(f"{'='*60}\n"))
                while not stop_flag[0]:
                    try:
                        ssh.stream(f"tail -F -n 50 {lf}",
                            on_line=lambda line: d.after(0, lambda l=line: write(l + "\n")),
                            timeout=None)
                    except Exception as e:
                        if not stop_flag[0]:
                            d.after(0, lambda: write(f"[断开] {e}，2秒后重连...\n"))
                            time.sleep(2)
                ssh.close()
            except Exception as e:
                d.after(0, lambda: write(f"❌ {e}\n"))

        threading.Thread(target=lambda: tail_log(log_file), daemon=True).start()
        d.protocol("WM_DELETE_WINDOW", lambda: (stop_flag.__setitem__(0, True), d.destroy()))

    def _restart_selected_client(self):
        ip = self._get_selected_client_ip()
        if not ip: return
        # 从 tree 中获取 uid + 窗口数
        vals = self._cd_tree.item(ip, "values")
        uid = int(vals[1]) if vals else 0
        wins = int(vals[2]) if vals and len(vals) > 2 and str(vals[2]).isdigit() else 1
        self._cd_tree.set(ip, "status", "🔄 重启中...")
        self._deploy_one(ip, uid, wins)

    def _stop_selected_client(self):
        ip = self._get_selected_client_ip()
        if not ip: return
        user = self._cd_user.get(); pwd = self._cd_pwd.get()
        def run():
            try:
                ssh = SSH(ip, 22, user, pwd)
                ssh.run("pkill -9 -f 'moutai_client_worker' 2>/dev/null")
                ssh.close()
                self.root.after(0, lambda: self._cd_tree.set(ip, "status", "⏹ 已停止"))
                self.root.after(0, lambda: self._log_write(f"[客户端 {ip}] ⏹ 已停止\n", "gray"))
            except Exception as e:
                self.root.after(0, lambda: self._cd_tree.set(ip, "status", f"❌ {e}"))
        threading.Thread(target=run, daemon=True).start()

    def _redeploy_restart_client(self):
        """重新部署启动：停止旧进程 → 修复关键依赖 → 上传最新代码 → 启动客户端"""
        ip = self._get_selected_client_ip()
        if not ip: return
        vals = self._cd_tree.item(ip, "values")
        uid = int(vals[1]) if vals else 0
        wins = int(vals[2]) if vals and len(vals) > 2 and str(vals[2]).isdigit() else 1
        user = self._cd_user.get(); pwd = self._cd_pwd.get()
        remote = self._CLIENT_REMOTE
        local = os.path.abspath(os.path.join(BASE_DIR, self.cfg["project_local"]))

        def log_st(msg, color="green"):
            self.root.after(0, lambda: self._cd_tree.set(ip, "status", msg))
            self.root.after(0, lambda: self._log_write(f"[客户端 {ip}] {msg}\n", color))

        def run():
            try:
                ssh = SSH(ip, 22, user, pwd)

                # 0. 检测 Python 路径（停进程前先检测，避免 clean 后找不到）
                py_check, _, _ = ssh.run(
                    f"test -f {remote}/venv/bin/python3 && echo 'VENV' || echo 'SYS'")
                py_bin = f"{remote}/venv/bin/python3" if "VENV" in py_check else "python3"
                pip_fix = f"{remote}/venv/bin/pip install --force-reinstall -q requests curl_cffi 2>&1" if "VENV" in py_check else "python3 -m pip install --force-reinstall --break-system-packages -q requests curl_cffi 2>&1"

                # 1. 停止旧进程
                log_st("⏹ 停止旧进程...")
                ssh.run(f"pkill -9 -f 'moutai_client_worker' 2>/dev/null; sleep 1")

                # 1.5 修复关键依赖（requests 库残缺是常见问题）
                log_st("🔧 修复依赖...")
                fix_out, fix_err, _ = ssh.run(pip_fix, timeout=30)
                if fix_err and "ERROR" in fix_err:
                    self.root.after(0, lambda e=fix_err: self._log_write(
                        f"[客户端 {ip}] pip修复: {e[-200:]}\n", "yellow"))

                # 2. 上传最新代码
                log_st("📤 上传最新代码...")
                for f in self._CLIENT_FILES:
                    ssh.upload(os.path.join(local, f), f"{remote}/{f}")
                for d in self._CLIENT_DIRS:
                    sd = os.path.join(local, d)
                    if os.path.isdir(sd):
                        ssh.run(f"mkdir -p {remote}/{d}")
                        for f in os.listdir(sd):
                            ssh.upload(os.path.join(sd, f), f"{remote}/{d}/{f}")
                log_st("✅ 代码上传完成")

                # 3. 启动客户端
                log_st(f"🚀 启动 {wins} 个窗口...")
                # 生成 N 个 nohup 启动命令
                start_cmds = []
                for wi in range(1, wins + 1):
                    start_cmds.append(
                        f"(nohup {py_bin} moutai_client_worker.py "
                        f"--user-id {uid} "
                        f"> client_w{wi}.log 2>&1 < /dev/null &)"
                    )
                cmd = (
                    f"cd {remote} && {' ; '.join(start_cmds)} ; sleep 3; "
                    f"WCOUNT=$(pgrep -fc 'python.*moutai_client_worker'); "
                    f"if [ $WCOUNT -ge {wins} ]; then "
                    f"echo 'OK|'$WCOUNT'/{wins}窗口运行中'; tail -3 client_w1.log; "
                    f"else echo 'FAIL|'$WCOUNT'/{wins}窗口'; tail -3 client_w1.log; fi"
                )
                out, err, _ = ssh.run(cmd, timeout=15)
                if "OK|" in out:
                    log_st(f"✅ {wins}窗口运行中 (uid={uid})", "green")
                else:
                    # 启动失败：输出完整诊断信息
                    fail_output = (out + err).strip()[-300:]
                    log_st(f"❌ {wins}窗口启动失败 (py={py_bin} uid={uid})", "red")
                    # 详细日志写入 log 面板
                    self.root.after(0, lambda o=fail_output: self._log_write(
                        f"[客户端 {ip}] 启动诊断:\n{o}\n", "yellow"))
                ssh.close()
            except Exception as e:
                import traceback
                log_st(f"❌ {e}", "red")
                self.root.after(0, lambda tb=traceback.format_exc(): self._log_write(
                    f"[客户端 {ip}] 异常详情:\n{tb[-500:]}\n", "yellow"))
        threading.Thread(target=run, daemon=True).start()


# ============================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
