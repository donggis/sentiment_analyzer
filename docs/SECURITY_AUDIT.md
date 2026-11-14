# Phase A 보안 감사 — 2026-11-14 갱신

아래 표는 2026-11-13에 찾은 항목입니다. 표 아래 날짜별 기록과 맨 끝 절이 그 이후 조치입니다. 최신 상태는 맨 끝의 "관리자 세션과 수집" 절입니다.

기준: 2026-11-13, donggis/sentiment_analyzer, 50381eafe5a3bf2988c5857137b925f43a50e33b.
작업 브랜치: feat/t3-private-youtube-dashboard. 원본 변경 없음. main 대비 보안 브랜치 변경: 7개 파일, +115/-6.
263개 추적 파일 목록 확인. 전체 수동 감사 완료를 의미하지 않음.

|심각도|근거 및 재현/검증 절차|상태 및 조치|
|---|---|---|
|높음|app/config.py Config.SECRET_KEY 개발 키 fallback; create_app 직접 호출에는 검증 없음. run.py는 FLASK_ENV 문자열이 production일 때만 검사하므로 다른 값에서 production config로 fallback하면서 검사 생략 가능|미해결. factory에서 운영 설정 검증 필요|
|높음|app/main/routes.py:1582 /subscribe/stripe 및 :1608 /webhook/stripe는 app/__init__.py 차단 목록 누락. 인증 후 해당 라우트 진입 가능. 실제 Stripe 호출은 미실행|미해결. 결제 라우트 전체 제거 및 호출 차단 테스트 필요|
|높음|app/auth/routes.py:168 구독 성공 라우트에서 결제 검증 없이 상태 변경. 현재 before_request가 이 경로를 차단|부분 완화. 로직 제거와 회귀 테스트 필요|
|높음|Basic Auth에 평문 환경변수 비밀번호 비교, 로그인 제한 없음. 전역 CSRFProtect 초기화 없음|미해결. 해시 기반 관리자 세션, CSRF, 공유 저장소 로그인 제한 필요|
|높음|fly.toml에 영구 볼륨/DB 설정 없음. config.py DB 미설정 시 로컬 SQLite|미해결. 배포 금지, 영구 DB와 복구 검증 필요|
|중간|app/auth/routes.py:69-71 next 값을 검증 없이 redirect|미해결. 로컬 경로만 허용|
|중간|app/services/sentiment_api.py URL 환경변수 설정만으로 외부 호출 활성화|미해결. 별도 명시적 동의 플래그 필요|
|중간|app/main/routes.py:365 원본 개발자 이메일 수신처. /contact는 현재 차단|부분 완화. 메일 기능 제거 필요|
|기능 차단|app/main/channel_routes.py:118 UC_placeholder, :299 동기화 TODO; :21 Pro 구독 검사|미구현. 실제 API 파이프라인 및 관리자 권한 재설계|
|배포 차단|추적 LICENSE 파일 및 .github/workflows 없음|라이선스 권한 확인 및 CI 추가 필요. 배포 권한을 추정하지 않음|

## 외부 전송 목록
YouTube Data API(요구 기능), Modal/외부 sentiment API(댓글 전송), Google OAuth(로그인), Stripe(결제), SMTP(메일), Redis(캐시/큐), 설정된 PostgreSQL. 템플릿 CDN 및 다른 전송 경로는 추가 조사 필요. 외부 서비스를 활성화하거나 실데이터를 전송하지 않음.

## 자동 검사
Bandit 1.9.4: 5905 LOC, HIGH 0 / MEDIUM 1 / LOW 13, 오류 0. docs/bandit.json 참고. MEDIUM은 run.py 0.0.0.0 바인딩으로 컨테이너 용도상 검토 필요. HIGH 0은 안전 판정이 아님.
pip-audit 간이 검사 실패: email-validator>=2.0.0이 정확한 버전 고정이 아니므로 --disable-pip 모드에서 처리 불가. 실제 해석된 Python 3.11 의존성 전체 검사를 해야 함.
gitleaks 미설치: 전체 Git 이력 비밀 스캔 미실행. 비밀 없음 판정 불가.
Docker CLI 없음: 빌드/non-root 런타임 검증 미실행.
GitHub 공개 clone 성공, 쓰기 권한 미확인(gh 미설치). Fly 로그인 확인, 조직/비용 미확인.

## 2026-11-14 보안 수정 1차
- Python 3.11.16 .venv에 운영 의존성과 pytest/fakeredis/pytest-mock/pip-audit 설치 완료.
- 개발 SECRET_KEY fallback 제거. 모든 운영 factory 진입점에서 키/관리자 설정 검사. run.py 문자열 분기에 의존하던 검증 제거.
- /subscribe/stripe, /webhook/stripe 차단 추가. 기존 결제/문의 경로 포함 인증 후에도 404 검증.
- 세션 Secure/HttpOnly/SameSite=Lax 기본값. UTF-8 Basic Auth 입력의 compare_digest TypeError 방지.
- 새 tests/test_private_security.py: 24 passed, 2 warnings (37.03s).
- pip-audit 설치 환경 검사 완료: 8개 패키지에 취약점 보고 156건. docs/pip-audit.json 참조. 기존 간이 검사 실패를 대체하는 실제 검사 결과이며 통과가 아님.
- 취약 패키지: aiohttp, Authlib, Flask, gunicorn, PyJWT, python-dotenv, requests, urllib3. 의존성 업그레이드/호환성 검증 미완료.
- 아직 미완료: 관리자 세션/해시/로그인 제한/전역 CSRF, 외부 전송 전체 차단, Git 이력 비밀 스캔, 전체 테스트 통과, 배포.

## 2026-11-14 배포 준비 중 의존성 수정
운영 requirements의 Flask/aiohttp/Authlib/gunicorn/PyJWT/python-dotenv/requests/urllib3 및 google-auth 버전을 업그레이드했다.
설치 환경 pip-audit 재검사: No known vulnerabilities found (docs/pip-audit-upgraded.json). uv pip check: 102 packages, compatible.
이 결과는 소스 취약점, 컨테이너 OS, 라이선스, 실제 배포 안전성 검증을 대체하지 않는다.
Fly 기존 앱 sentiment-analyzer-ywuuhq: 머신/볼륨/Secrets 없음. 리소스 생성/배포 미실행.

## 외부 전송 차단 후속 수정
- sentiment API는 ENABLE_EXTERNAL_AI=true 명시 전 요청을 거부한다. URL/키 설정만으로 활성화되지 않는다.
- 기존 Flask-Mail 전송 경로는 공통 transport에서 거부한다.
- /auth/ 이하 기존 OAuth/회원/결제 경로 차단. 신규 관리자 세션 구현 전에는 기존 Google 로그인도 사용 불가.
- 새 발견: migrations/versions/a140228fb140_make_theresa_pro_user.py가 특정 원본 개발자 이메일의 구독 권한을 변경한다. 신규 개인용 배포 migration 설계에서 제거 필요. 현재 실행하지 않음.
- 실제 회귀 테스트: 31 passed, 2 warnings, 22.16s. --disable-socket으로 외부 네트워크 차단.

## 2026-11-14 관리자 세션과 수집
- Git 이력 비밀 스캔: API 키 형식(AIza), AWS 키, 개인키, Stripe 라이브 키, GitHub 토큰은 추가된 줄에서 찾지 못했습니다. 문서와 예제에 있는 데이터베이스 주소는 `password` 같은 자리표시자입니다. 실제 비밀 값은 이 문서에 적지 않습니다.
- 원본 개발자 계정에 구독 권한을 주던 마이그레이션 `a140228fb140`을 삭제했습니다. 다음 리비전이 그 앞 리비전을 가리키게 고쳤습니다. 이력 커밋에는 남아 있으므로 히스토리를 다시 쓰지 않았습니다. `run_migration.py`도 더 이상 그 계정을 바꾸지 않습니다. 문의 메일의 고정 수신 주소도 제거했습니다. 개인정보/약관 템플릿에는 예전 연락 메일이 아직 있습니다. 그 화면은 관리자 로그인 뒤에만 열립니다.
- 임시 Basic Auth를 제거했습니다. 관리자는 `ADMIN_USERNAME`과 `ADMIN_PASSWORD_HASH`(Werkzeug 해시)로 로그인합니다. 세션 번호만 쿠키에 있고, 원문은 데이터베이스 해시로만 확인합니다. 쿠키는 HttpOnly, SameSite=Lax, 운영에서는 Secure입니다. 잘못된 비밀번호는 15분에 5번이면 429입니다. 실패 기록은 데이터베이스에 있어 워커가 여러 개여도 같이 셉니다. POST에는 Flask-WTF CSRF가 필요합니다. `next`는 사이트 안 경로만 허용합니다.
- 유료 외부 AI는 `ENABLE_EXTERNAL_AI=true`가 없으면 호출하지 않습니다. 주제 묶음은 기본으로 이 서버 안의 단어 묶음입니다.
- 라이선스: README가 MIT라고 적혀 있었고 저장소 이력에는 LICENSE 파일이 없었습니다. README와 같게 MIT LICENSE 파일을 추가했습니다. 의존성 중 psycopg, psycopg-binary, psycopg2-binary는 LGPL입니다. 앱은 이 라이브러리를 가져다 쓰는 형태입니다. numpy 메타데이터의 License 칸에 GPL 단어가 보이지만 분류와 본문은 BSD 계열입니다. 배포 권한을 이 검사만으로 확정하지 않습니다.
- Fly 리소스는 만들지 않았고, 시크릿을 바꾸거나 배포하지 않았습니다.

