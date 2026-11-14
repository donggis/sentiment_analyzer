# 테스트 결과 (2026-11-13)

|명령|실제 결과|
|---|---|
|python -m compileall -q app run.py|성공, Python 3.14.3. 운영 Python 3.11 검증과 다름|
|python -m pytest --collect-only -q|실패: pytest 미설치|
|uvx --from pytest pytest --collect-only -q|실패: conftest import redis 누락. 테스트 실행 0건|
|uvx bandit -r app run.py -f json -o docs/bandit.json|완료, 중간 1/낮음 13, 발견사항 존재|
|uvx pip-audit -r requirements-production.txt --no-deps --disable-pip --format json --output docs/pip-audit.json|실패: email-validator 비고정 버전|
|fly auth whoami|로그인 확인. 계정 식별값은 보고서에 저장하지 않음|

미실행: 전체 의존성 설치 및 CVE 검사, Git 이력 비밀 스캔, Docker 빌드, API 모킹/실제 수집, 권한/CSRF/CSV 회귀, 지속성/부하/복원 테스트. 배포 미실행.

## 2026-11-14
설치: uv venv --python 3.11 .venv; uv pip install --python .venv/Scripts/python.exe -r requirements-production.txt pytest fakeredis pytest-mock pip-audit

.venv/Scripts/python.exe -m pytest tests/test_private_security.py -q: 24 passed, 2 warnings, 37.03s.
.venv/Scripts/python.exe -m pip_audit --format json --output docs/pip-audit.json: exit 1, 156 vulnerability reports / 8 packages. 수정 전 운영 의존성 기준.
전체 수집 결과는 docs/pytest-collection.txt 참고. 이 명령은 테스트 실행이 아님.

## 업그레이드 후 검증
- pip-audit: 알려진 취약점 0건 (설치 환경 기준).
- uv pip check: 통과.
- 보안 회귀: 24 passed, 2 warnings, 43.52s.
- 전체 수집: 234 tests collected, 25.85s. 이전 5개 수집 오류 해결(테스트 실행 성공 의미 아님).
- 외부 네트워크 차단 실행: pytest --ignore=tests/e2e -m "not integration and not youtube and not redis" --disable-socket -q --maxfail=10
- 결과: 10 failed, 20 passed, 3 deselected, 109.50s. 10개 실패에서 중단하여 나머지 미실행. 기존 SaaS 인증 테스트는 관리자 설정 부재로 503을 받아 실패. 테스트를 통과시키기 위해 앱 인증을 우회하지 않음.
- Fly 배포 미실행. docs/DEPLOYMENT.md 참고.

## 외부 전송 기본 차단 검증
명령: .venv/Scripts/python.exe -m pytest tests/test_private_security.py tests/test_private_egress.py --disable-socket -q
결과: 31 passed, 2 warnings in 22.16s.
검증 범위: 운영 키, 기존 결제/메일/OAuth 차단, 외부 AI opt-in 부재 시 HTTP 미호출, 기존 Basic Auth 접근 제어. 관리자 세션/CSRF/클러스터링/배포 검증은 포함하지 않음.

## 2026-11-14 관리자 세션과 수집 이후
명령: `.venv/bin/python -m pytest -q`
결과: 196 passed, 17 skipped, 6 warnings, 약 20초. Python 3.12.3.
건너뛴 항목: 브라우저가 필요한 Playwright e2e, 서버가 꺼져 있어 건너뛴 캐시 시연, Redis Cloud 주소가 없을 때의 연결 테스트, integration으로 표시된 API 테스트 1건.
포함: 로그인, CSRF 없는 POST 거부, 비밀번호 5회 실패 후 429, 로그인 없이 API와 CSV 401, 결제/문의/기존 OAuth 404, 유료 AI 기본 미호출, 가짜 YouTube API로 페이지 나누기/이어받기/중복 없음/답글/주제 묶음, SQLite 파일을 새 앱에서 다시 열어도 댓글 유지.
배포와 Fly 자원 생성은 하지 않았습니다.

