"""
pytest configuration file with fixtures for Flask application testing.
"""
import os
import sys
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch
import redis
import fakeredis

from sqlalchemy.pool import StaticPool

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import User, Channel, Video, UserChannel, SentimentFeedback, AnalysisJob
from app.config import Config
from werkzeug.security import generate_password_hash

TEST_ADMIN_PASSWORD = 'test-password'
TEST_ADMIN_HASH = generate_password_hash(TEST_ADMIN_PASSWORD)


class TestConfig(Config):
    """Test configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {'check_same_thread': False},
        'poolclass': StaticPool,
    }
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = 'test-secret-key'
    MAIL_SUPPRESS_SEND = True
    REDIS_URL = 'redis://localhost:6379/1'
    YOUTUBE_API_KEY = 'test-api-key'
    CACHE_TYPE = 'simple'
    MODAL_ML_BASE_URL = 'http://test-modal-url'
    SKIP_MODEL_PRELOAD = True


@pytest.fixture(scope='function')
def app(monkeypatch):
    """Create application for testing."""
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', TEST_ADMIN_HASH)
    monkeypatch.setenv('YOUTUBE_API_KEY', 'test-api-key')
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    monkeypatch.delenv('ENABLE_EXTERNAL_AI', raising=False)
    application = create_app(TestConfig)

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def login_admin(client, password=TEST_ADMIN_PASSWORD):
    """Open a real admin session. Tests that need the library call this."""
    response = client.post('/login', data={
        'username': 'admin',
        'password': password,
        'next': '/admin',
    })
    assert response.status_code in (302, 303), response.status_code
    return client


@pytest.fixture(scope='function')
def client(app):
    """Create a test client for the app."""
    return app.test_client()


@pytest.fixture(scope='function')
def runner(app):
    """Create a test runner for the app's Click commands."""
    return app.test_cli_runner()


@pytest.fixture(scope='function')
def authenticated_client(client, test_user):
    """Create an authenticated test client."""
    with client:
        login_admin(client)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        yield client


@pytest.fixture(scope='function')
def test_user(app):
    """Create a test user."""
    user = User(
        name='Test User',
        email='test@example.com',
        is_subscribed=True  # Changed to True to fix 402 errors in tests
    )
    user.set_password('test_password')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def subscribed_user(app):
    """Create a subscribed test user."""
    user = User(
        name='Subscribed User',
        email='subscribed@example.com',
        is_subscribed=True,
        provider='stripe',
        customer_id='cus_test123'
    )
    user.set_password('test_password')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture(scope='function')
def auth_client(client, app):
    """Create an authenticated test client with a free user."""
    with app.app_context():
        user = User(
            name='Free User',
            email='free@example.com',
            is_subscribed=False
        )
        user.set_password('test_password')
        db.session.add(user)
        db.session.commit()

        login_admin(client)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
    return client


@pytest.fixture(scope='function')
def pro_client(client, app):
    """Create an authenticated test client with a pro user."""
    with app.app_context():
        user = User(
            name='Pro User',
            email='pro@example.com',
            is_subscribed=True,
            provider='stripe',
            customer_id='cus_test_pro'
        )
        user.set_password('test_password')
        db.session.add(user)
        db.session.commit()

        login_admin(client)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
    return client


@pytest.fixture(scope='function')
def test_channel(app):
    """Create a test channel."""
    channel = Channel(
        yt_channel_id='UC_test_channel',
        title='Test Channel',
        handle='@testchannel',
        uploads_playlist_id='UU_test_playlist',
        video_count=10,
        last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.session.add(channel)
    db.session.commit()
    return channel


@pytest.fixture(scope='function')
def test_video(app, test_channel):
    """Create a test video."""
    video = Video(
        yt_video_id='test_video_123',
        channel_id=test_channel.id,
        title='Test Video',
        published_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        views=1000,
        likes=100,
        comments=50
    )
    db.session.add(video)
    db.session.commit()
    return video


@pytest.fixture(scope='function')
def test_analysis_job(app, test_user):
    """Create a test analysis job."""
    job = AnalysisJob(
        user_id=test_user.id,
        video_id='test_video_123',
        video_title='Test Video',
        video_url='https://youtube.com/watch?v=test_video_123',
        channel_name='Test Channel',
        comment_count_requested=100,
        status='queued'
    )
    db.session.add(job)
    db.session.commit()
    return job


@pytest.fixture(scope='function')
def test_feedback(app, test_user):
    """Create test sentiment feedback."""
    feedback = SentimentFeedback(
        user_id=test_user.id,
        video_id='test_video_123',
        comment_text='This is a great video!',
        comment_author='Test Author',
        predicted_sentiment='positive',
        corrected_sentiment='positive',
        confidence_score=0.95,
        session_id='test_session_123'
    )
    db.session.add(feedback)
    db.session.commit()
    return feedback


@pytest.fixture(scope='function')
def mock_redis():
    """Mock Redis client using fakeredis."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(scope='function')
def mock_youtube_service():
    """Mock YouTube service."""
    mock_service = MagicMock()
    mock_service.get_video_comments.return_value = [
        {
            'text': 'Great video!',
            'author': 'User1',
            'published_at': '2024-01-01T00:00:00Z',
            'likes': 10
        },
        {
            'text': 'Not bad',
            'author': 'User2',
            'published_at': '2024-01-01T01:00:00Z',
            'likes': 5
        }
    ]
    mock_service.get_channel_info.return_value = {
        'channel_id': 'UC_test_channel',
        'title': 'Test Channel',
        'uploads_playlist_id': 'UU_test_playlist'
    }
    return mock_service


@pytest.fixture(scope='function')
def mock_sentiment_analyzer():
    """Mock sentiment analyzer."""
    mock_analyzer = MagicMock()
    mock_analyzer.analyze_sentiment.return_value = {
        'label': 'positive',
        'scores': {
            'negative': 0.1,
            'neutral': 0.2,
            'positive': 0.7
        },
        'confidence': 0.7,
        'model': 'roberta'
    }
    mock_analyzer.analyze_batch.return_value = {
        'overall_sentiment': 'positive',
        'distribution': {'positive': 7, 'neutral': 2, 'negative': 1},
        'distribution_percentage': {'positive': 70.0, 'neutral': 20.0, 'negative': 10.0},
        'average_confidence': 0.75,
        'total_analyzed': 10,
        'individual_results': []
    }
    return mock_analyzer


@pytest.fixture(scope='function')
def mock_ml_model():
    """Mock ML model for testing."""
    mock_model = MagicMock()
    mock_model.predict.return_value = [1]  # positive sentiment
    mock_model.predict_proba.return_value = [[0.1, 0.2, 0.7]]
    return mock_model


@pytest.fixture(scope='function')
def sample_comments():
    """Sample comments for testing."""
    return [
        "This video is amazing!",
        "I don't like this at all",
        "It's okay, nothing special",
        "Absolutely fantastic content!",
        "Terrible waste of time",
        "Pretty good, could be better",
        "Love it! Keep up the great work",
        "This is the worst video ever",
        "Not bad, not great either",
        "Outstanding quality!"
    ]


@pytest.fixture(scope='function')
def mock_stripe():
    """Mock Stripe API."""
    with patch('stripe.Customer') as mock_customer, \
         patch('stripe.Subscription') as mock_subscription, \
         patch('stripe.checkout.Session') as mock_session:

        mock_customer.create.return_value = MagicMock(id='cus_test123')
        mock_subscription.create.return_value = MagicMock(
            id='sub_test123',
            status='active'
        )
        mock_session.create.return_value = MagicMock(
            id='cs_test123',
            url='https://checkout.stripe.com/test'
        )

        yield {
            'customer': mock_customer,
            'subscription': mock_subscription,
            'session': mock_session
        }


@pytest.fixture(scope='function')
def mock_email():
    """Mock email sending."""
    with patch('app.email.send_email') as mock_send:
        mock_send.return_value = True
        yield mock_send


@pytest.fixture(scope='function')
def mock_youtube_api():
    """Mock YouTube API calls."""
    with patch('app.services.youtube.build') as mock:
        yield mock


@pytest.fixture(scope='function')
def mock_modal_client():
    """Mock Modal ML client."""
    with patch('app.services.sentiment.modal_client') as mock:
        mock_instance = Mock()
        mock.return_value = mock_instance
        mock_instance.analyze_sentiment.return_value = {
            'sentiment': 'positive',
            'confidence': 0.85,
            'emotions': {'joy': 0.7, 'anger': 0.1, 'sadness': 0.2}
        }
        yield mock_instance


@pytest.fixture(autouse=True)
def reset_database(app):
    """Reset database before each test."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.session.close()
        db.session.remove()
        db.engine.dispose()
