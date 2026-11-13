import pytest
from app import create_app
from app.config import Config

class LocalConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-only'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

@pytest.mark.parametrize('secret', [None, '', 'short', 'dev-secret-key-change-in-production'])
def test_factory_rejects_unsafe_production_secret(secret):
    class Production(Config):
        TESTING = False
        DEBUG = False
        SECRET_KEY = secret
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app(Production)

@pytest.fixture
def private_client(monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password')
    return create_app(LocalConfig).test_client()

@pytest.mark.parametrize('path', ['/auth/subscribe/success', '/auth/create-checkout-session', '/auth/stripe/webhook', '/subscribe/stripe', '/webhook/stripe', '/contact'])
@pytest.mark.parametrize('method', ['get', 'post'])
def test_legacy_billing_and_contact_disabled(private_client, path, method):
    response = getattr(private_client, method)(path, auth=('admin', 'test-password'))
    assert response.status_code == 404

@pytest.mark.parametrize('path', ['/', '/api/stats', '/health', '/api/admin/export/comments.csv'])
def test_unauthenticated_access_denied(private_client, path):
    assert private_client.get(path).status_code == 401

def test_health_minimal(private_client):
    assert private_client.get('/healthz').json == {'ok': True}

def test_unicode_credentials_do_not_crash(private_client):
    assert private_client.get('/api/stats', auth=('관리자', '틀림')).status_code == 401

def test_valid_credentials(private_client):
    assert private_client.get('/api/stats', auth=('admin', 'test-password')).status_code == 200

def test_missing_admin_fails_closed(monkeypatch):
    monkeypatch.delenv('ADMIN_USERNAME', raising=False)
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    assert create_app(LocalConfig).test_client().get('/').status_code == 503
