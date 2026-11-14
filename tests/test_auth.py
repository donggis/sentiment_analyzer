"""
Unit tests for authentication functionality.
"""
import pytest
from flask import url_for
from unittest.mock import patch, MagicMock
from app import db
from app.models import User
from app.auth.forms import LoginForm, RegisterForm, PasswordResetRequestForm, PasswordResetForm


class TestAuthForms:
    """Test authentication forms."""
    
    def test_login_form_validation(self, app):
        """Test login form validation."""
        with app.test_request_context():
            # Valid form
            form = LoginForm(data={
                'email': 'test@example.com',
                'password': 'password123',
                'remember_me': True
            })
            assert form.validate() is True
            
            # Invalid email
            form = LoginForm(data={
                'email': 'invalid-email',
                'password': 'password123'
            })
            assert form.validate() is False
            
            # Missing password
            form = LoginForm(data={
                'email': 'test@example.com'
            })
            assert form.validate() is False
    
    def test_registration_form_validation(self, app):
        """Test registration form validation."""
        with app.test_request_context():
            # Valid form
            form = RegisterForm(data={
                'name': 'John Doe',
                'email': 'john@example.com',
                'password': 'SecurePass123!',
                'confirm_password': 'SecurePass123!'
            })
            assert form.validate() is True
            
            # Password mismatch
            form = RegisterForm(data={
                'name': 'John Doe',
                'email': 'john@example.com',
                'password': 'SecurePass123!',
                'confirm_password': 'DifferentPass123!'
            })
            assert form.validate() is False
            
            # Invalid email
            form = RegisterForm(data={
                'name': 'John Doe',
                'email': 'not-an-email',
                'password': 'SecurePass123!',
                'confirm_password': 'SecurePass123!'
            })
            assert form.validate() is False
    
    def test_reset_password_request_form(self, app):
        """Test password reset request form."""
        with app.test_request_context():
            # Valid form
            form = PasswordResetRequestForm(data={
                'email': 'test@example.com'
            })
            assert form.validate() is True
            
            # Invalid email
            form = PasswordResetRequestForm(data={
                'email': 'invalid-email'
            })
            assert form.validate() is False
    
    def test_reset_password_form(self, app):
        """Test password reset form."""
        with app.test_request_context():
            # Valid form
            form = PasswordResetForm(data={
                'password': 'NewSecurePass123!',
                'confirm_password': 'NewSecurePass123!'
            })
            assert form.validate() is True
            
            # Password mismatch
            form = PasswordResetForm(data={
                'password': 'NewSecurePass123!',
                'confirm_password': 'DifferentPass123!'
            })
            assert form.validate() is False


class TestAuthRoutes:
    """Legacy member routes stay disabled. The admin uses /login."""

    def test_login_get(self, client):
        response = client.get('/auth/login')
        assert response.status_code == 404

    def test_login_post_success(self, client, test_user):
        response = client.post('/auth/login', data={
            'email': test_user.email,
            'password': 'test_password'
        })
        assert response.status_code == 404

    def test_login_post_invalid_credentials(self, client, test_user):
        response = client.post('/auth/login', data={
            'email': test_user.email,
            'password': 'wrong_password'
        })
        assert response.status_code == 404

    def test_login_post_nonexistent_user(self, client):
        response = client.post('/auth/login', data={
            'email': 'nonexistent@example.com',
            'password': 'password123'
        })
        assert response.status_code == 404

    def test_logout(self, authenticated_client):
        response = authenticated_client.post('/logout', follow_redirects=False)
        assert response.status_code == 302
        response = authenticated_client.get('/dashboard')
        assert response.status_code in [302, 401]

    def test_register_get(self, client):
        response = client.get('/auth/register')
        assert response.status_code == 404

    def test_register_post_success(self, client, mock_email):
        response = client.post('/auth/register', data={
            'name': 'New User',
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!'
        })
        assert response.status_code == 404
        user = User.query.filter_by(email='newuser@example.com').first()
        assert user is None

    def test_register_post_duplicate_email(self, client, test_user):
        response = client.post('/auth/register', data={
            'name': 'Another User',
            'email': test_user.email,
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!'
        })
        assert response.status_code == 404

    def test_reset_password_request_get(self, client):
        assert client.get('/auth/reset_password_request').status_code == 404

    @patch('app.email.send_email')
    def test_reset_password_request_post(self, mock_send_email, client, test_user):
        mock_send_email.return_value = True
        response = client.post('/auth/reset_password_request', data={'email': test_user.email})
        assert response.status_code == 404
        mock_send_email.assert_not_called()

    def test_reset_password_request_nonexistent_email(self, client):
        response = client.post('/auth/reset_password_request', data={'email': 'nonexistent@example.com'})
        assert response.status_code == 404

    def test_reset_password_get_valid_token(self, client, test_user):
        token = test_user.get_reset_password_token()
        assert client.get(f'/auth/reset_password/{token}').status_code == 404

    def test_reset_password_get_invalid_token(self, client):
        assert client.get('/auth/reset_password/invalid_token_123').status_code == 404

    def test_reset_password_post_success(self, client, test_user):
        token = test_user.get_reset_password_token()
        response = client.post(f'/auth/reset_password/{token}', data={
            'password': 'NewSecurePass123!',
            'confirm_password': 'NewSecurePass123!'
        })
        assert response.status_code == 404

    def test_reset_password_post_expired_token(self, client, test_user):
        from datetime import datetime, timedelta, timezone
        token = test_user.get_reset_password_token()
        test_user.reset_token_expires = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        db.session.commit()
        response = client.post(f'/auth/reset_password/{token}', data={
            'password': 'NewSecurePass123!',
            'confirm_password': 'NewSecurePass123!'
        })
        assert response.status_code == 404


class TestAuthenticationFlow:
    """Admin login replaces the old member and OAuth flows."""

    def test_registration_to_login_flow(self, client, mock_email):
        response = client.post('/auth/register', data={
            'name': 'Flow User',
            'email': 'flow@example.com',
            'password': 'FlowPass123!',
            'confirm_password': 'FlowPass123!'
        })
        assert response.status_code == 404
        response = client.post('/auth/login', data={
            'email': 'flow@example.com',
            'password': 'FlowPass123!'
        })
        assert response.status_code == 404
        response = client.get('/dashboard')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_password_reset_flow(self, client, test_user, mock_email):
        response = client.post('/auth/reset_password_request', data={'email': test_user.email})
        assert response.status_code == 404
        token = test_user.get_reset_password_token()
        response = client.post(f'/auth/reset_password/{token}', data={
            'password': 'ResetPass123!',
            'confirm_password': 'ResetPass123!'
        })
        assert response.status_code == 404

    def test_authenticated_redirect(self, authenticated_client):
        assert authenticated_client.get('/auth/login').status_code == 404
        assert authenticated_client.get('/auth/register').status_code == 404

    def test_remember_me_functionality(self, client, test_user):
        response = client.post('/auth/login', data={
            'email': test_user.email,
            'password': 'test_password',
            'remember_me': True
        })
        assert response.status_code == 404

    def test_login_required_decorator(self, client):
        for route in ['/dashboard', '/analyze', '/batch']:
            response = client.get(route)
            assert response.status_code in [302, 401, 404]
            if response.status_code == 302:
                assert 'login' in response.location

    def test_admin_login_then_library(self, client):
        blocked = client.get('/api/admin/export/comments.csv')
        assert blocked.status_code == 401
        response = client.post('/login', data={
            'username': 'admin',
            'password': 'test-password',
            'next': '/admin',
        })
        assert response.status_code == 302
        assert '/admin' in response.location
        assert client.get('/admin').status_code == 200
        assert client.get('/api/admin/export/comments.csv').status_code == 200

