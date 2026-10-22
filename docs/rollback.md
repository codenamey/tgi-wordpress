# Rollback

Retain the previous immutable image reference, Compose file and backups of both
the WordPress volume and database. If only the runtime changed and no data/schema
changes occurred, restore the previous image reference and run:

```bash
docker compose pull wordpress
docker compose up -d --no-deps wordpress
docker compose logs --tail=100 wordpress
```

A container rollback cannot reverse WordPress or plugin database migrations or
core files changed inside persistent volumes. When such changes occurred,
restore matching database and file backups together using the site's tested
recovery procedure. Preserve incoming data before restoring a backup. Never run
`docker compose down -v` as a rollback operation.

Returning to a vulnerable PHP image reintroduces the vulnerability. Prefer a
corrected rebuild or isolate the canary while resolving a compatibility problem;
record the security consequences of any emergency rollback.
