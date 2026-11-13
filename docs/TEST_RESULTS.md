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
