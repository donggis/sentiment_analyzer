"""
End-to-End tests for infinite scroll video loading functionality
Tests the complete workflow of loading videos with infinite scroll in "Your Videos" section
"""

import pytest
import json
import time
import re
pytest.importorskip('playwright.sync_api')
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture
def authenticated_user(page: Page):
    """Fixture to provide an authenticated user with a YouTube channel"""
    # Login
    page.goto('http://localhost:8001/login')
    page.fill('input[name="email"]', 'user@example.com')
    page.fill('input[name="password"]', 'password123')
    page.click('button[type="submit"]')
    
    # Wait for redirect to dashboard
    page.wait_for_url('**/dashboard', timeout=10000)
    
    # Set channel info in session
    page.evaluate("""
        window.userChannel = {
            channelId: 'UCtest123',
            channelTitle: 'Test Channel'
        };
        window.isAuthenticated = true;
    """)
    
    return page


@pytest.fixture
def mock_video_data():
    """Generate mock video data for testing"""
    videos = []
    for i in range(100):  # Create 100 videos for testing pagination
        videos.append({
            'video_id': f'video_{i}',
            'title': f'Test Video {i + 1}',
            'thumbnail': f'https://i.ytimg.com/vi/video_{i}/mqdefault.jpg',
            'duration': f'PT{i % 60}M{i % 60}S',
            'views': (i + 1) * 10000,
            'likes': (i + 1) * 100,
            'comments': (i + 1) * 50,
            'channel_title': 'Test Channel',
            'published_at': f'2024-01-{(i % 28) + 1:02d}T10:00:00Z',
            'sentiment_data': {
                'overall_sentiment': ['positive', 'neutral', 'negative'][i % 3],
                'comment_count': (i + 1) * 10
            } if i % 2 == 0 else None
        })
    return videos


class TestInfiniteScrollVideos:
    """Test the infinite scroll functionality for videos"""
    
    def test_initial_video_load(self, authenticated_user: Page, mock_video_data):
        """Test that videos load initially when visiting the page"""
        page = authenticated_user
        
        # Mock API response for first page
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': mock_video_data[:20],  # First 20 videos
                'total': 100,
                'has_more': True,
                'page': 1
            })
        ))
        
        # Navigate to videos section
        page.goto('http://localhost:8001/dashboard/videos')
        
        # Wait for videos to load
        page.wait_for_selector('.video-grid', timeout=10000)
        
        # Check header is present
        expect(page.locator('h2:has-text("Your Videos")')).to_be_visible()
        
        # Check video count indicator
        expect(page.locator('.videos-count')).to_contain_text('20 of 100 videos loaded')
        
        # Verify first batch of videos is displayed
        video_cards = page.locator('.video-card')
        expect(video_cards).to_have_count(20)
        
        # Verify first video details
        first_video = video_cards.first
        expect(first_video).to_contain_text('Test Video 1')
        expect(first_video.locator('img')).to_have_attribute('src', 'https://i.ytimg.com/vi/video_0/mqdefault.jpg')
    
    def test_infinite_scroll_loads_more_videos(self, authenticated_user: Page, mock_video_data):
        """Test that scrolling to bottom loads more videos"""
        page = authenticated_user
        
        request_count = {'count': 0}
        
        def handle_route(route):
            request_count['count'] += 1
            page_num = request_count['count']
            start_idx = (page_num - 1) * 20
            end_idx = start_idx + 20
            
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({
                    'success': True,
                    'videos': mock_video_data[start_idx:end_idx],
                    'total': 100,
                    'has_more': end_idx < 100,
                    'page': page_num
                })
            )
        
        page.route('**/api/channel/*/videos*', handle_route)
        
        page.goto('http://localhost:8001/dashboard/videos')
        
        # Wait for initial load
        page.wait_for_selector('.video-card')
        initial_count = page.locator('.video-card').count()
        assert initial_count == 20
        
        # Scroll to bottom to trigger loading more
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        
        # Wait for loading indicator
        page.wait_for_selector('.loading-more', timeout=5000)
        
        # Wait for more videos to load
        page.wait_for_function('document.querySelectorAll(".video-card").length > 20', timeout=10000)
        
        # Verify more videos are loaded
        updated_count = page.locator('.video-card').count()
        assert updated_count == 40  # Should have loaded 20 more
        
        # Check updated count
        expect(page.locator('.videos-count')).to_contain_text('40 of 100 videos loaded')
    
    def test_continuous_scrolling(self, authenticated_user: Page, mock_video_data):
        """Test continuous scrolling loads videos progressively"""
        page = authenticated_user
        
        request_count = {'count': 0}
        
        def handle_route(route):
            request_count['count'] += 1
            page_num = request_count['count']
            start_idx = (page_num - 1) * 20
            end_idx = min(start_idx + 20, 100)
            
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({
                    'success': True,
                    'videos': mock_video_data[start_idx:end_idx],
                    'total': 100,
                    'has_more': end_idx < 100,
                    'page': page_num
                })
            )
        
        page.route('**/api/channel/*/videos*', handle_route)
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Perform multiple scrolls
        for i in range(3):
            current_count = page.locator('.video-card').count()
            
            # Scroll to bottom
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            
            # Wait for new videos to load
            page.wait_for_function(
                f'document.querySelectorAll(".video-card").length > {current_count}',
                timeout=10000
            )
            
            new_count = page.locator('.video-card').count()
            assert new_count > current_count
        
        # Should have loaded at least 60 videos after 3 scrolls
        final_count = page.locator('.video-card').count()
        assert final_count >= 60
    
    def test_load_all_videos_button(self, authenticated_user: Page, mock_video_data):
        """Test the 'Load All Videos' button functionality"""
        page = authenticated_user
        
        # Mock initial load and load all requests
        page.route('**/api/channel/*/videos?page=1&limit=20', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': mock_video_data[:20],
                'total': 100,
                'has_more': True
            })
        ))
        
        # Mock load all request (larger batch)
        loaded_pages = {'count': 1}
        
        def handle_load_all(route):
            loaded_pages['count'] += 1
            page_num = loaded_pages['count']
            start_idx = (page_num - 1) * 50
            end_idx = min(start_idx + 50, 100)
            
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({
                    'success': True,
                    'videos': mock_video_data[start_idx:end_idx],
                    'total': 100,
                    'has_more': end_idx < 100
                })
            )
        
        page.route('**/api/channel/*/videos?page=*&limit=50', handle_load_all)
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Click Load All Videos button
        load_all_button = page.locator('button:has-text("Load All Videos")')
        expect(load_all_button).to_be_visible()
        load_all_button.click()
        
        # Button should be disabled while loading
        expect(load_all_button).to_be_disabled()
        
        # Wait for all videos to load
        page.wait_for_selector('.end-of-list:has-text("All 100 videos loaded")', timeout=15000)
        
        # Verify all videos are loaded
        video_count = page.locator('.video-card').count()
        assert video_count == 100
        
        # Load All button should be hidden
        expect(load_all_button).not_to_be_visible()
    
    def test_video_click_navigation(self, authenticated_user: Page, mock_video_data):
        """Test clicking on a video navigates to video details"""
        page = authenticated_user
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': mock_video_data[:20],
                'total': 100,
                'has_more': True
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Click on first video
        first_video = page.locator('.video-card').first
        first_video.click()
        
        # Should navigate to video analysis page
        page.wait_for_url('**/video/video_0', timeout=5000)
        
        # Verify we're on the correct page
        expect(page).to_have_url(re.compile(r'.*\/video\/video_0'))
    
    def test_error_handling(self, authenticated_user: Page):
        """Test error handling when API fails"""
        page = authenticated_user
        
        # Mock API error
        page.route('**/api/channel/*/videos*', lambda route: route.abort())
        
        page.goto('http://localhost:8001/dashboard/videos')
        
        # Should show error message
        page.wait_for_selector('.videos-error', timeout=10000)
        expect(page.locator('.videos-error')).to_contain_text('Failed to load videos')
        
        # Should show retry button
        retry_button = page.locator('button:has-text("Retry")')
        expect(retry_button).to_be_visible()
        
        # Mock successful response for retry
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': [],
                'total': 0,
                'has_more': False
            })
        ))
        
        # Click retry
        retry_button.click()
        
        # Error should disappear
        page.wait_for_selector('.video-grid-empty', timeout=10000)
        expect(page.locator('.videos-error')).not_to_be_visible()
    
    def test_empty_state(self, authenticated_user: Page):
        """Test empty state when no videos exist"""
        page = authenticated_user
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': [],
                'total': 0,
                'has_more': False
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        
        # Should show empty state
        page.wait_for_selector('.video-grid-empty', timeout=10000)
        expect(page.locator('.video-grid-empty')).to_contain_text('No videos found')
        expect(page.locator('.video-grid-empty')).to_contain_text('Videos from your channel will appear here')
    
    def test_progress_indicator(self, authenticated_user: Page, mock_video_data):
        """Test that progress indicator shows loading progress"""
        page = authenticated_user
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': mock_video_data[:20],
                'total': 100,
                'has_more': True
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Check progress bar exists and shows correct progress
        progress_bar = page.locator('.progress-bar')
        expect(progress_bar).to_be_visible()
        
        # Should show 20% progress (20 of 100 videos)
        progress_width = page.evaluate('document.querySelector(".progress-bar").style.width')
        assert progress_width == '20%'
    
    def test_responsive_mobile_view(self, authenticated_user: Page, mock_video_data):
        """Test infinite scroll works on mobile viewport"""
        page = authenticated_user
        
        # Set mobile viewport
        page.set_viewport_size({'width': 375, 'height': 667})
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': mock_video_data[:10],
                'total': 50,
                'has_more': True
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Videos should display in single column on mobile
        video_grid = page.locator('.video-grid')
        grid_style = page.evaluate('window.getComputedStyle(document.querySelector(".video-grid")).gridTemplateColumns')
        assert '1fr' in grid_style or 'auto' in grid_style
        
        # Scroll should still work
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        
        # Loading indicator should be visible
        expect(page.locator('.scroll-sentinel')).to_be_visible()
    
    def test_sentiment_badges_display(self, authenticated_user: Page, mock_video_data):
        """Test that sentiment analysis badges are displayed correctly"""
        page = authenticated_user
        
        # Filter to only videos with sentiment data
        videos_with_sentiment = [v for v in mock_video_data[:20] if v.get('sentiment_data')]
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': videos_with_sentiment,
                'total': len(videos_with_sentiment),
                'has_more': False
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Check sentiment badges are displayed
        sentiment_badges = page.locator('.sentiment-badge')
        expect(sentiment_badges.first).to_be_visible()
        
        # Verify different sentiment types
        positive_badges = page.locator('.sentiment-badge[data-sentiment="positive"]')
        neutral_badges = page.locator('.sentiment-badge[data-sentiment="neutral"]')
        negative_badges = page.locator('.sentiment-badge[data-sentiment="negative"]')
        
        assert positive_badges.count() > 0
        assert neutral_badges.count() > 0
        assert negative_badges.count() > 0
        
        # Check comment count is displayed
        comment_counts = page.locator('.comment-count')
        expect(comment_counts.first).to_be_visible()


class TestVideoFormatting:
    """Test video metadata formatting and display"""
    
    def test_duration_formatting(self, authenticated_user: Page):
        """Test that video durations are formatted correctly"""
        page = authenticated_user
        
        test_videos = [
            {
                'video_id': 'vid1',
                'title': 'Short Video',
                'duration': 'PT30S',  # 30 seconds
                'views': 100
            },
            {
                'video_id': 'vid2',
                'title': 'Medium Video',
                'duration': 'PT10M45S',  # 10 minutes 45 seconds
                'views': 100
            },
            {
                'video_id': 'vid3',
                'title': 'Long Video',
                'duration': 'PT2H15M30S',  # 2 hours 15 minutes 30 seconds
                'views': 100
            }
        ]
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': test_videos,
                'total': 3,
                'has_more': False
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Check duration formatting
        expect(page.locator('.video-duration:has-text("0:30")')).to_be_visible()
        expect(page.locator('.video-duration:has-text("10:45")')).to_be_visible()
        expect(page.locator('.video-duration:has-text("2:15:30")')).to_be_visible()
    
    def test_view_count_formatting(self, authenticated_user: Page):
        """Test that view counts are formatted with K/M notation"""
        page = authenticated_user
        
        test_videos = [
            {
                'video_id': 'vid1',
                'title': 'Hundreds',
                'views': 999
            },
            {
                'video_id': 'vid2',
                'title': 'Thousands',
                'views': 15500
            },
            {
                'video_id': 'vid3',
                'title': 'Millions',
                'views': 2500000
            }
        ]
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': test_videos,
                'total': 3,
                'has_more': False
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Check view count formatting
        expect(page.locator('.video-views:has-text("999 views")')).to_be_visible()
        expect(page.locator('.video-views:has-text("15.5K views")')).to_be_visible()
        expect(page.locator('.video-views:has-text("2.5M views")')).to_be_visible()
    
    def test_date_formatting(self, authenticated_user: Page):
        """Test that published dates are formatted as relative time"""
        page = authenticated_user
        
        from datetime import datetime, timedelta
        
        now = datetime.now()
        test_videos = [
            {
                'video_id': 'vid1',
                'title': 'Today',
                'published_at': now.isoformat() + 'Z',
                'views': 100
            },
            {
                'video_id': 'vid2',
                'title': 'Yesterday',
                'published_at': (now - timedelta(days=1)).isoformat() + 'Z',
                'views': 100
            },
            {
                'video_id': 'vid3',
                'title': 'Last Week',
                'published_at': (now - timedelta(days=5)).isoformat() + 'Z',
                'views': 100
            },
            {
                'video_id': 'vid4',
                'title': 'Last Month',
                'published_at': (now - timedelta(days=20)).isoformat() + 'Z',
                'views': 100
            }
        ]
        
        page.route('**/api/channel/*/videos*', lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'videos': test_videos,
                'total': 4,
                'has_more': False
            })
        ))
        
        page.goto('http://localhost:8001/dashboard/videos')
        page.wait_for_selector('.video-card')
        
        # Check date formatting
        expect(page.locator('.video-date:has-text("Today")')).to_be_visible()
        expect(page.locator('.video-date:has-text("Yesterday")')).to_be_visible()
        expect(page.locator('.video-date:has-text("5 days ago")')).to_be_visible()
        expect(page.locator('.video-date:has-text("weeks ago")')).to_be_visible()


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])