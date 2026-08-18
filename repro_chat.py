import http.client
import json
import urllib.parse

base = "127.0.0.1"
port = 8000
conn = http.client.HTTPConnection(base, port)
body = json.dumps({"email": "tempuser5@example.com", "password": "password123", "org_name": "TempOrg"})
conn.request("POST", "/auth/signup", body, {"Content-Type": "application/json"})
r = conn.getresponse()
print("SIGNUP", r.status, r.reason)
print(r.read().decode())
conn.close()

conn = http.client.HTTPConnection(base, port)
params = urllib.parse.urlencode({"username": "tempuser5@example.com", "password": "password123"})
conn.request("POST", "/auth/login", params, {"Content-Type": "application/x-www-form-urlencoded"})
r = conn.getresponse()
login_data = r.read().decode()
print("LOGIN", r.status, r.reason)
print(login_data)
if r.status != 200:
    raise SystemExit(1)

token = json.loads(login_data)["access_token"]
conn.close()

conn = http.client.HTTPConnection(base, port)
conn.request("POST", "/chat/conversations", "", {"Authorization": f"Bearer {token}"})
r = conn.getresponse()
print("CHAT_CONVERSATION", r.status, r.reason)
print(r.read().decode())
conn.close()
