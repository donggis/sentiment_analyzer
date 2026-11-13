# Phase A 보안 감사 — 진행 중

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
