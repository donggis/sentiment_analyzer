"""Group comments by shared words. No model download and no paid API by default."""
import os
import re
from collections import Counter

from app import db
from app.models import Channel, CollectedComment, CommentTopic, Topic, Video

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'on', 'for', 'is', 'it', 'this', 'that',
    'i', 'you', 'my', 'me', 'we', 'our', 'they', 'with', 'was', 'are', 'be', 'as', 'at', 'so',
    'too', 'very', 'just', 'not', 'but', 'if', 'from', 'your', 'have', 'has',
    '은', '는', '이', '가', '을', '를', '에', '의', '도', '로', '와', '과', '하다', '입니다',
    '너무', '정말', '그냥', '그리고', '근데', '이거', '저거', '그게',
}
TOKEN_RE = re.compile(r'[a-z0-9가-힣]{2,}')
UNCATEGORIZED = '미분류'


def tokenize(text):
    cleaned = re.sub(r'<[^>]+>', ' ', text or '').lower()
    return [token for token in TOKEN_RE.findall(cleaned) if token not in STOPWORDS]


def local_groups(comments):
    """Return {comment_id: (label or None, confidence)} using repeated keywords."""
    docs = [(comment, tokenize(comment.text)) for comment in comments]
    counts = Counter()
    for _comment, tokens in docs:
        counts.update(set(tokens))
    total = len(docs)
    assigned = {}
    for comment, tokens in docs:
        if total == 0 or not tokens:
            assigned[comment.id] = (None, 0.0)
            continue
        candidates = [
            token for token in tokens
            if counts[token] >= 2 and counts[token] <= max(2, int(total * 0.8))
        ]
        if not candidates:
            assigned[comment.id] = (None, 0.0)
            continue
        label = sorted(candidates, key=lambda token: (-counts[token], token))[0]
        assigned[comment.id] = (label, round(counts[label] / total, 3))
    return assigned


def _external_attempt(comments):
    """Return True only when a paid call was actually made. Failures stay local."""
    if os.getenv('ENABLE_EXTERNAL_AI', '').lower() != 'true':
        return False
    url = (os.getenv('SENTIMENT_API_URL') or os.getenv('MODAL_ML_BASE_URL') or '').strip()
    if not url:
        return False
    import requests
    payload = {'texts': [(comment.text or '')[:200] for comment in comments[:50]]}
    try:
        requests.post(url.rstrip('/') + '/cluster', json=payload, timeout=10)
    except Exception:
        return False
    return True


def cluster_channel(channel_id):
    channel = db.session.get(Channel, channel_id)
    if channel is None:
        return []
    comments = (
        CollectedComment.query.join(Video, CollectedComment.video_id == Video.id)
        .filter(Video.channel_id == channel.id)
        .order_by(CollectedComment.id)
        .all()
    )
    external_called = _external_attempt(comments)
    grouped = local_groups(comments)
    CommentTopic.query.filter(CommentTopic.comment_id.in_([c.id for c in comments] or [0])).delete(
        synchronize_session=False
    )
    Topic.query.filter_by(channel_id=channel.id).delete(synchronize_session=False)
    buckets = {}
    for comment in comments:
        label, confidence = grouped.get(comment.id, (None, 0.0))
        key = label or UNCATEGORIZED
        buckets.setdefault(key, []).append((comment, confidence if label else 0.0))
    method = 'external' if external_called else 'local'
    for label, rows in sorted(buckets.items()):
        topic = Topic(
            channel_id=channel.id,
            label=label,
            keywords=label,
            method=method if label != UNCATEGORIZED else 'local',
            comment_count=len(rows),
        )
        db.session.add(topic)
        db.session.flush()
        for comment, confidence in rows:
            db.session.add(CommentTopic(comment_id=comment.id, topic_id=topic.id, confidence=confidence))
    db.session.commit()
    return Topic.query.filter_by(channel_id=channel.id).order_by(Topic.id).all()
