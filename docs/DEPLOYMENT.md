# Fly 배포 준비 상태 — 2026-11-14

현재 배포 불가. 기존 앱 sentiment-analyzer-ywuuhq는 personal 조직/nrt, suspended, Machines=[], 볼륨 없음, Secrets 없음. fly.toml의 donggis-sentiment-private는 현재 계정에서 조회되지 않음. 기존 앱을 수정하거나 리소스를 생성하지 않음.

## 배포 전 필수
1. 관리자 세션/비밀번호 해시/CSRF/로그인 제한, 외부 전송 기본 차단을 완료하고 테스트.
2. 채널 수집 미구현 부분과 영구 DB migration/backup/restore 검증.
3. 업그레이드 의존성의 회귀 테스트, 비밀/이미지 스캔, 라이선스 확인.
4. 실제 리소스 구성 및 비용 확정 후 사용자 승인. 기존 앱에 머신을 추가해도 과금 가능.
5. 사용자가 직접 Fly Secrets에 SECRET_KEY, 관리자 인증 설정, YOUTUBE_API_KEY, DATABASE_URL 등록. 채팅에 값 입력 금지. 최종 인증 방식 확정 전 기존 ADMIN_PASSWORD 설정을 요구하지 않음.
6. 스테이징 배포 및 HTTPS/미인증 차단/실제 수집/재시작 데이터 지속성 검증 후 운영 전환.

Dockerfile.fly는 현재 production requirements를 설치하므로 해당 파일에 감사된 버전을 반영했다. 이미지 빌드 및 배포는 미실행.
