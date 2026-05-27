 #!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
养猫 ── Android App
WebSocket隧道代理 + 账号体系 + 猫粮经济 + 推荐团队
"""

import sys, os, socket, threading, time, json, uuid, hashlib
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError

# ==================== 配置 ====================
SERVER_HOST = 'ipla.top'
SERVER_PORT = 5000
WS_PATH = '/api/phone_proxy/ws'
API_BASE = f'http://{SERVER_HOST}:{SERVER_PORT}'
SERVER_WS = f'ws://{API_BASE}{WS_PATH}'
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ==================== 设备 ID ====================
def _get_device_id():
    fid = os.path.join(APP_DIR, '.device_id')
    try:
        with open(fid) as f:
            return f.read().strip()
    except Exception:
        did = uuid.uuid4().hex[:16]
        with open(fid, 'w') as f:
            f.write(did)
        return did

DEVICE_ID = _get_device_id()

# ==================== HTTP API ====================
class API:
    """养猫服务端 API 客户端"""
    _token = ''

    @classmethod
    def _post(cls, path, data):
        url = f'{API_BASE}{path}'
        headers = {
            'Content-Type': 'application/json',
            'X-Device-Id': DEVICE_ID,
        }
        if cls._token:
            headers['Authorization'] = f'Bearer {cls._token}'
        try:
            req = Request(url, data=json.dumps(data).encode(),
                          headers=headers, method='POST')
            resp = urlopen(req, timeout=10)
            return json.loads(resp.read().decode())
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    @classmethod
    def _get(cls, path):
        url = f'{API_BASE}{path}'
        headers = {'X-Device-Id': DEVICE_ID}
        if cls._token:
            headers['Authorization'] = f'Bearer {cls._token}'
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=10)
            return json.loads(resp.read().decode())
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    @classmethod
    def send_sms(cls, phone):
        return cls._post('/api/app/send_sms', {'phone': phone})

    @classmethod
    def register(cls, login_id, password, ref_code=''):
        return cls._post('/api/app/register',
                         {'login_id': login_id, 'password': password,
                          'ref_code': ref_code})

    @classmethod
    def login(cls, username, password):
        r = cls._post('/api/app/login',
                      {'username': username, 'password': password,
                       'device_id': DEVICE_ID})
        if r.get('ok') and r.get('token'):
            cls._token = r['token']
        return r

    @classmethod
    def heartbeat(cls):
        return cls._post('/api/app/heartbeat', {})

    @classmethod
    def get_cat_food(cls):
        return cls._get('/api/app/cat_food')

    @classmethod
    def get_orders(cls):
        return cls._get('/api/app/orders')

    @classmethod
    def bind_account(cls, account_phone, sms_code):
        return cls._post('/api/app/bind_account',
                         {'account_phone': account_phone, 'code': sms_code})

    @classmethod
    def get_referrals(cls):
        return cls._get('/api/app/referrals')

    @classmethod
    def get_refer_code(cls):
        return cls._get('/api/app/refer_code')

    @classmethod
    def team_list(cls):
        return cls._get('/api/app/team_list')

    @classmethod
    def team_add(cls, user_id):
        return cls._post('/api/app/team_add', {'user_id': user_id})

    @classmethod
    def get_bind_status(cls):
        """获取所有已绑定账号的登录状态"""
        return cls._get('/api/app/bind_status')

    @classmethod
    def refresh_bind_login(cls):
        """刷新绑定账号的登录状态（触发服务端重新登录检测）"""
        return cls._post('/api/app/refresh_bind_login', {})

    @classmethod
    def change_password(cls, old_pw, new_pw):
        return cls._post('/api/app/change_password',
                         {'old_password': old_pw, 'new_password': new_pw})

    @classmethod
    def ad_reward(cls, ad_type, ad_token):
        return cls._post('/api/app/ad_reward',
                         {'ad_type': ad_type, 'token': ad_token})


# ==================== 持久化 ====================
def _save(key, val):
    try:
        p = os.path.join(APP_DIR, f'.{key}')
        with open(p, 'w') as f:
            json.dump(val, f)
    except Exception:
        pass

def _load(key, default=None):
    try:
        p = os.path.join(APP_DIR, f'.{key}')
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default

# ==================== Kivy UI ====================
try:
    from kivy.app import App
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    from kivy.uix.button import Button
    from kivy.uix.textinput import TextInput
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
    from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
    from kivy.uix.popup import Popup
    from kivy.uix.checkbox import CheckBox
    from kivy.clock import Clock
    from kivy.core.window import Window
    HAS_KIVY = True
except ImportError:
    HAS_KIVY = False

if not HAS_KIVY:
    def run_cli():
        print('养猫 CLI 模式 — 请安装 Kivy')
    if __name__ == '__main__':
        run_cli()
    sys.exit(0)


# ==================== 颜色/样式 ====================
C_BG = (0.1, 0.1, 0.12, 1)
C_CARD = (0.15, 0.15, 0.18, 1)
C_ACCENT = (1, 0.42, 0.2, 1)
C_GREEN = (0.3, 1, 0.5, 1)
C_RED = (1, 0.3, 0.3, 1)
C_GOLD = (1, 0.8, 0.1, 1)
C_WHITE = (1, 1, 1, 1)
C_GREY = (0.5, 0.5, 0.55, 1)
C_DARKGREY = (0.25, 0.25, 0.28, 1)

def _txt(s, **kw):
    kw.setdefault('color', C_WHITE)
    kw.setdefault('font_size', '14sp')
    return Label(text=str(s), **kw)

def _btn(s, cb=None, accent=False, **kw):
    b = Button(text=s, font_size='14sp', background_normal='', size_hint_y=None, height=44)
    if accent:
        b.background_color = C_ACCENT
        b.color = C_WHITE
    else:
        b.background_color = C_CARD
        b.color = C_WHITE
    for k, v in kw.items():
        setattr(b, k, v)
    if cb:
        b.bind(on_press=cb)
    return b

# ==================== 登录页 ====================
class LoginScreen(Screen):
    def __init__(self, **kw):
        super().__init__(name='login', **kw)
        self.step = 'phone'

        self.layout = BoxLayout(orientation='vertical', padding=[30, 80], spacing=15)
        self.layout.add_widget(Label(text='🐱 养猫', font_size='28sp', bold=True,
                                     size_hint=(1, 0.25), color=C_ACCENT))

        self.msg = Label(text='登录养猫，开始觅食', font_size='14sp', color=C_GREY, size_hint=(1, 0.1))
        self.layout.add_widget(self.msg)

        self.user_input = TextInput(hint_text='手机号或用户名', multiline=False,
                                     font_size='18sp',
                                     size_hint=(1, None), height=48,
                                     background_color=C_CARD, foreground_color=C_WHITE,
                                     cursor_color=C_ACCENT, padding=[12, 12])
        self.layout.add_widget(self.user_input)

        self.pw_input = TextInput(hint_text='密码', multiline=False, password=True,
                                   font_size='18sp',
                                   size_hint=(1, None), height=48,
                                   background_color=C_CARD, foreground_color=C_WHITE,
                                   cursor_color=C_ACCENT, padding=[12, 12])
        self.layout.add_widget(self.pw_input)

        self.login_btn = _btn('登录', cb=self._login, accent=True)
        self.layout.add_widget(self.login_btn)

        self.layout.add_widget(_btn('注册新账号', cb=lambda x: setattr(
            self.manager, 'current', 'register')))
        self.layout.add_widget(Label(size_hint=(1, 0.3)))

        self.add_widget(self.layout)

        # 自动登录
        saved = _load('auth')
        if saved:
            API._token = saved.get('token', '')
            Clock.schedule_once(lambda dt: self._auto_login(), 0.5)

    def _login(self, *a):
        username = self.user_input.text.strip()
        password = self.pw_input.text.strip()
        if not username or not password:
            self._toast('请填写账号和密码')
            return
        self.login_btn.disabled = True
        threading.Thread(target=self._do_login, args=(username, password), daemon=True).start()

    def _do_login(self, username, password):
        r = API.login(username, password)
        Clock.schedule_once(lambda dt: self._on_login(r, username), 0)

    def _on_login(self, r, username):
        self.login_btn.disabled = False
        if r.get('ok'):
            _save('auth', {'username': username, 'token': API._token,
                           'user_id': r.get('user_id', '')})
            self.manager.current = 'main'
        else:
            self._toast(r.get('error', '登录失败'))

    def _auto_login(self):
        r = API.get_cat_food()
        if r.get('ok') is not False:
            self.manager.current = 'main'

    def _toast(self, msg):
        self.msg.text = msg
        self.msg.color = C_GOLD


# ==================== 注册页 ====================
class RegisterScreen(Screen):
    def __init__(self, **kw):
        super().__init__(name='register', **kw)
        lyt = BoxLayout(orientation='vertical', padding=[24, 40], spacing=9)

        lyt.add_widget(Label(text='注册养猫', font_size='22sp', bold=True,
                             size_hint=(1, 0.1), color=C_ACCENT))

        # 提示
        self.msg = Label(text='密码需含字母+数字，至少6位', font_size='11sp',
                         color=C_GREY, size_hint=(1, 0.04))
        lyt.add_widget(self.msg)

        self.login_id = TextInput(hint_text='手机号/用户名（任选一）', multiline=False,
                                   font_size='15sp', size_hint=(1, None), height=42,
                                   background_color=C_CARD, foreground_color=C_WHITE,
                                   cursor_color=C_ACCENT, padding=[10, 10])
        lyt.add_widget(self.login_id)

        self.pw = TextInput(hint_text='密码（字母+数字）', multiline=False, password=True,
                             font_size='15sp', size_hint=(1, None), height=42,
                             background_color=C_CARD, foreground_color=C_WHITE,
                             cursor_color=C_ACCENT, padding=[10, 10])
        lyt.add_widget(self.pw)

        self.ref_code = TextInput(hint_text='推荐码（选填）', multiline=False,
                                  font_size='15sp', size_hint=(1, None), height=42,
                                  background_color=C_CARD, foreground_color=C_WHITE,
                                  cursor_color=C_ACCENT, padding=[10, 10])
        lyt.add_widget(self.ref_code)

        lyt.add_widget(_btn('注册', cb=self._reg, accent=True))
        lyt.add_widget(_btn('← 返回登录', cb=lambda x: setattr(self.manager, 'current', 'login')))
        lyt.add_widget(Label(size_hint=(1, 0.25)))
        self.add_widget(lyt)

    def _reg(self, *a):
        uid = self.login_id.text.strip()
        p = self.pw.text.strip()
        r = self.ref_code.text.strip()
        if not uid or not p:
            self.msg.text = '请填写手机号/用户名和密码'
            self.msg.color = C_GOLD
            return
        # 客户端侧预校验
        has_letter = any(c.isalpha() for c in p)
        has_digit = any(c.isdigit() for c in p)
        if len(p) < 6 or not has_letter or not has_digit:
            self.msg.text = '密码至少6位，需含字母和数字'
            self.msg.color = C_RED
            return
        self.msg.text = '注册中…'
        self.msg.color = C_GOLD
        threading.Thread(target=self._do_reg, args=(uid, p, r), daemon=True).start()

    def _do_reg(self, uid, p, r):
        resp = API.register(uid, p, r)
        Clock.schedule_once(lambda dt: self._on_reg(resp), 0)

    def _on_reg(self, resp):
        if resp.get('ok'):
            self.msg.color = C_GREEN
            self.msg.text = '注册成功！请登录'
            Clock.schedule_once(lambda dt: setattr(self.manager, 'current', 'login'), 1.5)
        else:
            self.msg.color = C_RED
            self.msg.text = resp.get('error', '注册失败')


# ==================== 主页（4 Tab） ====================
class MainScreen(Screen):
    def __init__(self, **kw):
        super().__init__(name='main', **kw)
        self.tp = TabbedPanel(tab_pos='bottom', do_default_tab=False)
        self.tp.background_color = (0.07, 0.07, 0.09, 1)

        self.tp.add_widget(HomeTab(text='🏠 首页'))
        self.tp.add_widget(ReferralTab(text='👥 推荐'))
        self.tp.add_widget(TeamTab(text='👨‍👩‍👧 团队'))
        self.tp.add_widget(ProfileTab(text='👤 我的'))

        self.tp.default_tab = self.tp.tab_list[0]
        self.tp.switch_to(self.tp.tab_list[0])
        self.add_widget(self.tp)

    def on_enter(self):
        for t in self.tp.tab_list:
            if hasattr(t, 'on_enter'):
                t.on_enter()


# ==================== 首页 Tab ====================
class HomeTab(TabbedPanelItem):
    def __init__(self, **kw):
        super().__init__(**kw)
        lyt = BoxLayout(orientation='vertical', padding=[16, 20], spacing=10)

        self.cat_status = Label(text='🐱 猫咪正在醒来…', font_size='18sp',
                                color=C_GOLD, size_hint=(1, 0.1), halign='center')
        self.cat_status.bind(size=self.cat_status.setter('text_size'))
        lyt.add_widget(self.cat_status)

        self.food_label = Label(text='🍚 猫粮: --.--- 颗', font_size='20sp', bold=True,
                                color=C_GREEN, size_hint=(1, 0.1), halign='center')
        self.food_label.bind(size=self.food_label.setter('text_size'))
        lyt.add_widget(self.food_label)

        self.time_label = Label(text='⏱ 今日觅食: --', font_size='14sp',
                                color=C_GREY, size_hint=(1, 0.08), halign='center')
        self.time_label.bind(size=self.time_label.setter('text_size'))
        lyt.add_widget(self.time_label)

        self.info = Label(text='', font_size='12sp', color=C_GREY,
                          size_hint=(1, 0.15), halign='center')
        self.info.bind(size=self.info.setter('text_size'))
        lyt.add_widget(self.info)

        lyt.add_widget(_btn('🚶 换条街逛逛', cb=self._change_ip, accent=True))
        lyt.add_widget(_btn('🎬 看视频 +0.5猫粮', cb=self._watch_ad))
        lyt.add_widget(Label(size_hint=(1, 0.25)))

        self.add_widget(lyt)

    def on_enter(self):
        self._refresh(None)
        Clock.schedule_interval(self._refresh, 3)

    def _refresh(self, dt):
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        r = API.get_cat_food()
        Clock.schedule_once(lambda dt: self._update(r), 0)

    def _update(self, r):
        if r.get('ok') is False:
            return
        food = round(r.get('cat_food', 0), 3)
        online = r.get('online_today', 0)
        h = int(online // 3600)
        m = int((online % 3600) // 60)
        connected = r.get('proxy_connected', False)

        self.food_label.text = f'🍚 猫粮: {food:.3f} 颗'
        self.time_label.text = f'⏱ 今日觅食: {h}时{m}分'

        if connected:
            self.cat_status.text = '🐱 猫咪正在觅食中…'
            self.cat_status.color = C_GREEN
        else:
            self.cat_status.text = '🐱 猫咪睡着了，正在唤醒…'
            self.cat_status.color = C_GOLD

        self.info.text = f'用户ID: {r.get("user_id","")}\n🐾 累计猫粮: {r.get("total_food",0):.3f}'

    def _change_ip(self, *a):
        threading.Thread(target=_change_ip, daemon=True).start()
        popup = Popup(title='换 IP', content=Label(
            text='正在切换网络…\n3秒后恢复', color=C_WHITE),
            size_hint=(0.6, 0.3), background_color=C_CARD)
        popup.open()
        Clock.schedule_once(lambda dt: setattr(popup, 'dismiss', popup.dismiss) and popup.dismiss(), 3)

    def _watch_ad(self, *a):
        self._toast('广告模块开发中…')

    def _toast(self, msg):
        try:
            p = Popup(title='', content=Label(text=msg, color=C_WHITE),
                      size_hint=(0.5, 0.2), background_color=C_CARD)
            p.open()
            Clock.schedule_once(lambda dt: p.dismiss(), 1.5)
        except Exception:
            pass


# ==================== 推荐 Tab ====================
class ReferralTab(TabbedPanelItem):
    def __init__(self, **kw):
        super().__init__(**kw)
        lyt = BoxLayout(orientation='vertical', padding=[16, 20], spacing=8)

        self.code_label = Label(text='推荐码: ---', font_size='16sp',
                                color=C_ACCENT, size_hint=(1, 0.08))
        self.code_label.bind(size=self.code_label.setter('text_size'))
        lyt.add_widget(self.code_label)

        self.stat_label = Label(text='', font_size='13sp', color=C_GREY,
                                size_hint=(1, 0.08))
        self.stat_label.bind(size=self.stat_label.setter('text_size'))
        lyt.add_widget(self.stat_label)

        sv = ScrollView(size_hint=(1, 1))
        self.list_box = BoxLayout(orientation='vertical', spacing=4, size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter('height'))
        sv.add_widget(self.list_box)
        lyt.add_widget(sv)

        self.add_widget(lyt)

    def on_enter(self):
        self._refresh(None)
        Clock.schedule_interval(self._refresh, 15)

    def _refresh(self, dt):
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        rc = API.get_refer_code()
        rr = API.get_referrals()
        Clock.schedule_once(lambda dt: self._update(rc, rr), 0)

    def _update(self, rc, rr):
        if rc.get('ok') is not False:
            self.code_label.text = f'📋 推荐码: {rc.get("code", "---")}  [长按复制]'

        self.list_box.clear_widgets()
        if not rr.get('list'):
            self.stat_label.text = '还没有推荐的小猫咪'
            return

        total = len(rr['list'])
        active = sum(1 for x in rr['list'] if x.get('online'))
        earned = rr.get('earned_food', 0)
        self.stat_label.text = f'总推荐 {total} 人 | 活跃 {active} 只 | 赚 {earned} 猫粮'

        for x in rr['list']:
            card = BoxLayout(orientation='vertical', size_hint_y=None, height=52,
                             padding=[10, 6], spacing=2)
            card.canvas.before.clear()
            with card.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(*C_CARD)
                Rectangle(pos=card.pos, size=card.size)
            card.bind(pos=lambda i, v, c=card: c.canvas.before.children[-1].pos if False else None)

            phone = x.get('phone', '***')[:3] + '****' + x.get('phone', '***')[-4:]
            online_h = round(x.get('online_hours', 0), 1)
            food = round(x.get('cat_food', 0), 3)
            status = '🟢 觅食中' if x.get('online') else '🔴 离线'
            won = ' 🎉中奖' if x.get('won') else ''

            card.add_widget(_txt(f'{phone}  {status}{won}  |  挂机{online_h}h  |  猫粮{food}',
                                 font_size='12sp', size_hint_y=None, height=20))
            self.list_box.add_widget(card)


# ==================== 团队 Tab（绑定管理） ====================
class TeamTab(TabbedPanelItem):
    """团队/绑定页面：上方为已绑定账号状态列表+刷新，下方为绑定新号表单"""
    def __init__(self, **kw):
        super().__init__(**kw)
        lyt = BoxLayout(orientation='vertical', padding=[12, 14], spacing=6)

        # ── 标题 + 刷新 ──
        hdr = BoxLayout(size_hint=(1, None), height=34, spacing=6)
        hdr.add_widget(_txt('👨‍👩‍👧 绑定管理', font_size='17sp', bold=True,
                             color=C_ACCENT, size_hint=(0.6, 1)))
        self.refresh_btn = _btn('🔄 刷新', cb=self._refresh_status, accent=True,
                                size_hint=(0.4, 1))
        hdr.add_widget(self.refresh_btn)
        lyt.add_widget(hdr)

        # ── 时间状态 ──
        self.time_status = _txt('', font_size='13sp', bold=True,
                                size_hint=(1, None), height=22, halign='center')
        self.time_status.bind(size=self.time_status.setter('text_size'))
        lyt.add_widget(self.time_status)

        # ── 状态提示 ──
        self.status_msg = _txt('点击刷新查看绑定状态', font_size='11sp',
                                color=C_GREY, size_hint=(1, None), height=18)
        lyt.add_widget(self.status_msg)

        # ── 已绑定账号列表 ──
        sv = ScrollView(size_hint=(1, 0.45))
        self.list_box = BoxLayout(orientation='vertical', spacing=3, size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter('height'))
        sv.add_widget(self.list_box)
        lyt.add_widget(sv)

        # ── 分隔线 ──
        lyt.add_widget(_txt('─ 绑定新号码 ─', font_size='11sp', color=C_DARKGREY,
                             size_hint=(1, None), height=20, halign='center'))

        # ── 绑定表单 ──
        self.phone = TextInput(hint_text='目标站手机号', multiline=False,
                               font_size='14sp', size_hint=(1, None), height=40,
                               background_color=C_CARD, foreground_color=C_WHITE,
                               cursor_color=C_ACCENT, padding=[8, 8])
        lyt.add_widget(self.phone)

        hb = BoxLayout(spacing=5, size_hint=(1, None), height=40)
        self.code = TextInput(hint_text='验证码', multiline=False, input_filter='int',
                              font_size='14sp', size_hint=(0.5, 1),
                              background_color=C_CARD, foreground_color=C_WHITE,
                              cursor_color=C_ACCENT, padding=[6, 6])
        hb.add_widget(self.code)
        self.send_btn = _btn('获取验证码', cb=self._send_sms, accent=True)
        hb.add_widget(self.send_btn)
        lyt.add_widget(hb)

        self.bind_btn = _btn('确认绑定', cb=self._bind, accent=True)
        lyt.add_widget(self.bind_btn)
        self.bind_msg = _txt('', font_size='11sp', color=C_GOLD, size_hint=(1, None), height=18)
        lyt.add_widget(self.bind_msg)

        self.add_widget(lyt)

    def on_enter(self):
        self._update_time_status()
        self._refresh_status()
        Clock.schedule_interval(self._update_time_status, 60)
        Clock.schedule_interval(self._refresh_status, 30)

    # ── 根据当前时间返回活动状态 ──
    @staticmethod
    def _get_time_status():
        import datetime
        now = datetime.datetime.now()
        h = now.hour
        m = now.minute
        t = h * 60 + m  # 总分钟数

        if 420 <= t < 1195:        # 07:00 ~ 19:55
            return '🐱 养号中…', C_GREEN
        elif 1195 <= t < 1260:     # 19:55 ~ 21:00
            return '⚡ 抢购窗口', C_ACCENT
        else:                      # 21:00 ~ 07:00
            return '🌙 夜间休息中…', C_GOLD

    def _update_time_status(self, *a):
        txt, color = self._get_time_status()
        self.time_status.text = txt
        self.time_status.color = color

    # ── 刷新绑定列表 ──
    def _refresh_status(self, *a):
        self.refresh_btn.disabled = True
        self.status_msg.text = '🔄 正在刷新…'
        self.status_msg.color = C_GOLD
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        r = API.get_bind_status()
        Clock.schedule_once(lambda dt: self._on_status(r), 0)

    def _on_status(self, r):
        self.refresh_btn.disabled = False
        self.list_box.clear_widgets()

        if r.get('ok') is False:
            self.status_msg.text = '❌ 获取状态失败'
            self.status_msg.color = C_RED
            return

        accounts = r.get('accounts', [])
        if not accounts:
            self.status_msg.text = '还没有绑定账号，请在下方绑定'
            self.status_msg.color = C_GOLD
            return

        online = sum(1 for a in accounts if a.get('login_status') == 'success')
        self.status_msg.text = f'📱 已绑定 {len(accounts)} 个 | 🟢 在线 {online}'
        self.status_msg.color = C_GREEN

        # 当前时间段的活动状态
        act_txt, act_color = self._get_time_status()

        for a in accounts:
            phone = a.get('phone', '***')
            ls = a.get('login_status', 'never')
            at = a.get('account_type', '')

            if ls == 'success':
                st, sc = '正常', C_GREEN
            elif ls == 'offline':
                st, sc = '掉线', C_GOLD
            else:
                st, sc = '未登录', C_RED

            if at == 'white':
                tt, tc = '白号', C_GREEN
            elif at == 'black':
                tt, tc = '黑号', C_RED
            else:
                tt, tc = '正常', C_GREY

            card = BoxLayout(size_hint_y=None, height=32, padding=[8, 4], spacing=4)
            card.canvas.before.clear()
            with card.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(*C_CARD)
                Rectangle(pos=card.pos, size=card.size)
            card.add_widget(_txt(phone, font_size='12sp', size_hint=(0.30, 1)))
            card.add_widget(_txt(st, font_size='12sp', color=sc, size_hint=(0.22, 1)))
            card.add_widget(_txt(f'{tt}', font_size='12sp', color=tc, size_hint=(0.18, 1)))
            card.add_widget(_txt(act_txt, font_size='12sp', color=act_color, size_hint=(0.30, 1)))
            self.list_box.add_widget(card)

    # ── 发送验证码 ──
    def _send_sms(self, *a):
        phone = self.phone.text.strip()
        if len(phone) != 11:
            self.bind_msg.text = '请输入正确的11位手机号'
            return
        self.send_btn.disabled = True
        threading.Thread(target=lambda: self._do_sms_result(API.send_sms(phone)), daemon=True).start()

    def _do_sms_result(self, r):
        Clock.schedule_once(lambda dt: self._on_sms(r), 0)

    def _on_sms(self, r):
        self.send_btn.disabled = False
        self.bind_msg.text = '✅ 验证码已发送' if r.get('ok') else f'❌ {r.get("error","发送失败")}'

    # ── 提交绑定 ──
    def _bind(self, *a):
        phone = self.phone.text.strip()
        code = self.code.text.strip()
        if not phone or not code:
            self.bind_msg.text = '请填写手机号和验证码'
            return
        self.bind_btn.disabled = True
        self.bind_msg.color = C_GOLD
        self.bind_msg.text = '绑定中…'
        threading.Thread(target=self._do_bind, args=(phone, code), daemon=True).start()

    def _do_bind(self, phone, code):
        r = API.bind_account(phone, code)
        Clock.schedule_once(lambda dt: self._on_bind_result(r), 0)

    def _on_bind_result(self, r):
        self.bind_btn.disabled = False
        if r.get('ok'):
            self.bind_msg.color = C_GREEN
            self.bind_msg.text = '🎉 绑定成功！'
            self.phone.text = ''
            self.code.text = ''
            self._refresh_status()
        else:
            self.bind_msg.color = C_RED
            self.bind_msg.text = r.get('error', '绑定失败')


# ==================== 我的 Tab ====================
class ProfileTab(TabbedPanelItem):
    def __init__(self, **kw):
        super().__init__(**kw)
        lyt = BoxLayout(orientation='vertical', padding=[16, 30], spacing=10)

        saved = _load('auth') or {}
        self.username = saved.get('username', '未登录') or '未登录'
        self.uid_display = saved.get('user_id', '---')

        lyt.add_widget(_txt(f'👤 {self.username}', font_size='18sp',
                             size_hint=(1, 0.08), bold=True))
        lyt.add_widget(_txt(f'ID: {self.uid_display}', font_size='13sp',
                             color=C_GREY, size_hint=(1, 0.06)))
        lyt.add_widget(Label(size_hint=(1, 0.04)))

        lyt.add_widget(_btn('📋 查单记录', cb=self._orders))
        lyt.add_widget(_btn('🔑 修改密码', cb=self._change_pw))
        lyt.add_widget(_btn('📊 猫粮明细', cb=self._food_log))
        lyt.add_widget(_btn('⚙ 设置', cb=self._settings))
        lyt.add_widget(Label(size_hint=(1, 0.1)))
        lyt.add_widget(_btn('🚪 退出登录', cb=self._logout))

        self.add_widget(lyt)

    def _orders(self, *a):
        self.manager.add_widget(OrderListScreen(name='order_list'))
        self.manager.current = 'order_list'

    def _change_pw(self, *a):
        self.manager.add_widget(ChangePwScreen(name='change_pw'))
        self.manager.current = 'change_pw'

    def _food_log(self, *a):
        self._toast('猫粮明细开发中…')

    def _settings(self, *a):
        self.manager.add_widget(SettingsScreen(name='settings'))
        self.manager.current = 'settings'

    def _logout(self, *a):
        _save('auth', {})
        API._token = ''
        self.manager.current = 'login'

    def _toast(self, msg):
        try:
            p = Popup(title='', content=Label(text=msg, color=C_WHITE),
                      size_hint=(0.5, 0.2), background_color=C_CARD)
            p.open()
            Clock.schedule_once(lambda dt: p.dismiss(), 1.5)
        except Exception:
            pass


# ==================== 子页面 ====================
class BindAccountScreen(Screen):
    """绑定页面：上方显示已绑定账号的登录状态+刷新，下方绑定新账号"""
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation='vertical', padding=[16, 16], spacing=6)

        # ── 标题 + 刷新 ──
        hdr = BoxLayout(size_hint=(1, None), height=36, spacing=8)
        hdr.add_widget(_txt('🔗 账号绑定', font_size='18sp', bold=True,
                             color=C_ACCENT, size_hint=(0.65, 1)))
        self.refresh_btn = _btn('🔄 刷新状态', cb=self._refresh_status, accent=True,
                                size_hint=(0.35, 1))
        hdr.add_widget(self.refresh_btn)
        root.add_widget(hdr)

        # ── 状态提示 ──
        self.status_msg = _txt('点击刷新查看登录状态', font_size='12sp',
                                color=C_GREY, size_hint=(1, None), height=20)
        root.add_widget(self.status_msg)

        # ── 已绑定账号状态列表 ──
        sv = ScrollView(size_hint=(1, 0.45))
        self.status_box = BoxLayout(orientation='vertical', spacing=4, size_hint_y=None)
        self.status_box.bind(minimum_height=self.status_box.setter('height'))
        sv.add_widget(self.status_box)
        root.add_widget(sv)

        # ── 分隔线 ──
        root.add_widget(_txt('─ 绑定新账号 ─', font_size='12sp', color=C_DARKGREY,
                             size_hint=(1, None), height=24, halign='center'))

        # ── 绑定表单 ──
        root.add_widget(_txt('目标站手机号', font_size='12sp', color=C_GREY,
                             size_hint=(1, None), height=18))
        self.phone = TextInput(hint_text='输入要绑定的手机号', multiline=False,
                               font_size='15sp', size_hint=(1, None), height=42,
                               background_color=C_CARD, foreground_color=C_WHITE,
                               cursor_color=C_ACCENT, padding=[10, 10])
        root.add_widget(self.phone)

        hb = BoxLayout(spacing=6, size_hint=(1, None), height=42)
        self.code = TextInput(hint_text='短信验证码', multiline=False, input_filter='int',
                              font_size='15sp', size_hint=(0.55, 1),
                              background_color=C_CARD, foreground_color=C_WHITE,
                              cursor_color=C_ACCENT, padding=[8, 8])
        hb.add_widget(self.code)
        self.send_btn = _btn('获取验证码', cb=self._send_sms, accent=True)
        hb.add_widget(self.send_btn)
        root.add_widget(hb)

        root.add_widget(_btn('确认绑定', cb=self._bind, accent=True))
        self.bind_msg = _txt('', font_size='12sp', color=C_GOLD, size_hint=(1, None), height=20)
        root.add_widget(self.bind_msg)
        root.add_widget(_btn('← 返回', cb=lambda x: self._back()))

        self.add_widget(root)

    def on_enter(self):
        self._refresh_status()

    # ── 状态刷新 ──
    def _refresh_status(self, *a):
        self.refresh_btn.disabled = True
        self.status_msg.text = '🔄 正在刷新…'
        self.status_msg.color = C_GOLD
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        r = API.get_bind_status()
        Clock.schedule_once(lambda dt: self._on_status(r), 0)

    def _on_status(self, r):
        self.refresh_btn.disabled = False
        self.status_box.clear_widgets()

        if r.get('ok') is False:
            self.status_msg.text = '❌ 获取状态失败'
            self.status_msg.color = C_RED
            return

        accounts = r.get('accounts', [])
        if not accounts:
            self.status_msg.text = '⚠ 还没有绑定账号，请在下方绑定'
            self.status_msg.color = C_GOLD
            return

        online_count = sum(1 for a in accounts if a.get('login_status') == 'success')
        self.status_msg.text = f'📱 已绑定 {len(accounts)} 个账号 | 在线 {online_count}'
        self.status_msg.color = C_GREEN

        for a in accounts:
            phone = a.get('phone', '***')
            ls = a.get('login_status', 'never')
            at = a.get('account_type', '')

            # 登录状态文案
            if ls == 'success':
                status_text = '正常'
                status_color = C_GREEN
            elif ls == 'offline':
                status_text = '掉线'
                status_color = C_GOLD
            else:
                status_text = '未登录'
                status_color = C_RED

            # 号类型
            if at == 'white':
                type_text = '| 白号'
                type_color = C_GREEN
            elif at == 'black':
                type_text = '| 黑号'
                type_color = C_RED
            else:
                type_text = '| 正常'
                type_color = C_GREY

            card = BoxLayout(size_hint_y=None, height=36, padding=[10, 6], spacing=6)
            card.canvas.before.clear()
            with card.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(*C_CARD)
                Rectangle(pos=card.pos, size=card.size)
            card.add_widget(_txt(phone, font_size='13sp', size_hint=(0.35, 1)))
            card.add_widget(_txt(status_text, font_size='13sp', color=status_color,
                                 size_hint=(0.25, 1)))
            card.add_widget(_txt(type_text, font_size='13sp', color=type_color,
                                 size_hint=(0.4, 1)))
            self.status_box.add_widget(card)

    # ── 发送验证码 ──
    def _send_sms(self, *a):
        phone = self.phone.text.strip()
        if len(phone) != 11:
            self.bind_msg.text = '请输入正确的手机号'
            return
        self.send_btn.disabled = True
        threading.Thread(target=lambda: self._do_sms_result(API.send_sms(phone)), daemon=True).start()

    def _do_sms_result(self, r):
        Clock.schedule_once(lambda dt: self._on_sms(r), 0)

    def _on_sms(self, r):
        self.send_btn.disabled = False
        self.bind_msg.text = '验证码已发送' if r.get('ok') else r.get('error', '发送失败')

    # ── 提交绑定 ──
    def _bind(self, *a):
        phone = self.phone.text.strip()
        code = self.code.text.strip()
        if not phone or not code:
            self.bind_msg.text = '请填写手机号和验证码'
            return
        self.bind_msg.color = C_GOLD
        self.bind_msg.text = '绑定中…'
        threading.Thread(target=self._do_bind, args=(phone, code), daemon=True).start()

    def _do_bind(self, phone, code):
        r = API.bind_account(phone, code)
        Clock.schedule_once(lambda dt: self._on_result(r), 0)

    def _on_result(self, r):
        if r.get('ok'):
            self.bind_msg.color = C_GREEN
            self.bind_msg.text = '🎉 绑定成功！'
            self.phone.text = ''
            self.code.text = ''
            self._refresh_status()  # 自动刷新状态列表
        else:
            self.bind_msg.color = C_RED
            self.bind_msg.text = r.get('error', '绑定失败')

    def _back(self):
        self.manager.current = 'main'


class OrderListScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        lyt = BoxLayout(orientation='vertical', padding=[16, 20], spacing=8)
        lyt.add_widget(_txt('📋 查单记录', font_size='20sp', bold=True,
                             color=C_ACCENT, size_hint=(1, 0.1)))
        sv = ScrollView(size_hint=(1, 1))
        self.list_box = BoxLayout(orientation='vertical', spacing=4, size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter('height'))
        sv.add_widget(self.list_box)
        lyt.add_widget(sv)
        lyt.add_widget(_btn('← 返回', cb=lambda x: setattr(self.manager, 'current', 'main')))
        self.add_widget(lyt)

    def on_enter(self):
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        r = API.get_orders()
        Clock.schedule_once(lambda dt: self._show(r), 0)

    def _show(self, r):
        self.list_box.clear_widgets()
        orders = r.get('orders', []) if r.get('ok') is not False else []
        if not orders:
            self.list_box.add_widget(_txt('暂无记录', color=C_GREY))
            return
        for o in orders:
            status = '🎉 中奖' if o.get('won') else '❌ 未中'
            card = BoxLayout(orientation='vertical', size_hint_y=None, height=48,
                             padding=[10, 4], spacing=2)
            card.canvas.before.clear()
            with card.canvas.before:
                from kivy.graphics import Color, Rectangle
                Color(*C_CARD)
                Rectangle(pos=card.pos, size=card.size)
            card.add_widget(_txt(
                f"{o.get('date','')}  {status}  消耗: -50.000猫粮  {o.get('item','')}",
                font_size='12sp'))
            self.list_box.add_widget(card)


class ChangePwScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        lyt = BoxLayout(orientation='vertical', padding=[30, 80], spacing=12)
        lyt.add_widget(_txt('🔑 修改密码', font_size='20sp', bold=True,
                             color=C_ACCENT, size_hint=(1, 0.12)))
        self.msg = _txt('', font_size='13sp', color=C_GOLD, size_hint=(1, 0.06))
        lyt.add_widget(self.msg)
        self.old = TextInput(hint_text='旧密码', multiline=False, password=True,
                             font_size='16sp', size_hint=(1, None), height=44,
                             background_color=C_CARD, foreground_color=C_WHITE,
                             cursor_color=C_ACCENT, padding=[10, 10])
        lyt.add_widget(self.old)
        self.new = TextInput(hint_text='新密码', multiline=False, password=True,
                             font_size='16sp', size_hint=(1, None), height=44,
                             background_color=C_CARD, foreground_color=C_WHITE,
                             cursor_color=C_ACCENT, padding=[10, 10])
        lyt.add_widget(self.new)
        lyt.add_widget(_btn('确认修改', cb=self._change, accent=True))
        lyt.add_widget(_btn('← 返回', cb=lambda x: setattr(self.manager, 'current', 'main')))
        lyt.add_widget(Label(size_hint=(1, 0.4)))
        self.add_widget(lyt)

    def _change(self, *a):
        o, n = self.old.text.strip(), self.new.text.strip()
        if not o or not n:
            self.msg.text = '请填写完整'
            return
        threading.Thread(target=lambda: self._do_change(o, n), daemon=True).start()

    def _do_change(self, o, n):
        r = API.change_password(o, n)
        Clock.schedule_once(lambda dt: self._on_change(r), 0)

    def _on_change(self, r):
        self.msg.color = C_GREEN if r.get('ok') else C_RED
        self.msg.text = '修改成功' if r.get('ok') else r.get('error', '修改失败')


class SettingsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        lyt = BoxLayout(orientation='vertical', padding=[30, 60], spacing=12)
        lyt.add_widget(_txt('⚙ 设置', font_size='20sp', bold=True,
                             color=C_ACCENT, size_hint=(1, 0.1)))
        lyt.add_widget(_txt('服务器地址', font_size='13sp', color=C_GREY,
                             size_hint=(1, 0.05)))
        saved = _load('settings') or {}
        self.svr = TextInput(text=saved.get('server', f'{SERVER_HOST}:{SERVER_PORT}'),
                             multiline=False, font_size='14sp',
                             size_hint=(1, None), height=40,
                             background_color=C_CARD, foreground_color=C_WHITE,
                             cursor_color=C_ACCENT, padding=[8, 8])
        lyt.add_widget(self.svr)
        lyt.add_widget(_txt('设备名称', font_size='13sp', color=C_GREY,
                             size_hint=(1, 0.05)))
        self.name = TextInput(text=saved.get('device_name', socket.gethostname()),
                              multiline=False, font_size='14sp',
                              size_hint=(1, None), height=40,
                              background_color=C_CARD, foreground_color=C_WHITE,
                              cursor_color=C_ACCENT, padding=[8, 8])
        lyt.add_widget(self.name)
        lyt.add_widget(_btn('💾 保存', cb=self._save, accent=True))
        lyt.add_widget(_btn('← 返回', cb=lambda x: setattr(self.manager, 'current', 'main')))
        lyt.add_widget(Label(size_hint=(1, 0.4)))
        self.add_widget(lyt)

    def _save(self, *a):
        _save('settings', {
            'server': self.svr.text.strip(),
            'device_name': self.name.text.strip(),
        })


# ==================== IP 切换 ====================
def _change_ip():
    """双保险：反射法优先，失败切 root"""
    # 方式1：反射
    try:
        from jnius import autoclass
        Context = autoclass('android.content.Context')
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        ctx = activity.getApplicationContext()
        ConnectivityManager = autoclass('android.net.ConnectivityManager')
        service = ctx.getSystemService(Context.CONNECTIVITY_SERVICE)
        method = service.getClass().getDeclaredMethod('setMobileDataEnabled', bool)
        method.setAccessible(True)
        method.invoke(service, False)
        time.sleep(3)
        method.invoke(service, True)
        print('[换IP] 反射法成功')
        return True
    except Exception as e:
        print(f'[换IP] 反射法失败: {e}')

    # 方式2：root
    try:
        import subprocess
        subprocess.run(['su', '-c',
                        'svc data disable && sleep 3 && svc data enable'],
                       timeout=10, capture_output=True)
        print('[换IP] root法执行完毕')
        return True
    except Exception as e:
        print(f'[换IP] root法失败: {e}')
    return False


# ==================== 代理核心（保持原有） ====================
_ws_status = {
    'tunnel_id': '', 'local_port': 0, 'proxy_addr': '',
    'connected': False, 'active_tunnels': 0, 'error': '',
}
_ws_lock = threading.Lock()

def _ws_set(k, v):
    with _ws_lock:
        _ws_status[k] = v

def _ws_get(k):
    with _ws_lock:
        return _ws_status.get(k)


# ==================== 强制蜂窝网络 ====================
def _enable_cellular():
    """强行打开蜂窝数据（反射法 + root 兜底）"""
    # 方式1：反射 setMobileDataEnabled
    try:
        from jnius import autoclass
        Context = autoclass('android.content.Context')
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        ctx = activity.getApplicationContext()
        cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE)
        method = cm.getClass().getDeclaredMethod('setMobileDataEnabled', autoclass('java.lang.Boolean').TYPE)
        method.setAccessible(True)
        method.invoke(cm, True)
        print('[网络] 反射法已开启蜂窝数据')
        return True
    except Exception as e:
        print(f'[网络] 反射法开启蜂窝失败: {e}')

    # 方式2：root 执行 svc data enable
    try:
        import subprocess
        subprocess.run(['su', '-c', 'svc data enable'], timeout=8, capture_output=True)
        print('[网络] root法已开启蜂窝数据')
        return True
    except Exception as e:
        print(f'[网络] root法开启蜂窝失败: {e}')
    return False


def force_cellular():
    """强制 App 所有流量走 4G/5G，绕过 WiFi
    1. 先尝试绑定已有的蜂窝网络
    2. 若无蜂窝 → 反射/root 强制开启 → 等待注册 → 再绑定"""
    try:
        from jnius import autoclass
        ConnectivityManager = autoclass('android.net.ConnectivityManager')
        NetworkCapabilities = autoclass('android.net.NetworkCapabilities')
        Context = autoclass('android.content.Context')

        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        cm = activity.getSystemService(Context.CONNECTIVITY_SERVICE)

        def _find_and_bind():
            networks = cm.getAllNetworks()
            for net in networks:
                caps = cm.getNetworkCapabilities(net)
                if caps and caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR):
                    if hasattr(cm, 'bindProcessToNetwork'):
                        cm.bindProcessToNetwork(net)
                    else:
                        cm.setProcessDefaultNetwork(net)
                    return True
            return False

        if _find_and_bind():
            print('[网络] ✅ 已绑定蜂窝网络 (4G/5G)，绕过 WiFi')
            return True

        # 蜂窝未开启 → 强制打开
        print('[网络] ⚠️ 蜂窝未开启，尝试强制打开…')
        if _enable_cellular():
            # 等待网络注册（最多等 8 秒）
            for i in range(16):
                time.sleep(0.5)
                if _find_and_bind():
                    print('[网络] ✅ 蜂窝已开启并绑定 (4G/5G)')
                    return True
            print('[网络] ⚠️ 蜂窝已开启但未注册到网络，使用默认')
        else:
            print('[网络] ❌ 无法开启蜂窝，使用默认网络（可能走 WiFi）')
        return False
    except Exception as e:
        print(f'[网络] ❌ 切换蜂窝失败: {e}')
        return False


class TunnelClient:
    """WebSocket 隧道客户端"""
    def __init__(self):
        self.tunnel_id = ''
        self._ws = None
        self._running = False
        self._reconnect_delay = 3

    def connect(self):
        import websocket as ws_module
        url = SERVER_WS
        self._running = True
        while self._running:
            try:
                _ws_set('error', '')
                ws = ws_module.WebSocket()
                ws.connect(url, timeout=15)
                ws.send(json.dumps({'type': 'register', 'name': socket.gethostname(),
                                    'device_id': DEVICE_ID}))
                resp = json.loads(ws.recv())
                if resp.get('type') == 'registered':
                    self.tunnel_id = resp['tunnel_id']
                    _ws_set('tunnel_id', self.tunnel_id)
                    _ws_set('local_port', resp.get('local_port', 0))
                    _ws_set('proxy_addr', resp.get('proxy_addr', ''))
                    _ws_set('connected', True)
                self._ws = ws
                self._handle_messages(ws)
            except Exception as e:
                _ws_set('connected', False)
                _ws_set('error', str(e)[:40])
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 1.5, 30)

    def _handle_messages(self, ws):
        import websocket as ws_module
        last_ping = time.time()
        while self._running:
            try:
                ws.settimeout(5)
                opcode, data = ws.recv_data()
                if opcode == ws_module.ABNF.OPCODE_TEXT:
                    msg = json.loads(data.decode())
                    self._handle_text(msg, ws)
                elif opcode == ws_module.ABNF.OPCODE_PING:
                    ws.pong(data)
                elif opcode == ws_module.ABNF.OPCODE_CLOSE:
                    break

                if time.time() - last_ping > 20:
                    ws.send(json.dumps({'type': 'ping'}))
                    last_ping = time.time()
            except ws_module.WebSocketTimeoutException:
                if time.time() - last_ping > 20:
                    try:
                        ws.send(json.dumps({'type': 'ping'}))
                        last_ping = time.time()
                    except Exception:
                        break
            except Exception:
                break
        self._ws = None
        _ws_set('connected', False)
        self._reconnect_delay = 3

    def _handle_text(self, msg, ws):
        if msg.get('type') == 'connect':
            t = threading.Thread(target=self._do_connect,
                                 args=(msg['tunnel_id'], msg['host'],
                                       msg['port'], ws), daemon=True)
            t.start()
            _ws_set('active_tunnels', _ws_get('active_tunnels') + 1)
        elif msg.get('type') == 'change_ip':
            threading.Thread(target=_change_ip, daemon=True).start()
        elif msg.get('type') == 'won':
            # 中签通知 → 回调 UI 层弹出提示
            global _on_won_callback
            if _on_won_callback:
                _on_won_callback(msg.get('phone', ''), msg.get('masked', ''),
                                 msg.get('item', '茅台'), msg.get('order_id', ''))

    def _do_connect(self, tunnel_id, host, port, ws):
        import websocket as ws_module
        try:
            remote = socket.create_connection((host, port), timeout=10)
        except Exception:
            ws.send(json.dumps({'type': 'error', 'tunnel_id': tunnel_id}))
            _ws_set('active_tunnels', max(0, _ws_get('active_tunnels') - 1))
            return

        ws.send(json.dumps({'type': 'connected', 'tunnel_id': tunnel_id}))
        running = {'v': True}

        def ws_to_tcp():
            try:
                while running['v']:
                    ws.settimeout(2)
                    op, dat = ws.recv_data()
                    if op == ws_module.ABNF.OPCODE_BINARY:
                        if len(dat) > 13 and dat[0:1] == b'T':
                            if dat[1:13].decode() == tunnel_id:
                                p = dat[13:]
                                if p == b'__CLOSE__':
                                    break
                                remote.sendall(p)
                    elif op == ws_module.ABNF.OPCODE_CLOSE:
                        break
            except ws_module.WebSocketTimeoutException:
                pass
            except Exception:
                pass
            running['v'] = False

        threading.Thread(target=ws_to_tcp, daemon=True).start()

        try:
            while running['v']:
                d = remote.recv(8192)
                if not d:
                    break
                ws.send(b'T' + tunnel_id.encode() + d, opcode=ws_module.ABNF.OPCODE_BINARY)
        except Exception:
            pass
        running['v'] = False
        try:
            remote.close()
            ws.send(b'T' + tunnel_id.encode() + b'__CLOSE__',
                    opcode=ws_module.ABNF.OPCODE_BINARY)
        except Exception:
            pass
        _ws_set('active_tunnels', max(0, _ws_get('active_tunnels') - 1))


def run_tunnel():
    TunnelClient().connect()


# 中签回调（由 YangMaoApp 设置）
_on_won_callback = None


# ==================== App 入口 ====================
class YangMaoApp(App):
    def build(self):
        self.title = '养猫'
        Window.size = (400, 680)
        sm = ScreenManager(transition=SlideTransition())
        sm.add_widget(LoginScreen())
        sm.add_widget(RegisterScreen())
        sm.add_widget(MainScreen())
        self.sm = sm
        return sm

    def on_start(self):
        global _on_won_callback
        _on_won_callback = self._show_won_popup
        force_cellular()  # WiFi + 4G 同时开启时强制走蜂窝数据
        threading.Thread(target=run_tunnel, daemon=True).start()
        self._start_foreground()
        Clock.schedule_interval(self._heartbeat, 60)

    def _show_won_popup(self, phone, masked, item, order_id):
        """中签弹窗 → 屏幕上显示 '手机号已中签'"""
        display = masked or (phone[:3] + '****' + phone[-4:])
        Clock.schedule_once(lambda dt: self._do_popup(f'🎉 {display} 已中签…'), 0)

    def _do_popup(self, msg):
        try:
            content = Label(text=msg, font_size='16sp', color=C_GREEN,
                          halign='center', valign='middle')
            content.bind(size=content.setter('text_size'))
            popup = Popup(title='🎯 中签通知', content=content,
                         size_hint=(0.75, 0.35), background_color=C_CARD,
                         title_color=C_ACCENT, auto_dismiss=True)
            popup.open()
            # 10 秒后自动关闭
            Clock.schedule_once(lambda dt: popup.dismiss() if popup else None, 10)
        except Exception:
            pass

    def _start_foreground(self):
        try:
            from jnius import autoclass
            Context = autoclass('android.content.Context')
            NotificationManager = autoclass('android.app.NotificationManager')
            NotificationChannel = autoclass('android.app.NotificationChannel')
            NotificationBuilder = autoclass('android.app.Notification$Builder')
            Notification = autoclass('android.app.Notification')
            Intent = autoclass('android.content.Intent')
            PendingIntent = autoclass('android.app.PendingIntent')
            R = autoclass('org.kivy.android.R$drawable')

            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            ctx = activity.getApplicationContext()
            nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE)

            CH = 'yangmao_channel'
            ch = NotificationChannel(CH, '养猫', NotificationManager.IMPORTANCE_LOW)
            ch.setDescription('猫咪正在觅食中')
            ch.setShowBadge(False)
            nm.createNotificationChannel(ch)

            intent = Intent(ctx, activity.getClass())
            pi = PendingIntent.getActivity(ctx, 0, intent,
                                           PendingIntent.FLAG_UPDATE_CURRENT |
                                           PendingIntent.FLAG_IMMUTABLE)

            builder = NotificationBuilder(ctx, CH)
            builder.setContentTitle('养猫')
            builder.setContentText('猫咪正在觅食中…')
            builder.setSmallIcon(R.icon)
            builder.setOngoing(True)
            builder.setContentIntent(pi)
            builder.setPriority(Notification.PRIORITY_LOW)

            activity.startForeground(1, builder.build())

            PowerManager = autoclass('android.os.PowerManager')
            pm = ctx.getSystemService(Context.POWER_SERVICE)
            wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, 'YangMao:WakeLock')
            wl.acquire()
            print('[前台服务] 已启动')
        except Exception as e:
            print(f'[前台服务] 失败: {e}')
            try:
                from jnius import autoclass
                Context = autoclass('android.content.Context')
                PowerManager = autoclass('android.os.PowerManager')
                act = autoclass('org.kivy.android.PythonActivity').mActivity
                pm = act.getSystemService(Context.POWER_SERVICE)
                pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, 'YangMao:WakeLock').acquire()
            except Exception:
                pass

    def _heartbeat(self, dt):
        if API._token:
            threading.Thread(target=lambda: API.heartbeat(), daemon=True).start()

    def on_pause(self):
        return True


if __name__ == '__main__':
    YangMaoApp().run()
