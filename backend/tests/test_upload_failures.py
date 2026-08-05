import io
import asyncio
from fastapi.testclient import TestClient


def test_invalid_extension(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE_PATH', str(tmp_path))
    monkeypatch.setenv('DATABASE_URL', 'sqlite+aiosqlite:///'+str(tmp_path/'test.db'))
    from backend.app.database import init_db
    asyncio.run(init_db())

    from backend.app.main import app
    client = TestClient(app)

    file_content = b'test content'
    files = {'file': ('test.exe', io.BytesIO(file_content), 'application/octet-stream')}
    r = client.post('/api/v1/documents/upload', files=files)
    assert r.status_code == 400
    assert r.json()['detail'] == 'unsupported_file_type'


def test_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE_PATH', str(tmp_path))
    monkeypatch.setenv('DATABASE_URL', 'sqlite+aiosqlite:///'+str(tmp_path/'test.db'))
    monkeypatch.setenv('MAX_UPLOAD_SIZE_BYTES', '10')
    from backend.app.database import init_db
    asyncio.run(init_db())

    from backend.app.main import app
    client = TestClient(app)

    file_content = b'0123456789ABC'  # length > 10
    files = {'file': ('test.pdf', io.BytesIO(file_content), 'application/pdf')}
    r = client.post('/api/v1/documents/upload', files=files)
    assert r.status_code == 400
    assert r.json()['detail'] == 'file_too_large'


def test_path_traversal_filename(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE_PATH', str(tmp_path))
    monkeypatch.setenv('DATABASE_URL', 'sqlite+aiosqlite:///'+str(tmp_path/'test.db'))
    from backend.app.database import init_db
    asyncio.run(init_db())

    from backend.app.main import app
    client = TestClient(app)

    file_content = b'test'
    # simulate malicious filename
    files = {'file': ('../../etc/passwd', io.BytesIO(file_content), 'application/octet-stream')}
    r = client.post('/api/v1/documents/upload', files=files)
    # should still accept but sanitize filename on storage and return 200
    assert r.status_code == 200
    data = r.json()
    assert 'id' in data


def test_duplicate_filename_creates_new_record(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE_PATH', str(tmp_path))
    monkeypatch.setenv('DATABASE_URL', 'sqlite+aiosqlite:///'+str(tmp_path/'test.db'))
    from backend.app.database import init_db
    asyncio.run(init_db())

    from backend.app.main import app
    client = TestClient(app)

    file_content = b'test1'
    files = {'file': ('dup.pdf', io.BytesIO(file_content), 'application/pdf')}
    r1 = client.post('/api/v1/documents/upload', files=files)
    assert r1.status_code == 200

    file_content2 = b'test2'
    files2 = {'file': ('dup.pdf', io.BytesIO(file_content2), 'application/pdf')}
    r2 = client.post('/api/v1/documents/upload', files=files2)
    assert r2.status_code == 200

    rlist = client.get('/api/v1/documents/')
    assert rlist.status_code == 200
    docs = rlist.json()
    assert len(docs) == 2
