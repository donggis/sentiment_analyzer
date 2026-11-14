"""
Unit tests for preload and job management API endpoints.
Tests the PRO dashboard features including preload, job status, and job management.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timedelta
from flask_login import login_user
from app.models import db, User, AnalysisJob, Video, Channel
from app import cache
from conftest import login_admin


class TestPreloadAPI:
    """Test suite for preload API endpoints."""

    def test_preload_comments_requires_auth(self, client):
        """Test that preload endpoint requires authentication."""
        response = client.post('/api/preload/comments/test_video_id')
        assert response.status_code == 401

    def test_preload_comments_requires_pro(self, client, test_user, app):
        """Test that preload endpoint requires PRO subscription."""
        with app.app_context():
            # Make user non-PRO
            test_user.is_subscribed = False
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.post('/api/preload/comments/test_video_id')
                assert response.status_code == 402
                data = json.loads(response.data)
                assert not data['success']
                assert 'Subscription required' in data['error']

    def test_preload_comments_success(self, client, test_user, app):
        """Test successful preload job creation."""
        video_id = 'abc123'
        
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                with patch('app.cache') as mock_cache:
                    mock_cache.enabled = True
                    mock_cache.redis_client = MagicMock()
                    mock_cache.redis_client.lpush = MagicMock()
                    
                response = client.post(f'/api/preload/comments/{video_id}',
                                     json={'target_comments': 5000})
                
                assert response.status_code == 200
                data = json.loads(response.data)
                assert data['success']
                assert 'job_id' in data
                
                # Verify job was created in database
                job = AnalysisJob.query.filter_by(video_id=video_id).first()
                assert job is not None
                assert job.status == 'queued'
                # Preload endpoint caps at 500 comments
                assert job.comment_count_requested == 500

    def test_preload_prevents_duplicate_jobs(self, client, test_user, app):
        """Test that duplicate preload jobs are prevented."""
        video_id = 'abc123'
        
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            # Create existing job
            existing_job = AnalysisJob(
                user_id=test_user.id,
                video_id=video_id,
                video_url=f'https://youtube.com/watch?v={video_id}',
                status='processing',
                comment_count_requested=1000
            )
            db.session.add(existing_job)
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.post(f'/api/preload/comments/{video_id}',
                                     json={'target_comments': 5000})
                
                assert response.status_code == 409
                data = json.loads(response.data)
                assert not data['success']
                assert 'already in progress' in data['error']
                assert data['job_id'] == existing_job.job_id

    def test_preload_with_invalid_target_comments(self, client, test_user, app):
        """Test preload with invalid target_comments parameter."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.post('/api/preload/comments/abc123',
                                     json={'target_comments': 'invalid'})
                
                assert response.status_code == 400
                data = json.loads(response.data)
                assert not data['success']
                assert 'must be an integer' in data['error']

    def test_preload_caps_at_500_comments(self, client, test_user, app):
        """Test that preload caps at 500 comments even if more requested."""
        video_id = 'xyz789'
        
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                with patch('app.cache') as mock_cache:
                    mock_cache.enabled = True
                    mock_cache.redis_client = MagicMock()
                    mock_cache.redis_client.lpush = MagicMock()
                    
                    response = client.post(f'/api/preload/comments/{video_id}',
                                         json={'target_comments': 15000})
                    
                    assert response.status_code == 200
                    data = json.loads(response.data)
                    assert data['success']
                    
                    # Verify cap was applied - preload endpoint caps at 500
                    job = AnalysisJob.query.filter_by(video_id=video_id).first()
                    assert job.comment_count_requested == 500


class TestJobsStatusAPI:
    """Test suite for jobs status API endpoint."""

    def test_jobs_status_requires_auth(self, client):
        """Test that jobs status endpoint requires authentication."""
        response = client.get('/api/jobs/status')
        assert response.status_code == 401

    def test_jobs_status_requires_pro(self, client, test_user, app):
        """Test that jobs status endpoint requires PRO subscription."""
        with app.app_context():
            # Make user non-PRO
            test_user.is_subscribed = False
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.get('/api/jobs/status')
                assert response.status_code == 402

    def test_jobs_status_returns_user_jobs(self, client, test_user, app):
        """Test that jobs status returns jobs for authenticated user."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            # Create test jobs
            job1 = AnalysisJob(
                user_id=test_user.id,
                video_id='video1',
                video_url='https://youtube.com/watch?v=video1',
                status='queued',
                comment_count_requested=1000,
                progress=0
            )
            job2 = AnalysisJob(
                user_id=test_user.id,
                video_id='video2',
                video_url='https://youtube.com/watch?v=video2',
                status='processing',
                comment_count_requested=5000,
                progress=50
            )
            job3 = AnalysisJob(
                user_id=2,  # Different user
                video_id='video3',
                video_url='https://youtube.com/watch?v=video3',
                status='completed',
                comment_count_requested=2000
            )
            db.session.add_all([job1, job2, job3])
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.get('/api/jobs/status')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success']
            assert 'jobs' in data
            assert len(data['jobs']) == 2  # Only user's jobs
            
            # Verify job details
            jobs = data['jobs']
            assert jobs[0]['video_id'] in ['video1', 'video2']
            assert jobs[1]['video_id'] in ['video1', 'video2']
            
            # Check job type classification
            # API logic: jobs with count <= 500 are 'preload', others are 'analysis'
            for job in jobs:
                if job['comment_count_requested'] <= 500:
                    assert job['job_type'] == 'preload'
                else:
                    assert job['job_type'] == 'analysis'

    def test_jobs_status_includes_video_metadata(self, client, test_user, app):
        """Test that jobs status includes video metadata when available."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            # Create channel and video
            channel = Channel(
                yt_channel_id='channel1',
                title='Test Channel',
                handle='@testchannel'
            )
            db.session.add(channel)
            db.session.commit()
            
            video = Video(
                yt_video_id='video1',
                channel_id=channel.id,
                title='Test Video',
                views=10000,
                comments=500,
                published_at=datetime.utcnow() - timedelta(days=7)
            )
            db.session.add(video)
            
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='video1',
                video_url='https://youtube.com/watch?v=video1',
                video_title='Test Video',
                status='completed',
                comment_count_requested=3000
            )
            db.session.add(job)
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.get('/api/jobs/status')
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['success']
            
            job_data = data['jobs'][0]
            assert job_data['video_id'] == 'video1'
            assert job_data['video_title'] == 'Test Video'
            assert 'video_metadata' in job_data
            
            metadata = job_data['video_metadata']
            assert metadata['title'] == 'Test Video'
            assert metadata['views'] == 10000
            assert metadata['comments'] == 500
            assert 'published_at' in metadata


class TestJobCancellationAPI:
    """Test suite for job cancellation API endpoint."""

    def test_cancel_job_requires_auth(self, client):
        """Test that cancel job endpoint requires authentication."""
        response = client.post('/api/jobs/cancel/test_job_id')
        assert response.status_code in [302, 401]

    def test_cancel_job_requires_pro(self, client, test_user, app):
        """Test that cancel job endpoint requires PRO subscription."""
        with app.app_context():
            # Make user non-PRO
            test_user.is_subscribed = False
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.post('/api/jobs/cancel/test_job_id')
                assert response.status_code == 402

    @patch('app.cache.cache.redis_client')
    def test_cancel_job_success(self, mock_redis, client, test_user, app):
        """Test successful job cancellation."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            job_id = 'job_123'
            mock_redis.lrange.return_value = [job_id]
            mock_redis.srem = MagicMock()
            mock_redis.setex = MagicMock()
            
            with patch('app.cache.cache.enabled', True):
              with patch('app.cache.cache.get') as mock_get:
                mock_get.return_value = {
                    'status': 'running',
                    'progress': 50,
                    'video_id': 'video1'
                }
                
                with patch('app.cache.cache.set') as mock_set:
                    # Login the user
                    with client:
                        login_admin(client)
                        with client.session_transaction() as sess:
                            sess['_user_id'] = str(test_user.id)
                            sess['_fresh'] = True
                        
                        response = client.post(f'/api/jobs/cancel/{job_id}')
                
                        assert response.status_code == 200
                        data = json.loads(response.data)
                        assert data['success']
                        assert 'cancellation requested' in data['message']
                        
                        # Verify status was updated
                        mock_set.assert_called_with('preload_status', job_id, ANY, ttl_hours=6)
                        updated_status = mock_set.call_args[0][2]
                        assert updated_status['status'] == 'cancelled'
                        assert 'cancelled_at' in updated_status

    @patch('app.cache.cache.redis_client')
    def test_cancel_job_not_found(self, mock_redis, client, test_user, app):
        """Test cancelling a job that doesn't exist."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            mock_redis.lrange.return_value = []
            
            with patch('app.cache.cache.enabled', True):
              # Login the user
              with client:
                  login_admin(client)
                  with client.session_transaction() as sess:
                      sess['_user_id'] = str(test_user.id)
                      sess['_fresh'] = True
                  
                  response = client.post('/api/jobs/cancel/nonexistent_job')
          
                  assert response.status_code == 404
                  data = json.loads(response.data)
                  assert not data['success']
                  assert 'not found' in data['error']

    @patch('app.cache.cache.redis_client')
    def test_cancel_completed_job_fails(self, mock_redis, client, test_user, app):
        """Test that completed jobs cannot be cancelled."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            job_id = 'job_123'
            mock_redis.lrange.return_value = [job_id]
            
            with patch('app.cache.cache.enabled', True):
              with patch('app.cache.cache.get') as mock_get:
                mock_get.return_value = {
                    'status': 'completed',
                    'progress': 100,
                    'video_id': 'video1'
                }
                
                # Login the user
                with client:
                    login_admin(client)
                    with client.session_transaction() as sess:
                        sess['_user_id'] = str(test_user.id)
                        sess['_fresh'] = True
                    
                    response = client.post(f'/api/jobs/cancel/{job_id}')
            
                    assert response.status_code == 400
                    data = json.loads(response.data)
                    assert not data['success']
                    assert 'cannot be cancelled' in data['error']


class TestClearOldJobsAPI:
    """Test suite for clear old jobs API endpoint."""

    def test_clear_old_jobs_requires_auth(self, client):
        """Test that clear old jobs endpoint requires authentication."""
        response = client.post('/api/jobs/clear-old')
        assert response.status_code in [302, 401]

    @patch('app.cache.cache.redis_client')
    def test_clear_old_jobs_success(self, mock_redis, client, test_user, app):
        """Test successful clearing of old jobs."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            # Setup mock data
            job_ids = ['job_1', 'job_2', 'job_3', 'job_4']
            mock_redis.lrange.return_value = job_ids
            mock_redis.delete = MagicMock()
            mock_redis.rpush = MagicMock()
            
            with patch('app.cache.cache.enabled', True):
              with patch('app.cache.cache.get') as mock_get:
                # Mock job statuses - mix of completed and active
                def get_status(prefix, job_id):
                    statuses = {
                        'job_1': {'status': 'completed'},
                        'job_2': {'status': 'failed'},
                        'job_3': {'status': 'running'},
                        'job_4': {'status': 'cancelled'}
                    }
                    return statuses.get(job_id)
                
                mock_get.side_effect = get_status
                
                with patch('app.cache.cache.delete') as mock_delete:
                    # Login the user
                    with client:
                        login_admin(client)
                        with client.session_transaction() as sess:
                            sess['_user_id'] = str(test_user.id)
                            sess['_fresh'] = True
                        
                        response = client.post('/api/jobs/clear-old')
                
                        assert response.status_code == 200
                        data = json.loads(response.data)
                        assert data['success']
                        assert data['cleared'] == 3  # job_1, job_2, job_4
                        assert data['remaining'] == 1  # job_3
                        
                        # Verify completed jobs were deleted
                        assert mock_delete.call_count == 3

    @patch('app.cache.cache.enabled', False)
    def test_clear_old_jobs_cache_disabled(self, client, test_user, app):
        """Test clear old jobs when cache is disabled."""
        with app.app_context():
            # Make user PRO
            test_user.is_subscribed = True
            db.session.commit()
            
            # Login the user
            with client:
                login_admin(client)
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(test_user.id)
                    sess['_fresh'] = True
                
                response = client.post('/api/jobs/clear-old')
                
                assert response.status_code == 500
                data = json.loads(response.data)
                assert not data['success']
                assert 'Cache disabled' in data['error']
