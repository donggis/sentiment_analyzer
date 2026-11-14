"""YouTube Data API adapter.

Tests pass a fake with the same method names. This class is the only place
that talks to Google, and collection tests never construct it.
"""
import re
from datetime import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class YouTubeError(Exception):
    def __init__(self, message, reason='error', status=0):
        super().__init__(message)
        self.reason = reason
        self.status = status


def parse_iso8601_duration(value):
    if not value:
        return None
    match = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', value)
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _execute(request):
    try:
        return request.execute()
    except HttpError as exc:
        content = exc.content.decode('utf-8', 'replace') if exc.content else str(exc)
        reason = 'http'
        if 'commentsDisabled' in content:
            reason = 'commentsDisabled'
        elif 'quotaExceeded' in content:
            reason = 'quotaExceeded'
        elif 'rateLimitExceeded' in content:
            reason = 'rateLimitExceeded'
        status = getattr(getattr(exc, 'resp', None), 'status', 0) or 0
        raise YouTubeError(content, reason=reason, status=int(status)) from exc


def _comment_snippet(item):
    snippet = item.get('snippet') or {}
    return {
        'id': item.get('id'),
        'text': snippet.get('textOriginal') or snippet.get('textDisplay') or '',
        'author': snippet.get('authorDisplayName') or '',
        'likes': int(snippet.get('likeCount') or 0),
        'published_at': snippet.get('publishedAt'),
    }


class GoogleYouTubeApi:
    def __init__(self, api_key):
        if not api_key:
            raise YouTubeError('YOUTUBE_API_KEY is not configured', reason='config')
        self.youtube = build(
            'youtube', 'v3', developerKey=api_key,
            cache_discovery=False,
            # The bundled discovery file in this client version predates
            # channels.list(forHandle=...). Fetch the live document instead.
            static_discovery=False,
        )

    def get_channel(self, handle=None, channel_id=None, username=None):
        kwargs = {'part': 'snippet,contentDetails,statistics'}
        if channel_id:
            kwargs['id'] = channel_id
        elif handle:
            kwargs['forHandle'] = handle.lstrip('@')
        elif username:
            kwargs['forUsername'] = username
        else:
            raise YouTubeError('channel reference is empty', reason='invalid')
        response = _execute(self.youtube.channels().list(**kwargs))
        items = response.get('items') or []
        if not items:
            raise YouTubeError('channel not found', reason='notFound', status=404)
        item = items[0]
        uploads = ((item.get('contentDetails') or {}).get('relatedPlaylists') or {}).get('uploads')
        if not uploads:
            raise YouTubeError('uploads playlist missing', reason='notFound', status=404)
        stats = item.get('statistics') or {}
        return {
            'id': item.get('id'),
            'title': (item.get('snippet') or {}).get('title') or '',
            'uploads_playlist_id': uploads,
            'video_count': int(stats.get('videoCount') or 0),
        }

    def list_uploads(self, playlist_id, page_token=None):
        kwargs = {
            'part': 'contentDetails,snippet',
            'playlistId': playlist_id,
            'maxResults': 50,
        }
        if page_token:
            kwargs['pageToken'] = page_token
        response = _execute(self.youtube.playlistItems().list(**kwargs))
        items = []
        for item in response.get('items') or []:
            content = item.get('contentDetails') or {}
            snippet = item.get('snippet') or {}
            video_id = content.get('videoId')
            if not video_id:
                continue
            items.append({
                'video_id': video_id,
                'title': snippet.get('title') or video_id,
                'published_at': snippet.get('publishedAt') or content.get('videoPublishedAt'),
            })
        return {'items': items, 'next_page_token': response.get('nextPageToken')}

    def list_videos(self, video_ids):
        if not video_ids:
            return {}
        response = _execute(self.youtube.videos().list(
            part='snippet,statistics,contentDetails',
            id=','.join(video_ids),
            maxResults=50,
        ))
        found = {}
        for item in response.get('items') or []:
            snippet = item.get('snippet') or {}
            stats = item.get('statistics') or {}
            details = item.get('contentDetails') or {}
            published = snippet.get('publishedAt')
            found[item['id']] = {
                'title': snippet.get('title') or item['id'],
                'published_at': published,
                'views': int(stats.get('viewCount') or 0),
                'likes': int(stats.get('likeCount') or 0),
                'comments': int(stats.get('commentCount') or 0),
                'duration_seconds': parse_iso8601_duration(details.get('duration')),
            }
        return found

    def list_threads(self, video_id, page_token=None):
        kwargs = {
            'part': 'snippet,replies',
            'videoId': video_id,
            'maxResults': 100,
            'textFormat': 'plainText',
            'order': 'time',
        }
        if page_token:
            kwargs['pageToken'] = page_token
        response = _execute(self.youtube.commentThreads().list(**kwargs))
        items = []
        for item in response.get('items') or []:
            top = (item.get('snippet') or {}).get('topLevelComment') or {}
            comment = _comment_snippet(top)
            comment['id'] = top.get('id') or comment.get('id')
            comment['reply_count'] = int((item.get('snippet') or {}).get('totalReplyCount') or 0)
            replies = []
            for reply in ((item.get('replies') or {}).get('comments') or []):
                replies.append(_comment_snippet(reply))
            comment['replies'] = replies
            items.append(comment)
        return {'items': items, 'next_page_token': response.get('nextPageToken')}

    def list_replies(self, parent_id, page_token=None):
        kwargs = {
            'part': 'snippet',
            'parentId': parent_id,
            'maxResults': 100,
            'textFormat': 'plainText',
        }
        if page_token:
            kwargs['pageToken'] = page_token
        response = _execute(self.youtube.comments().list(**kwargs))
        items = [_comment_snippet(item) for item in response.get('items') or []]
        return {'items': items, 'next_page_token': response.get('nextPageToken')}


def parse_published(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).replace('Z', '+00:00')
    return datetime.fromisoformat(text).replace(tzinfo=None)
