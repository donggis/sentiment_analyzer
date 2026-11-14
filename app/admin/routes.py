"""Browse, tag, export, and resume collection for one channel."""
import csv
import io
import os
from datetime import datetime

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, stream_with_context, url_for

from app import db
from app.admin_auth import (
    admin_configured,
    attach_session_cookie,
    clear_session,
    client_address,
    delete_session_cookie,
    load_session,
    passwords_match,
    record_attempt,
    safe_next,
    start_session,
    too_many_failures,
)
from app.models import CollectedComment, CollectionJob, CommentTag, CommentTopic, Topic, Video
from app.services.collector import run_collection
from app.services.youtube_api import GoogleYouTubeApi, YouTubeError

bp = Blueprint('admin', __name__)


def _topics_for(channel_id):
    if not channel_id:
        return []
    return Topic.query.filter_by(channel_id=channel_id).order_by(Topic.label).all()


def _like_escape(value):
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def comment_query_from_args(args):
    query = CollectedComment.query.join(Video, CollectedComment.video_id == Video.id)
    text = (args.get('q') or '').strip()
    if text:
        query = query.filter(CollectedComment.text.ilike(f'%{_like_escape(text)}%', escape='\\'))
    video_id = (args.get('video') or '').strip()
    if video_id:
        query = query.filter(Video.yt_video_id == video_id)
    topic_id = (args.get('topic') or '').strip()
    if topic_id.isdigit():
        query = query.join(CommentTopic, CommentTopic.comment_id == CollectedComment.id)
        query = query.filter(CommentTopic.topic_id == int(topic_id))
    tag = (args.get('tag') or '').strip()
    if tag:
        query = query.join(CommentTag, CommentTag.comment_id == CollectedComment.id)
        query = query.filter(CommentTag.tag == tag)
    start = _parse_day(args.get('start'))
    end = _parse_day(args.get('end'))
    if start:
        query = query.filter(CollectedComment.published_at >= start)
    if end:
        query = query.filter(CollectedComment.published_at < end)
    return query.order_by(CollectedComment.published_at.desc(), CollectedComment.id.desc())


def _parse_day(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None


def csv_cell(value):
    if value is None:
        return ''
    text = str(value).replace('\r', ' ').replace('\n', ' ')
    if text[:1] in ('=', '+', '-', '@', '\t'):
        return "'" + text
    return text


def _csv_response():
    def generate():
        query = comment_query_from_args(request.args)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['comment_id', 'video_id', 'parent_id', 'author', 'published_at', 'likes', 'topic', 'tags', 'text'])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for comment in query.yield_per(200):
            topic_row = CommentTopic.query.filter_by(comment_id=comment.id).first()
            tags = [row.tag for row in CommentTag.query.filter_by(comment_id=comment.id).all()]
            writer.writerow([
                csv_cell(comment.yt_comment_id),
                csv_cell(comment.video.yt_video_id if comment.video else ''),
                csv_cell(comment.parent_yt_comment_id or ''),
                csv_cell(comment.author_display or ''),
                csv_cell(comment.published_at.isoformat() if comment.published_at else ''),
                csv_cell(comment.like_count),
                csv_cell(topic_row.topic.label if topic_row and topic_row.topic else ''),
                csv_cell(', '.join(tags)),
                csv_cell(comment.text),
            ])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    response = Response(stream_with_context(generate()), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = 'attachment; filename="comments.csv"'
    return response


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if not admin_configured():
        return Response('Admin authentication not configured', status=503)
    nxt = safe_next(request.values.get('next'))
    if request.method == 'GET':
        if load_session() is not None:
            return redirect(nxt)
        return render_template('admin/login.html', next_url=nxt, error=None)
    address = client_address()
    if too_many_failures(address):
        return render_template('admin/login.html', next_url=nxt, error='시도가 너무 많습니다. 잠시 후 다시 로그인하세요.'), 429
    username = request.form.get('username') or ''
    password = request.form.get('password') or ''
    if not passwords_match(username, password):
        record_attempt(address, False)
        return render_template('admin/login.html', next_url=nxt, error='아이디 또는 비밀번호가 올바르지 않습니다.'), 401
    record_attempt(address, True)
    raw = start_session()
    response = redirect(nxt)
    return attach_session_cookie(response, raw)


@bp.route('/logout', methods=['POST'])
def logout():
    clear_session()
    response = redirect('/login')
    return delete_session_cookie(response)


@bp.route('/admin')
def dashboard():
    job = CollectionJob.query.order_by(CollectionJob.id.desc()).first()
    channel_id = job.channel_id if job else None
    page = max(int(request.args.get('page') or 1), 1)
    per_page = 50
    comments = comment_query_from_args(request.args).limit(per_page).offset((page - 1) * per_page).all()
    videos = Video.query.order_by(Video.published_at.desc()).limit(200).all() if channel_id else []
    topics = _topics_for(channel_id)
    rows = []
    for comment in comments:
        topic_row = CommentTopic.query.filter_by(comment_id=comment.id).first()
        tags = [item.tag for item in CommentTag.query.filter_by(comment_id=comment.id).all()]
        rows.append({'comment': comment, 'topic': topic_row.topic if topic_row else None, 'tags': tags})
    kept = {}
    for key in ('q', 'video', 'topic', 'tag', 'start', 'end'):
        value = (request.args.get(key) or '').strip()
        if value:
            kept[key] = value
    export_url = url_for('admin.export_comments', **kept)
    return render_template(
        'admin/dashboard.html',
        job=job,
        rows=rows,
        videos=videos,
        topics=topics,
        page=page,
        filters=request.args,
        export_url=export_url,
        prev_url=url_for('admin.dashboard', page=page - 1, **kept) if page > 1 else None,
        next_url=url_for('admin.dashboard', page=page + 1, **kept),
        default_channel=os.environ.get('TARGET_CHANNEL_URL') or 'https://www.youtube.com/@jangpm',
    )


@bp.route('/collect', methods=['POST'])
def collect():
    ref = (request.form.get('channel_url') or os.environ.get('TARGET_CHANNEL_URL') or 'https://www.youtube.com/@jangpm').strip()
    try:
        budget = int(request.form.get('budget') or 20)
    except ValueError:
        budget = 20
    budget = max(1, min(budget, 50))
    job = None
    job_id = (request.form.get('job_id') or '').strip()
    if job_id.isdigit():
        job = db.session.get(CollectionJob, int(job_id))
    if job is None or job.phase == 'done':
        job = CollectionJob(channel_ref=ref, status='pending', phase='channel')
        db.session.add(job)
        db.session.commit()
    api_key = current_app.config.get('YOUTUBE_API_KEY') or os.environ.get('YOUTUBE_API_KEY')
    try:
        run_collection(job.id, GoogleYouTubeApi(api_key), max_steps=budget)
    except YouTubeError as exc:
        job = db.session.get(CollectionJob, job.id)
        job.status = 'error'
        job.error_message = str(exc)[:500]
        db.session.commit()
    return redirect(url_for('admin.dashboard'))


@bp.route('/api/library/comments')
def list_comments():
    comments = comment_query_from_args(request.args).limit(100).all()
    payload = []
    for comment in comments:
        topic_row = CommentTopic.query.filter_by(comment_id=comment.id).first()
        tags = [item.tag for item in CommentTag.query.filter_by(comment_id=comment.id).all()]
        payload.append({
            'id': comment.id,
            'yt_comment_id': comment.yt_comment_id,
            'video_id': comment.video.yt_video_id if comment.video else None,
            'parent_id': comment.parent_yt_comment_id,
            'text': comment.text,
            'author': comment.author_display,
            'likes': comment.like_count,
            'published_at': comment.published_at.isoformat() if comment.published_at else None,
            'topic': topic_row.topic.label if topic_row and topic_row.topic else None,
            'tags': tags,
        })
    return jsonify({'comments': payload})


@bp.route('/api/library/comments/<int:comment_id>/tags', methods=['POST'])
def add_tag(comment_id):
    body = request.get_json(silent=True) or {}
    tag = (request.form.get('tag') or body.get('tag') or '').strip()
    if not tag or len(tag) > 64 or any(char in tag for char in '\r\n'):
        return jsonify({'success': False, 'error': 'invalid tag'}), 400
    comment = db.session.get(CollectedComment, comment_id)
    if comment is None:
        return jsonify({'success': False, 'error': 'not found'}), 404
    if CommentTag.query.filter_by(comment_id=comment.id, tag=tag).first() is None:
        db.session.add(CommentTag(comment_id=comment.id, tag=tag))
        db.session.commit()
    if request.is_json:
        return jsonify({'success': True, 'tag': tag})
    return redirect(request.referrer or url_for('admin.dashboard'))


@bp.route('/api/library/comments/<int:comment_id>/tags', methods=['DELETE'])
def delete_tag(comment_id):
    body = request.get_json(silent=True) or {}
    tag = (request.args.get('tag') or body.get('tag') or '').strip()
    CommentTag.query.filter_by(comment_id=comment_id, tag=tag).delete()
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/export/comments.csv')
@bp.route('/api/admin/export/comments.csv')
def export_comments():
    return _csv_response()
