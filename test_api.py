import requests

token = 'f6f1c693c5a845f8a8656360abb782ad'
h = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

tests = [
    ('heartbeat',   'POST', '/api/app/heartbeat', None),
    ('cat_food',    'GET',  '/api/app/cat_food', None),
    ('orders',      'GET',  '/api/app/orders', None),
    ('refer_code',  'GET',  '/api/app/refer_code', None),
    ('referrals',   'GET',  '/api/app/referrals', None),
    ('change_pw',   'POST', '/api/app/change_password', {'old_password': 'x', 'new_password': 'y'}),
]

for name, method, path, body in tests:
    try:
        url = 'http://ipla.top:5000' + path
        if method == 'POST':
            r = requests.post(url, headers=h, json=body or {}, timeout=10)
        else:
            r = requests.get(url, headers=h, timeout=10)
        code = r.status_code
        data = r.json()
        print(f'[{code}] {method} {path} => {data}')
    except Exception as e:
        print(f'[ERR] {method} {path} => {e}')
