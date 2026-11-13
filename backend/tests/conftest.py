import os
import secrets
import tempfile
from pathlib import Path

# Settings loaded at import; configure isolated DB before importing app.
_test_dir = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_test_dir.name) / 'test.db').replace('\\','/')
os.environ['ADMIN_SECRET'] = 'test-admin-' + secrets.token_urlsafe(32)
os.environ['KEY_PEPPER'] = 'test-pepper-' + secrets.token_urlsafe(32)

import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture
def admin_headers():
    return {'X-Admin-Key':os.environ['ADMIN_SECRET']}

@pytest.fixture
def registered(client, admin_headers):
    device=client.post('/admin/devices',headers=admin_headers,json={'name':'Pixel Lab'}).json()
    key=client.post('/admin/keys',headers=admin_headers,json={'device_id':device['device_id']}).json()
    return device, key
