# external_api.py
# 平台 API 封装：发送验证码、提交验证码、查询余额
import requests
from config import Config
from demo import MoutaiClient
client = MoutaiClient()
# 平台基础地址（从 Config 中读取）
BASE_URL = Config.PLATFORM_BASE_URL

def send_verification_code(phone):
    """
    向第三方平台请求发送验证码
    :param phone: 手机号字符串
    :return: 成功返回 True，失败返回 False
    """
    url = f"{BASE_URL}/sendCode"
    payload = {'phone': phone}
    print(payload)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        # 假设平台返回格式：{"code":0, "msg":"success"}
        if resp.status_code == 200 and resp.json().get('code') == 0:
            return True
        else:
            return False
    except Exception as e:
        print(f"发送验证码失败: {e}-------------------------")
        return False
'''
def send_verification_code(phone):
    
    """
    向第三方平台请求发送验证码
    :param phone: 手机号字符串
    :return: 成功返回 True，失败返回 False
    """
    url = f"{BASE_URL}/sendCode"
    payload = {'phone': phone}
    print(payload)
    try:
        # 向媽媽 請求发送验证码--------------------------------------------
        resp = client.send_vcode(phone)
        # 假设平台返回格式：{"code":0, "msg":"success"}
        if resp.status_code == 2000 and resp.json().get('code') == 0:
            return True
        else:
            return False
    except Exception as e:
        print(f"发送验证码失败: {e}")
        return False
        '''
def submit_verification_code(phone, code):
    """
    向平台提交验证码完成登录
    :param phone: 手机号
    :param code: 用户输入的验证码
    :return: 成功返回 token 字符串, 失败返回 None
    """
    # url = f"{BASE_URL}/login"
    payload = {'phone': phone, 'code': code}
    print(payload)
    try:
        resp = client.login(payload)
        if resp.status_code == 200 and resp.json().get('code') == 0:
            # 假设返回数据中 token 在 data.token 字段
            return resp.json().get('data', {}).get('token')
        else:
            return None
    except Exception as e:
        print(f"登录失败: {e}")
        return None

def query_balance(phone, token):
    """
    登录成功后查询账户余额
    :param phone: 手机号
    :param token: 登录后获得的 token
    :return: 余额字符串，失败返回 '0'
    """
    url = f"{BASE_URL}/balance"
    headers = {'Authorization': f'Bearer {token}'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and resp.json().get('code') == 0:
            return resp.json().get('data', {}).get('balance', '0')
        else:
            return '0'
    except Exception as e:
        print(f"查询余额失败: {e}")
        return '0'