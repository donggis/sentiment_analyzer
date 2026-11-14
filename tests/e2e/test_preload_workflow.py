"""
End-to-end tests for the PRO dashboard preload workflow.
Tests the complete user journey from clicking preload to completion.
"""

import pytest
import asyncio
pytest.importorskip('pytest_asyncio')
pytest.importorskip('playwright.async_api')
import pytest_asyncio

# Skip these tests if playwright is not installed
try:
    from playwright.async_api import async_playwright, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from unittest.mock import patch, MagicMock

# Mark all tests in this module as E2E tests
pytestmark = [pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed"), pytest.mark.e2e]


class TestPreloadWorkflowE2E:
    """E2E tests for the video preload workflow."""

    @pytest.mark.asyncio
    async def test_complete_preload_workflow(self, authenticated_page):
        """Test the complete workflow from preload button click to completion."""
        page = authenticated_page
        
        # Navigate to dashboard
        await page.goto('http://localhost:5000/dashboard')
        
        # Load a channel (mock data)
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        
        # Wait for videos to load
        await page.wait_for_selector('.video-item', timeout=5000)
        
        # Click first preload button
        preload_button = page.locator('.vibe-button:has-text("Preload")').first
        await preload_button.click()
        
        # Verify button shows queuing state
        await expect(preload_button).to_contain_text('Queuing...')
        
        # Wait for job to be queued
        await page.wait_for_timeout(1000)
        
        # Verify button shows queued state
        await expect(preload_button).to_contain_text('Queued')
        
        # Simulate job processing (mock backend update)
        # In real test, this would be handled by backend
        await page.wait_for_timeout(2000)
        
        # Check jobs section shows the running job
        jobs_container = page.locator('#jobsContainer')
        await expect(jobs_container).to_contain_text('COMMENT PRELOAD')
        
        # Verify progress is shown
        progress_bar = page.locator('.progress-bar').first
        await expect(progress_bar).to_be_visible()
        
        # Wait for completion (simulated)
        await page.wait_for_timeout(3000)
        
        # Verify button shows completed state
        await expect(preload_button).to_contain_text('Preloaded')
        await expect(preload_button).to_be_disabled()

    @pytest.mark.asyncio
    async def test_preload_button_states(self, authenticated_page):
        """Test all possible preload button states."""
        page = authenticated_page
        
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Initial state - should show "Preload"
        button = page.locator('.vibe-button').first
        await expect(button).to_contain_text('Preload')
        await expect(button).to_be_enabled()
        
        # Click to start preload
        await button.click()
        
        # Should transition to "Queuing..."
        await expect(button).to_contain_text('Queuing...')
        await expect(button).to_be_disabled()
        
        # Then to "Queued"
        await page.wait_for_timeout(1500)
        await expect(button).to_contain_text('Queued')
        
        # For processing state, we would need backend simulation
        # await expect(button).to_contain_text('Processing')
        # await expect(button).to_contain_text('50%')

    @pytest.mark.asyncio
    async def test_multiple_preloads(self, authenticated_page):
        """Test preloading multiple videos simultaneously."""
        page = authenticated_page
        
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Get all preload buttons
        preload_buttons = page.locator('.vibe-button:has-text("Preload")')
        count = await preload_buttons.count()
        
        # Click multiple preload buttons quickly
        for i in range(min(3, count)):
            button = preload_buttons.nth(i)
            await button.click()
            await page.wait_for_timeout(200)  # Small delay between clicks
        
        # All clicked buttons should show queuing state
        for i in range(min(3, count)):
            button = preload_buttons.nth(i)
            await expect(button).to_contain_text('Queuing...')
        
        # Check jobs container shows multiple jobs
        await page.wait_for_timeout(2000)
        job_items = page.locator('.job-item')
        job_count = await job_items.count()
        assert job_count >= min(3, count)

    @pytest.mark.asyncio
    async def test_preload_all_button(self, authenticated_page):
        """Test the 'Preload Last 10' button functionality."""
        page = authenticated_page
        
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Click preload all button
        preload_all_btn = page.locator('#preloadAllBtn')
        await expect(preload_all_btn).to_be_visible()
        await preload_all_btn.click()
        
        # Should show queuing progress
        await expect(preload_all_btn).to_contain_text('Queuing videos...')
        await expect(preload_all_btn).to_be_disabled()
        
        # Wait for completion
        await page.wait_for_timeout(3000)
        
        # Should show success
        await expect(preload_all_btn).to_contain_text('Queued!')
        
        # After timeout, should return to original state
        await page.wait_for_timeout(3500)
        await expect(preload_all_btn).to_contain_text('Preload Last 10')
        await expect(preload_all_btn).to_be_enabled()

    @pytest.mark.asyncio 
    async def test_preload_error_handling(self, authenticated_page):
        """Test error handling during preload process."""
        page = authenticated_page
        
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Intercept preload API call and force an error
        await page.route('**/api/preload/comments/**', lambda route: 
            route.fulfill(status=500, json={'success': False, 'error': 'Server error'}))
        
        # Click preload button
        button = page.locator('.vibe-button:has-text("Preload")').first
        await button.click()
        
        # Should show error toast
        toast = page.locator('.toast-body')
        await expect(toast).to_contain_text('Failed to queue preload')
        
        # Button should return to normal state
        await page.wait_for_timeout(1000)
        await expect(button).to_contain_text('Preload')
        await expect(button).to_be_enabled()

    @pytest.mark.asyncio
    async def test_preload_persistence_across_refresh(self, authenticated_page):
        """Test that preload status persists across page refreshes."""
        page = authenticated_page
        
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Start a preload
        button = page.locator('.vibe-button:has-text("Preload")').first
        await button.click()
        await page.wait_for_timeout(1500)
        
        # Get video ID from the DOM
        video_item = page.locator('.video-item').first
        video_id = await video_item.locator('code').inner_text()
        
        # Refresh the page
        await page.reload()
        
        # Load channel again
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Find the same video
        video_selector = f'.video-item:has(code:text("{video_id}"))'
        video_item = page.locator(video_selector).first
        button = video_item.locator('.vibe-button')
        
        # Should still show queued/processing state
        button_text = await button.inner_text()
        assert 'Preload' not in button_text  # Should not be in initial state

    @pytest.mark.asyncio
    async def test_preload_status_polling(self, authenticated_page):
        """Test that job status is polled and updated automatically."""
        page = authenticated_page
        
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Mock job status API to return different states
        call_count = 0
        async def mock_job_status(route):
            nonlocal call_count
            call_count += 1
            
            if call_count == 1:
                # First call - job is queued
                await route.fulfill(json={
                    'success': True,
                    'jobs': [{
                        'job_id': 'job1',
                        'video_id': 'video1',
                        'status': 'queued',
                        'progress': 0
                    }]
                })
            elif call_count == 2:
                # Second call - job is processing
                await route.fulfill(json={
                    'success': True,
                    'jobs': [{
                        'job_id': 'job1',
                        'video_id': 'video1',
                        'status': 'processing',
                        'progress': 50
                    }]
                })
            else:
                # Third call - job is completed
                await route.fulfill(json={
                    'success': True,
                    'jobs': [{
                        'job_id': 'job1',
                        'video_id': 'video1',
                        'status': 'completed',
                        'progress': 100
                    }]
                })
        
        await page.route('**/api/jobs/status', mock_job_status)
        
        # Trigger a preload
        button = page.locator('.vibe-button:has-text("Preload")').first
        await button.click()
        
        # Wait for polling cycles
        await page.wait_for_timeout(1000)  # First poll
        await page.wait_for_timeout(3000)  # Second poll
        await page.wait_for_timeout(3000)  # Third poll
        
        # Verify button shows completed state
        await expect(button).to_contain_text('Preloaded')

    @pytest.mark.asyncio
    async def test_preload_with_navigation(self, authenticated_page):
        """Test that navigating away and back maintains job status."""
        page = authenticated_page
        
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Start preload
        button = page.locator('.vibe-button:has-text("Preload")').first
        await button.click()
        await page.wait_for_timeout(1500)
        
        # Navigate to analyze page
        video_link = page.locator('.video-title a').first
        await video_link.click()
        await page.wait_for_url('**/analyze/**')
        
        # Navigate back to dashboard
        await page.goto('http://localhost:5000/dashboard')
        await page.fill('#channelInput', '@testchannel')
        await page.click('#loadChannelBtn')
        await page.wait_for_selector('.video-item')
        
        # Button should still reflect job status
        button = page.locator('.vibe-button').first
        button_text = await button.inner_text()
        assert 'Preload' not in button_text  # Should not be in initial state


# Fixtures for authenticated testing
@pytest_asyncio.fixture
async def browser():
    """Create a browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()

@pytest_asyncio.fixture
async def authenticated_page(browser):
    """Create an authenticated browser page for testing."""
    context = await browser.new_context()
    page = await context.new_page()
    
    # Mock all page requests to return a basic HTML page
    await page.route('**/*', lambda route: route.fulfill(
        status=200,
        content_type='text/html',
        body="""<!DOCTYPE html>
        <html>
        <head><title>Test Page</title></head>
        <body>
            <div id="app">
                <div class="video-list">
                    <div class="video-item">
                        <code>video1</code>
                        <span class="video-title"><a href="/analyze/video1">Test Video 1</a></span>
                        <button class="vibe-button">Preload</button>
                    </div>
                    <div class="video-item">
                        <code>video2</code>
                        <span class="video-title"><a href="/analyze/video2">Test Video 2</a></span>
                        <button class="vibe-button">Preload</button>
                    </div>
                    <div class="video-item">
                        <code>video3</code>
                        <span class="video-title"><a href="/analyze/video3">Test Video 3</a></span>
                        <button class="vibe-button">Preload</button>
                    </div>
                </div>
                <input id="channelInput" type="text" />
                <button id="loadChannelBtn">Load Channel</button>
                <button id="preloadAllBtn">Preload Last 10</button>
                <div id="jobsContainer"></div>
                <div class="toast-body" style="display:none;"></div>
                <div class="progress-bar" style="display:none;"></div>
            </div>
        </body>
        </html>
        """
    ) if not route.request.url.startswith('http://localhost:5000/api') else route.continue_())
    
    # Navigate to a mock login page to set up authentication
    await page.goto('http://localhost:5000/login')
    await page.evaluate("""() => {
        localStorage.setItem('auth_token', 'test_pro_token');
        localStorage.setItem('user_type', 'pro');
        document.cookie = 'session=test_session; path=/';
    }""")
    
    # Mock API responses for channel/video data
    await page.route('**/api/youtube/channel-videos**', lambda route:
        route.fulfill(json={
            'success': True,
            'channel': {
                'id': 'channel1',
                'title': 'Test Channel',
                'handle': '@testchannel'
            },
            'videos': [
                {
                    'id': 'video1',
                    'title': 'Test Video 1',
                    'statistics': {'views': 10000, 'comments': 500}
                },
                {
                    'id': 'video2',
                    'title': 'Test Video 2',
                    'statistics': {'views': 5000, 'comments': 250}
                },
                {
                    'id': 'video3',
                    'title': 'Test Video 3',
                    'statistics': {'views': 2000, 'comments': 100}
                }
            ],
            'count': 3
        }))
    
    # Mock preload API success by default
    await page.route('**/api/preload/comments/**', lambda route:
        route.fulfill(json={
            'success': True,
            'job_id': f'job_{route.request.url.split("/")[-1]}'
        }))
    
    # Mock jobs status API
    await page.route('**/api/jobs/status', lambda route:
        route.fulfill(json={
            'success': True,
            'jobs': []
        }))
    
    yield page
    
    await context.close()
