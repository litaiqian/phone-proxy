path = r'D:\采购管理\连通服务器\server_manager.py'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Add CLIENT_DEPLOY_FILE after CONFIG_FILE
old_cfg = "CONFIG_FILE = os.path.join(BASE_DIR, \"config.json\")"
new_cfg = """CONFIG_FILE = os.path.join(BASE_DIR, \"config.json\")
CLIENT_DEPLOY_FILE = os.path.join(BASE_DIR, \"client_deploy.json\")"""
c = c.replace(old_cfg, new_cfg)

# 2. Add _save/_load methods before _client_deploy_window
old_win_def = '    def _client_deploy_window(self):'
new_methods = '''    def _load_client_data(self):
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
            # 恢复客户端列表
            for item in data.get('clients', []):
                ip = item.get('ip', '')
                if ip:
                    self._cd_tree.insert('', tk.END, iid=ip,
                        values=(ip, item.get('uid', 0), item.get('status', '')))
        except Exception:
            pass

    def _save_client_data(self):
        """保存 IP 列表和客户端列表到持久化文件"""
        try:
            ip_text = self._cd_ip.get('1.0', tk.END).strip()
            clients = []
            for iid in self._cd_tree.get_children():
                vals = self._cd_tree.item(iid, 'values')
                if vals:
                    clients.append({
                        'ip': vals[0],
                        'uid': int(vals[1]) if vals[1] else 0,
                        'status': vals[2] if len(vals) > 2 else ''
                    })
            data = {'ip_text': ip_text, 'clients': clients}
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

    def _client_deploy_window(self):'''
c = c.replace(old_win_def, new_methods)

# 3. After the right-click menu (end of _client_deploy_window), add load + bind close
old_menu_end = '        self._cd_tree.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))'
new_menu_end = '''        self._cd_tree.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))

        # 恢复上次保存的数据
        self.root.after(100, self._load_client_data)

        # 窗口关闭时自动保存
        d.protocol("WM_DELETE_WINDOW", lambda: (self._save_client_data(), d.destroy()))'''
c = c.replace(old_menu_end, new_menu_end)

# 4. Modify "清空IP" button to use _clear_client_data
old_clear_btn = 'ttk.Button(bf, text="🗑 清空IP", command=lambda: self._cd_ip.delete("1.0", tk.END)).pack(side=tk.RIGHT, padx=2)'
new_clear_btn = 'ttk.Button(bf, text="🗑 清空IP", command=self._clear_client_data).pack(side=tk.RIGHT, padx=2)'
c = c.replace(old_clear_btn, new_clear_btn)

# 5. Auto-save in _batch_deploy_clients after inserting tree items
old_batch_end = '        threading.Thread(target=lambda: deploy_next(0), daemon=True).start()'
new_batch_end = '''        # 保存到持久化文件
        self._save_client_data()
        threading.Thread(target=lambda: deploy_next(0), daemon=True).start()'''
c = c.replace(old_batch_end, new_batch_end)

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)

# Verify with partial syntax check
with open(path, 'r', encoding='utf-8') as f:
    verify = f.read()

checks = [
    ('CLIENT_DEPLOY_FILE', 'CLIENT_DEPLOY_FILE' in verify),
    ('_load_client_data', '_load_client_data' in verify),
    ('_save_client_data', '_save_client_data' in verify),
    ('_clear_client_data', '_clear_client_data' in verify),
    ('WM_DELETE_WINDOW', 'WM_DELETE_WINDOW' in verify and '_save_client_data' in verify.split('WM_DELETE_WINDOW')[1]),
]
for name, ok in checks:
    print(f'  {name}: {"OK" if ok else "MISSING"}')
print('Done')
