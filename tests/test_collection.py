"""Collection, clustering, and persistence. The YouTube API is faked."""
import socket
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask_migrate import upgrade
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.config import TestingConfig
from app.models import CollectedComment, CollectionJob, CommentTag
from app.services.collector import run_collection
from app.services.youtube_api import YouTubeError
from tests.conftest import TEST_ADMIN_HASH, login_admin


class FakeYouTube:
    def __init__(self):
        self.calls = []

    def get_channel(self, **kwargs):
        self.calls.append('channel')
        return {
            'id': 'UC1',
            'title': '장피엠',
            'uploads_playlist_id': 'UU1',
            'video_count': 3,
        }

    def list_uploads(self, playlist_id, page_token=None):
        self.calls.append(('uploads', page_token))
        if page_token is None:
            return {
                'items': [{'video_id': 'v1', 'title': 'one', 'published_at': '2024-01-01T00:00:00Z'}],
                'next_page_token': 'p2',
            }
        return {
            'items': [
                {'video_id': 'v2', 'title': 'two', 'published_at': '2024-01-02T00:00:00Z'},
                {'video_id': 'v3', 'title': 'three', 'published_at': '2024-01-03T00:00:00Z'},
            ],
            'next_page_token': None,
        }

    def list_videos(self, video_ids):
        self.calls.append(('videos', tuple(video_ids)))
        return {
            video_id: {
                'title': video_id,
                'published_at': '2024-01-01T00:00:00Z',
                'views': 3,
                'likes': 1,
                'comments': 2,
                'duration_seconds': 45,
            }
            for video_id in video_ids
        }

    def list_threads(self, video_id, page_token=None):
        self.calls.append(('threads', video_id, page_token))
        if video_id == 'v3':
            raise YouTubeError('disabled', reason='commentsDisabled', status=403)
        if video_id == 'v1' and page_token is None:
            return {
                'items': [{
                    'id': 'c1',
                    'text': '배송 느려요',
                    'author': '가',
                    'likes': 1,
                    'published_at': '2024-02-01T00:00:00Z',
                    'reply_count': 3,
                    'replies': [{
                        'id': 'r1',
                        'text': '배송 동의',
                        'author': '나',
                        'likes': 0,
                        'published_at': '2024-02-02T00:00:00Z',
                    }],
                }],
                'next_page_token': 't2',
            }
        if video_id == 'v1':
            return {
                'items': [{
                    'id': 'c2',
                    'text': '배송 최고',
                    'author': '다',
                    'likes': 2,
                    'published_at': '2024-02-03T00:00:00Z',
                    'reply_count': 0,
                    'replies': [],
                }],
                'next_page_token': None,
            }
        return {
            'items': [
                {
                    'id': 'c3',
                    'text': '가격 비싸요',
                    'author': '라',
                    'likes': 0,
                    'published_at': '2024-03-01T00:00:00Z',
                    'reply_count': 0,
                    'replies': [],
                },
                {
                    'id': 'c4',
                    'text': '가격 괜찮아요',
                    'author': '마',
                    'likes': 0,
                    'published_at': '2024-03-02T00:00:00Z',
                    'reply_count': 0,
                    'replies': [],
                },
            ],
            'next_page_token': None,
        }

    def list_replies(self, parent_id, page_token=None):
        self.calls.append(('replies', parent_id, page_token))
        if page_token is None:
            return {
                'items': [
                    {'id': 'r1', 'text': '배송 동의', 'author': '나', 'likes': 0, 'published_at': '2024-02-02T00:00:00Z'},
                    {'id': 'r2', 'text': '배송 최악', 'author': '바', 'likes': 0, 'published_at': '2024-02-04T00:00:00Z'},
                ],
                'next_page_token': 'rp2',
            }
        return {
            'items': [
                {'id': 'r2', 'text': '배송 최악', 'author': '바', 'likes': 1, 'published_at': '2024-02-04T00:00:00Z'},
                {'id': 'r3', 'text': '날씨 좋다', 'author': '사', 'likes': 0, 'published_at': '2024-02-05T00:00:00Z'},
            ],
            'next_page_token': None,
        }


def _new_job():
    job = CollectionJob(channel_ref='https://www.youtube.com/@jangpm', status='pending', phase='channel')
    db.session.add(job)
    db.session.commit()
    return job


def _finish(api, job):
    guard = 30
    while job.phase != 'done' and guard:
        job = run_collection(job.id, api, max_steps=1)
        guard -= 1
    assert job.phase == 'done', job.phase
    return job


def test_pagination_resume_and_dedupe(app, monkeypatch):
    monkeypatch.setattr('app.services.youtube_api.GoogleYouTubeApi', Mock(side_effect=AssertionError('real api')))
    monkeypatch.setattr(socket, 'socket', Mock(side_effect=AssertionError('network')))
    posted = Mock(side_effect=AssertionError('external ai'))
    monkeypatch.setattr('requests.post', posted)
    api = FakeYouTube()
    with app.app_context():
        job = _new_job()
        paused = run_collection(job.id, api, max_steps=2)
        assert paused.phase != 'done'
        assert paused.status == 'paused'
        job = _finish(api, paused)
        ids = [row.yt_comment_id for row in CollectedComment.query.all()]
        assert sorted(ids) == ['c1', 'c2', 'c3', 'c4', 'r1', 'r2', 'r3']
        assert len(ids) == len(set(ids))
        again = run_collection(job.id, api, max_steps=5)
        assert again.status == 'completed'
        assert CollectedComment.query.count() == 7
        from app.models import CommentTopic, Topic
        labels = {row.topic.label for row in CommentTopic.query.all()}
        assert '배송' in labels
        assert '가격' in labels
        assert '미분류' in labels
        assert all(topic.method == 'local' for topic in Topic.query.all())
        posted.assert_not_called()


def test_external_cluster_only_when_enabled(app, monkeypatch):
    monkeypatch.setenv('ENABLE_EXTERNAL_AI', 'true')
    monkeypatch.setenv('SENTIMENT_API_URL', 'https://example.invalid')
    posted = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr('requests.post', posted)
    api = FakeYouTube()
    with app.app_context():
        job = _finish(api, _new_job())
        assert job.status == 'completed'
        posted.assert_called()


def test_quota_pause_is_resumable(app):
    class QuotaApi(FakeYouTube):
        def __init__(self):
            super().__init__()
            self.uploads = 0

        def list_uploads(self, playlist_id, page_token=None):
            self.uploads += 1
            if self.uploads > 1:
                raise YouTubeError('quota', reason='quotaExceeded', status=403)
            return super().list_uploads(playlist_id, page_token)

    api = QuotaApi()
    with app.app_context():
        job = _new_job()
        run_collection(job.id, api, max_steps=1)
        paused = run_collection(job.id, api, max_steps=5)
        assert paused.status == 'paused'
        assert 'quota' in (paused.error_message or '')
        api.uploads = 0
        # The failing call did not advance the cursor, so a later run can continue.
        api.uploads = 99
        # Force the next uploads call to succeed by replacing the method.
        api.list_uploads = FakeYouTube.list_uploads.__get__(api, QuotaApi)
        done = _finish(api, paused)
        assert done.status == 'completed'
        assert CollectedComment.query.count() == 7


def test_search_tag_and_csv_injection(client, app):
    api = FakeYouTube()
    with app.app_context():
        _finish(api, _new_job())
        comment = CollectedComment.query.filter_by(yt_comment_id='c1').one()
        comment.text = '=1+1 배송'
        db.session.commit()
        comment_id = comment.id
    login_admin(client)
    found = client.get('/api/library/comments?q=배송')
    assert found.status_code == 200
    ids = {item['yt_comment_id'] for item in found.get_json()['comments']}
    assert 'c1' in ids
    assert 'c3' not in ids
    tagged = client.post(f'/api/library/comments/{comment_id}/tags', json={'tag': '확인'})
    assert tagged.status_code == 200
    again = client.post(f'/api/library/comments/{comment_id}/tags', json={'tag': '확인'})
    assert again.status_code == 200
    with app.app_context():
        assert CommentTag.query.filter_by(tag='확인').count() == 1
    exported = client.get('/export/comments.csv?q=배송')
    assert exported.status_code == 200
    assert "'=1+1" in exported.get_data(as_text=True)
    fresh = app.test_client()
    assert fresh.get('/export/comments.csv').status_code == 401


def test_sqlite_survives_new_process(tmp_path, monkeypatch):
    db_path = tmp_path / 'persist.db'
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', TEST_ADMIN_HASH)
    monkeypatch.delenv('ENABLE_EXTERNAL_AI', raising=False)

    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + str(db_path)
        SECRET_KEY = 'persist-test-secret-key'

    first = create_app(Cfg)
    with first.app_context():
        upgrade()
        job = CollectionJob(channel_ref='https://www.youtube.com/@jangpm', status='pending', phase='channel')
        db.session.add(job)
        db.session.commit()
        run_collection(job.id, FakeYouTube(), max_steps=None)
        assert CollectedComment.query.count() == 7
    db.session.remove()
    db.engine.dispose()

    second = create_app(Cfg)
    with second.app_context():
        rows = CollectedComment.query.all()
        assert len(rows) == 7
        assert {row.yt_comment_id for row in rows} == {'c1', 'c2', 'c3', 'c4', 'r1', 'r2', 'r3'}


def test_grant_migration_not_in_tree():
    root = Path(__file__).resolve().parents[1] / 'migrations'
    assert 'theresasumma@gmail.com' not in '\n'.join(path.read_text(encoding='utf-8') for path in root.rglob('*.py'))
