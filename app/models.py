from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from flask import current_app
import jwt
import uuid
from app import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_subscribed = db.Column(db.Boolean, default=False)
    provider = db.Column(db.String(50))  # 'stripe' or 'paypal'
    customer_id = db.Column(db.String(255))  # Stripe customer ID or PayPal subscriber ID
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Database-based password reset fields
    reset_token = db.Column(db.String(255), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
    
    def get_reset_password_token(self, expires_in=3600):
        """Generate a password reset token that expires in `expires_in` seconds (default: 60 minutes)."""
        import secrets
        import string
        
        # Generate a secure random token
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(64))
        
        # Store in database with expiration
        self.reset_token = token
        self.reset_token_expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=expires_in)
        db.session.commit()
        
        current_app.logger.info(f'✅ Generated database reset token for {self.email}')
        return token
    
    @staticmethod
    def verify_reset_password_token(token):
        """Verify a password reset token and return the user if valid."""
        try:
            current_app.logger.info(f'🔍 Verifying database token: {token[:20]}...')
            
            # Look up user by token in database
            user = User.query.filter_by(reset_token=token).first()
            
            if not user:
                current_app.logger.warning('❌ No user found with this reset token')
                return None
            
            # Check if token has expired
            if user.reset_token_expires and user.reset_token_expires < datetime.now(timezone.utc).replace(tzinfo=None):
                current_app.logger.warning(f'⏰ Reset token expired for {user.email}')
                # Clear expired token
                user.reset_token = None
                user.reset_token_expires = None
                db.session.commit()
                return None
            
            current_app.logger.info(f'✅ Valid reset token found for {user.email}')
            return user
            
        except Exception as e:
            current_app.logger.error(f'❌ Error verifying reset token: {str(e)}')
            return None
    
    def clear_reset_token(self):
        """Clear the password reset token after use."""
        self.reset_token = None
        self.reset_token_expires = None
        db.session.commit()
        current_app.logger.info(f'✅ Cleared reset token for {self.email}')


class Channel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yt_channel_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    handle = db.Column(db.String(255), nullable=True, index=True)
    uploads_playlist_id = db.Column(db.String(255), nullable=True)
    latest_video_id = db.Column(db.String(64), nullable=True)
    video_count = db.Column(db.Integer, default=0)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yt_video_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    published_at = db.Column(db.DateTime, nullable=True, index=True)
    views = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    comments = db.Column(db.Integer, default=0)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    comments_disabled = db.Column(db.Boolean, nullable=False, default=False)
    comments_synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class UserChannel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'channel_id', name='uq_user_channel'),
    )


class AnalysisJob(db.Model):
    """Track queued sentiment analysis jobs for background processing."""
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(100), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Video information
    video_id = db.Column(db.String(20), nullable=False)
    video_title = db.Column(db.Text, nullable=True)
    video_url = db.Column(db.String(500), nullable=True)
    channel_name = db.Column(db.String(200), nullable=True)
    
    # Job details
    comment_count_requested = db.Column(db.Integer, nullable=False)
    comment_count_processed = db.Column(db.Integer, default=0)
    include_replies = db.Column(db.Boolean, default=True, nullable=False)  # Whether to include reply threads
    status = db.Column(db.String(50), nullable=False, default='queued', index=True)
    # Status values: queued, processing, completed, failed, cancelled
    progress = db.Column(db.Integer, default=0)  # 0-100 percentage
    error_message = db.Column(db.Text, nullable=True)
    
    # Results storage
    results = db.Column(db.JSON, nullable=True)  # Store full analysis results
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    processing_time_seconds = db.Column(db.Float, nullable=True)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('analysis_jobs', lazy='dynamic'))
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.job_id:
            self.job_id = f"job_{uuid.uuid4().hex[:12]}_{self.video_id}"
    
    def to_dict(self):
        """Convert job to dictionary for API responses."""
        # Calculate queue position if queued
        queue_position = None
        estimated_wait_time = None
        estimated_processing_time = None
        
        if self.status == 'queued':
            # Count jobs ahead in queue
            from datetime import datetime, timezone
            queue_position = AnalysisJob.query.filter(
                AnalysisJob.status == 'queued',
                AnalysisJob.created_at < self.created_at
            ).count() + 1
            
            # Count currently processing jobs
            processing_count = AnalysisJob.query.filter_by(status='processing').count()
            
            # Estimate time based on average processing time and queue position
            # Fetch time: ~1 second per 100 comments
            # Analysis time: ~0.5 seconds per 100 comments  
            # Total: ~1.5 seconds per 100 comments
            estimated_processing_time = (self.comment_count_requested / 100) * 1.5
            
            # Get average processing time from recent jobs
            recent_jobs = AnalysisJob.query.filter(
                AnalysisJob.status == 'completed',
                AnalysisJob.processing_time_seconds.isnot(None)
            ).order_by(AnalysisJob.completed_at.desc()).limit(10).all()
            
            if recent_jobs:
                avg_time = sum(j.processing_time_seconds for j in recent_jobs) / len(recent_jobs)
                # Use actual average if available
                estimated_processing_time = avg_time
            
            # Wait time = (position - 1) * average processing time + current job time
            if processing_count > 0:
                # Add time for currently processing job (assume 50% complete)
                estimated_wait_time = estimated_processing_time * 0.5
            else:
                estimated_wait_time = 0
                
            # Add time for jobs ahead in queue
            if queue_position > 1:
                estimated_wait_time += (queue_position - 1) * estimated_processing_time
        
        elif self.status == 'processing' and self.started_at:
            # For processing jobs, estimate remaining time
            from datetime import datetime, timezone
            elapsed = (datetime.now(timezone.utc).replace(tzinfo=None) - self.started_at).total_seconds()
            if self.progress > 0:
                total_estimated = (elapsed / self.progress) * 100
                estimated_processing_time = total_estimated - elapsed
            else:
                estimated_processing_time = (self.comment_count_requested / 100) * 1.5
        
        return {
            'job_id': self.job_id,
            'video_id': self.video_id,
            'video_title': self.video_title,
            'channel_name': self.channel_name,
            'comment_count_requested': self.comment_count_requested,
            'comment_count_processed': self.comment_count_processed,
            'include_replies': self.include_replies,
            'status': self.status,
            'progress': self.progress,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'processing_time_seconds': self.processing_time_seconds,
            'has_results': bool(self.results),
            'queue_position': queue_position,
            'estimated_wait_time': estimated_wait_time,
            'estimated_processing_time': estimated_processing_time
        }


class SentimentFeedback(db.Model):
    """Store user feedback on sentiment predictions for model training."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)  # Nullable for anonymous feedback
    video_id = db.Column(db.String(64), nullable=False, index=True)
    comment_id = db.Column(db.String(128), nullable=True, index=True)  # YouTube comment ID if available
    comment_text = db.Column(db.Text, nullable=False)  # Store the actual comment text
    comment_author = db.Column(db.String(255), nullable=True)  # Store author for context
    
    # Sentiment labels
    predicted_sentiment = db.Column(db.String(20), nullable=False)  # What our model predicted
    corrected_sentiment = db.Column(db.String(20), nullable=False)  # What the user says it should be
    confidence_score = db.Column(db.Float, nullable=True)  # Model's confidence in its prediction
    
    # Metadata
    session_id = db.Column(db.String(128), nullable=True)  # Track feedback within a session
    ip_hash = db.Column(db.String(64), nullable=True)  # Hashed IP for spam prevention
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    
    # Training status
    used_for_training = db.Column(db.Boolean, default=False, index=True)  # Track if used in model retraining
    training_batch = db.Column(db.String(64), nullable=True)  # Batch ID when used for training
    
    __table_args__ = (
        # Prevent duplicate feedback for the same comment from the same user/session
        db.UniqueConstraint('user_id', 'video_id', 'comment_text', name='uq_user_comment_feedback'),
        db.UniqueConstraint('session_id', 'video_id', 'comment_text', name='uq_session_comment_feedback'),
        # Index for efficient training data queries
        db.Index('idx_training_queries', 'used_for_training', 'created_at'),
    )


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AdminSession(db.Model):
    """Server-side administrator session. The cookie stores only an unguessable id."""
    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)


class LoginAttempt(db.Model):
    """Shared login-failure record so every worker enforces the same limit."""
    id = db.Column(db.Integer, primary_key=True)
    ip_hash = db.Column(db.String(64), nullable=False, index=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False, index=True)


class CollectionJob(db.Model):
    """Resumable YouTube collection cursor. One row is one channel walk."""
    id = db.Column(db.Integer, primary_key=True)
    channel_ref = db.Column(db.String(500), nullable=False)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    phase = db.Column(db.String(32), nullable=False, default='channel')
    page_token = db.Column(db.String(255), nullable=True)
    saved_next_thread_token = db.Column(db.String(255), nullable=True)
    current_video_yt_id = db.Column(db.String(64), nullable=True)
    reply_parent_id = db.Column(db.String(128), nullable=True)
    reply_page_token = db.Column(db.String(255), nullable=True)
    pending_reply_ids = db.Column(db.JSON, nullable=True)
    api_steps = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)
    lease_owner = db.Column(db.String(64), nullable=True)
    lease_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class CollectedComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yt_comment_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False, index=True)
    parent_yt_comment_id = db.Column(db.String(128), nullable=True, index=True)
    text = db.Column(db.Text, nullable=False, default='')
    author_display = db.Column(db.String(255), nullable=True)
    like_count = db.Column(db.Integer, nullable=False, default=0)
    published_at = db.Column(db.DateTime, nullable=True, index=True)
    reply_count = db.Column(db.Integer, nullable=False, default=0)
    replies_complete = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    video = db.relationship('Video', backref=db.backref('collected_comments', lazy='dynamic'))


class CommentTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('collected_comment.id'), nullable=False, index=True)
    tag = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('comment_id', 'tag', name='uq_comment_tag'),
    )


class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False, index=True)
    label = db.Column(db.String(255), nullable=False)
    keywords = db.Column(db.String(500), nullable=True)
    method = db.Column(db.String(32), nullable=False, default='local')
    comment_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)


class CommentTopic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('collected_comment.id'), nullable=False, unique=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=False, index=True)
    confidence = db.Column(db.Float, nullable=False, default=0.0)

    topic = db.relationship('Topic')


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
