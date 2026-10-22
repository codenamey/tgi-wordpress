# First canary (operator-run only)

Prerequisites: an approved tested and scanned release with a verified registry
digest; confirmed GHCR owner/access; tested database and volume backups; recorded
current image digest and Compose configuration. None of the examples below
constitute a scheduled deployment.

For private GHCR packages use a read:packages token with the necessary package
access and `docker login ghcr.io --username <account> --password-stdin`. Keep the
token outside Compose, Git and shell history.

In a canary site's Compose file replace only its WordPress image reference with
`ghcr.io/<verified-owner>/tgi-wordpress@sha256:<approved-manifest-digest>`.
Keep its existing volumes, database variables, Traefik labels and networks.
Choose one low-risk site first and arrange a maintenance window if required.

After substituting verified values, the operator runs:

```bash
cd /path/to/canary-compose-project
docker compose config --quiet
docker compose pull wordpress
docker compose up -d --no-deps wordpress
docker compose exec -T wordpress php -r 'echo PHP_VERSION, PHP_EOL;'
docker compose logs --tail=100 wordpress
curl --fail --silent --show-error https://canary.example.invalid/ >/dev/null
```

Check the real site through Traefik, login, database connectivity, plugin/theme
compatibility, uploads, cron, forms and error logs. Monitor before proceeding to
a small server cohort, then the remaining hosts. Stop on failures. Updating the
container does not automatically update WordPress core in an existing volume.
