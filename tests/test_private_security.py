import re
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.config import Config

PASSWORD = 'test-password'
PASSWORD_HASH = generate_password_hash(PASSWORD)


class LocalConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-only-secret-key-for-sessions'
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'check_same_thread': False},
        'poolclass': StaticPool,
    }
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_SECURE = False


def _client(monkeypatch, csrf=True):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', PASSWORD_HASH)
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    monkeypatch.delenv('ENABLE_EXTERNAL_AI', raising=False)

    class _Cfg(LocalConfig):
        WTF_CSRF_ENABLED = csrf

    application = create_app(_Cfg)
    with application.app_context():
        db.create_all()
    return application.test_client()


@pytest.fixture
def private_client(monkeypatch):
    return _client(monkeypatch, csrf=True)


def _csrf(client):
    page = client.get('/login')
    if page.status_code != 200:
        page = client.get('/admin')
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    assert match, page.get_data(as_text=True)
    return match.group(1)


def _login(client, username='admin', password=PASSWORD, nxt='/admin'):
    return client.post('/login', data={
        'username': username,
        'password': password,
        'csrf_token': _csrf(client),
        'next': nxt,
    }, headers={'Referer': 'https://localhost/login'})


@pytest.mark.parametrize('secret', [None, '', 'short', 'dev-secret-key-change-in-production'])
def test_factory_rejects_unsafe_production_secret(secret, monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', PASSWORD_HASH)

    class Production(Config):
        TESTING = False
        DEBUG = False
        SECRET_KEY = secret

    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app(Production)


def test_factory_requires_password_hash(monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'plaintext-is-not-enough')
    monkeypatch.delenv('ADMIN_PASSWORD_HASH', raising=False)

    class Production(Config):
        TESTING = False
        DEBUG = False
        SECRET_KEY = 'a' * 40

    with pytest.raises(RuntimeError, match='ADMIN_PASSWORD_HASH'):
        create_app(Production)


@pytest.mark.parametrize('path', [
    '/auth/subscribe/success', '/auth/create-checkout-session', '/auth/stripe/webhook',
    '/auth/login', '/subscribe/stripe', '/webhook/stripe', '/contact',
])
@pytest.mark.parametrize('method', ['get', 'post'])
def test_legacy_billing_and_contact_disabled(private_client, path, method):
    response = getattr(private_client, method)(path)
    assert response.status_code == 404


@pytest.mark.parametrize('path', ['/api/stats', '/api/admin/export/comments.csv', '/export/comments.csv'])
def test_unauthenticated_api_and_csv_blocked(private_client, path):
    assert private_client.get(path).status_code == 401


def test_html_page_redirects_to_login(private_client):
    response = private_client.get('/admin')
    assert response.status_code == 302
    assert '/login' in response.location
    assert 'accounts.google.com' not in response.location


def test_health_minimal(private_client):
    assert private_client.get('/healthz').json == {'ok': True}


def test_basic_auth_is_not_accepted(private_client):
    assert private_client.get('/api/stats', auth=('admin', PASSWORD)).status_code == 401


def test_unicode_credentials_do_not_crash(private_client):
    response = _login(private_client, username='관리자', password='틀림')
    assert response.status_code == 401


def test_login_csrf_missing(private_client):
    response = private_client.post('/login', data={'username': 'admin', 'password': PASSWORD})
    assert response.status_code == 400


def test_login_rate_limit(private_client):
    for _ in range(5):
        response = _login(private_client, password='wrong-password')
        assert response.status_code == 401
    blocked = _login(private_client, password=PASSWORD)
    assert blocked.status_code == 429


def test_valid_session_allows_api_and_csv(private_client):
    response = _login(private_client)
    assert response.status_code == 302
    set_cookie = response.headers.get('Set-Cookie', '')
    assert 'HttpOnly' in set_cookie
    assert 'SameSite=Lax' in set_cookie
    assert private_client.get('/api/stats').status_code == 200
    exported = private_client.get('/api/admin/export/comments.csv')
    assert exported.status_code == 200
    assert b'comment_id' in exported.data
    private_client.post('/logout', data={'csrf_token': _csrf(private_client)}, headers={'Referer': 'https://localhost/admin'})
    assert private_client.get('/api/stats').status_code == 401
    assert private_client.get('/export/comments.csv').status_code == 401


def test_open_redirect_rejected(private_client):
    response = _login(private_client, nxt='https://evil.example/phish')
    assert response.status_code == 302
    assert 'evil.example' not in (response.location or '')
    response = _login(private_client, nxt='//evil.example')
    assert 'evil.example' not in (response.location or '')


def test_secure_cookie_flag_when_configured(monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', PASSWORD_HASH)

    class SecureConfig(LocalConfig):
        SESSION_COOKIE_SECURE = True

    application = create_app(SecureConfig)
    with application.app_context():
        db.create_all()
    client = application.test_client()
    response = _login(client)
    assert 'Secure' in response.headers.get('Set-Cookie', '')


def test_missing_admin_fails_closed(monkeypatch):
    monkeypatch.delenv('ADMIN_USERNAME', raising=False)
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    monkeypatch.delenv('ADMIN_PASSWORD_HASH', raising=False)
    assert create_app(LocalConfig).test_client().get('/').status_code == 503


def test_developer_grant_migration_removed():
    root = Path(__file__).resolve().parents[1]
    assert not list((root / 'migrations').rglob('*theresa*'))
    tree = '\n'.join(path.read_text(encoding='utf-8') for path in (root / 'migrations').rglob('*.py'))
    assert 'theresasumma@gmail.com' not in tree
    assert "down_revision = 'a140228fb140'" not in tree
