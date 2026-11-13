# Private Fly.io deployment (not yet validated)
This branch is a security-hardening work in progress. Do not deploy until dependency audit, endpoint authorization review, and smoke tests pass.

1. Review the full repository for secrets and license constraints.
2. Run `pip-audit -r requirements-production.txt` and fix reported vulnerabilities.
3. Review routes for background jobs, billing, OAuth, CSRF, and request limits.
4. Configure Fly.io account and billing. Use a unique app name in fly.toml.
5. Generate random secrets locally. Do not commit them.
6. Set `SECRET_KEY` (32+ random characters), `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `YOUTUBE_API_KEY`, and a persistent `DATABASE_URL` using `fly secrets set`.
7. Deploy with `fly deploy`, only after the checks pass.
8. Test unauthenticated 401, authenticated access, API behavior, and persistence.

HTTP Basic Auth is a temporary administrator gate, not MFA or a full security review. Do not expose private content without HTTPS. The /healthz endpoint is deliberately public and contains no sensitive details. SQLite in an ephemeral container is not suitable for durable data.
