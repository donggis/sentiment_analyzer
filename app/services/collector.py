"""Paginated, resumable collection of one channel's public videos and comments."""
import re
import secrets
from datetime import timedelta

from app import db
from app.models import Channel, CollectedComment, CollectionJob, Video, _utcnow
from app.services.clustering import cluster_channel
from app.services.youtube_api import YouTubeError, parse_published

HANDLE_RE = re.compile(r'youtube\.com/@([\w.-]+)', re.IGNORECASE)
CHANNEL_RE = re.compile(r'youtube\.com/channel/(UC[\w-]+)', re.IGNORECASE)
USER_RE = re.compile(r'youtube\.com/user/([\w-]+)', re.IGNORECASE)
TAG_RE = re.compile(r'<[^>]+>')


def parse_channel_ref(ref):
    text = (ref or '').strip()
    if not text:
        raise YouTubeError('channel reference is empty', reason='invalid')
    if text.startswith('@'):
        return {'handle': text}
    channel_match = CHANNEL_RE.search(text)
    if channel_match:
        return {'channel_id': channel_match.group(1)}
    handle_match = HANDLE_RE.search(text)
    if handle_match:
        return {'handle': '@' + handle_match.group(1)}
    user_match = USER_RE.search(text)
    if user_match:
        return {'username': user_match.group(1)}
    if re.fullmatch(r'UC[\w-]{20,}', text):
        return {'channel_id': text}
    return {'handle': text if text.startswith('@') else '@' + text}


def clean_text(value):
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', value or '')).strip()


def _lock(job, owner):
    now = _utcnow()
    if job.lease_until and job.lease_until > now and job.lease_owner and job.lease_owner != owner:
        return False
    job.lease_owner = owner
    job.lease_until = now + timedelta(seconds=120)
    job.status = 'running'
    job.error_message = None
    db.session.commit()
    return True


def _upsert_video(channel, item, details=None):
    details = details or {}
    row = Video.query.filter_by(yt_video_id=item['video_id']).first()
    if row is None:
        row = Video(
            yt_video_id=item['video_id'],
            channel_id=channel.id,
            title=details.get('title') or item.get('title') or item['video_id'],
        )
        db.session.add(row)
    row.channel_id = channel.id
    row.title = details.get('title') or item.get('title') or row.title
    published = details.get('published_at') or item.get('published_at')
    if published:
        row.published_at = parse_published(published)
    if 'views' in details:
        row.views = int(details.get('views') or 0)
        row.likes = int(details.get('likes') or 0)
        row.comments = int(details.get('comments') or 0)
    if details.get('duration_seconds') is not None:
        row.duration_seconds = details.get('duration_seconds')
    row.last_synced_at = _utcnow()
    return row


def _upsert_comment(video, payload, parent_id=None, reply_count=0, replies_complete=True):
    yt_id = payload.get('id')
    if not yt_id:
        return None
    row = CollectedComment.query.filter_by(yt_comment_id=yt_id).first()
    if row is None:
        row = CollectedComment(yt_comment_id=yt_id, video_id=video.id, text='')
        db.session.add(row)
    row.video_id = video.id
    row.text = clean_text(payload.get('text'))
    author = (payload.get('author') or '').strip()
    row.author_display = author[:255] or None
    row.like_count = int(payload.get('likes') or 0)
    row.published_at = parse_published(payload.get('published_at'))
    row.parent_yt_comment_id = parent_id
    if parent_id is None:
        row.reply_count = int(reply_count or 0)
        row.replies_complete = bool(replies_complete)
    return row


def _step_channel(job, api):
    ref = parse_channel_ref(job.channel_ref)
    data = api.get_channel(**ref)
    channel = Channel.query.filter_by(yt_channel_id=data['id']).first()
    if channel is None:
        channel = Channel(yt_channel_id=data['id'], title=data.get('title') or data['id'])
        db.session.add(channel)
    channel.title = data.get('title') or channel.title
    if ref.get('handle'):
        channel.handle = ref['handle']
    channel.uploads_playlist_id = data['uploads_playlist_id']
    channel.video_count = int(data.get('video_count') or 0)
    channel.last_synced_at = _utcnow()
    db.session.flush()
    job.channel_id = channel.id
    job.phase = 'videos'
    job.page_token = None
    return 1


def _step_videos(job, api):
    channel = db.session.get(Channel, job.channel_id)
    response = api.list_uploads(channel.uploads_playlist_id, job.page_token)
    items = response.get('items') or []
    details = api.list_videos([item['video_id'] for item in items]) if items else {}
    for item in items:
        _upsert_video(channel, item, details.get(item['video_id']))
    job.page_token = response.get('next_page_token')
    if not job.page_token:
        job.phase = 'comments'
        job.current_video_yt_id = None
    return 1


def _finish_video(job, video):
    video.comments_synced_at = _utcnow()
    job.current_video_yt_id = None
    job.page_token = None
    job.saved_next_thread_token = None
    job.reply_parent_id = None
    job.reply_page_token = None
    job.pending_reply_ids = []


def _advance_after_replies(job, video):
    pending = list(job.pending_reply_ids or [])
    if pending:
        job.reply_parent_id = pending.pop(0)
        job.pending_reply_ids = pending
        job.reply_page_token = None
        return
    job.reply_parent_id = None
    job.reply_page_token = None
    if job.saved_next_thread_token:
        job.page_token = job.saved_next_thread_token
        job.saved_next_thread_token = None
        return
    _finish_video(job, video)


def _step_replies(job, api, video):
    response = api.list_replies(job.reply_parent_id, job.reply_page_token)
    for item in response.get('items') or []:
        _upsert_comment(video, item, parent_id=job.reply_parent_id)
    parent = CollectedComment.query.filter_by(yt_comment_id=job.reply_parent_id).first()
    if response.get('next_page_token'):
        job.reply_page_token = response['next_page_token']
        if parent is not None:
            parent.replies_complete = False
        return 1
    if parent is not None:
        parent.replies_complete = True
    _advance_after_replies(job, video)
    return 1


def _step_threads(job, api):
    if job.current_video_yt_id:
        video = Video.query.filter_by(yt_video_id=job.current_video_yt_id, channel_id=job.channel_id).first()
    else:
        video = (
            Video.query.filter_by(channel_id=job.channel_id, comments_synced_at=None)
            .order_by(Video.id)
            .first()
        )
    if video is None:
        job.phase = 'cluster'
        job.current_video_yt_id = None
        job.page_token = None
        return 0
    job.current_video_yt_id = video.yt_video_id
    if job.reply_parent_id:
        return _step_replies(job, api, video)
    try:
        response = api.list_threads(video.yt_video_id, job.page_token)
    except YouTubeError as exc:
        if exc.reason != 'commentsDisabled':
            raise
        video.comments_disabled = True
        _finish_video(job, video)
        return 1
    pending = []
    for item in response.get('items') or []:
        replies = item.get('replies') or []
        reply_count = int(item.get('reply_count') or 0)
        complete = reply_count <= len(replies)
        _upsert_comment(video, item, reply_count=reply_count, replies_complete=complete)
        for reply in replies:
            _upsert_comment(video, reply, parent_id=item.get('id'))
        if not complete and item.get('id'):
            pending.append(item['id'])
    job.pending_reply_ids = pending
    job.saved_next_thread_token = response.get('next_page_token')
    if pending:
        job.reply_parent_id = pending.pop(0)
        job.pending_reply_ids = pending
        job.reply_page_token = None
        return 1
    if response.get('next_page_token'):
        job.page_token = response['next_page_token']
        return 1
    _finish_video(job, video)
    return 1


def _one_step(job, api):
    if job.phase == 'channel':
        return _step_channel(job, api)
    if job.phase == 'videos':
        return _step_videos(job, api)
    if job.phase == 'comments':
        return _step_threads(job, api)
    if job.phase == 'cluster':
        if job.channel_id:
            cluster_channel(job.channel_id)
        job.phase = 'done'
        job.status = 'completed'
        return 0
    job.phase = 'done'
    job.status = 'completed'
    return 0


def run_collection(job_id, api, max_steps=None):
    """Advance one job. max_steps limits API pages so a request can resume later."""
    owner = secrets.token_hex(8)
    job = db.session.get(CollectionJob, job_id)
    if job is None:
        raise YouTubeError('collection job not found', reason='notFound', status=404)
    if job.phase == 'done':
        job.status = 'completed'
        db.session.commit()
        return job
    if not _lock(job, owner):
        return job
    steps = 0
    try:
        while True:
            job = db.session.get(CollectionJob, job_id)
            if job.phase == 'done':
                job.status = 'completed'
                break
            if max_steps is not None and steps >= max_steps and job.phase != 'cluster':
                job.status = 'paused'
                break
            try:
                used = _one_step(job, api)
                job.api_steps = (job.api_steps or 0) + used
                db.session.commit()
                steps += used
            except YouTubeError as exc:
                db.session.rollback()
                job = db.session.get(CollectionJob, job_id)
                job.error_message = str(exc)[:500]
                job.status = 'paused' if exc.reason in ('quotaExceeded', 'rateLimitExceeded') else 'error'
                db.session.commit()
                break
    finally:
        job = db.session.get(CollectionJob, job_id)
        if job is not None and job.lease_owner == owner:
            job.lease_owner = None
            job.lease_until = None
            db.session.commit()
    return db.session.get(CollectionJob, job_id)
