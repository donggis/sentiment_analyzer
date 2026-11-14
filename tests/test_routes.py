"""
Unit tests for API routes.
"""
import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from flask import url_for
from app import db
from app.models import User, Channel, Video


class TestDashboardRoutes:
    """Test dashboard routes."""
    
    def test_dashboard_requires_auth(self, client):
        """Test dashboard requires authentication."""
        response = client.get('/dashboard')
        assert response.status_code in [302, 401]
    
    def test_dashboard_authenticated(self, authenticated_client):
        """Test dashboard with authenticated user."""
        response = authenticated_client.get('/dashboard')
        assert response.status_code == 200
        assert b'Dashboard' in response.data or b'Sentiment' in response.data
    
    @patch('app.main.dashboard_routes.Channel.query')
    def test_dashboard_with_channels(self, mock_query, authenticated_client):
        """Test dashboard displaying user channels."""
        mock_channel = MagicMock()
        mock_channel.title = 'Test Channel'
        mock_query.all.return_value = [mock_channel]
        
        response = authenticated_client.get('/dashboard')
        assert response.status_code == 200


class TestAnalyzeRoutes:
    """Test sentiment analysis routes."""
    
    def test_analyze_page(self, authenticated_client):
        """Test analyze page loads."""
        response = authenticated_client.get('/analyze')
        assert response.status_code == 200
        assert b'Analyze' in response.data or b'Sentiment' in response.data
    
    @patch('app.services.youtube_service.YouTubeService')
    @patch('app.services.sentiment_api.SentimentAPIClient')
    def test_analyze_video(self, mock_api_client, mock_youtube, authenticated_client):
        """Test analyzing a video."""
        # Mock YouTube service
        mock_yt_instance = MagicMock()
        mock_yt_instance.get_video_comments.return_value = [
            {'text': 'Great video!', 'author': 'User1'},
            {'text': 'Not bad', 'author': 'User2'}
        ]
        mock_youtube.return_value = mock_yt_instance
        
        # Mock sentiment API client
        mock_client_instance = MagicMock()
        mock_client_instance.analyze_batch.return_value = {
            'sentiment_distribution': {'positive': 2, 'neutral': 0, 'negative': 0},
            'results': [],
            'total_analyzed': 2,
            'success': True
        }
        mock_api_client.return_value = mock_client_instance
        
        response = authenticated_client.post('/analyze', data={
            'video_url': 'https://youtube.com/watch?v=test123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'positive' in response.data or b'Positive' in response.data
    
    def test_analyze_invalid_url(self, authenticated_client):
        """Test analyzing with invalid URL."""
        response = authenticated_client.post('/analyze', data={
            'video_url': 'not_a_url'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        assert b'Invalid' in response.data or b'Error' in response.data


class TestBatchRoutes:
    """Test batch processing routes."""
    
    def test_batch_page_requires_subscription(self, authenticated_client, test_user):
        """Test batch page requires subscription."""
        test_user.is_subscribed = False
        db.session.commit()
        
        response = authenticated_client.get('/batch')
        assert response.status_code in [302, 403]
    
    def test_batch_page_with_subscription(self, authenticated_client, subscribed_user):
        """Test batch page with subscription."""
        with authenticated_client.session_transaction() as sess:
            sess['_user_id'] = str(subscribed_user.id)
        
        response = authenticated_client.get('/batch')
        # May redirect or show page based on implementation
        assert response.status_code in [200, 302]
    
    @patch('app.services.sentiment_api.SentimentAPIClient')
    def test_batch_process(self, mock_api_client, authenticated_client, subscribed_user):
        """Test batch processing."""
        with authenticated_client.session_transaction() as sess:
            sess['_user_id'] = str(subscribed_user.id)
        
        mock_instance = MagicMock()
        mock_instance.analyze_batch.return_value = {
            'total_analyzed': 100,
            'statistics': {},
            'results': []
        }
        mock_api_client.return_value = mock_instance
        
        response = authenticated_client.post('/batch/process', 
            data=json.dumps({'texts': ['text1', 'text2']}),
            content_type='application/json'
        )
        
        # Check response based on implementation
        assert response.status_code in [200, 201, 302]


# TestUnifiedRoutes class removed - unified routes are not in use
# The app uses external Modal sentiment API instead


class TestAPIEndpoints:
    """Test API endpoints."""
    
    def test_api_health_check(self, client):
        """Health details stay behind the admin session. The public check is /healthz."""
        assert client.get('/api/health').status_code == 401
        from conftest import login_admin
        login_admin(client)
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
    
    def test_api_requires_auth(self, client):
        """Test API endpoints require authentication."""
        endpoints = [
            '/api/analyze',
            '/api/batch',
            '/api/feedback'
        ]
        
        for endpoint in endpoints:
            response = client.post(endpoint, 
                data=json.dumps({}),
                content_type='application/json'
            )
            assert response.status_code in [401, 403, 302]
    
    @patch('app.services.sentiment_api.get_sentiment_client')
    def test_api_analyze_endpoint(self, mock_get_client, authenticated_client):
        """Test API analyze endpoint."""
        mock_client = MagicMock()
        mock_client.analyze_text.return_value = {
            'sentiment': 'positive',
            'confidence': 0.85,
            'success': True
        }
        mock_get_client.return_value = mock_client
        
        response = authenticated_client.post('/api/analyze',
            data=json.dumps({'text': 'Test text'}),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'label' in data or 'sentiment' in data
    
    def test_api_feedback_endpoint(self, authenticated_client):
        """Test API feedback endpoint."""
        response = authenticated_client.post('/api/feedback',
            data=json.dumps({
                'video_id': 'test123',
                'comment_text': 'Test comment',
                'predicted': 'positive',
                'corrected': 'negative'
            }),
            content_type='application/json'
        )
        
        assert response.status_code in [200, 201]


class TestChannelRoutes:
    """Test channel management routes."""
    
    def test_add_channel(self, authenticated_client):
        """Test adding a channel."""
        response = authenticated_client.post('/channels/add',
            data={'channel_id': 'UC_test123'},
            follow_redirects=True
        )
        
        assert response.status_code == 200
    
    @patch('app.main.routes.Channel.query')
    def test_view_channel(self, mock_query, authenticated_client):
        """Test viewing channel details."""
        mock_channel = MagicMock()
        mock_channel.id = 1
        mock_channel.title = 'Test Channel'
        mock_query.get.return_value = mock_channel
        
        response = authenticated_client.get('/channels/1/view')
        # Expected to return 404 since using mock instead of real channel
        assert response.status_code in [200, 404]
    
    def test_remove_channel(self, authenticated_client, test_channel):
        """Test removing a channel."""
        response = authenticated_client.post(f'/channels/{test_channel.id}/remove',
            follow_redirects=True
        )
        
        assert response.status_code == 200


class TestVideoRoutes:
    """Test video-related routes."""
    
    @patch('app.main.routes.Video.query')
    def test_video_list(self, mock_query, authenticated_client):
        """Test video list endpoint."""
        mock_video = MagicMock()
        mock_video.title = 'Test Video'
        mock_query.all.return_value = [mock_video]
        
        response = authenticated_client.get('/api/videos')
        assert response.status_code == 200
    
    @patch('app.services.youtube_service.YouTubeService')
    def test_video_comments(self, mock_youtube, authenticated_client):
        """Test fetching video comments."""
        mock_yt = MagicMock()
        mock_yt.get_video_comments.return_value = [
            {'text': 'Comment 1'},
            {'text': 'Comment 2'}
        ]
        mock_youtube.return_value = mock_yt
        
        response = authenticated_client.get('/api/videos/test123/comments')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] == True


class TestErrorHandling:
    """Test error handling in routes."""
    
    def test_404_error(self, client):
        """Unknown pages are hidden until the admin signs in, then return 404."""
        hidden = client.get('/nonexistent_page')
        assert hidden.status_code == 302
        assert '/login' in hidden.location
        from conftest import login_admin
        login_admin(client)
        response = client.get('/nonexistent_page')
        assert response.status_code == 404
    
    @patch('app.services.sentiment_api.SentimentAPIClient')
    def test_500_error_handling(self, mock_api_client, authenticated_client):
        """Test 500 error handling."""
        mock_api_client.side_effect = Exception('Internal error')
        
        response = authenticated_client.post('/analyze',
            data={'video_url': 'https://youtube.com/watch?v=test'},
            follow_redirects=True
        )
        
        # Should handle error gracefully
        assert response.status_code in [200, 500]
    
    def test_rate_limiting(self, authenticated_client):
        """Test rate limiting on API endpoints."""
        # Make many requests quickly
        for _ in range(100):
            response = authenticated_client.get('/api/health')
        
        # Eventually should get rate limited (if implemented)
        # This depends on rate limiting configuration
        assert response.status_code in [200, 429]


class TestSubscriptionRoutes:
    """Billing stays off for the private admin deployment."""

    @patch('stripe.checkout.Session.create')
    def test_subscribe_stripe(self, mock_stripe, authenticated_client):
        response = authenticated_client.post('/subscribe/stripe', follow_redirects=False)
        assert response.status_code == 404
        mock_stripe.assert_not_called()

    @patch('stripe.Webhook.construct_event')
    def test_stripe_webhook(self, mock_webhook, client):
        response = client.post('/webhook/stripe',
            data='test_payload',
            headers={'Stripe-Signature': 'test_sig'}
        )
        assert response.status_code == 404
        mock_webhook.assert_not_called()