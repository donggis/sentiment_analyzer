"""Single-administrator sessions for the private deployment.

The browser cookie holds a random id. The database stores only its hash.
Passwords are checked against ADMIN_PASSWORD_HASH (Werkzeug). Failed attempts
are counted in the database so every process shares one limit.
"""
import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from urllib.parse import quote

from flask import Response, current_app, redirect, request
from werkzeug.security import check_password_hash

from app import db
from app.models import AdminSession, LoginAttempt, _utcnow

SESSION_COOKIE = 'admin_session'
SESSION_HOURS = 12
BLOCKED_EXACT = {
    '/contact',
    '/subscribe/stripe',
    '/webhook/stripe',
    '/auth',
}
BLOCKED_PREFIXES = ('/auth/',)


def password_hash_is_usable(value):
    return isinstance(value, str) and value.startswith(('pbkdf2:', 'scrypt:', 'argon2:')) and len(value) >= 20


def admin_configured():
    username = os.environ.get('ADMIN_USERNAME') or ''
    password_hash = os.environ.get('ADMIN_PASSWORD_HASH') or ''
    return bool(username) and password_hash_is_usable(password_hash)


def is_blocked_path(path):
    if path in BLOCKED_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in BLOCKED_PREFIXES)


def safe_next(value):
    """Allow only a local path. Reject protocol-relative and backslash tricks."""
    if not isinstance(value, str):
        return '/admin'
    candidate = value.strip()
    if not candidate.startswith('/') or candidate.startswith('//') or candidate.startswith('/\\'):
        return '/admin'
    if '\\' in candidate or '://' in candidate:
        return '/admin'
    return candidate


def client_address():
    if os.environ.get('FLY_APP_NAME'):
        forwarded = request.headers.get('Fly-Client-IP')
        if forwarded:
            return forwarded.strip()
    return request.remote_addr or 'unknown'


def _ip_hash(address):
    secret = str(current_app.config.get('SECRET_KEY') or '')
    return hmac.new(secret.encode('utf-8'), address.encode('utf-8'), hashlib.sha256).hexdigest()


def too_many_failures(address):
    limit = int(current_app.config.get('LOGIN_FAIL_LIMIT', 5))
    window = int(current_app.config.get('LOGIN_FAIL_WINDOW_SECONDS', 900))
    cutoff = _utcnow() - timedelta(seconds=window)
    failures = LoginAttempt.query.filter(
        LoginAttempt.ip_hash == _ip_hash(address),
        LoginAttempt.success.is_(False),
        LoginAttempt.created_at >= cutoff,
    ).count()
    return failures >= limit


def record_attempt(address, success):
    db.session.add(LoginAttempt(ip_hash=_ip_hash(address), success=bool(success)))
    db.session.commit()


def passwords_match(username, password):
    expected_user = os.environ.get('ADMIN_USERNAME') or ''
    password_hash = os.environ.get('ADMIN_PASSWORD_HASH') or ''
    supplied = password or ''
    try:
        password_ok = bool(password_hash) and check_password_hash(password_hash, supplied)
    except (TypeError, ValueError):
        password_ok = False
    try:
        user_ok = hmac.compare_digest(username.encode('utf-8'), expected_user.encode('utf-8'))
    except (TypeError, AttributeError):
        user_ok = False
    return password_ok and user_ok


def token_hash(raw_token):
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def load_session():
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    row = AdminSession.query.filter_by(token_hash=token_hash(raw)).first()
    if row is None or row.expires_at <= _utcnow():
        return None
    return row


def start_session():
    AdminSession.query.delete()
    raw = secrets.token_urlsafe(32)
    db.session.add(AdminSession(
        token_hash=token_hash(raw),
        created_at=_utcnow(),
        expires_at=_utcnow() + timedelta(hours=SESSION_HOURS),
    ))
    db.session.commit()
    return raw


def clear_session():
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        AdminSession.query.filter_by(token_hash=token_hash(raw)).delete()
        db.session.commit()


def attach_session_cookie(response, raw_token):
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=bool(current_app.config.get('SESSION_COOKIE_SECURE')),
        samesite='Lax',
        path='/',
    )
    return response


def delete_session_cookie(response):
    response.delete_cookie(
        SESSION_COOKIE,
        path='/',
        secure=bool(current_app.config.get('SESSION_COOKIE_SECURE')),
        samesite='Lax',
        httponly=True,
    )
    return response


def _wants_anonymous_json():
    path = request.path or ''
    if path.startswith('/api/') or path.startswith('/export/') or path.endswith('.csv'):
        return True
    best = request.accept_mimetypes.best
    return best == 'application/json'


def install_admin_gate(app):
    @app.before_request
    def require_admin_session():
        path = request.path or '/'
        if path == '/healthz':
            return None
        if is_blocked_path(path):
            return Response('Feature disabled for private deployment', status=404)
        if not admin_configured():
            return Response('Admin authentication not configured', status=503)
        if path == '/login' or path.startswith('/static/'):
            return None
        if load_session() is not None:
            return None
        if _wants_anonymous_json():
            return Response('Administrator authentication required', status=401)
        target = path
        if request.query_string:
            target = path + '?' + request.query_string.decode('utf-8', 'ignore')
        return redirect('/login?next=' + quote(safe_next(target), safe=''))
