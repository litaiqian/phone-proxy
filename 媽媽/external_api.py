from moutai_service import MoutaiService

def send_verification_code(phone):
    """向第三方平台请求发送验证码（实际调用茅台真实接口）"""
    return MoutaiService.send_verification_code(phone)

def submit_verification_code(phone, code):
    """提交验证码完成登录"""
    token = MoutaiService.submit_verification_code(phone, code)
    return token

def query_balance(phone, token):
    """查询账户余额"""
    # token 参数暂时不用，由 service 内部根据 phone 查询数据库中的 token
    return MoutaiService.query_balance(phone)