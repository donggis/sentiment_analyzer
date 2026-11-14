"""No real network requests are permitted by these regression tests."""
import pytest
from unittest.mock import Mock
from app.services.sentiment_api import SentimentAPIClient
from app.email import mail

@pytest.mark.parametrize('method,args', [
    ('make_request', ('/summarize', {'comments': ['private']})),
    ('analyze_text', ('private',)),
    ('analyze_batch', (['private'],)),
])
def test_external_ai_requires_explicit_opt_in(monkeypatch, method, args):
    monkeypatch.delenv('ENABLE_EXTERNAL_AI', raising=False)
    monkeypatch.setenv('SENTIMENT_API_URL', 'https://example.invalid')
    post = Mock(side_effect=AssertionError('Unexpected external request'))
    monkeypatch.setattr('app.services.sentiment_api.requests.post', post)
    result = getattr(SentimentAPIClient(), method)(*args)
    assert result['success'] is False
    assert 'disabled' in result['error']
    post.assert_not_called()

def test_mail_transport_disabled():
    with pytest.raises(RuntimeError, match='disabled'):
        mail.send(Mock())

@pytest.mark.parametrize('path', ['/auth/login', '/auth/google/callback', '/auth/profile'])
def test_legacy_oauth_disabled(client, path):
    assert client.get(path).status_code == 404
