# Fly 배포 안내 — 2026-11-14

아직 배포하지 않았습니다. 비용을 승인한 뒤에만 아래 순서를 실행하세요. 이 문서를 만든 작업에서는 머신을 만들지 않았고, 볼륨을 만들지 않았고, 시크릿을 바꾸지 않았고, 배포하지 않았습니다.

앱 이름: `sentiment-analyzer-ywuuhq`
리전: `nrt`
설정 파일: `fly.toml`
데이터: 1GB 볼륨 `sentiment_data`를 `/data`에 붙이고, SQLite 파일은 `/data/app.db`입니다.
머신: shared CPU 1개, 메모리 512MB. 요청이 없으면 멈추고, 요청이 오면 다시 켜집니다.
헬스 체크: `GET /healthz` (로그인 없이 `{ "ok": true }`만 반환)

## 한 달 비용 추정

Fly 공식 가격표(가장 싼 미국 리전 `iad`/`ewr`, 2026-11-14 문서) 기준입니다. 이 앱의 리전은 도쿄(`nrt`)라서 머신 요금이 더 높을 수 있습니다. 승인 전에 https://fly.io/docs/about/pricing 에서 `nrt` 가격을 다시 확인하세요.

| 항목 | 대략적인 달 요금 |
|---|---|
| shared-cpu-1x, 메모리 512MB, 한 달 내내 켜짐 | $3.69 |
| 볼륨 1GB | $0.15 |
| 공유 IPv4 | $0 |
| 전용 IPv4를 일부러 만들 때 | $2 |
| 아시아에서 밖으로 나가는 데이터 | $0.04/GB. 들어오는 데이터는 $0 |
| 관리형 Postgres | 사용하지 않음 |

항상 켜 두면 미국 가격으로 약 $3.84에 적은 트래픽 요금이 더해집니다. `auto_stop`이 켜져 있으면 머신이 돌고 있는 초만 계산 요금이 나오고, 꺼져 있는 동안에는 볼륨과 루트 디스크($0.15/GB)가 계속 과금됩니다. 첫 배포로 머신이 생기면 그때부터 요금이 시작됩니다.

YouTube Data API 할당량은 Fly 요금과 별개입니다.

## 소유자가 넣을 시크릿 이름

값은 채팅이나 git에 넣지 마세요. 이름만 적습니다.

반드시 있어야 하는 이름:

- `SECRET_KEY` — 32자 이상의 무작위 문자열
- `ADMIN_USERNAME` — 관리자 아이디
- `ADMIN_PASSWORD_HASH` — 비밀번호 원문이 아니라 Werkzeug 해시
- `YOUTUBE_API_KEY` — 이미 이 앱의 시크릿으로 들어 있는 상태. 값을 다시 묻거나 출력하지 않습니다.

`fly.toml`에 이미 들어 있어 시크릿이 아닌 값:

- `DATABASE_URL` = `sqlite:////data/app.db`
- `TARGET_CHANNEL_URL` = `https://www.youtube.com/@jangpm`
- `FLASK_ENV` = `production`

넣으면 안 되는 이름:

- `ADMIN_PASSWORD` — 평문 비밀번호는 거부됩니다.
- `ENABLE_EXTERNAL_AI` — 넣지 않으면 유료 AI는 꺼진 상태입니다. 나중에 켜려면 값을 `true`로 하고, 그 호출 주소도 그때 정합니다.
- `STRIPE_SECRET_KEY`, `GOOGLE_CLIENT_SECRET`, `MAIL_PASSWORD` — 이 배포에서는 쓰지 않습니다.

해시 만들기 (비밀번호는 화면에 남지 않습니다):

```bash
python scripts/print_password_hash.py
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

등록:

```bash
fly secrets set -a sentiment-analyzer-ywuuhq \
  SECRET_KEY="방금 만든 값" \
  ADMIN_USERNAME="관리자 아이디" \
  ADMIN_PASSWORD_HASH="방금 만든 해시"
```

`YOUTUBE_API_KEY`는 이미 있으므로 위 명령에 넣지 않아도 됩니다. 키를 바꿀 때만 같은 방식으로 그 이름을 설정합니다.

## 배포 순서

1. 위 비용과 `nrt` 가격을 확인하고 승인합니다.
2. 이 브랜치가 `security/fly-private-deploy`에 합쳐진 뒤, 그 코드를 받아서 작업 디렉터리로 이동합니다.
3. 볼륨이 없을 때만 만듭니다. 이미 있으면 건너뜁니다.

```bash
fly volumes create sentiment_data --region nrt --size 1 -a sentiment-analyzer-ywuuhq
```

4. 위 시크릿 세 개를 설정합니다.
5. 배포합니다.

```bash
fly deploy -a sentiment-analyzer-ywuuhq
```

6. 확인합니다.

```bash
fly status -a sentiment-analyzer-ywuuhq
fly checks list -a sentiment-analyzer-ywuuhq
```

브라우저에서 `/healthz`는 로그인 없이 열리고, `/admin`과 `/api/stats`와 CSV는 로그인 전에 막혀 있어야 합니다. 로그인한 뒤 채널 `https://www.youtube.com/@jangpm`으로 수집을 몇 페이지씩 이어 갑니다. 머신을 재시작해도 `/data/app.db`의 댓글이 남아 있어야 합니다.

## 백업과 복구

데이터베이스 파일은 볼륨의 `/data/app.db`입니다. 이미지 안의 다른 폴더는 머신이 바뀌면 사라집니다.

백업:

```bash
fly ssh console -a sentiment-analyzer-ywuuhq -C "mkdir -p /data/backups && cp /data/app.db /data/backups/app.db"
```

앱 안의 `python scripts/db_backup.py`도 SQLite가 `/data` 아래면 `/data/backups`에 압축 파일을 만듭니다. Fly 볼륨 스냅샷은 콘솔에서 추가로 켜 둘 수 있습니다. 스냅샷은 저장된 용량 기준이며, 문서상 매월 처음 10GB는 무료이고 그다음부터 GB당 $0.08입니다.

복구:

1. 앱 머신을 멈춰 파일 쓰기가 겹치지 않게 합니다.
2. 백업 파일을 `/data/app.db` 자리에 덮어씁니다.
3. 머신을 다시 시작합니다.
4. 댓글 개수가 백업 시점과 같은지 관리자 화면에서 확인합니다.

`python scripts/db_restore.py`는 `/data/backups`가 있으면 그 폴더의 백업을 사용합니다.

## 롤백

데이터 파일이 아니라 앱 버전만 되돌릴 때:

```bash
fly releases -a sentiment-analyzer-ywuuhq
fly releases rollback <버전번호> -a sentiment-analyzer-ywuuhq
```

롤백은 디스크의 SQLite를 자동으로 되돌리지 않습니다. 수집 데이터가 잘못된 경우에는 위 백업 파일을 복구하세요. 볼륨을 지우면 댓글이 사라지므로, 삭제 전에 백업을 받습니다.
