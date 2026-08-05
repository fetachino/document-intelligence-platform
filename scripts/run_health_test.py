from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
resp = client.get('/api/v1/health')
print('status_code:', resp.status_code)
try:
    print('json:', resp.json())
except Exception as e:
    print('json parse error:', e)
    print(resp.text)
