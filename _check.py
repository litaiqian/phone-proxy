import urllib.request, json
try:
    r = urllib.request.urlopen("http://127.0.0.1:8000/api/health")
    d = json.loads(r.read())
    print("8000:", d)
except Exception as e:
    print("8000: ERROR -", e)

try:
    r = urllib.request.urlopen("http://127.0.0.1:5000/api/health")
    d = json.loads(r.read())
    print("5000:", d)
except Exception as e:
    print("5000: ERROR -", e)
