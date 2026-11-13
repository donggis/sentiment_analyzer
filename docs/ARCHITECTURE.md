# 아키텍처 제안 — 승인 전 초안

현재 Flask factory + SQLAlchemy/Migrate + Flask-Login + OAuth, Redis 캐시/기존 분석 작업, 외부 sentiment API 구성. Basic Auth가 모든 요청 앞에 추가되었지만 기존 사용자/Pro 구독 권한과 충돌한다.

제안: Flask와 마이그레이션 기반을 유지하고 개인 관리자 전용 경로로 정리한다. 관리자 해시 비밀번호와 세션, CSRF, 로그인 제한을 적용한다. Google OAuth/Stripe/메일/외부 AI는 기본 차단한다. Basic Auth만으로 최종 인증을 완료하지 않는다.

데이터: PostgreSQL에 채널/영상/댓글/수집 작업/태그/클러스터/감사 이벤트를 저장한다. 기존 모델과 실제 migration을 대조한 뒤 증분 migration 작성. 작성자 식별자 최소화. DB 기반 작업 lease와 cursor를 통해 HTTP와 별도 worker로 수집하고 재시작 시 재개한다. 추가 Redis 필요성은 기존 구현 검토 후 결정한다.

공식 YouTube API: 채널 정규화 → uploads playlist 전체 페이지 → 영상 메타데이터 → commentThreads → comments 답글 전체 페이지. 댓글 ID unique upsert, 페이지별 cursor/데이터 원자적 commit, 재시도 상한/할당량 예산/오류 상태 기록. Shorts는 길이만으로 확정하지 않고 추정과 미확정을 구분한다.

한국어 키워드 태그는 주제 클러스터와 별도 저장하고 신뢰도/미분류를 노출한다. 초기 로컬 분석을 사용하며 모델 선택과 라이선스 검토는 후속 작업이다. 검색/기간/영상/주제 필터와 관리자 CSV 내보내기에서 수식 주입을 방어한다.

YouTube 보관/갱신 정책 공식 문서 확인은 미완료이며 정책 수치와 자동 삭제 주기는 확정하지 않는다. Fly 자원 크기는 측정 후 결정한다. 영구 DB/백업 복원 검증 및 비용 승인 전 배포하지 않는다.
