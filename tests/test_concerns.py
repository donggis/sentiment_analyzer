"""Viewer worries and problems. No live YouTube or LLM calls."""
import csv
import io
from datetime import datetime
from unittest.mock import Mock

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app import create_app, db
from app.config import TestingConfig
from app.models import Channel, CollectedComment, CommentConcern, Video
from app.services.concerns import _assign_themes, analyze_comments, concern_groups, detect_concern
from tests.conftest import TEST_ADMIN_HASH, login_admin


DETECTED = [
    ('취업이 안 돼서 고민이에요', 'problem', '취업'),
    ('로그인이 안 됩니다', 'problem', '로그인'),
    ('소리가 안 들려요', 'problem', '소리'),
    ('배송이 아직도 안 와요 어떻게 해야 하나요', 'problem', '배송'),
    ('이 부분 이해가 어려워요', 'problem', '이해'),
    ('가격이 너무 부담돼요', 'problem', '가격'),
    ('진로가 고민입니다', 'worry', '진로'),
    ('수강료가 궁금합니다', 'question', '수강료'),
    ('레시피 알려주세요', 'request', '레시피'),
    ('초보인데 어떻게 시작하나요?', 'question', '시작'),
    ('앱이 계속 오류가 나요', 'problem', '앱'),
    ('등록금이 너무 비싸요', 'problem', '등록금'),
    ('환불은 어떻게 하나요?', 'problem', '환불'),
    ('안 돼요 제발', 'problem', '기타'),
    ('방법이 없나요?', 'request', '기타'),
    ('<b>배송</b>이 느려요 https://evil.example/track', 'problem', '배송'),
    ('로그인 error가 계속 나요', 'problem', '로그인'),
]

NOT_CONCERNS = [
    '너무 좋아요',
    '어떻게 이렇게 잘하세요',
    'ㅋㅋㅋㅋ',
    '배송 최고',
    '고민 없어요 재밌어요',
    '문제 없습니다',
    '가격 괜찮아요',
    '날씨 좋다',
    '배송 동의',
    '구독 부탁드려요',
    '어렵지만 해냈어요',
    '부담 없이 보세요',
    '잘 봤습니다',
    '',
    '   ',
    '???',
]


@pytest.mark.parametrize('text,kind,theme', DETECTED)
def test_detects_korean_worries_and_problems(text, kind, theme):
    found = detect_concern(text)
    assert found is not None, text
    assert found['kind'] == kind
    _assign_themes([found])
    assert found['theme'] == theme


@pytest.mark.parametrize('text', NOT_CONCERNS)
def test_ignores_praise_noise_and_negation(text):
    assert detect_concern(text) is None


def _channel():
    channel = Channel(yt_channel_id='UCconcern', title='채널')
    db.session.add(channel)
    db.session.flush()
    return channel


def _video(channel, yt_id, title):
    video = Video(yt_video_id=yt_id, channel_id=channel.id, title=title, published_at=datetime(2024, 1, 1))
    db.session.add(video)
    db.session.flush()
    return video


def _comment(video, yt_id, text, likes, published, parent=None):
    row = CollectedComment(
        yt_comment_id=yt_id,
        video_id=video.id,
        text=text,
        like_count=likes,
        published_at=published,
        parent_yt_comment_id=parent,
        author_display='시청자',
    )
    db.session.add(row)
    db.session.flush()
    return row


def _library():
    channel = _channel()
    video_a = _video(channel, 'va', '영상A')
    video_b = _video(channel, 'vb', '영상B')
    _comment(video_a, 'c-hot', '배송이 열흘째 느려요', 10, datetime(2024, 2, 1))
    _comment(video_a, 'c-mid', '배송이 안 와요', 1, datetime(2024, 2, 2))
    _comment(video_b, 'c-track', '배송 추적이 안 돼요', 0, datetime(2024, 3, 1))
    _comment(video_b, 'c-price', '가격이 너무 비싸요', 50, datetime(2024, 3, 2))
    _comment(video_a, 'c-pay', '=1+1 결제가 안 돼요', 4, datetime(2024, 2, 3))
    _comment(video_a, 'c-love', '너무 좋아요', 9, datetime(2024, 2, 1))
    _comment(video_a, 'c-praise', '어떻게 이렇게 잘하세요', 8, datetime(2024, 2, 1))
    _comment(video_a, 'c-reply', '소리가 안 들려요', 3, datetime(2024, 2, 4), parent='c-hot')
    _comment(video_a, 'c-worry', '진로가 고민입니다', 2, datetime(2024, 2, 5))
    db.session.commit()
    return channel


def test_groups_rank_by_frequency_then_likes(app):
    with app.app_context():
        _library()
        first = analyze_comments(CollectedComment.query.all(), use_external=False)
        again = analyze_comments(CollectedComment.query.all(), use_external=False)
        assert first['external_calls'] == 0
        assert again['concerns'] == first['concerns']
        assert CommentConcern.query.count() == first['concerns']
        groups, total = concern_groups({})
        assert total == len(groups)
        assert groups[0]['theme'] == '배송'
        assert groups[0]['count'] == 2
        assert groups[0]['likes'] == 11
        assert groups[0]['samples'][0]['text'] == '배송이 열흘째 느려요'
        assert groups[0]['samples'][0]['comment_url'].endswith('watch?v=va&lc=c-hot') or 'lc=c-hot' in groups[0]['samples'][0]['comment_url']
        assert '배송' in groups[0]['summary']
        assert '댓글 2개' in groups[0]['summary']
        assert [group['theme'] for group in groups[:2]] == ['배송', '가격']
        reply = next(group for group in groups if group['theme'] == '소리')
        assert reply['samples'][0]['is_reply'] is True
        themes = {row.theme for row in CommentConcern.query.all()}
        assert '좋아요' not in themes
        video_groups, _ = concern_groups({'video': 'vb'})
        assert {group['theme'] for group in video_groups} == {'추적', '가격'}
        march, _ = concern_groups({'start': '2024-03-01', 'end': '2024-03-03'})
        assert {group['theme'] for group in march} == {'추적', '가격'}
        worries, _ = concern_groups({'kind': 'worry'})
        assert [group['theme'] for group in worries] == ['진로']
        early, _ = concern_groups({'end': '2024-02-01'})
        assert early == []


def test_dashboard_and_csv_export(client, app):
    with app.app_context():
        _library()
        analyze_comments(CollectedComment.query.all(), use_external=False)
    login_admin(client)
    page = client.get('/admin/concerns')
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert '배송' in body
    assert '댓글 2개' in body
    assert 'lc=c-hot' in body
    assert '답글' in body
    assert '외부 AI로 분석' not in body
    assert '추가 요금은 없습니다' in body or '요금도 없습니다' in body
    home = client.get('/admin')
    assert home.status_code == 200
    assert '고민·문제' in home.get_data(as_text=True)
    exported = client.get('/export/concerns.csv?video=va')
    assert exported.status_code == 200
    text = exported.get_data(as_text=True)
    assert text.startswith('\ufeff')
    assert "'=1+1" in text
    assert '결제' in text
    assert '가격이 너무 비싸요' not in text
    rows = list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))
    assert rows[0][0] == 'rank'
    fresh = app.test_client()
    assert fresh.get('/admin/concerns').status_code == 302
    assert fresh.get('/export/concerns.csv').status_code == 401
    assert fresh.post('/admin/concerns/analyze').status_code == 302


def test_external_mode_is_off_without_the_flag(app, monkeypatch):
    monkeypatch.delenv('ENABLE_EXTERNAL_AI', raising=False)
    monkeypatch.setenv('SENTIMENT_API_URL', 'https://example.invalid')
    monkeypatch.setattr('requests.post', Mock(side_effect=AssertionError('paid call')))
    with app.app_context():
        channel = _channel()
        video = _video(channel, 'vx', '영상')
        _comment(video, 'cx', '결제가 안 돼요', 1, datetime(2024, 2, 1))
        db.session.commit()
        result = analyze_comments(CollectedComment.query.all(), use_external=True)
        assert result['external_calls'] == 0
        assert CommentConcern.query.one().method == 'local'
        assert CommentConcern.query.one().theme == '결제'


def _response(payload):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload
    return Response()


def test_external_calls_are_batched_and_capped(app, monkeypatch):
    monkeypatch.setenv('ENABLE_EXTERNAL_AI', 'true')
    monkeypatch.setenv('SENTIMENT_API_URL', 'https://example.invalid')
    monkeypatch.setenv('CONCERN_AI_MAX_CALLS', '100')
    monkeypatch.setenv('CONCERN_AI_BATCH', '1')
    monkeypatch.delenv('SENTIMENT_API_KEY', raising=False)
    monkeypatch.delenv('MODAL_ML_API_KEY', raising=False)
    seen = []

    def fake_post(url, **kwargs):
        assert url == 'https://example.invalid/concerns'
        assert kwargs['allow_redirects'] is False
        assert kwargs['timeout'] == 8
        assert 'headers' not in kwargs
        item = kwargs['json']['items'][0]
        assert len(item['text']) <= 180
        seen.append(item['id'])
        return _response({'items': [
            {'id': item['id'], 'theme': '결제 오류', 'kind': 'problem', 'summary': '결제가 되지 않습니다'},
            {'id': '999999', 'theme': '무시', 'kind': 'worry', 'summary': '다른 댓글입니다'},
        ]})

    monkeypatch.setattr('requests.post', fake_post)
    with app.app_context():
        channel = _channel()
        video = _video(channel, 'vbcap', '영상')
        for index in range(20):
            _comment(video, f'cap-{index}', '결제가 안 돼요', index, datetime(2024, 4, 1))
        db.session.commit()
        result = analyze_comments(CollectedComment.query.all(), use_external=True)
        assert result['external_calls'] == 8
        assert len(seen) == 8
        themes = {row.theme: 0 for row in CommentConcern.query.all()}
        for row in CommentConcern.query.all():
            themes[row.theme] = themes.get(row.theme, 0) + 1
        assert themes['결제 오류'] == 8
        assert themes['결제'] == 12
        groups, _ = concern_groups({})
        external = next(group for group in groups if group['theme'] == '결제 오류')
        assert '결제가 되지 않습니다' in external['summary']
        assert external['method'] == 'external'
        assert '무시' not in themes


def test_default_call_cap_and_batch_cap(app, monkeypatch):
    monkeypatch.setenv('ENABLE_EXTERNAL_AI', 'true')
    monkeypatch.setenv('SENTIMENT_API_URL', 'https://example.invalid')
    monkeypatch.delenv('CONCERN_AI_MAX_CALLS', raising=False)
    monkeypatch.setenv('CONCERN_AI_BATCH', '1')

    def fake_post(url, **kwargs):
        assert len(kwargs['json']['items']) == 1
        return _response({'items': []})

    monkeypatch.setattr('requests.post', fake_post)
    with app.app_context():
        channel = _channel()
        video = _video(channel, 'vbatch', '영상')
        for index in range(10):
            _comment(video, f'batch-{index}', '배송이 느려요', 0, datetime(2024, 5, 1))
        db.session.commit()
        result = analyze_comments(CollectedComment.query.all(), use_external=True)
        assert result['external_calls'] == 4

    sizes = []

    def fake_batch(url, **kwargs):
        sizes.append(len(kwargs['json']['items']))
        return _response({'items': []})

    monkeypatch.setenv('CONCERN_AI_MAX_CALLS', '4')
    monkeypatch.setenv('CONCERN_AI_BATCH', '100')
    monkeypatch.setattr('requests.post', fake_batch)
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        channel = _channel()
        video = _video(channel, 'vbatch2', '영상')
        for index in range(25):
            _comment(video, f'wide-{index}', '배송이 느려요', 0, datetime(2024, 5, 2))
        db.session.commit()
        result = analyze_comments(CollectedComment.query.all(), use_external=True)
        assert result['external_calls'] == 2
        assert sizes == [20, 5]


def test_bad_external_response_keeps_local_labels(app, monkeypatch):
    monkeypatch.setenv('ENABLE_EXTERNAL_AI', 'true')
    monkeypatch.setenv('SENTIMENT_API_URL', 'https://example.invalid')
    monkeypatch.setenv('CONCERN_AI_MAX_CALLS', '1')
    monkeypatch.setenv('SENTIMENT_API_KEY', 'secret-test')
    calls = {'n': 0}

    def fake_post(url, **kwargs):
        calls['n'] += 1
        assert kwargs['headers']['Authorization'] == 'Bearer secret-test'
        assert 'secret-test' not in kwargs['json']['items'][0]['text']
        if calls['n'] == 1:
            raise OSError('down')
        return _response({'items': [{'id': kwargs['json']['items'][0]['id'], 'summary': 'payment failed'}]})

    monkeypatch.setattr('requests.post', fake_post)
    with app.app_context():
        channel = _channel()
        video = _video(channel, 'vbad', '영상')
        _comment(video, 'bad-1', '가격이 비싸요 ' + ('가' * 400), 1, datetime(2024, 6, 1))
        db.session.commit()
        result = analyze_comments(CollectedComment.query.all(), use_external=True)
        assert result['external_calls'] == 1
        row = CommentConcern.query.one()
        assert row.theme == '가격'
        assert row.method == 'local'
        assert row.summary is None


def test_collecting_comments_analyzes_locally(app, monkeypatch):
    from tests.test_collection import FakeYouTube, _finish, _new_job
    monkeypatch.setattr('requests.post', Mock(side_effect=AssertionError('paid call')))
    with app.app_context():
        _finish(FakeYouTube(), _new_job())
        by_text = {row.comment.text: row for row in CommentConcern.query.all()}
        assert by_text['배송 느려요'].theme == '배송'
        assert by_text['배송 느려요'].method == 'local'
        assert by_text['가격 비싸요'].theme == '가격'
        assert by_text['배송 최악'].theme == '배송'
        assert '날씨 좋다' not in by_text
        assert '배송 최고' not in by_text
        assert '가격 괜찮아요' not in by_text


def test_analyze_route_does_not_call_out_when_disabled(client, app, monkeypatch):
    monkeypatch.delenv('ENABLE_EXTERNAL_AI', raising=False)
    monkeypatch.setenv('SENTIMENT_API_URL', 'https://example.invalid')
    monkeypatch.setattr('requests.post', Mock(side_effect=AssertionError('paid call')))
    with app.app_context():
        channel = _channel()
        video = _video(channel, 'vroute', '영상')
        _comment(video, 'route-1', '로그인이 안 돼요', 2, datetime(2024, 7, 1))
        db.session.commit()
    login_admin(client)
    response = client.post('/admin/concerns/analyze', data={'mode': 'external', 'video': 'vroute'})
    assert response.status_code == 302
    page = client.get(response.location)
    body = page.get_data(as_text=True)
    assert '로그인' in body
    assert '서버 안에서 분석했습니다' in body
    filtered = client.get('/admin/concerns?video=vroute')
    assert '로그인' in filtered.get_data(as_text=True)


def test_migration_keeps_existing_comments(tmp_path, monkeypatch):
    db_path = tmp_path / 'concerns.db'
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', TEST_ADMIN_HASH)
    monkeypatch.delenv('ENABLE_EXTERNAL_AI', raising=False)

    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + str(db_path)
        SECRET_KEY = 'persist-test-secret-key'

    application = create_app(Cfg)
    with application.app_context():
        upgrade(revision='b7e1c0a11ad2')
        assert 'comment_concern' not in inspect(db.engine).get_table_names()
        channel = Channel(yt_channel_id='UCold', title='예전')
        db.session.add(channel)
        db.session.flush()
        video = Video(yt_video_id='vold', channel_id=channel.id, title='예전 영상')
        db.session.add(video)
        db.session.flush()
        db.session.add(CollectedComment(yt_comment_id='cold', video_id=video.id, text='그대로 배송이 느려요'))
        db.session.commit()
        upgrade()
        kept = db.session.execute(text("select text from collected_comment where yt_comment_id = 'cold'")).scalar()
        assert kept == '그대로 배송이 느려요'
        assert 'comment_concern' in inspect(db.engine).get_table_names()
        analyze_comments(CollectedComment.query.all(), use_external=False)
        assert CommentConcern.query.count() == 1
        downgrade(revision='b7e1c0a11ad2')
        assert 'comment_concern' not in inspect(db.engine).get_table_names()
        kept = db.session.execute(text("select text from collected_comment where yt_comment_id = 'cold'")).scalar()
        assert kept == '그대로 배송이 느려요'
    db.session.remove()
    db.engine.dispose()
