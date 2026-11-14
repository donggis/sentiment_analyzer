"""
End-to-End tests for enhanced job queue with metadata display
Tests the complete workflow of displaying jobs with titles and metadata across all views
"""

import pytest
import json
import time
pytest.importorskip('playwright.sync_api')
from playwright.sync_api import Page, expect
from unittest.mock import patch, MagicMock

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


@pytest.fixture
def authenticated_pro_user(page: Page):
    """Fixture to provide an authenticated PRO user"""
    # Login as PRO user
    page.goto('http://localhost:8001/login')
    page.fill('input[name="email"]', 'pro@example.com')
    page.fill('input[name="password"]', 'password123')
    page.click('button[type="submit"]')
    
    # Wait for redirect to dashboard
    page.wait_for_url('**/dashboard', timeout=10000)
    
    # Mock PRO status
    page.evaluate("""
        window.isProUser = true;
        window.isAuthenticated = true;
    """)
    
    return page


@pytest.fixture
def mock_jobs_data():
    """Fixture providing test job data with complete metadata"""
    return [
        {
            'job_id': 'job_active_1',
            'status': 'processing',
            'progress': 45,
            'video_id': 'abc123',
            'video_title': 'Amazing Tech Review 2024',
            'job_type': 'preload',
            'comment_count_requested': 500,
            'created_at': '2024-01-15T10:30:00Z',
            'video_metadata': {
                'title': 'Amazing Tech Review 2024',
                'description': 'In-depth review of the latest tech gadgets',
                'duration': 'PT15M30S',
                'views': 1500000,
                'likes': 85000,
                'comments': 12000,
                'channel_title': 'TechReviewer Pro',
                'published_at': '2024-01-10T00:00:00Z',
                'thumbnail': 'https://i.ytimg.com/vi/abc123/maxresdefault.jpg'
            }
        },
        {
            'job_id': 'job_queued_1',
            'status': 'queued',
            'progress': 0,
            'video_id': 'def456',
            'video_title': 'Cooking Tutorial: Italian Pasta',
            'job_type': 'analysis',
            'comment_count_requested': 1000,
            'created_at': '2024-01-15T11:00:00Z',
            'video_metadata': {
                'title': 'Cooking Tutorial: Italian Pasta',
                'duration': 'PT8M45S',
                'views': 500000,
                'likes': 30000,
                'comments': 5000,
                'channel_title': 'Cooking Masters',
                'published_at': '2024-01-12T00:00:00Z',
                'thumbnail': 'https://i.ytimg.com/vi/def456/maxresdefault.jpg'
            }
        },
        {
            'job_id': 'job_completed_1',
            'status': 'completed',
            'progress': 100,
            'video_id': 'ghi789',
            'video_title': 'Travel Vlog: Japan Adventures',
            'job_type': 'preload',
            'comment_count_requested': 500,
            'created_at': '2024-01-14T09:00:00Z',
            'completed_at': '2024-01-14T09:15:00Z',
            'video_metadata': {
                'title': 'Travel Vlog: Japan Adventures',
                'duration': 'PT25M00S',
                'views': 2000000,
                'likes': 150000,
                'comments': 20000,
                'channel_title': 'World Traveler',
                'published_at': '2024-01-08T00:00:00Z',
                'thumbnail': 'https://i.ytimg.com/vi/ghi789/maxresdefault.jpg'
            }
        },
        {
            'job_id': 'job_failed_1',
            'status': 'failed',
            'progress': 0,
            'video_id': 'jkl012',
            'video_title': 'Gaming Stream Highlights',
            'job_type': 'analysis',
            'comment_count_requested': 2000,
            'created_at': '2024-01-13T15:00:00Z',
            'error_message': 'Failed to fetch video data: API rate limit exceeded',
            'video_metadata': {
                'title': 'Gaming Stream Highlights',
                'duration': 'PT2H30M00S',
                'views': 100000,
                'likes': 8000,
                'comments': 3000,
                'channel_title': 'ProGamer123',
                'published_at': '2024-01-05T00:00:00Z'
            }
        }
    ]


class TestEnhancedJobQueue:
    """Test the enhanced job queue with metadata display"""
    
    def test_job_queue_displays_metadata(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test that job queue displays video metadata correctly"""
        page = authenticated_pro_user
        
        # Mock API response
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'jobs': mock_jobs_data
            })
        ))
        
        # Navigate to dashboard
        page.goto('http://localhost:8001/dashboard')
        
        # Wait for job queue to load
        page.wait_for_selector('.job-queue', timeout=10000)
        
        # Verify all job cards are displayed
        job_cards = page.locator('.job-card')
        expect(job_cards).to_have_count(4)
        
        # Verify metadata is displayed for each job
        for job_data in mock_jobs_data:
            # Find the job card
            job_card = page.locator(f'[data-job-id="{job_data["job_id"]}"]')
            expect(job_card).to_be_visible()
            
            # Check title is displayed
            expect(job_card).to_contain_text(job_data['video_title'])
            
            # Check channel name is displayed
            if job_data['video_metadata'].get('channel_title'):
                expect(job_card).to_contain_text(job_data['video_metadata']['channel_title'])
            
            # Check thumbnail is displayed (for jobs with thumbnails)
            if job_data['video_metadata'].get('thumbnail'):
                thumbnail = job_card.locator('img')
                expect(thumbnail).to_have_attribute('src', job_data['video_metadata']['thumbnail'])
    
    def test_active_jobs_view(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test that active view shows only queued, processing, and running jobs"""
        page = authenticated_pro_user
        
        # Setup API mock
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Click on Active tab
        page.click('button:has-text("Active")')
        
        # Wait for filtering
        page.wait_for_timeout(500)
        
        # Should show only active jobs (processing and queued)
        visible_cards = page.locator('.job-card:visible')
        expect(visible_cards).to_have_count(2)
        
        # Verify correct jobs are shown
        expect(page.locator('[data-job-id="job_active_1"]')).to_be_visible()
        expect(page.locator('[data-job-id="job_queued_1"]')).to_be_visible()
        expect(page.locator('[data-job-id="job_completed_1"]')).not_to_be_visible()
        expect(page.locator('[data-job-id="job_failed_1"]')).not_to_be_visible()
    
    def test_completed_jobs_view(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test that completed view shows only completed jobs"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Click on Completed tab
        page.click('button:has-text("Completed")')
        page.wait_for_timeout(500)
        
        # Should show only completed jobs
        visible_cards = page.locator('.job-card:visible')
        expect(visible_cards).to_have_count(1)
        
        expect(page.locator('[data-job-id="job_completed_1"]')).to_be_visible()
        
        # Verify View Analysis button is shown for completed jobs
        completed_card = page.locator('[data-job-id="job_completed_1"]')
        completed_card.click()  # Expand the card
        
        view_button = completed_card.locator('button:has-text("View Analysis")')
        expect(view_button).to_be_visible()
    
    def test_history_view(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test that history view shows completed, failed, and cancelled jobs"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Click on History tab
        page.click('button:has-text("History")')
        page.wait_for_timeout(500)
        
        # Should show completed and failed jobs
        visible_cards = page.locator('.job-card:visible')
        expect(visible_cards).to_have_count(2)
        
        expect(page.locator('[data-job-id="job_completed_1"]')).to_be_visible()
        expect(page.locator('[data-job-id="job_failed_1"]')).to_be_visible()
    
    def test_job_card_expansion(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test expanding job cards to show detailed metadata"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Click on the first job card to expand it
        first_card = page.locator('[data-job-id="job_active_1"]')
        first_card.click()
        
        # Wait for expansion animation
        page.wait_for_timeout(300)
        
        # Check that detailed metadata is visible
        expanded_content = first_card.locator('.job-card-body')
        expect(expanded_content).to_be_visible()
        
        # Verify statistics are shown
        expect(expanded_content).to_contain_text('1,500,000')  # Views
        expect(expanded_content).to_contain_text('85,000')  # Likes
        expect(expanded_content).to_contain_text('12,000')  # Comments
        
        # Verify job information is shown
        expect(expanded_content).to_contain_text('Job ID')
        expect(expanded_content).to_contain_text('job_active_1')
        expect(expanded_content).to_contain_text('Comments Requested')
        expect(expanded_content).to_contain_text('500')
    
    def test_search_functionality(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test searching jobs by title, channel, or ID"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Search by video title
        search_input = page.locator('input[placeholder*="Search"]')
        search_input.fill('Tech Review')
        page.wait_for_timeout(500)
        
        visible_cards = page.locator('.job-card:visible')
        expect(visible_cards).to_have_count(1)
        expect(page.locator('[data-job-id="job_active_1"]')).to_be_visible()
        
        # Clear search and search by channel
        search_input.clear()
        search_input.fill('Cooking Masters')
        page.wait_for_timeout(500)
        
        visible_cards = page.locator('.job-card:visible')
        expect(visible_cards).to_have_count(1)
        expect(page.locator('[data-job-id="job_queued_1"]')).to_be_visible()
        
        # Search by video ID
        search_input.clear()
        search_input.fill('ghi789')
        page.wait_for_timeout(500)
        
        visible_cards = page.locator('.job-card:visible')
        expect(visible_cards).to_have_count(1)
        expect(page.locator('[data-job-id="job_completed_1"]')).to_be_visible()
    
    def test_sorting_options(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test different sorting options for jobs"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Default should be newest first
        first_card = page.locator('.job-card').first
        expect(first_card).to_have_attribute('data-job-id', 'job_queued_1')
        
        # Sort by oldest first
        sort_select = page.locator('select').first
        sort_select.select_option('oldest')
        page.wait_for_timeout(300)
        
        first_card = page.locator('.job-card').first
        expect(first_card).to_have_attribute('data-job-id', 'job_failed_1')
        
        # Sort by title
        sort_select.select_option('title')
        page.wait_for_timeout(300)
        
        first_card = page.locator('.job-card').first
        expect(first_card).to_contain_text('Amazing Tech Review')
    
    def test_job_actions(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test job action buttons (cancel, retry, view analysis)"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.route('/api/jobs/cancel/**', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Test cancel button for active job
        active_card = page.locator('[data-job-id="job_active_1"]')
        active_card.click()  # Expand
        page.wait_for_timeout(300)
        
        cancel_button = active_card.locator('button:has-text("Cancel")')
        expect(cancel_button).to_be_visible()
        
        # Test retry button for failed job
        page.click('button:has-text("Failed")')  # Switch to failed view
        failed_card = page.locator('[data-job-id="job_failed_1"]')
        failed_card.click()  # Expand
        page.wait_for_timeout(300)
        
        retry_button = failed_card.locator('button:has-text("Retry")')
        expect(retry_button).to_be_visible()
        
        # Test YouTube link
        youtube_link = failed_card.locator('a:has-text("View on YouTube")')
        expect(youtube_link).to_have_attribute('href', 'https://youtube.com/watch?v=jkl012')
    
    def test_auto_refresh(self, authenticated_pro_user: Page):
        """Test that job queue auto-refreshes"""
        page = authenticated_pro_user
        
        call_count = {'count': 0}
        
        def handle_route(route):
            call_count['count'] += 1
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({'success': True, 'jobs': []})
            )
        
        page.route('/api/jobs/status', handle_route)
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Initial load
        assert call_count['count'] == 1
        
        # Wait for auto-refresh (default is 5 seconds)
        page.wait_for_timeout(5500)
        
        # Should have made another call
        assert call_count['count'] >= 2
        
        # Check auto-refresh indicator
        expect(page.locator('.auto-refresh-indicator')).to_be_visible()
        expect(page.locator('.auto-refresh-indicator')).to_contain_text('Auto-refreshing')
    
    def test_batch_operations(self, authenticated_pro_user: Page, mock_jobs_data):
        """Test batch selection and cancellation of jobs"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': mock_jobs_data})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Click Select All button
        select_all_button = page.locator('button:has-text("Select All")')
        select_all_button.click()
        
        # Should show batch cancel button
        batch_cancel = page.locator('button:has-text("Cancel")')
        expect(batch_cancel).to_contain_text('Cancel 4')
        
        # Test deselect all
        select_all_button.click()
        expect(batch_cancel).not_to_be_visible()
    
    def test_responsive_design(self, authenticated_pro_user: Page):
        """Test that job queue is responsive on mobile"""
        page = authenticated_pro_user
        
        # Set mobile viewport
        page.set_viewport_size({'width': 375, 'height': 667})
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': []})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Check that elements are properly stacked on mobile
        queue_header = page.locator('.queue-header')
        expect(queue_header).to_be_visible()
        
        # Tabs should still be visible
        tabs = page.locator('.queue-tabs')
        expect(tabs).to_be_visible()
        
        # Filters should stack vertically
        filters = page.locator('.queue-filters')
        expect(filters).to_be_visible()


class TestJobQueueErrorHandling:
    """Test error handling in job queue"""
    
    def test_api_failure_handling(self, authenticated_pro_user: Page):
        """Test handling of API failures"""
        page = authenticated_pro_user
        
        # Mock API failure
        page.route('/api/jobs/status', lambda route: route.abort())
        
        page.goto('http://localhost:8001/dashboard')
        
        # Should show error message
        page.wait_for_selector('.queue-error', timeout=10000)
        expect(page.locator('.alert-danger')).to_be_visible()
        
        # Should show retry button
        retry_button = page.locator('button:has-text("Retry")')
        expect(retry_button).to_be_visible()
    
    def test_empty_queue_message(self, authenticated_pro_user: Page):
        """Test empty queue message"""
        page = authenticated_pro_user
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': []})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Should show empty state
        expect(page.locator('.queue-empty')).to_be_visible()
        expect(page.locator('text=No jobs found')).to_be_visible()
    
    def test_failed_job_error_display(self, authenticated_pro_user: Page):
        """Test that failed jobs display error messages"""
        page = authenticated_pro_user
        
        failed_job = {
            'job_id': 'job_error',
            'status': 'failed',
            'video_id': 'error123',
            'video_title': 'Error Test Video',
            'job_type': 'analysis',
            'error_message': 'Connection timeout: Unable to reach YouTube API',
            'video_metadata': {
                'title': 'Error Test Video'
            }
        }
        
        page.route('/api/jobs/status', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'jobs': [failed_job]})
        ))
        
        page.goto('http://localhost:8001/dashboard')
        page.wait_for_selector('.job-queue')
        
        # Expand the failed job
        failed_card = page.locator('[data-job-id="job_error"]')
        failed_card.click()
        page.wait_for_timeout(300)
        
        # Error message should be visible
        expect(failed_card).to_contain_text('Connection timeout: Unable to reach YouTube API')


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])