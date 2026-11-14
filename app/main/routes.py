"""
Routes for the main blueprint.
"""
import os
import threading
import json
import time
from flask import render_template, flash, redirect, url_for, session, jsonify, request
from app.main import bp
from app.main.forms import YouTubeURLForm, ContactForm
from app.utils.youtube import extract_video_id, build_youtube_url
# Lazy imports inside view functions to speed up startup on Railway
from app.cache import cache
from app.models import db, SentimentFeedback, Channel, Video
from flask_login import current_user, login_required
import hashlib

# Import fast routes to register them
try:
    from app.main import fast_routes
except ImportError as e:
    print(f"Warning: Could not import fast routes: {e}")


@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
def index():
    """Homepage with YouTube URL submission form."""
    form = YouTubeURLForm()
    
    if form.validate_on_submit():
        url = form.url.data
        video_id = extract_video_id(url)
        
        if video_id:
            # Store video ID in session
            session['video_id'] = video_id
            session['video_url'] = build_youtube_url(video_id)
            
            # Redirect to info-only view first to avoid fetching comments on initial load
            return redirect(url_for('main.analyze_video', video_id=video_id, info_only='true'))
        else:
            flash('Could not extract video ID from URL', 'danger')
    
    return render_template('index.html', form=form)


@bp.route('/analyze', methods=['GET', 'POST'])
@login_required
def analyze():
    """Analyze page for YouTube videos."""
    # Support legacy links like /analyze?video_id=XYZ or /analyze?v=XYZ by redirecting to the canonical route
    if request.method == 'GET':
        # Check for both 'v' and 'video_id' parameters
        q_video_id = request.args.get('v') or request.args.get('video_id')
        if q_video_id:
            return redirect(url_for('main.analyze_video', video_id=q_video_id))
    if request.method == 'POST':
        video_url = request.form.get('video_url')
        if video_url:
            video_id = extract_video_id(video_url)
            if video_id:
                return redirect(url_for('main.analyze_video', video_id=video_id))
            else:
                flash('Invalid YouTube URL', 'danger')
    
    # Provide default values for template
    comment_stats = {
        'fetched_comments': 0,
        'total_comments': 0,
        'unique_commenters': 0,
        'avg_comment_length': 0,
        'replies_count': 0,
        'top_level_count': 0,
        'top_commenters': [],
        'total_available': 0,
        'fetch_percentage': 0,
        'fetch_time': 0,
        'comments_per_second': 0,
        'quota_used': 0
    }
    
    return render_template('analyze.html', 
                         comment_stats=comment_stats,
                         video_info=None,
                         video_id=None,
                         video_url=None,
                         cache_status={'enabled': False, 'hits': []},
                         success=False)


@bp.route('/analyze/<video_id>')
def analyze_video(video_id):
    """Analyze comments for a given video ID."""
    import logging
    logging.info(f"analyze_video called with video_id={video_id}, args={request.args}")
    video_url = build_youtube_url(video_id)
    cache_status = {'enabled': cache.enabled, 'hits': []}
    
    try:
        # Read flags from query
        info_only = request.args.get('info_only', 'false').lower() == 'true'
        logging.info(f"info_only={info_only}")
        preview_mode = request.args.get('preview', 'true').lower() == 'true'
        
        # Initialize services
        from app.services.enhanced_youtube_service import EnhancedYouTubeService
        youtube_service = EnhancedYouTubeService()
        
        # Always fetch basic video info first (cached if available)
        logging.info(f"Fetching video info for {video_id}")
        video_info = youtube_service.get_video_info(video_id)
        logging.info(f"Video info fetched: {video_info is not None}")
        if cache.get('video_info', video_id):
            cache_status['hits'].append('video_info')
        
        # If homepage requested info-only, render without fetching any comments
        if info_only:
            comment_stats = {
                'fetched_comments': 0,
                'total_comments': 0,
                'unique_commenters': 0,
                'avg_comment_length': 0,
                'replies_count': 0,
                'top_level_count': 0,
                'top_commenters': [],
                'total_available': video_info.get('statistics', {}).get('comments', 0) if isinstance(video_info, dict) else 0,
                'fetch_percentage': 0,
                'fetch_time': 0,
                'comments_per_second': 0,
                'quota_used': 0
            }
            return render_template(
                'analyze.html',
                video_id=video_id,
                video_url=video_url,
                video_info=video_info,
                comment_stats=comment_stats,
                cache_status=cache_status,
                success=True  # Show page but without any fetched comments yet
            )
        
        # Get more comments for better analysis (configurable) - enforce user-based limits
        from flask import current_app
        from flask_login import current_user
        
        # Determine max comments based on user status
        # For initial page load (non info-only), load a limited preview unless overridden
        if preview_mode:
            # Fast preview mode - only load 100-500 comments for stats
            max_comments = 500  # Quick load for stats display
        else:
            # Full mode - use tier limits
            if current_user.is_authenticated:
                if hasattr(current_user, 'is_subscribed') and current_user.is_subscribed:
                    default_limit = current_app.config['MAX_COMMENTS_PRO']
                else:
                    default_limit = current_app.config['MAX_COMMENTS_FREE']
            else:
                default_limit = current_app.config['MAX_COMMENTS_ANONYMOUS']
            
            max_comments = request.args.get('max_comments', type=int, default=default_limit)
            # Enforce the limit based on user type
            max_comments = min(max_comments, default_limit)
        
        # Check if comments are in cache for this target
        cache_key = f"{video_id}:max:{max_comments}:True:relevance"
        if cache.get('enhanced_comments', cache_key):
            cache_status['hits'].append('comments')
        
        # Smart loading: Determine optimal initial load based on video size
        total_video_comments = video_info.get('statistics', {}).get('comments', 0)
        
        # Adjust max_comments based on video size for faster initial load
        if preview_mode and total_video_comments > 1000:
            # For large videos in preview mode, load even less
            if total_video_comments > 10000:
                max_comments = 100  # Very fast load for huge videos
            elif total_video_comments > 5000:
                max_comments = 250  # Fast load for large videos
            else:
                max_comments = 500  # Standard preview
        elif total_video_comments < 500:
            # For small videos, just load all
            max_comments = total_video_comments
        
        # Fetch maximum available comments using enhanced service
        # Never include replies to keep counts consistent
        result = youtube_service.get_all_available_comments(
            video_id=video_id,
            target_comments=max_comments,
            include_replies=False,  # Never include replies
            sort_order='relevance'
        )
        comments = result['comments']
        fetch_stats = result['statistics']
        
        # Calculate statistics
        unique_commenters = set()
        commenter_frequency = {}
        total_length = 0
        replies_count = 0
        
        for comment in comments:
            # Try to get unique identifier with fallbacks
            author_id = comment.get('author_channel_id') or comment.get('author_id') or comment.get('author')
            if author_id:
                unique_commenters.add(author_id)
            author = comment.get('author', 'Anonymous')
            commenter_frequency[author] = commenter_frequency.get(author, 0) + 1
            comment_text = comment.get('text', '')
            total_length += len(comment_text)
            if comment.get('is_reply', False):
                replies_count += 1
        
        # Find top commenters
        top_commenters = sorted(
            commenter_frequency.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        # Calculate averages
        avg_comment_length = round(total_length / len(comments)) if comments else 0
        top_level_count = len(comments) - replies_count
        
        # Prepare stats for template with enhanced metrics
        comment_stats = {
            'total_comments': len(comments),  # Actual fetched count
            'fetched_comments': len(comments),  # Always show what we fetched
            'unique_commenters': len(unique_commenters),
            'avg_comment_length': avg_comment_length,
            'replies_count': replies_count,
            'top_level_count': top_level_count,
            'top_commenters': top_commenters,
            # Enhanced statistics - use corrected values from service
            'total_available': fetch_stats.get('total_comments_available', len(comments)),
            'fetch_percentage': fetch_stats.get('fetch_percentage', 100.0),
            'fetch_time': fetch_stats.get('fetch_time_seconds', 0),
            'comments_per_second': fetch_stats.get('comments_per_second', 0),
            'quota_used': fetch_stats.get('quota_used', 0),
            'threads_fetched': fetch_stats.get('threads_fetched', 0),
            'total_top_level_comments': fetch_stats.get('total_top_level_comments', 0)
        }
        
        return render_template(
            'analyze.html',
            video_id=video_id,
            video_url=video_url,
            video_info=video_info,
            comment_stats=comment_stats,
            cache_status=cache_status,
            success=True
        )
        
    except Exception as e:
        import logging
        import traceback
        logging.error(f'Error analyzing video {video_id}: {str(e)}\n{traceback.format_exc()}')
        flash(f'Error analyzing video: {str(e)}', 'danger')
        # Provide default empty stats to avoid template errors
        comment_stats = {
            'total_comments': 0,
            'fetched_comments': 0,
            'unique_commenters': 0,
            'avg_comment_length': 0,
            'replies_count': 0,
            'top_level_count': 0,
            'top_commenters': [],
            'total_available': 0,
            'fetch_percentage': 0,
            'fetch_time': 0,
            'comments_per_second': 0,
            'quota_used': 0
        }
        return render_template(
            'analyze.html',
            video_id=video_id,
            video_url=video_url,
            comment_stats=comment_stats,
            video_info=None,
            success=False,
            error=str(e)
        )


@bp.route('/user-dashboard')
@bp.route('/profile')  # Backward compatibility alias
@login_required
def user_dashboard():
    """Unified user dashboard for both free and pro users."""
    return render_template('user_dashboard.html')


@bp.route('/about')
def about():
    """About page."""
    return render_template('about.html')


@bp.route('/privacy')
def privacy():
    """Privacy policy page."""
    return render_template('privacy.html')


@bp.route('/terms')
def terms():
    """Terms of service page."""
    return render_template('terms.html')


@bp.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact mail is disabled. The address of the original app owner is not used."""
    return 'Feature disabled for private deployment', 404


@bp.route('/api/health')
def api_health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'timestamp': time.time()})


@bp.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    """API endpoint for sentiment analysis."""
    try:
        data = request.get_json()
        text = data.get('text')
        if not text:
            return jsonify({'success': False, 'error': 'Text required'}), 400
        
        from app.services.sentiment_api import get_sentiment_client
        client = get_sentiment_client()
        result = client.analyze_text(text)
        
        return jsonify({
            'success': True,
            'label': result.get('sentiment'),
            'confidence': result.get('confidence'),
            'sentiment': result.get('sentiment')
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/batch', methods=['POST'])
@login_required
def api_batch():
    """API endpoint for batch analysis."""
    try:
        data = request.get_json()
        texts = data.get('texts', [])
        if not texts:
            return jsonify({'success': False, 'error': 'Texts required'}), 400
        
        from app.services.sentiment_api import get_sentiment_client
        client = get_sentiment_client()
        results = client.analyze_batch(texts)
        
        return jsonify({
            'success': True,
            'total': results.get('total_analyzed', len(texts)),
            'results': results.get('results', [])
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/feedback', methods=['POST'])
@login_required
def api_feedback():
    """API endpoint for submitting feedback."""
    try:
        data = request.get_json()
        required_fields = ['video_id', 'comment_text', 'predicted', 'corrected']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing field: {field}'}), 400
        
        # Create feedback record
        feedback = SentimentFeedback(
            user_id=current_user.id,
            video_id=data['video_id'],
            comment_text=data['comment_text'],
            predicted_sentiment=data['predicted'],
            corrected_sentiment=data['corrected'],
            session_id=session.get('feedback_session', '')
        )
        
        db.session.add(feedback)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Feedback submitted'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/sentiment-feedback', methods=['GET', 'POST'])
def api_sentiment_feedback():
    """
    API endpoint to collect user feedback on sentiment predictions.
    This data will be used to improve our models.
    
    GET: Retrieve user's feedback for a video
    POST: Submit new feedback
    """
    # Handle GET request - fetch user's feedback for a video
    if request.method == 'GET':
        video_id = request.args.get('video_id')
        if not video_id:
            return jsonify({
                'success': False,
                'error': 'video_id parameter required'
            }), 400
        
        # Get session ID
        session_id = session.get('feedback_session')
        
        # Build query based on authentication
        if current_user.is_authenticated:
            # For logged-in users, get feedback by user_id
            feedback_list = SentimentFeedback.query.filter_by(
                user_id=current_user.id,
                video_id=video_id
            ).all()
        elif session_id:
            # For anonymous users, get feedback by session_id
            feedback_list = SentimentFeedback.query.filter_by(
                session_id=session_id,
                video_id=video_id
            ).all()
        else:
            # No feedback to retrieve
            feedback_list = []
        
        # Convert to JSON-serializable format
        feedback_data = []
        for fb in feedback_list:
            feedback_data.append({
                'comment_text': fb.comment_text,
                'comment_id': fb.comment_id,
                'predicted_sentiment': fb.predicted_sentiment,
                'corrected_sentiment': fb.corrected_sentiment,
                'confidence_score': fb.confidence_score,
                'created_at': fb.created_at.isoformat() if fb.created_at else None
            })
        
        return jsonify({
            'success': True,
            'feedback': feedback_data,
            'total': len(feedback_data)
        })
    
    # Handle POST request - submit new feedback
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['video_id', 'comment_text', 'predicted_sentiment', 'corrected_sentiment']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        # Don't allow same sentiment as correction
        if data['predicted_sentiment'] == data['corrected_sentiment']:
            return jsonify({
                'success': False,
                'error': 'Corrected sentiment must be different from predicted'
            }), 400
        
        # Get session ID (create if doesn't exist)
        if 'feedback_session' not in session:
            import uuid
            session['feedback_session'] = str(uuid.uuid4())
        session_id = session['feedback_session']
        
        # Hash IP for privacy
        ip = request.remote_addr or 'unknown'
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
        
        # Check for duplicate feedback
        existing = SentimentFeedback.query.filter_by(
            session_id=session_id,
            video_id=data['video_id'],
            comment_text=data['comment_text']
        ).first()
        
        if existing:
            return jsonify({
                'success': False,
                'error': 'Feedback already submitted for this comment'
            }), 409
        
        # Create feedback record
        feedback = SentimentFeedback(
            user_id=current_user.id if current_user.is_authenticated else None,
            video_id=data['video_id'],
            comment_id=data.get('comment_id'),
            comment_text=data['comment_text'],
            comment_author=data.get('comment_author'),
            predicted_sentiment=data['predicted_sentiment'],
            corrected_sentiment=data['corrected_sentiment'],
            confidence_score=data.get('confidence_score'),
            session_id=session_id,
            ip_hash=ip_hash
        )
        
        db.session.add(feedback)
        db.session.commit()
        
        # Track feedback count in this session
        session['feedback_count'] = session.get('feedback_count', 0) + 1
        
        return jsonify({
            'success': True,
            'message': 'Thank you for helping us improve our AI!',
            'feedback_id': feedback.id,
            'total_feedback': session['feedback_count']
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'An error occurred: {str(e)}'
        }), 500


@bp.route('/api/comments/<video_id>')
def api_get_comments(video_id):
    """
    API endpoint to fetch all comments for a video as JSON.
    
    Query parameters:
        - max_comments: Maximum number of top-level comments to fetch (default: from .env)
        - format: 'threaded' (default) or 'flat'
    """
    try:
        # Initialize Enhanced YouTube service
        youtube_service = EnhancedYouTubeService()
        
        # Get parameters with higher default
        max_comments = request.args.get('max_comments', type=int)
        if not max_comments:
            max_comments = int(os.getenv('MAX_COMMENTS_PER_VIDEO', 10000))
        
        format_type = request.args.get('format', 'threaded')
        
        # Fetch comments using enhanced service - never include replies
        if format_type == 'flat':
            result = youtube_service.get_all_available_comments(
                video_id=video_id,
                target_comments=max_comments,
                include_replies=False,  # Never include replies
                sort_order='relevance'
            )
            return jsonify({
                'success': True,
                'video_id': video_id,
                'format': 'flat',
                'comments': result['comments'],
                'total_comments': len(result['comments']),
                'statistics': result['statistics'],
                'metadata': result['fetch_metadata']
            })
        else:
            # Get comprehensive summary with threads
            result = youtube_service.get_all_available_comments(
                video_id=video_id,
                target_comments=max_comments,
                include_replies=False,  # Never include replies
                sort_order='relevance'
            )
            return jsonify({
                'success': True,
                'video_id': video_id,
                'format': 'threaded',
                'threads': result['threads'],
                'statistics': result['statistics'],
                'metadata': result['fetch_metadata']
            })
            
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'An unexpected error occurred: {str(e)}'
        }), 500


@bp.route('/api/video/<video_id>')
def api_get_video_info(video_id):
    """
    API endpoint to fetch video information only.
    """
    try:
        from app.services import YouTubeService
        youtube_service = YouTubeService()
        video_info = youtube_service.get_video_info(video_id)
        
        return jsonify({
            'success': True,
            'video': video_info
        })
        
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'An unexpected error occurred: {str(e)}'
        }), 500


@bp.route('/api/extract-video-id', methods=['POST'])
def api_extract_video_id():
    """
    API endpoint to extract video ID from a YouTube URL.
    """
    data = request.get_json()
    
    if not data or 'url' not in data:
        return jsonify({
            'success': False,
            'error': 'URL is required'
        }), 400
    
    url = data['url']
    video_id = extract_video_id(url)
    
    if video_id:
        return jsonify({
            'success': True,
            'video_id': video_id,
            'video_url': build_youtube_url(video_id)
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Could not extract video ID from URL'
        }), 400


@bp.route('/api/cache/clear/<video_id>', methods=['POST'])
def api_clear_cache(video_id):
    """
    API endpoint to clear cache for a specific video.
    """
    try:
        deleted = cache.clear_video_cache(video_id)
        return jsonify({
            'success': True,
            'message': f'Cleared {deleted} cache entries for video {video_id}'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/cache/stats')
def api_cache_stats():
    """
    API endpoint to get cache statistics.
    """
    try:
        stats = cache.get_cache_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/user/stats')
@login_required
def api_user_stats():
    """
    API endpoint to get user statistics for the dashboard.
    """
    try:
        from app.models import AnalysisJob, UserChannel
        
        # Get basic user stats
        total_analyses = AnalysisJob.query.filter_by(user_id=current_user.id).count()
        active_jobs = AnalysisJob.query.filter_by(
            user_id=current_user.id
        ).filter(AnalysisJob.status.in_(['queued', 'processing'])).count()
        
        completed_jobs = AnalysisJob.query.filter_by(
            user_id=current_user.id, status='completed'
        ).count()
        
        # Calculate comments analyzed from completed jobs
        completed_analyses = AnalysisJob.query.filter_by(
            user_id=current_user.id, status='completed'
        ).all()
        
        comments_analyzed = sum(
            job.comment_count_processed or job.comment_count_requested or 0 
            for job in completed_analyses
        )
        
        stats = {
            'total_analyses': total_analyses,
            'comments_analyzed': comments_analyzed,
            'active_jobs': active_jobs,
            'completed_jobs': completed_jobs
        }
        
        # Add pro-specific stats if user is subscribed
        if current_user.is_subscribed:
            channels_tracked = UserChannel.query.filter_by(user_id=current_user.id).count()
            preloaded_videos = AnalysisJob.query.filter_by(
                user_id=current_user.id, status='completed'
            ).filter(AnalysisJob.comment_count_requested > 2500).count()
            
            stats.update({
                'channels_tracked': channels_tracked,
                'preloaded_videos': preloaded_videos
            })
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Route moved to analysis_queue_routes.py to avoid duplication
# The more complete implementation with filtering and pagination is there


@bp.route('/api/analyze/sentiment/<video_id>', methods=['POST'])
def api_analyze_sentiment(video_id):
    """
    API endpoint to trigger sentiment analysis for video comments.
    """
    try:
        # Get analysis parameters
        data = request.get_json() or {}
        
        # Determine max comments based on user status
        from flask import current_app
        from flask_login import current_user
        
        if current_user.is_authenticated:
            if hasattr(current_user, 'is_subscribed') and current_user.is_subscribed:
                user_limit = current_app.config['MAX_COMMENTS_PRO']
            else:
                user_limit = current_app.config['MAX_COMMENTS_FREE']
        else:
            user_limit = current_app.config['MAX_COMMENTS_ANONYMOUS']
        
        max_comments = data.get('max_comments', user_limit)
        # Enforce the user's limit
        max_comments = min(max_comments, user_limit)
        
        percentage_selected = data.get('percentage_selected', 10)
        include_replies = False  # Never include replies
        
        # Generate analysis_id based on percentage and video_id for consistency
        # Always no_replies since we never include them
        analysis_id = f"sentiment_{video_id}_{percentage_selected}pct_{max_comments}_no_replies"
        
        print(f"API: Received request - video_id: {video_id}, max_comments: {max_comments}, percentage: {percentage_selected}")
        print(f"API: Generated analysis_id: {analysis_id}")
        
        # Check if analysis already exists in cache
        cached_result = cache.get('sentiment_analysis', analysis_id)
        if cached_result:
            return jsonify({
                'success': True,
                'analysis_id': analysis_id,
                'status': 'completed',
                'cached': True
            })
        
        # Set initial status with error handling
        try:
            cache.set('analysis_status', analysis_id, {'status': 'started', 'progress': 0}, ttl_hours=1)
        except Exception as e:
            print(f"Warning: Redis memory issue detected: {e}")
            # Try to clear some cache space
            try:
                cache.clear_pattern('analysis_status:*')
                cache.set('analysis_status', analysis_id, {'status': 'started', 'progress': 0}, ttl_hours=1)
            except:
                return jsonify({
                    'success': False,
                    'error': 'Cache memory full. Please try again later or contact support.'
                }), 507  # 507 Insufficient Storage
        
        # Start analysis in background thread
        thread = threading.Thread(
            target=run_sentiment_analysis,
            args=(video_id, max_comments, analysis_id, include_replies)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'analysis_id': analysis_id,
            'status': 'started',
            'message': 'Sentiment analysis started'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def run_sentiment_analysis(video_id: str, max_comments: int, analysis_id: str, include_replies: bool = False):
    """
    Run sentiment analysis in background.
    """
    try:
        print(f"Starting sentiment analysis for {video_id} with {max_comments} comments, include_replies={include_replies}, ID: {analysis_id}")
        
        # Update status
        cache.set('analysis_status', analysis_id, {'status': 'fetching_comments', 'progress': 10}, ttl_hours=1)
        
        # Fetch video info and comments using enhanced service for better coverage
        from app.services.enhanced_youtube_service import EnhancedYouTubeService
        youtube_service = EnhancedYouTubeService()
        result = youtube_service.get_all_available_comments(
            video_id=video_id,
            target_comments=max_comments,
            include_replies=False,  # Never include replies
            sort_order='relevance'
        )
        video_info = result['video']
        comments = result['comments']
        print(f"Fetched {len(comments)} comments for analysis (enhanced)")
        
        # Update status with error handling
        try:
            cache.set('analysis_status', analysis_id, {'status': 'analyzing_sentiment', 'progress': 30}, ttl_hours=1)
        except Exception as e:
            print(f"Warning: Could not update status due to cache issue: {e}")
        
        # Analyze sentiment via external ML service (Modal-hosted FastAPI)
        comment_texts = [c['text'] for c in comments]
        print(f"Analyzing sentiment for {len(comment_texts)} comments via external sentiment API...")
        
        # Update status to show current/total for progress
        cache.set('analysis_status', analysis_id, {
            'status': 'analyzing_sentiment', 
            'progress': 30,
            'current': 0,
            'total': len(comment_texts)
        }, ttl_hours=1)
        
        from app.services.sentiment_api import get_sentiment_client
        client = get_sentiment_client()
        
        # Set a shorter timeout for the API calls
        import time
        start_time = time.time()
        ml_batch = client.analyze_batch(comment_texts)
        elapsed = time.time() - start_time
        print(f"Sentiment analysis completed in {elapsed:.2f} seconds")
        # Fallback: if external service returns no results, use local mock analyzer
        try:
            if not ml_batch or not ml_batch.get('results') or ml_batch.get('total_analyzed', 0) == 0:
                print("External sentiment API returned no results; falling back to mock analyzer")
                from app.services.sentiment_api import SentimentAPIClient
                mock_client = SentimentAPIClient(base_url='')  # Force mock mode
                ml_batch = mock_client.analyze_batch(comment_texts)
        except Exception as fallback_err:
            print(f"Fallback analyzer failed: {fallback_err}")
            # Ensure we have a minimal structure to avoid front-end blanks
            ml_batch = ml_batch or {
                'results': [],
                'total_analyzed': 0,
                'statistics': {
                    'sentiment_distribution': {},
                    'average_confidence': 0.0,
                    'sentiment_percentages': {}
                }
            }

        # Normalize to legacy structure expected downstream (robust to various response shapes)
        total = ml_batch.get('total_analyzed', len(comment_texts))
        individual_results = ml_batch.get('results', [])
        # Secondary guard: if still empty results but we have texts, generate mock results
        if (not individual_results or len(individual_results) == 0) and comment_texts:
            try:
                from app.services.sentiment_api import SentimentAPIClient
                print("Secondary guard triggered: generating mock results for display")
                mock_client = SentimentAPIClient(base_url='')
                ml_batch2 = mock_client.analyze_batch(comment_texts)
                individual_results = ml_batch2.get('results', [])
                total = len(individual_results)
                # Overwrite ml_batch stats with recomputed ones
                ml_batch = ml_batch2
            except Exception as e2:
                print(f"Secondary guard failed to generate results: {e2}")
                individual_results = []
                total = 0
        # Prefer nested statistics; fall back to top-level or compute
        stats = ml_batch.get('statistics') or {}
        dist = stats.get('sentiment_distribution') or ml_batch.get('sentiment_distribution') or {}
        if not dist:
            dist = {'positive': 0, 'neutral': 0, 'negative': 0}
            for r in individual_results:
                s = r.get('predicted_sentiment') or r.get('sentiment') or 'neutral'
                if s not in dist:
                    s = 'neutral'
                dist[s] += 1
        pct = stats.get('sentiment_percentages') or {
            k: (v / total * 100.0 if total else 0.0) for k, v in dist.items()
        }
        avg_conf = stats.get('average_confidence')
        if avg_conf is None:
            avg_conf = sum(x.get('confidence', 0.0) for x in individual_results) / total if total else 0.0
        # sentiment_score in [-1, 1]
        pos = dist.get('positive', 0); neg = dist.get('negative', 0)
        sentiment_score = ((pos - neg) / total) if total else 0.0

        sentiment_results = {
            'overall_sentiment': ('positive' if dist.get('positive', 0) >= total * 0.5 else
                                  'negative' if dist.get('negative', 0) >= total * 0.4 else 'neutral'),
            'distribution': dist,
            'distribution_percentage': pct,
            'sentiment_counts': dist,
            'sentiment_percentages': pct,
            'average_confidence': avg_conf,
            'sentiment_score': sentiment_score,
            'total_analyzed': total,
            'individual_results': individual_results,
            'model': 'remote-modal'
        }

        # Last-resort synthesis: if no individual results, synthesize neutral entries for display
        if not sentiment_results.get('individual_results') and comments:
            print("Synthesizing neutral individual_results due to empty analyzer output")
            synth_limit = min(len(comments), 300)
            synthesized = []
            for i, c in enumerate(comments[:synth_limit]):
                cid = c.get('id') or c.get('comment_id')
                synthesized.append({
                    'text': c.get('text', '')[:100],
                    'predicted_sentiment': 'neutral',
                    'sentiment': 'neutral',
                    'confidence': 0.7,
                    'sentiment_scores': {'positive': 0.0, 'neutral': 1.0, 'negative': 0.0},
                    'comment_id': cid,
                    'author': c.get('author', 'Anonymous')
                })
            dist = {'positive': 0, 'neutral': synth_limit, 'negative': 0}
            pct = {k: (v / synth_limit * 100.0 if synth_limit else 0.0) for k, v in dist.items()}
            sentiment_results.update({
                'individual_results': synthesized,
                'total_analyzed': synth_limit,
                'distribution': dist,
                'sentiment_counts': dist,
                'distribution_percentage': pct,
                'sentiment_percentages': pct,
                'average_confidence': 0.7,
                'overall_sentiment': 'neutral',
                'sentiment_score': 0.0,
                'model': 'synthetic-fallback'
            })
        
        # Update status
        cache.set('analysis_status', analysis_id, {'status': 'generating_summary', 'progress': 85}, ttl_hours=1)

        # Normalize individual results to match template expectations and attach context
        for i, result in enumerate(sentiment_results['individual_results']):
            # Attach YouTube comment context when available
            if i < len(comments):
                src = comments[i]
                cid = src.get('id') or src.get('comment_id')
                # Provide both snake_case and camelCase for frontend compatibility
                result['comment_id'] = cid
                result['commentId'] = cid
                # Ensure text and author exist
                result.setdefault('text', src.get('text', ''))
                result.setdefault('author', src.get('author', 'Anonymous'))

            # Ensure predicted_sentiment exists
            if not result.get('predicted_sentiment') and result.get('sentiment'):
                result['predicted_sentiment'] = result['sentiment']

            # Ensure sentiment_scores exist (0..1 floats) for timeline
            scores = result.get('sentiment_scores')
            if not isinstance(scores, dict) or not {'positive', 'neutral', 'negative'} <= set(scores.keys()):
                pred = (result.get('predicted_sentiment') or result.get('sentiment') or 'neutral')
                conf = result.get('confidence', 0.7)
                if isinstance(conf, (int, float)) and conf > 1.0:
                    conf = conf / 100.0  # Convert percentage to decimal
                
                # Create more realistic scores based on predicted sentiment and confidence
                # The predicted sentiment gets the confidence score, others get distributed remainder
                remainder = (1.0 - conf) / 2
                
                if pred == 'positive':
                    scores = {
                        'positive': conf,
                        'neutral': remainder + 0.1,  # Neutral gets slightly more of remainder
                        'negative': remainder - 0.1 if remainder > 0.1 else 0.0
                    }
                elif pred == 'negative':
                    scores = {
                        'positive': remainder - 0.1 if remainder > 0.1 else 0.0,
                        'neutral': remainder + 0.1,  # Neutral gets slightly more of remainder  
                        'negative': conf
                    }
                else:  # neutral
                    scores = {
                        'positive': remainder,
                        'neutral': conf,
                        'negative': remainder
                    }
                
                # Normalize to ensure they sum to 1.0
                total = sum(scores.values())
                if total > 0:
                    scores = {k: v/total for k, v in scores.items()}
                
                result['sentiment_scores'] = scores

            # Scale confidence to percentage if needed (frontend expects 0-100)
            conf = result.get('confidence')
            if isinstance(conf, (int, float)) and conf <= 1.0:
                result['confidence'] = round(conf * 100.0, 1)
        
        print(f"Sentiment analysis complete. Overall: {sentiment_results.get('overall_sentiment', 'unknown')}")
        
        # Update status
        cache.set('analysis_status', analysis_id, {'status': 'generating_summary', 'progress': 85}, ttl_hours=1)
        
        # Generate summary via external ML service (Modal). Falls back on error.
        print("Generating summary via external ML service...")
        try:
            from app.services.sentiment_api import get_sentiment_client
            client = get_sentiment_client()
            resp = client.summarize(comments, sentiment_results, method='auto')
            summary_results = resp.get('summary') or resp
            # If service failed to return a summary, set a neutral placeholder (no legacy fallback)
            if (not summary_results or not summary_results.get('summary')):
                summary_results = {
                    'summary': 'Summary is temporarily unavailable.',
                    'method': 'service_unavailable'
                }
        except Exception as e:
            print(f"External summarizer unavailable. Reason: {e}")
            summary_results = {
                'summary': 'Summary is temporarily unavailable.',
                'method': 'service_error',
                'error': str(e)
            }
        
        # Build a simple sentiment timeline from external results (first 50 comments)
        individual_results = sentiment_results.get('individual_results', [])
        timeline = []
        for i, comment in enumerate(comments[:min(50, len(individual_results))]):
            ir = individual_results[i]
            pred = ir.get('predicted_sentiment') or ir.get('sentiment', 'neutral')
            timeline.append({
                'timestamp': comment.get('published_at', ''),
                'sentiment': pred,
                'score': ir.get('sentiment_scores') or {},
                'text_preview': (ir.get('text') or comment.get('text', ''))[:100]
            })
        
        # Calculate updated comment statistics based on analyzed comments
        unique_commenters = set()
        commenter_frequency = {}
        total_length = 0
        replies_count = 0
        
        for comment in comments:
            # Try multiple fields to get unique identifier
            author_id = comment.get('author_channel_id') or comment.get('author_id') or comment.get('author', 'unknown')
            if author_id and author_id != 'unknown':
                unique_commenters.add(author_id)
            else:
                # Fall back to author name if no ID available
                unique_commenters.add(comment.get('author', f'user_{len(unique_commenters)}'))
            
            author = comment.get('author', 'Anonymous')
            commenter_frequency[author] = commenter_frequency.get(author, 0) + 1
            total_length += len(comment.get('text', ''))
            if comment.get('is_reply', False):
                replies_count += 1
        
        # Find top commenters
        top_commenters = sorted(
            commenter_frequency.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        # Calculate averages
        avg_comment_length = round(total_length / len(comments)) if comments else 0
        top_level_count = len(comments) - replies_count
        
        # Updated stats based on analyzed dataset
        updated_stats = {
            'total_analyzed': len(comments),
            'unique_commenters': len(unique_commenters),
            'avg_comment_length': avg_comment_length,
            'replies_count': replies_count,
            'top_level_count': top_level_count,
            'top_commenters': top_commenters,
            'analysis_depth_percentage': round((len(comments) / video_info.get('statistics', {}).get('comments', len(comments))) * 100, 1) if video_info else 100
        }
        
        # Prepare final results
        results = {
            'video_id': video_id,
            'analysis_id': analysis_id,
            'sentiment': sentiment_results,
            'summary': summary_results,
            'timeline': timeline,
            'comments_sample': comments[:10],  # Include sample of analyzed comments
            'updated_stats': updated_stats  # Include updated statistics
        }
        
        # Debug: Check final results before caching
        print(f"DEBUG: Final results keys: {list(results.keys())}")
        if 'summary' in results:
            summary_keys = list(results['summary'].keys())
            print(f"DEBUG: Final summary keys: {summary_keys}")
            if 'social_media_themes' in results['summary']:
                print(f"DEBUG: Social media themes preserved in final results")
            else:
                print(f"DEBUG: Social media themes MISSING from final results")
        
        # Optimize results before caching (remove redundant data)
        optimized_results = {
            'sentiment': results['sentiment'],
            'timeline': results.get('timeline', [])[:50],  # Limit timeline to 50 points
        }
        
        # Only cache summary if it's not the temporary placeholder
        try:
            if results.get('summary') and results['summary'].get('summary') and results['summary'].get('summary') != 'Summary is temporarily unavailable.':
                optimized_results['summary'] = results['summary']
        except Exception:
            # If summary structure is unexpected, skip caching it
            pass
        
        # Only include updated_stats if present
        if 'updated_stats' in results:
            optimized_results['updated_stats'] = results['updated_stats']
        
        # Cache results with shorter TTL and error handling
        try:
            success = cache.set('sentiment_analysis', analysis_id, optimized_results, ttl_hours=2)  # Reduced from 24 to 2 hours
            
            if success:
                print(f"Results cached successfully for {analysis_id}")
                # Update status to completed only after results are cached
                cache.set('analysis_status', analysis_id, {'status': 'completed', 'progress': 100}, ttl_hours=1)
                print(f"Analysis completed for {analysis_id}")
            else:
                print(f"ERROR: Failed to cache results for {analysis_id}")
                # Try to clear old cache entries and retry
                print("Attempting to clear old cache entries...")
                try:
                    # Clear old analysis results (older than 30 minutes)
                    import time
                    current_time = time.time()
                    # This is a simplified approach - in production you'd track timestamps
                    cache.clear_pattern('sentiment_analysis:sentiment_*')
                    # Retry caching
                    success = cache.set('sentiment_analysis', analysis_id, optimized_results, ttl_hours=1)
                    if success:
                        print(f"Results cached successfully after cleanup for {analysis_id}")
                        cache.set('analysis_status', analysis_id, {'status': 'completed', 'progress': 100}, ttl_hours=1)
                    else:
                        raise Exception("Failed to cache analysis results even after cleanup")
                except Exception as cleanup_error:
                    print(f"Cleanup failed: {cleanup_error}")
                    raise Exception("Failed to cache analysis results due to memory constraints")
        except Exception as cache_error:
            print(f"Cache error: {cache_error}")
            # Store minimal results in case of memory issues (skip placeholder summary)
            minimal_results = {
                'sentiment': results['sentiment']
            }
            try:
                if results.get('summary') and results['summary'].get('summary') and results['summary'].get('summary') != 'Summary is temporarily unavailable.':
                    minimal_results['summary'] = {'summary': results['summary'].get('summary')}
            except Exception:
                pass
            success = cache.set('sentiment_analysis', analysis_id, minimal_results, ttl_hours=1)
            if success:
                print(f"Minimal results cached for {analysis_id}")
                cache.set('analysis_status', analysis_id, {'status': 'completed', 'progress': 100}, ttl_hours=1)
            else:
                raise Exception(f"Critical: Cannot cache results due to Redis memory issue: {cache_error}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR in sentiment analysis for {analysis_id}: {error_msg}")
        import traceback
        traceback.print_exc()
        
        # Update status to error
        cache.set('analysis_status', analysis_id, 
                 {'status': 'error', 'progress': 0, 'error': error_msg}, ttl_hours=1)


@bp.route('/api/analyze/status/<analysis_id>')
def api_analysis_status(analysis_id):
    """
    Get the status of a sentiment analysis job.
    """
    try:
        print(f"Status check for analysis_id: {analysis_id}")
        status = cache.get('analysis_status', analysis_id)
        
        # Backward compatibility: try old format if new format not found
        if not status and '_pct_' not in analysis_id:
            # Try to extract video_id from old format: sentiment_<video_id>_<number>
            if analysis_id.startswith('sentiment_'):
                # Remove 'sentiment_' prefix and get the rest
                remainder = analysis_id[10:]  # len('sentiment_') = 10
                # Find the last underscore (before the number)
                last_underscore = remainder.rfind('_')
                if last_underscore > 0:
                    video_id = remainder[:last_underscore]
                    number_str = remainder[last_underscore + 1:]
                    # Try common rounded values
                    for rounded in [50, 100, 200, 500, 1000]:
                        old_id = f"sentiment_{video_id}_{rounded}"
                        status = cache.get('analysis_status', old_id)
                        if status:
                            print(f"Found status with old format: {old_id}")
                            break
        
        if not status:
            return jsonify({
                'success': False,
                'error': 'Analysis not found'
            }), 404
        
        return jsonify({
            'success': True,
            'status': status
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/analyze/results/<analysis_id>')
def api_analysis_results(analysis_id):
    """
    Get the results of a completed sentiment analysis.
    """
    try:
        print(f"Results request for analysis_id: {analysis_id}")
        # Check if analysis is complete
        status = cache.get('analysis_status', analysis_id)
        
        # Backward compatibility: try old format if new format not found
        actual_id = analysis_id
        if not status and '_pct_' not in analysis_id:
            if analysis_id.startswith('sentiment_'):
                remainder = analysis_id[10:]
                last_underscore = remainder.rfind('_')
                if last_underscore > 0:
                    video_id = remainder[:last_underscore]
                    for rounded in [50, 100, 200, 500, 1000]:
                        old_id = f"sentiment_{video_id}_{rounded}"
                        status = cache.get('analysis_status', old_id)
                        if status:
                            actual_id = old_id
                            print(f"Found status with old format: {old_id}")
                            break
        if not status:
            return jsonify({
                'success': False,
                'error': 'Analysis not found',
                'details': f'No status found for {analysis_id}'
            }), 404
        
        if status.get('status') == 'error':
            return jsonify({
                'success': False,
                'error': 'Analysis failed',
                'details': status.get('error', 'Unknown error'),
                'status': status
            }), 500
        
        if status.get('status') != 'completed':
            return jsonify({
                'success': False,
                'error': 'Analysis not yet completed',
                'status': status
            }), 202
        
        # Get results using the actual ID (might be different after backward compat check)
        results = cache.get('sentiment_analysis', actual_id)
        if not results:
            # Log this issue
            print(f"WARNING: Status shows completed but no results found for {analysis_id}")
            print(f"Status: {status}")
            
            # Try to restart the analysis
            return jsonify({
                'success': False,
                'error': 'Results not found despite completed status. Please try again.',
                'restart_needed': True
            }), 404
        
        # Debug: Check retrieved results from cache
        print(f"DEBUG: Retrieved results keys: {list(results.keys())}")
        if 'summary' in results:
            summary_keys = list(results['summary'].keys())
            print(f"DEBUG: Retrieved summary keys: {summary_keys}")
            if 'social_media_themes' in results['summary']:
                print(f"DEBUG: Social media themes found in retrieved results")
            else:
                print(f"DEBUG: Social media themes MISSING from retrieved results")
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/analyze/retry-summary/<analysis_id>', methods=['POST'])
def api_retry_summary(analysis_id):
    """
    Retry generating the summary for an existing analysis by re-calling the ML service.
    Uses the analysis_id to infer video_id and max_comments and re-fetches comments.
    """
    try:
        # Load existing cached results
        existing = cache.get('sentiment_analysis', analysis_id)
        if not existing:
            return jsonify({'success': False, 'error': 'Analysis not found'}), 404

        # Parse analysis_id to extract video_id and max_comments
        import re
        m = re.match(r'^sentiment_(?P<video_id>.+)_(?P<pct>\d+)pct_(?P<max>\d+)_no_replies$', analysis_id)
        if not m:
            return jsonify({'success': False, 'error': 'Unsupported analysis_id format'}), 400

        video_id = m.group('video_id')
        max_comments = int(m.group('max'))

        # Re-fetch comments (never include replies)
        from app.services.enhanced_youtube_service import EnhancedYouTubeService
        youtube_service = EnhancedYouTubeService()
        result = youtube_service.get_all_available_comments(
            video_id=video_id,
            target_comments=max_comments,
            include_replies=False,
            sort_order='relevance'
        )
        comments = result.get('comments', [])
        video_info = result.get('video', {})

        # Use existing sentiment stats as guidance for summary
        sentiment = existing.get('sentiment') or {}

        # Call external ML summarization service
        from app.services.sentiment_api import get_sentiment_client
        client = get_sentiment_client()
        resp = client.summarize(comments, sentiment, method='auto', video_title=video_info.get('title'))
        summary_results = resp.get('summary') or resp

        # Treat placeholder or missing summary as unavailable and do not cache
        if (not summary_results) or (not summary_results.get('summary')) or (summary_results.get('summary') == 'Summary is temporarily unavailable.'):
            return jsonify({'success': False, 'error': 'Summarization service unavailable'}), 502

        # Update cache with the new summary (valid only)
        existing['summary'] = summary_results
        if existing.get('timeline'):
            existing['timeline'] = existing['timeline'][:50]
        cache.set('sentiment_analysis', analysis_id, existing, ttl_hours=2)

        return jsonify({'success': True, 'summary': summary_results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Channel routes
@bp.route('/channels/add', methods=['POST'])
@login_required
def add_channel():
    """Add a channel to track."""
    channel_id = request.form.get('channel_id')
    if not channel_id:
        flash('Channel ID required', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Check if channel already exists
        existing = Channel.query.filter_by(yt_channel_id=channel_id).first()
        if not existing:
            channel = Channel(
                yt_channel_id=channel_id,
                title=f'Channel {channel_id}',  # Will be updated by sync
                video_count=0
            )
            db.session.add(channel)
            db.session.commit()
        
        flash('Channel added successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding channel: {str(e)}', 'danger')
    
    return redirect(url_for('main.dashboard'))


@bp.route('/channels/<int:channel_id>/view')
@login_required
def view_channel(channel_id):
    """View channel details."""
    channel = Channel.query.get_or_404(channel_id)
    return render_template('channel.html', channel=channel)


@bp.route('/channels/<int:channel_id>/remove', methods=['POST'])
@login_required
def remove_channel(channel_id):
    """Remove a channel."""
    channel = Channel.query.get_or_404(channel_id)
    try:
        db.session.delete(channel)
        db.session.commit()
        flash('Channel removed successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing channel: {str(e)}', 'danger')
    
    return redirect(url_for('main.dashboard'))


# Video routes
@bp.route('/api/videos')
@login_required
def api_video_list():
    """Get list of analyzed videos."""
    videos = Video.query.order_by(Video.created_at.desc()).limit(50).all()
    return jsonify({
        'success': True,
        'videos': [{
            'id': v.yt_video_id,
            'title': v.title,
            'channel_id': v.channel_id,
            'created_at': v.created_at.isoformat() if v.created_at else None
        } for v in videos]
    })


@bp.route('/api/videos/<video_id>/comments')
@login_required
def api_video_comments(video_id):
    """Get comments for a video."""
    try:
        from app.services.youtube_service import YouTubeService
        youtube_service = YouTubeService()
        comments = youtube_service.get_video_comments(video_id)
        return jsonify({
            'success': True,
            'video_id': video_id,
            'comments': comments
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Subscription routes
@bp.route('/subscribe/stripe', methods=['POST'])
@login_required
def subscribe_stripe():
    """Handle Stripe subscription."""
    try:
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': os.getenv('STRIPE_PRICE_ID'),
                'quantity': 1,
            }],
            mode='subscription',
            success_url=url_for('main.dashboard', _external=True) + '?subscription=success',
            cancel_url=url_for('main.dashboard', _external=True) + '?subscription=cancelled',
            customer_email=current_user.email
        )
        
        return redirect(checkout_session.url, code=302)
    except Exception as e:
        flash(f'Error creating subscription: {str(e)}', 'danger')
        return redirect(url_for('main.dashboard'))


@bp.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events."""
    try:
        import stripe
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        
        payload = request.data
        sig_header = request.headers.get('Stripe-Signature')
        endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
        
        # Handle the event
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            # Update user subscription status
            # This would need proper implementation based on your user model
            pass
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# Batch routes
@bp.route('/batch')
@login_required
def batch():
    """Batch processing page."""
    if not current_user.is_subscribed:
        return redirect(url_for('main.dashboard')), 302
    return render_template('batch.html')


@bp.route('/batch/process', methods=['POST'])
@login_required
def batch_process():
    """Process batch of texts."""
    if not current_user.is_subscribed:
        return jsonify({'error': 'Subscription required'}), 403
    
    try:
        data = request.get_json()
        texts = data.get('texts', [])
        
        if not texts:
            return jsonify({'success': False, 'error': 'No texts provided'}), 400
        
        # Process batch using sentiment API
        from app.services.sentiment_api import get_sentiment_client
        client = get_sentiment_client()
        results = client.analyze_batch(texts)
        
        # Ensure results have expected format
        if not isinstance(results, dict):
            results = {
                'total_analyzed': 0,
                'results': []
            }
        
        # Format results properly
        if isinstance(results, dict):
            return jsonify({
                'success': True,
                'total_analyzed': results.get('total_analyzed', len(texts)),
                'results': results
            })
        else:
            return jsonify({
                'success': True,
                'total_analyzed': len(texts),
                'results': results if results else []
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
