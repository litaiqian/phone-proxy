#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
haotian / mshield 固定请求体常量 — 从 HAR 抓包提取
====================================================
来源: Reqable MITM 代理抓取 i茅台 1.9.7 (Android 14, Xiaomi 2211133C)
提取时间: 2026-05-25
验证: body 无时效性，5月21日的 body 在5月25日重放依然 200

使用方式:
    import base64
    from _security_bodies import HAOTIAN_BODIES, MSHIELD_BODIES

    for entry in HAOTIAN_BODIES:
        body = base64.b64decode(entry['body_b64'])
        _post(entry['url'], headers=entry['headers'], data=body, proxy=..., timeout=5)

注意:
  - body 存的是 base64 字符串（HAR 原始格式），发送前需 decode
  - 所有账号共用同一套 body（服务器不校验 device-id 与 body 的绑定关系）
"""

# ==================== haotian 百度昊天设备指纹 SDK ====================
# product_id=953300288, 5个核心 API 路径各取一条代表性请求

HAOTIAN_BODIES = [
    {
        "name": "p/5/aio (认证换skey)",
        "url": "https://haotian.baidu.com/p/5/aio/210/953300288/1779367500/50d77a1aaa4ebdb3ede0b0ca366f4e56?skey=O5Rtr5zNS4XPGOYl6cpEWg%3D%3D%0A",
        "headers": {
            "User-Agent": "haotian/953300288/1.9.7/3.6.8.0",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
            "Accept-Language": "zh-CN",
            "x-device-id": "392f698e29684451e3ae8fb5cfd51d9d",
            "x-auth-ver": "2",
            "Connection": "Keep-Alive",
        },
        "body_b64": "N70gAXjcDTiDqCRsjmkFQEpSS2ILslnT6j46v/pcjaZRpwO8uKPp7lYiowki17nx2Kqvc9pGeTAxs3iapDjEGD1LnoTndegmxoMfgBA1ajiNPzCQhXZ/Rv2yB6oh86J1Z7NfG4lRPQbfRAzTG4S1jx0OAXyPFmd+NKlTrXG+naOrcXNku0hQLIPY12QYYNxZZjIMYdb2PLr3Oo1UfWn8mr8zl+JigPwF/NYWjvO2wEI=",
    },
    {
        "name": "p/1/r (上报安全数据)",
        "url": "https://haotian.baidu.com/p/1/r/210/953300288/1779367500/50d77a1aaa4ebdb3ede0b0ca366f4e56?skey=epV4kqfRdIe2LM4q2NVlTQ%3D%3D%0A",
        "headers": {
            "User-Agent": "haotian/953300288/1.9.7/3.6.8.0",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip,deflate",
            "Accept-Language": "zh-CN",
            "x-device-id": "392f698e29684451e3ae8fb5cfd51d9d",
            "x-auth-ver": "2",
            "Connection": "Keep-Alive",
        },
        "body_b64": "2HtElM3l0XTaRHh1z2j+1wqPlkuk/n0GmxjrWxHYcE9AzrAdaxOi0MwHtmdAWytoYSRrXgquENMiT6ZuMXkj1j4BJPDp6M8etTAXTH/tDwt4xLREzBQS8GTMmltA8JCfOWdp0cHsh8ZQFQQHASH3EIDeGw6QG+vzZ4/FuncZzg3rOrg9lPWxnGJ+w/ekBcL/FSd4t7tngT60RtV33PYP/Dal0AlB3Vy/6ezPv3ZO7AZgLtMMz9/Jk1V7IPVVK1AaiF2aUhn9ffrF6WEljZ5cScrhxmCWYWghrv/2qX2J95Jz6qEB31OljjLqJON3uvP7hYIMTbCgbDh/HAyO0HJlgqQTKZ0cndiACNDMwJ97YZm4r9jupgtbAFiJcKF6oCnPvuaETHjA5biS9we9VI5uj8MuRYbp/Ai45XvMl6sKrjo=",
    },
    {
        "name": "r/5/c (收集设备数据)",
        "url": "https://haotian.baidu.com/r/5/c/210/953300288/1779367500/50d77a1aaa4ebdb3ede0b0ca366f4e56?skey=O4NmoOTmQ4vNM%2FQz%2Ffd%2FPQ%3D%3D%0A",
        "headers": {
            "x-device-id": "392f698e29684451e3ae8fb5cfd51d9d",
            "User-Agent": "haotian_x0/953300288/1.9.7/4.4.3.4.3",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
            "Accept-Language": "zh",
            "x-sdk-ver": "haotian/3.6.8.0",
            "x-plu-ver": "haotian_x0/4.4.3.4.3",
            "x-app-ver": "com.moutai.mall/1.9.7",
            "x-api-ver": "34",
            "Connection": "Keep-Alive",
        },
        "body_b64": "P2k0mtkfYiVZcT1tJhrEAAqr5Cf3ZhVaZiC63wfmet/+9TuSDyvYbc646E72x7iehMauetw3QDv+gBsXJzjhHXyWAqdfEP6MJRKLsPrqUHKzIbiA/oqXVQwhNhtDyOaBIre9nYY+/O/RCGoerutRPUoqq/IJTfzmqGNBOskM2AjDY5vQV+5p5SM2DYRftYjER44L62VDV0aohTC+2bO79+/QURTIqPBAoIaSKl06CZzuWcUjEN/iRUjxxzCvsnVZyaSSx3bJLYmFBDVkxv2K5Ge1R1YB1YxYplrVjhVvNLvrJVtiM8coGjZFERXdY+z2/q8CNMJc6ZN4agpylEgON2iyRAROhT1cfPf9iAvu1hTar1hfWXJzNwTw4mTP/PEIhpHOu25qIYPkX9CRYoG1nZwnMhERSLi3fJvBMpOwbfWMRWlHZ9VZpFanV37DVA7qC5oFrD88eZrqW/q/lQ+J8mqb9E248TvIdiGhnyrDpyOunz8T6KBEr9DSy8b/0QXYmJ6ckg7KNMF450dawBCCD2HRsE5gda+wtAliclI0U425bGf23Ad9fXNnW/y+ipkm9oHYxDrSkNEYYQAROzEE7snhhga9tHdomkTPDfZ+HkJyu3ygvdEj7jriQzn7EvUnBvNNMFSk9KaK4OOb4i44Nz+Lq2eGsWMTRIT0cy8cLt5XYgH8fF5Rd8/g+8PZMUBNp9By1iR85oPgBhCH4wyW8CxrvtRAo0dlvRqkj95okwZ1uz9pnbZ1r9D002D9QZHFDQ30Is1RktD+AELVIgYKqXdCE2mzHQ6kPBVSow3xQW0=",
    },
    {
        "name": "c/11/z (压缩上报)",
        "url": "https://haotian.baidu.com/c/11/z/210/953300288/1779365701/1039aa164a460ff6d5c8ff39ef7763ba?skey=MoFNo4HZZratDdEm8MpIfg%3D%3D%0A",
        "headers": {
            "x-device-id": "392f698e29684451e3ae8fb5cfd51d9d",
            "x-client-src": "jar",
            "User-Agent": "haotian_x6/953300288/1.9.7/4.4.3.4.3",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
            "Accept-Language": "zh",
            "x-sdk-ver": "haotian/3.6.8.0",
            "x-plu-ver": "haotian_x6/4.4.3.4.3",
            "x-app-ver": "com.moutai.mall/1.9.7",
            "x-api-ver": "34",
            "Connection": "Keep-Alive",
        },
        "body_b64": "TYRjsluYF3FHQbPLfw4Nj/4dFmTfgTW0q6BqqUXL1KchG6SQU8bVmXY6HhRKZcVaPeKf0HJyzpsBOohGkRP71gQQ04y1LeUYS49ef6DfK+KGeoodZThfKcjoAJb668psi8jLBSljOcqEGiFYu8qXvrIG2ZV6MvFwVDYYYHotzMxPsfM2A+DoK/Ace0EtSg7UCaa2IdNKCpwVmqRwcoe62gwk+mhrU/sRuWSJ9kd1A9jTK5q7iIoZoNIXUOsIa56PhjVH9fwEObxQvskIwEp9AmQmXmkS+4Rg6Yz534GSzxsLSAmGP71j+q9ok1Y4xdMP7EirhUaVqKuiCXtoNkcCe/qiSFOSuSHTDNpP6BAd5Et5R9ZtQbkQ/t+H+4j/JSGdJvariqpFmrXpgbT6/fFkcjix74SPB3QLJ3AdM56p3lrNTYy2bVBKTcUM3C35XNBxOAMlA7N3sEfDVpsXIH0089NuRrKaMnwd4tcttXykXr4psuAHfI9MI8g1YIoqtE3BTTKg61VMYZPT7K7QjHO3azNVwlG/Fs4dmoD3fHuiAr8AcC4/ftQxU3wCsClcr3QUX1+rAEBzGI8LMLPZthonTljmNupGwZ1QZG6LD85b1DPA5aGAstvj6/+P7rxKTDry+d5+K2Dx3W29cRlGWHKpWUXlRUk29VZPnvOsrz1otTq47+vLdtdZOu16e5l6gep+JRwuB82rkqF8naiw8UMpZYHm119OJVzeOnfKN45Uvo4=",
    },
]

# ==================== mshield 百度移动盾 SDK ====================
# product_id=985689349, 2个核心 API 路径

MSHIELD_BODIES = [
    {
        "name": "p/1/r (盾上报)",
        "url": "https://mshield.baidu.com/p/1/r/250/985689349/1779438335/2d8d774ab16058c37ebf0ef1e45dc81f?skey=QaSlweSPsMrvbFsvSuMWSw%3D%3D%0A",
        "headers": {
            "x-device-id": "e61f934acf4aabcb70e16d5ab23cf7ef",
            "User-Agent": "mshield/985689349//4.2.6",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
            "Accept-Language": "zh",
            "x-sdk-ver": "mshield/4.2.6",
            "x-plu-ver": "x0/4.2.6",
            "x-app-ver": "com.moutai.mall/",
            "x-sys-ver": "android/",
            "x-sys-dev": "/",
            "x-api-ver": "34",
            "Connection": "Keep-Alive",
        },
        "body_b64": "wuzX/c5yJ6Ye4hWmzkmAs9YWEZ6ZVMTktwnz7WwJv+sapMShfGd8KbML1Qg/UnZai4eaCrx89wljo5RwFZNf+zfjsKsb+kWxQ2PDNqbrdx+dRXJZ0+ULjD+dXOwixfZYoBbZPNhhs1yb+ZaQUjeehLtJZ+wKcV94JIjAsL1TDmDCCXoRFJqOSsT0q4dh79HOm0s32Broj6NgSVuN6PmWHwODqPcPQdqXwmoPgA7Py/dLRn1XyAPERTJ7Gpe+bkcSm3bfd5C9x80tzQNdt5/y3sB3p2SvBkmN7/qAa09vnjqXbP4NDVJWOEA9g3mfEx4g3vze2j29zWY6C3hZJn6AjgGV8gVOzPOLLfOI+UbVirx7zDWDD9UhXfDBfLIAYtXQEftIzxpC5n2gMogxitgFrw==",
    },
    {
        "name": "s/5/aio (盾安全通信)",
        "url": "https://mshield.baidu.com/s/5/aio/250/985689349/1779438335/2d8d774ab16058c37ebf0ef1e45dc81f?skey=OY6Y0eaz6O75bQkreO4OUg%3D%3D%0A",
        "headers": {
            "x-device-id": "e61f934acf4aabcb70e16d5ab23cf7ef",
            "User-Agent": "mshield/985689349//4.2.6",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
            "Accept-Language": "zh",
            "x-sdk-ver": "mshield/4.2.6",
            "x-plu-ver": "x0/4.2.6",
            "x-app-ver": "com.moutai.mall/",
            "x-sys-ver": "android/",
            "x-sys-dev": "/",
            "x-api-ver": "34",
            "Connection": "Keep-Alive",
        },
        "body_b64": "NJVuR7nXhMWLOFviHDjKk3JZbyUCpqKzrm6BLeRdtANwtgKiryEGMtVnXXIDE8eYBmqazAuGx1So3iU1+XHvgVbCWW1z2i/hJtcGZkRcWLGaNo2ihEccI4Xr+OBdOqvbqPfrfIRd8GHQFfSeHbEa49/kGgxsJzFNCNnplZeVDgKNpY+cys4JhbgF4qPRQvh2X0hUouruQTqO+01G8WDXSc/VxXLe0cEkd9enKo75iKH0pXuDOQ8CqXrvgtWPuANO4gJfnGtWAAlHOSqsCfFd+lkrFB8wNm53jpssf9GhD/G6YjimLMufY5xWJQcKXPnfKmjnCm2BOvwRx2hJAEhRqereze+h83dk2tCL13M064iHQQmPTHzMfg2ncAzFk9PvErF5R2SmcYZ7TXunCZFeDZzt8C3waZUXP2ZeqoSknllmFbcgET1VxnUZ9kztpHuP",
    },
]
