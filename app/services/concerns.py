"""Group viewer worries and problems. Local rules by default, no paid API.

Korean comments are scored with cues for questions, worries, failures, and
requests. Themes are the noun next to that cue, not the cue word itself.
ENABLE_EXTERNAL_AI=true is required before any comment text leaves the machine,
and even then a run stops after a hard call cap.
"""
import html
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime
from urllib.parse import quote

from flask import current_app

from app import db
from app.models import CollectedComment, CommentConcern, Video, _utcnow

OTHER = '기타'
CALL_CAP = 8
BATCH_CAP = 20
TEXT_LIMIT = 180
KIND_LABELS = {
    'problem': '문제',
    'worry': '고민',
    'request': '요청',
    'question': '질문',
}
CUE_TEXT = {
    'broken': '되지 않거나 오류가 난다고',
    'late': '늦거나 도착하지 않는다고',
    'hard': '어렵거나 막막하다고',
    'cost': '비용이 부담된다고',
    'complain': '불편하거나 불만이라고',
    'worry': '걱정하거나 고민이 된다고',
    'help': '도움을 요청한다고',
    'how': '방법을 궁금해한다고',
}
_CUE_ORDER = ('broken', 'late', 'hard', 'cost', 'complain', 'worry', 'help', 'how')
_PROBLEM_CUES = {'broken', 'late', 'hard', 'cost', 'complain'}

_TAG = re.compile(r'<[^>]+>')
_URL = re.compile(r'https?://\S+|www\.\S+')
_SPACE = re.compile(r'\s+')
_TOKEN = re.compile(r'[0-9a-z가-힣]{2,}')
_HOW_PRAISE = re.compile(
    r'어떻게\s*이렇게\s*(?:잘|예쁘|이쁘|좋|멋|귀엽|대박|완벽|웃|재밌|재미|훌륭|신기)'
)
_ADMIRATION = re.compile(
    r'어떻게\s*이렇게\s*(?:잘|예쁘|이쁘|좋|멋|귀엽|대박|완벽|웃|재밌|재미|훌륭|신기)'
    r'|재밌|재미있|잘\s*봤|잘봤|멋있|예뻐|이뻐|훌륭|대박|사랑해|응원'
)
_SUBSCRIBE = re.compile(
    r'구독(?:\s*과)?\s*좋아요(?:\s*부탁\S*)?'
    r'|구독\s*(?:부탁\S*|버튼\s*눌러\S*|눌러\s*주\S*|해\s*주\S*)'
    r'|좋아요\s*부탁\S*'
    r'|알림\s*설정\s*부탁\S*'
)
_NEGATED = re.compile(
    r'(?:고민|걱정|문제|불안)(?:이|가|은|는|도|요)?\s*(?:없|안)'
    r'|어렵지\s*않|힘들지\s*않|막막하지\s*않|답답하지\s*않'
    r'|안\s*어렵|안\s*힘들|안\s*막막|안\s*답답'
)
_OVERCOME = re.compile(r'어렵(?:지만|었지만)|힘들(?:지만|었지만)|막막(?:했지만)')
_BROKEN = re.compile(
    r'안\s*돼|안\s*되|안\s*됩|안\s*됨|안되|안돼|안됨|안됩'
    r'|되지\s*않|되면\s*안'
    r'|오류|에러|버그|고장|실패'
    r'|작동(?:이|을|를)?\s*안'
    r'|안\s*나(?:와|옴|옵|오네|온다)'
    r'|안\s*보(?:여|입|임|인다|이네)'
    r'|안\s*들(?:려|립|림|리네|린다)'
    r'|(?<![a-z])(?:error|bug|crash)(?![a-z])'
)
_PROBLEM_WORD = re.compile(r'문제(?:가|는|점|있|돼|되|에요|예요|네|임)')
_LATE = re.compile(r'느리|느려|느린|느렸|느림|늦어|늦은|늦었|늦음|늦다|안\s*왔|안\s*와|안\s*옴|안왔|안와')
_HARD = re.compile(r'어렵|어려워|어려움|어려운|어려웠|힘들|막막|답답')
_COST = re.compile(r'비싸|비싼|비쌌|부담|돈이\s*없|돈\s*없')
_WORRY = re.compile(r'고민|걱정|불안|두렵|무서|스트레스|조마조마|초조|망설')
_COMPLAIN = re.compile(r'최악|실망|화나|화났|짜증|불편|불만|환불|사기|별로(?:예요|에요|다|네|임|야)')
_HELP = re.compile(
    r'도와\s*주|도와주|도와\s*줘|도와줘'
    r'|알려\s*주|알려주|알려\s*줘|알려줘'
    r'|조언(?:좀|해\s*주|부탁)?'
    r'|부탁(?:드릴|드립|해요|합니다|요)?'
    r'|방법(?:이|을|를|도)?\s*(?:없|좀|알려)'
    r'|어떻게\s*해야'
    r'|해결\s*(?:방법|좀|부탁|이\s*안|안\s*됨|안\s*돼)'
)
_CURIOUS = re.compile(r'궁금|어떻게|왜\s|왜요|뭘|뭐가|무엇|어디|언제|얼마')
_QUESTION_END = re.compile(
    r'(?:나요|까요|가요|습니까|인가요|일까요|을까요|ㄹ까요)\s*\??\s*$|\?\s*$'
)
_CUE_TAIL = (
    r'안\s*[돼되됩됨]|안되|안돼|안됨|안됩|느려|느리|느린|늦|어렵|어려워|어려운|어려움|어려웠|'
    r'힘들|막막|답답|걱정|고민|궁금|오류|에러|고장|비싸|비싼|부담|불편|실패|최악|실망|화나|짜증|환불|별로|'
    r'안\s*와|안\s*왔|안\s*옴|안\s*들|안\s*보|안\s*나|스트레스|불안|무서|두렵|문제|'
    r'(?<![a-z])(?:error|bug|crash)(?![a-z])'
)
_HEAD = re.compile(
    r'([0-9a-z가-힣]{2,16})\s*'
    r'(?:이|가|은|는|을|를|의|도|만)?\s*'
    r'(?:너무|정말|진짜|아직|계속|자꾸|좀|많이|매우|아주|완전)?\s*'
    r'(?:' + _CUE_TAIL + r')'
)
_TOKEN_CUE = re.compile(
    r'^(?:어렵|어려|힘들|막막|답답|느리|느려|늦|비싸|부담|고민|걱정|궁금|오류|에러|고장|실패|'
    r'불편|최악|문제|안되|안돼|부탁|알려|도와|실망|짜증|화나)'
)
_SUFFIX_WORDS = (
    '해주세요', '입니다', '합니다', '이라서', '인데요', '하나요', '할까요', '는데', '인데', '에서', '으로',
    '에게', '한테', '까지', '부터', '처럼', '보다', '나요', '까요', '가요', '네요', '데요',
    '어요', '아요', '해요', '세요', '예요', '에요', '주세요', '이죠', '죠', '은', '는', '이', '가', '을', '를',
    '의', '에', '도', '로', '와', '과', '만', '요', '음', '해',
)
_SUFFIXES = tuple(sorted(set(_SUFFIX_WORDS), key=len, reverse=True))
_SHORT_PARTICLES = set('이가은는을를')
_SHORT_ENDINGS = {'나요', '까요', '가요', '해요', '세요', '죠', '합니다', '입니다', '하나요', '할까요'}
_ONE_CHAR_STOP = set('이가은는을를의에도로와과요안못더좀왜뭐없있되하보오등및또잘')
STOP = {
    '너무', '정말', '진짜', '그냥', '그리고', '근데', '그래서', '그런데', '하지만', '이거', '저거',
    '그게', '그거', '제가', '저는', '저도', '우리', '여러분', '오늘', '지금', '계속', '아직',
    '조금', '많이', '아주', '매우', '영상', '댓글', '채널', '유튜브', '구독', '좋아요', '감사',
    '내용', '이야기', '정도', '같은', '이런', '저런', '그런', '있는', '없는', '하는', '되는',
    '합니다', '했어요', '입니다', '이번', '다음', '한번', '하나', '뭔가', '어떻게', '왜요',
    '뭐가', '무엇', '어디', '언제', '누가', '얼마', '궁금', '고민', '걱정', '문제', '오류',
    '에러', '버그', '고장', '실패', '불편', '불만', '최악', '실망', '부탁', '방법', '해결',
    '도와', '알려', '느려', '느리', '어렵', '힘들', '막막', '답답', '비싸', '부담', '무서',
    '두렵', '불안', '해요', '네요', '데요', 'ㅋㅋ', 'ㅎㅎ', 'ㅠㅠ', 'ㅜㅜ', '하는', '해요',
    '예요', '에요', '거죠', '인데', '주세요', '됩니다', '안돼요', '안됩니다', '이거', '그거',
    '저기', '여기', '뭔가', '살짝', '완전', '자꾸', '계속', '아직', '바로', '일단', '그냥',
    '거예요', '거에요', '건가요', '걸까요', '잖아요', '인데요', '이건', '저건', '그건',
    '열흘', '열흘째', '아직도', '요즘', '어제', '내일', '방금', '해야', '하나요', '할까요', '돼요', '하죠',
    '제발', '없나', '있나', '되나',
    'the', 'and', 'you', 'this', 'that', 'have', 'with', 'for', 'error', 'bug',
}


def external_ai_enabled():
    return os.getenv('ENABLE_EXTERNAL_AI', '').lower() == 'true'


def parse_day(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None


def normalize_text(text):
    raw = html.unescape(unicodedata.normalize('NFKC', text or ''))
    raw = _TAG.sub(' ', raw)
    raw = _URL.sub(' ', raw)
    raw = raw.replace('\u200b', '').replace('\ufeff', '')
    raw = raw.lower()
    raw = _SUBSCRIBE.sub(' ', raw)
    return _SPACE.sub(' ', raw).strip()


def strip_particle(token):
    changed = True
    guard = 0
    while changed and len(token) >= 2 and guard < 6:
        guard += 1
        changed = False
        for suffix in _SUFFIXES:
            if not token.endswith(suffix):
                continue
            remain = len(token) - len(suffix)
            short_ok = remain >= 1 and (suffix in _SHORT_ENDINGS or (len(suffix) == 1 and suffix in _SHORT_PARTICLES))
            if remain >= 2 or short_ok:
                token = token[:remain]
                changed = True
                break
            return token
    return token


def _usable(token):
    if not token or len(token) > 12:
        return False
    if len(token) == 1:
        if token in _ONE_CHAR_STOP or not re.match(r'[0-9a-z가-힣]', token):
            return False
    elif len(token) < 2:
        return False
    if token in STOP or token.isdigit():
        return False
    if _TOKEN_CUE.match(token):
        return False
    return True


def content_tokens(text):
    seen = []
    for raw in _TOKEN.findall(text):
        token = strip_particle(raw)
        if not _usable(token) or token in seen:
            continue
        seen.append(token)
    return seen


def _keyword_from_raw(raw):
    token = strip_particle(raw)
    if _usable(token):
        return token
    parts = re.split(r'(?:이|가|은|는|을|를|의|에|도|과|와|로|요)', raw)
    for part in parts:
        part = strip_particle(part.strip())
        if _usable(part):
            return part
    return None


def extract_keyword(text):
    for found in _HEAD.finditer(text):
        token = _keyword_from_raw(found.group(1))
        if token:
            return token
    return None


def _is_question(text, tokens):
    if not tokens:
        return False
    if _HOW_PRAISE.search(text) and not re.search(r'궁금|왜\s|얼마|무엇', text):
        return False
    return bool(_QUESTION_END.search(text) or _CURIOUS.search(text))


def _kind(cues):
    if any(cue in _PROBLEM_CUES for cue in cues):
        return 'problem'
    if 'worry' in cues:
        return 'worry'
    if 'help' in cues:
        return 'request'
    return 'question'


def detect_concern(text):
    """Return a concern dict, or None when the comment is not asking for help."""
    cleaned = normalize_text(text)
    substance = re.sub(r'[^0-9a-z가-힣]', '', cleaned)
    if len(substance) < 2:
        return None
    negated = bool(_NEGATED.search(cleaned))
    tokens = content_tokens(cleaned)
    keyword = extract_keyword(cleaned)
    cues = []
    if _BROKEN.search(cleaned) or (_PROBLEM_WORD.search(cleaned) and not negated):
        cues.append('broken')
    if _LATE.search(cleaned):
        cues.append('late')
    if _HARD.search(cleaned) and not _OVERCOME.search(cleaned) and not negated:
        cues.append('hard')
    if _COST.search(cleaned) and not re.search(r'부담\s*없', cleaned):
        cues.append('cost')
    if _COMPLAIN.search(cleaned) and (tokens or keyword):
        cues.append('complain')
    if _WORRY.search(cleaned) and not negated:
        cues.append('worry')
    if _HELP.search(cleaned):
        cues.append('help')
    if _is_question(cleaned, tokens or ([keyword] if keyword else [])):
        cues.append('how')
    if not cues:
        return None
    if _ADMIRATION.search(cleaned) and cues == ['how']:
        return None
    return {
        'kind': _kind(cues),
        'keyword': keyword if _usable(keyword) else None,
        'tokens': tokens,
        'cues': cues,
        'score': 3,
        'method': 'local',
        'external_summary': None,
    }


def _assign_themes(hits):
    freq = Counter()
    for hit in hits:
        freq.update(hit['tokens'])
    for hit in hits:
        if hit['keyword']:
            hit['theme'] = hit['keyword']
            continue
        ranked = sorted(hit['tokens'], key=lambda token: (-freq[token], token))
        repeated = [token for token in ranked if freq[token] >= 2]
        hit['theme'] = (repeated or ranked or [OTHER])[0]


def _bounded_int(name, default, low, high):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _limits():
    return (
        _bounded_int('CONCERN_AI_MAX_CALLS', 4, 1, CALL_CAP),
        _bounded_int('CONCERN_AI_BATCH', 20, 1, BATCH_CAP),
    )


def _endpoint():
    base = (os.getenv('SENTIMENT_API_URL') or os.getenv('MODAL_ML_BASE_URL') or '').strip()
    if not base:
        return None
    return base.rstrip('/') + '/concerns'


def _ai_headers():
    key = (os.getenv('SENTIMENT_API_KEY') or os.getenv('MODAL_ML_API_KEY') or '').strip()
    if not key:
        return None
    return {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + key,
        'X-API-Key': key,
    }


def _clean_external_theme(value):
    if not isinstance(value, str):
        return None
    text = _SPACE.sub(' ', value).strip()
    if not text or len(text) > 40 or re.search(r'[\r\n\t]', text):
        return None
    if not re.search(r'[가-힣a-z0-9]', text):
        return None
    return text


def _clean_external_summary(value):
    if not isinstance(value, str):
        return None
    text = _SPACE.sub(' ', value).strip()
    if len(text) < 4 or len(text) > 160 or re.search(r'[\r\n\t]', text):
        return None
    if not re.search(r'[가-힣]', text):
        return None
    return text


def _apply_external(payload, batch):
    if not isinstance(payload, dict):
        return
    items = payload.get('items')
    if not isinstance(items, list):
        return
    by_id = {str(hit['comment'].id): hit for hit in batch}
    for item in items:
        if not isinstance(item, dict):
            continue
        hit = by_id.get(str(item.get('id')))
        if hit is None:
            continue
        changed = False
        theme = _clean_external_theme(item.get('theme'))
        if theme:
            hit['theme'] = theme
            changed = True
        kind = item.get('kind')
        if isinstance(kind, str) and kind in KIND_LABELS:
            hit['kind'] = kind
            changed = True
        summary = _clean_external_summary(item.get('summary'))
        if summary:
            hit['external_summary'] = summary
            changed = True
        if changed:
            hit['method'] = 'external'


def refine_external(hits):
    """Relabel concerns with one capped batch endpoint. Returns calls made."""
    if not hits or not external_ai_enabled():
        return 0
    endpoint = _endpoint()
    if not endpoint:
        return 0
    import requests
    call_limit, batch_size = _limits()
    headers = _ai_headers()
    calls = 0
    for start in range(0, len(hits), batch_size):
        if calls >= call_limit:
            break
        batch = hits[start:start + batch_size]
        payload = {
            'items': [
                {'id': str(hit['comment'].id), 'text': (hit['comment'].text or '')[:TEXT_LIMIT]}
                for hit in batch
            ]
        }
        calls += 1
        kwargs = {'json': payload, 'timeout': 8, 'allow_redirects': False}
        if headers:
            kwargs['headers'] = headers
        try:
            response = requests.post(endpoint, **kwargs)
            response.raise_for_status()
            _apply_external(response.json(), batch)
        except Exception:
            continue
    return calls


def _delete_for(comment_ids):
    for start in range(0, len(comment_ids), 400):
        chunk = comment_ids[start:start + 400]
        CommentConcern.query.filter(CommentConcern.comment_id.in_(chunk)).delete(synchronize_session=False)


def analyze_comments(comments, use_external=False):
    """Replace stored concerns for these comments. External calls are opt-in."""
    unique = []
    seen = set()
    for comment in comments:
        if comment.id in seen:
            continue
        seen.add(comment.id)
        unique.append(comment)
    hits = []
    for comment in unique:
        found = detect_concern(comment.text)
        if not found:
            continue
        found['comment'] = comment
        hits.append(found)
    _assign_themes(hits)
    calls = refine_external(hits) if use_external else 0
    _delete_for([comment.id for comment in unique])
    for hit in hits:
        db.session.add(CommentConcern(
            comment_id=hit['comment'].id,
            kind=hit['kind'],
            theme=(hit['theme'] or OTHER)[:80],
            cues=','.join(hit['cues']),
            summary=hit['external_summary'],
            score=hit['score'],
            method=hit['method'],
            created_at=_utcnow(),
        ))
    db.session.commit()
    current_app.logger.info(
        'concern analysis comments=%s concerns=%s external_calls=%s',
        len(unique), len(hits), calls,
    )
    return {'concerns': len(hits), 'external_calls': calls}


def analyze_channel(channel_id, use_external=False):
    comments = (
        CollectedComment.query.join(Video, CollectedComment.video_id == Video.id)
        .filter(Video.channel_id == channel_id)
        .order_by(CollectedComment.id)
        .all()
    )
    return analyze_comments(comments, use_external=use_external)


def _filtered_rows(args):
    query = (
        db.session.query(CommentConcern, CollectedComment, Video)
        .join(CollectedComment, CommentConcern.comment_id == CollectedComment.id)
        .join(Video, CollectedComment.video_id == Video.id)
    )
    video_id = (args.get('video') or '').strip()
    if video_id:
        query = query.filter(Video.yt_video_id == video_id)
    start = parse_day(args.get('start'))
    end = parse_day(args.get('end'))
    if start:
        query = query.filter(CollectedComment.published_at >= start)
    if end:
        query = query.filter(CollectedComment.published_at < end)
    kind = (args.get('kind') or '').strip()
    if kind in KIND_LABELS:
        query = query.filter(CommentConcern.kind == kind)
    return query.all()


def build_summary(theme, count, likes, cue_counter, external_summary):
    stats = f'댓글 {count}개, 좋아요는 합계 {likes}개입니다.'
    if external_summary:
        return f'{external_summary.rstrip(" .")}. {stats}'
    ordered = [cue for cue, _count in sorted(
        cue_counter.items(),
        key=lambda item: (-item[1], _CUE_ORDER.index(item[0]) if item[0] in _CUE_ORDER else 99),
    )]
    phrases = [CUE_TEXT[cue] for cue in ordered if cue in CUE_TEXT][:2]
    if len(phrases) == 2:
        detail = phrases[0] + ', ' + phrases[1]
    elif phrases:
        detail = phrases[0]
    else:
        detail = ''
    if theme == OTHER:
        if detail:
            return f'한 주제로 묶이지 않았지만, {detail} 말한 댓글입니다. {stats}'
        return f'한 주제로 묶이지 않은 고민·문제입니다. {stats}'
    if detail:
        return f'{theme}에 대해 {detail} 말한 댓글입니다. {stats}'
    return f'{theme}에 대한 고민·문제입니다. {stats}'


def _kind_label(kinds):
    if not kinds:
        return '문제'
    best = max(kinds.values())
    tied = {kind for kind, count in kinds.items() if count == best}
    for kind in ('problem', 'worry', 'request', 'question'):
        if kind in tied:
            return KIND_LABELS[kind]
    return '문제'


def _comment_link(video_id, comment_id):
    return 'https://www.youtube.com/watch?v={}&lc={}'.format(
        quote(video_id or '', safe=''),
        quote(comment_id or '', safe=''),
    )


def _video_link(video_id):
    return 'https://www.youtube.com/watch?v={}'.format(quote(video_id or '', safe=''))


def concern_groups(args, limit=None):
    """Aggregate stored concerns for the current video and date filters."""
    buckets = {}
    for concern, comment, video in _filtered_rows(args):
        bucket = buckets.get(concern.theme)
        if bucket is None:
            bucket = {
                'theme': concern.theme,
                'count': 0,
                'likes': 0,
                'kinds': Counter(),
                'cues': Counter(),
                'summaries': [],
                'samples': [],
                'methods': Counter(),
            }
            buckets[concern.theme] = bucket
        bucket['count'] += 1
        bucket['likes'] += comment.like_count or 0
        bucket['kinds'][concern.kind] += 1
        bucket['methods'][concern.method or 'local'] += 1
        for cue in (concern.cues or '').split(','):
            if cue:
                bucket['cues'][cue] += 1
        if concern.summary:
            bucket['summaries'].append(concern.summary)
        published = comment.published_at
        bucket['samples'].append({
            'id': comment.id,
            'text': comment.text or '',
            'likes': comment.like_count or 0,
            'author': comment.author_display or '',
            'video_id': video.yt_video_id,
            'video_title': video.title,
            'comment_url': _comment_link(video.yt_video_id, comment.yt_comment_id),
            'video_url': _video_link(video.yt_video_id),
            'is_reply': bool(comment.parent_yt_comment_id),
            'published_label': published.strftime('%Y-%m-%d') if published else '',
            'published_ord': published.timestamp() if published else float('-inf'),
        })
    groups = []
    for bucket in buckets.values():
        samples = sorted(bucket['samples'], key=lambda sample: (
            -sample['likes'], -sample['published_ord'], -sample['id'],
        ))[:3]
        external = None
        if bucket['summaries']:
            external = Counter(bucket['summaries']).most_common(1)[0][0]
        groups.append({
            'theme': bucket['theme'],
            'count': bucket['count'],
            'likes': bucket['likes'],
            'summary': build_summary(bucket['theme'], bucket['count'], bucket['likes'], bucket['cues'], external),
            'kind_label': _kind_label(bucket['kinds']),
            'kind_counts': dict(bucket['kinds']),
            'samples': samples,
            'method': 'external' if bucket['methods'].get('external') else 'local',
        })
    groups.sort(key=lambda group: (-group['count'], -group['likes'], group['theme']))
    for index, group in enumerate(groups, start=1):
        group['rank'] = index
    total = len(groups)
    if limit is not None:
        groups = groups[:limit]
    return groups, total


def stored_concern_count():
    return CommentConcern.query.count()
