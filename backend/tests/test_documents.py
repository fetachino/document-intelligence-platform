import io
import asyncio
from pathlib import Path
from fastapi.testclient import TestClient


def test_health():
    from backend.app.main import app
    client = TestClient(app)
    r = client.get('/api/v1/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_upload_and_list(tmp_path, monkeypatch):
    # use temp storage and sqlite db (async driver)
    monkeypatch.setenv('STORAGE_PATH', str(tmp_path))
    monkeypatch.setenv('DATABASE_URL', 'sqlite+aiosqlite:///'+str(tmp_path/'test.db'))

    # recreate DB
    from backend.app.database import init_db
    asyncio.run(init_db())

    from backend.app.main import app
    client = TestClient(app)

    file_content = b'%%PDF-1.4 test content'  # small fake pdf bytes
    files = {'file': ('test.pdf', io.BytesIO(file_content), 'application/pdf')}
    r = client.post('/api/v1/documents/upload', files=files)
    assert r.status_code == 200
    data = r.json()
    assert 'id' in data
    assert data['filename'] == 'test.pdf'

    r2 = client.get('/api/v1/documents/')
    assert r2.status_code == 200
    docs = r2.json()
    assert len(docs) == 1
    assert docs[0]['filename'] == 'test.pdf'
    storage_reference = docs[0]['storage_path']
    assert storage_reference.startswith(f"documents/{data['id']}/")
    assert not Path(storage_reference).is_absolute()
    assert (tmp_path / Path(storage_reference)).read_bytes() == file_content
