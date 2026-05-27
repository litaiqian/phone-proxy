import json, urllib.request, http.cookiejar, urllib.parse

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Login
data = urllib.parse.urlencode({'username': 'admin', 'password': 'admin888'}).encode()
req = urllib.request.Request('http://127.0.0.1:5000/login', data=data)
r = opener.open(req)
print('Login status:', r.status)

# Get stats
r = opener.open('http://127.0.0.1:5000/api/stats')
d = json.loads(r.read())
print('teams:', json.dumps(d.get('teams', []), ensure_ascii=False))
print('team_total:', d.get('team_total_accounts', 0))
print('total records:', d.get('total', 0))
