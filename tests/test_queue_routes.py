"""
Comprehensive tests for analysis queue routes and functionality.
"""
import pytest
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, ANY
from app import db
from app.models import User, AnalysisJob


class TestQueueAnalysisRoute:
    """Test the queue analysis endpoint."""
    
    def test_queue_analysis_success(self, authenticated_client, test_user):
        """Test successful job queuing."""
        with authenticated_client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        response = authenticated_client.post('/api/analyze/queue', 
            data=json.dumps({
                'video_id': 'test123',
                'comment_count': 100
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'job_id' in data
        
        # Check job was created in database and is queued
        job = AnalysisJob.query.filter_by(video_id='test123').first()
        assert job is not None
        assert job.comment_count_requested == 100
        assert job.status == 'queued'
    
    def test_queue_analysis_missing_video_id(self, authenticated_client):
        """Test queuing without video_id."""
        response = authenticated_client.post('/api/analyze/queue',
            data=json.dumps({
                'comment_count': 100
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'valid video id' in data['error'].lower()
    
    def test_queue_analysis_comment_count_capped(self, authenticated_client, test_user):
        """Test queuing caps comment_count at 10000 for Pro users."""
        with authenticated_client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        response = authenticated_client.post('/api/analyze/queue',
            data=json.dumps({
                'video_id': 'test123',
                'comment_count': 200000
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 200
        job = AnalysisJob.query.filter_by(video_id='test123').first()
        assert job is not None
        assert job.comment_count_requested == 10000
    
    @patch('app.main.analysis_queue_routes.db.session.commit', side_effect=Exception('DB error'))
    def test_queue_analysis_db_error(self, mock_commit, authenticated_client, test_user):
        """Test handling of database errors on queue."""
        with authenticated_client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        response = authenticated_client.post('/api/analyze/queue',
            data=json.dumps({
                'video_id': 'test123',
                'comment_count': 100
            }),
            content_type='application/json'
        )
        
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'db error' in data['error'].lower()
    
    def test_queue_duplicate_job(self, authenticated_client, test_user):
        """Test handling duplicate job requests."""
        with authenticated_client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
        
        # Create existing job in processing state
        existing_job = AnalysisJob(
            user_id=test_user.id,
            video_id='test123',
            comment_count_requested=100,
            status='processing'
        )
        db.session.add(existing_job)
        db.session.commit()
        
        # Try to queue another job for same video
        response = authenticated_client.post('/api/analyze/queue',
            data=json.dumps({
                'video_id': 'test123',
                'comment_count': 100
            }),
            content_type='application/json'
        )
        
        # Should return 409 conflict
        assert response.status_code == 409
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'already in progress' in data['error'].lower()
        assert 'job_id' in data  # Should return existing job ID


class TestJobStatusRoute:
    """Test job status endpoint."""
    
    def test_get_job_status_success(self, app, authenticated_client, test_user):
        """Test getting job status."""
        with app.app_context():
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100,
                status='processing',
                progress=50
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id
        
        response = authenticated_client.get(f'/api/analyze/job/{job_id}')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['job']['status'] == 'processing'
        assert data['job']['progress'] == 50
        assert data['job']['video_id'] == 'test123'
    
    def test_get_job_status_not_found(self, authenticated_client):
        """Test getting status for non-existent job."""
        response = authenticated_client.get('/api/analyze/job/nonexistent_job')
        
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'not found' in data['error'].lower()
    
    def test_get_job_status_unauthorized(self, app, client, test_user):
        """Test getting status for another user's job."""
        with app.app_context():
            # Create job for test_user
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100
            )
            db.session.add(job)
            
            # Create another user
            other_user = User(
                name='Other User',
                email='other@test.com'
            )
            other_user.set_password('password123')
            db.session.add(other_user)
            db.session.commit()
            job_id = job.job_id
            other_id = other_user.id

        from conftest import login_admin
        login_admin(client)
        with client.session_transaction() as sess:
            sess['_user_id'] = str(other_id)
            sess['_fresh'] = True

        response = client.get(f'/api/analyze/job/{job_id}')
        assert response.status_code == 404
        assert response.get_json()['success'] is False


class TestJobResultsRoute:
    """Test job results endpoint."""
    
    def test_get_job_results_success(self, app, authenticated_client, test_user):
        """Test getting completed job results."""
        with app.app_context():
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100,
                status='completed',
                progress=100,
                results={
                    'sentiment': 'positive',
                    'confidence': 0.85,
                    'statistics': {
                        'positive': 60,
                        'negative': 20,
                        'neutral': 20
                    }
                }
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id
        
        response = authenticated_client.get(f'/api/analyze/job/{job_id}/results')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'results' in data
        assert data['results']['sentiment'] == 'positive'
    
    def test_get_job_results_not_ready(self, app, authenticated_client, test_user):
        """Test getting results for incomplete job."""
        with app.app_context():
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100,
                status='processing',
                progress=50
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id
        
        response = authenticated_client.get(f'/api/analyze/job/{job_id}/results')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'not completed' in data['error'].lower()
    
    def test_get_job_results_failed(self, app, authenticated_client, test_user):
        """Test getting results for failed job."""
        with app.app_context():
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100,
                status='failed',
                error_message='API rate limit exceeded'
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id
        
        response = authenticated_client.get(f'/api/analyze/job/{job_id}/results')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'not completed' in data['error'].lower()


class TestCancelJobRoute:
    """Test job cancellation endpoint."""
    
    def test_cancel_job_success(self, app, authenticated_client, test_user):
        """Test cancelling a queued job."""
        with app.app_context():
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100,
                status='queued'
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id
        
        response = authenticated_client.delete(f'/api/analyze/job/{job_id}')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        
        # Check job was cancelled
        with app.app_context():
            job = AnalysisJob.query.filter_by(job_id=job_id).first()
            assert job.status == 'cancelled'
    
    def test_cancel_processing_job(self, app, authenticated_client, test_user):
        """Test cancelling a processing job."""
        with app.app_context():
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100,
                status='processing',
                progress=50
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id
        
        response = authenticated_client.delete(f'/api/analyze/job/{job_id}')
        
        # Should be able to cancel processing job
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
    
    def test_cancel_completed_job(self, app, authenticated_client, test_user):
        """Test cancelling a completed job (should fail)."""
        with app.app_context():
            job = AnalysisJob(
                user_id=test_user.id,
                video_id='test123',
                comment_count_requested=100,
                status='completed'
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id
        
        response = authenticated_client.delete(f'/api/analyze/job/{job_id}')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
        assert 'cannot cancel' in data['error'].lower()


class TestUserJobsRoute:
    """Test user jobs listing endpoint."""
    
    def test_get_user_jobs(self, app, authenticated_client, test_user):
        """Test getting user's job history."""
        with app.app_context():
            # Create multiple jobs
            jobs = []
            for i, status in enumerate(['queued', 'processing', 'completed', 'failed']):
                job = AnalysisJob(
                    user_id=test_user.id,
                    video_id=f'video_{i}',
                    comment_count_requested=100,
                    status=status
                )
                jobs.append(job)
            db.session.add_all(jobs)
            db.session.commit()
        
        response = authenticated_client.get('/api/user/analysis-jobs')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'jobs' in data
        assert len(data['jobs']) == 4
        
        # Check statuses present
        statuses = [job['status'] for job in data['jobs']]
        assert set(statuses) == {'queued', 'processing', 'completed', 'failed'}
    
    def test_get_user_jobs_filtered(self, app, authenticated_client, test_user):
        """Test getting filtered job history."""
        with app.app_context():
            # Create jobs with different statuses
            for i in range(3):
                job = AnalysisJob(
                    user_id=test_user.id,
                    video_id=f'video_completed_{i}',
                    comment_count_requested=100,
                    status='completed'
                )
                db.session.add(job)
            
            for i in range(2):
                job = AnalysisJob(
                    user_id=test_user.id,
                    video_id=f'video_queued_{i}',
                    comment_count_requested=100,
                    status='queued'
                )
                db.session.add(job)
            
            db.session.commit()
        
        # Get only completed jobs
        response = authenticated_client.get('/api/user/analysis-jobs?status=completed')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['jobs']) == 3
        assert all(job['status'] == 'completed' for job in data['jobs'])
    
    def test_get_user_jobs_pagination(self, app, authenticated_client, test_user):
        """Test job history pagination."""
        with app.app_context():
            # Create many jobs
            for i in range(25):
                job = AnalysisJob(
                    user_id=test_user.id,
                    video_id=f'video_{i}',
                    comment_count_requested=100,
                    status='completed'
                )
                db.session.add(job)
            db.session.commit()
        
        # Get first page
        response = authenticated_client.get('/api/user/analysis-jobs?limit=10&offset=0')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['jobs']) == 10
        assert data['total'] == 25
        assert data['limit'] == 10
        assert data['offset'] == 0
        
        # Get last chunk
        response = authenticated_client.get('/api/user/analysis-jobs?limit=10&offset=20')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert len(data['jobs']) == 5
