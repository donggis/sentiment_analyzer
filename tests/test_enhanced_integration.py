#!/usr/bin/env python
"""
Test script to verify the enhanced YouTube comment fetching integration.

This script tests that all the enhanced features are properly integrated
and working together in the application.
"""
import sys
import os

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.enhanced_youtube_service import EnhancedYouTubeService
from app.services.sentiment_api import SentimentAPIClient
from app.main.forms import EnhancedYouTubeURLForm
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _fake_youtube():
    """Canned YouTube responses so this file never calls the network."""
    video = {
        'items': [{
            'id': 'dQw4w9WgXcQ',
            'snippet': {
                'title': 'Test video',
                'description': 'desc',
                'channelTitle': 'Channel',
                'publishedAt': '2020-01-01T00:00:00Z',
                'thumbnails': {},
            },
            'contentDetails': {'duration': 'PT3M'},
            'statistics': {'viewCount': '10', 'likeCount': '2', 'commentCount': '1'},
        }]
    }
    threads = {
        'items': [{
            'id': 'thread1',
            'snippet': {
                'totalReplyCount': 0,
                'topLevelComment': {
                    'id': 'comment1',
                    'snippet': {
                        'textDisplay': 'hello',
                        'authorDisplayName': 'viewer',
                        'authorChannelId': {'value': 'UC1'},
                        'authorProfileImageUrl': '',
                        'likeCount': 0,
                        'publishedAt': '2020-01-02T00:00:00Z',
                    },
                },
            },
        }]
    }

    class Request:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class Resource:
        def list(self, **kwargs):
            if 'videoId' in kwargs:
                return Request(threads)
            return Request(video)

    class Fake:
        def videos(self):
            return Resource()

        def commentThreads(self):
            return Resource()

    return Fake()


def test_enhanced_service(monkeypatch):
    """Test the enhanced YouTube service against a fake API."""
    monkeypatch.setenv('YOUTUBE_API_KEY', 'test-key')
    monkeypatch.setattr('app.services.youtube_service.build', lambda *args, **kwargs: _fake_youtube())
    service = EnhancedYouTubeService(api_key='test-key')
    video_info = service.get_video_info('dQw4w9WgXcQ', use_cache=False)
    assert video_info['title'] == 'Test video'
    result = service.get_all_available_comments(
        video_id='dQw4w9WgXcQ',
        target_comments=50,
        use_cache=False,
    )
    assert result['comments']
    assert result['statistics']['comments_fetched'] >= 1


def test_batch_sentiment_analysis():
    """Test batch processing in sentiment analyzer."""
    print("\n" + "="*60)
    print("Testing Batch Sentiment Analysis")
    print("="*60)
    
    try:
        # Initialize sentiment API client
        client = SentimentAPIClient(base_url="https://test.api.com")
        client.mock_mode = True  # Use mock mode for testing
        print("✓ Sentiment API client initialized with mock mode")
        
        # Create test texts
        test_texts = [
            "This video is absolutely amazing!",
            "I hate this content",
            "Not sure how I feel about this",
            "Best video ever!",
            "Terrible quality",
            "It's okay I guess",
            "Love it so much!",
            "Worst thing I've ever seen",
            "Pretty good overall",
            "Could be better",
            "Fantastic work!",
            "Disappointing",
            "Average content",
            "Excellent presentation!",
            "Not my cup of tea"
        ]
        
        print(f"\nAnalyzing {len(test_texts)} test comments...")
        
        # Test batch analysis
        results = client.analyze_batch(test_texts)
        
        print(f"✓ Batch analysis completed")
        print(f"  Total analyzed: {results['total_analyzed']}")
        
        # Count sentiments from results
        sentiment_counts = {'positive': 0, 'neutral': 0, 'negative': 0}
        for result in results['results']:
            sentiment = result.get('sentiment', 'neutral')
            sentiment_counts[sentiment] += 1
            
        print(f"  Positive: {sentiment_counts['positive']}")
        print(f"  Neutral: {sentiment_counts['neutral']}")
        print(f"  Negative: {sentiment_counts['negative']}")
        
        if 'statistics' in results:
            avg_conf = results['statistics'].get('average_confidence', 0.5)
            print(f"  Average confidence: {avg_conf:.2f}")
        
    except Exception as e:
        print(f"✗ Error testing batch sentiment analysis: {e}")
        import traceback
        traceback.print_exc()
        assert False, f"Error testing batch sentiment analysis: {e}"


def test_forms():
    """Test the enhanced forms."""
    print("\n" + "="*60)
    print("Testing Enhanced Forms")
    print("="*60)
    
    try:
        # Test that enhanced form exists and has new fields
        from flask import Flask
        from app.config import Config
        
        app = Flask(__name__)
        app.config.from_object(Config)
        app.config['SECRET_KEY'] = 'test-secret-key'
        app.config['WTF_CSRF_ENABLED'] = False
        
        with app.test_request_context():
            form = EnhancedYouTubeURLForm()
            
            # Check that new fields exist
            assert hasattr(form, 'max_comments'), "Missing max_comments field"
            assert hasattr(form, 'sort_order'), "Missing sort_order field"
            assert hasattr(form, 'use_cache'), "Missing use_cache field"
            
            print("✓ Enhanced form has all required fields:")
            print(f"  - max_comments (default: {form.max_comments.default})")
            print(f"  - sort_order (default: {form.sort_order.default})")
            print(f"  - use_cache (default: {form.use_cache.default})")
            
    except Exception as e:
        print(f"✗ Error testing forms: {e}")
        assert False, f"Error testing forms: {e}"


def test_integration(monkeypatch):
    """Test full integration of enhanced features without calling YouTube."""
    monkeypatch.setenv('YOUTUBE_API_KEY', 'test-key')
    monkeypatch.setenv('ENABLE_EXTERNAL_AI', 'true')
    monkeypatch.setattr('app.services.youtube_service.build', lambda *args, **kwargs: _fake_youtube())
    youtube_service = EnhancedYouTubeService(api_key='test-key')
    sentiment_client = SentimentAPIClient(base_url='https://test.api.com')
    sentiment_client.mock_mode = True
    result = youtube_service.get_all_available_comments(
        video_id='dQw4w9WgXcQ',
        target_comments=30,
        use_cache=False,
    )
    comments = result['comments']
    comment_texts = [comment['text'] for comment in comments[:20]]
    sentiment_results = sentiment_client.analyze_batch(comment_texts)
    assert len(comments) > 0
    assert sentiment_results['total_analyzed'] > 0


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  Enhanced YouTube Comment Analyzer Integration Test")
    print("="*60)
    
    tests = [
        ("Enhanced Service", test_enhanced_service),
        ("Batch Sentiment Analysis", test_batch_sentiment_analysis),
        ("Enhanced Forms", test_forms),
        ("Full Integration", test_integration)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"\nUnexpected error in {test_name}: {e}")
            results.append((test_name, False))
    
    # Print summary
    print("\n" + "="*60)
    print("  TEST SUMMARY")
    print("="*60)
    
    for test_name, success in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        print("\n🎉 All tests passed! The enhanced features are properly integrated.")
        print("\nYou can now:")
        print("1. Run the app: python run.py")
        print("2. Visit http://localhost:5000")
        print("3. Analyze videos with up to 10,000 comments!")
        print("4. Get comprehensive fetching statistics")
        print("5. Use batch processing for efficient sentiment analysis")
    else:
        print("\n⚠️ Some tests failed. Please check the errors above.")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
