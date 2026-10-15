# Working native parser packaged in Docker

Application source and exact pip dependencies are copied from /root/parse-tender.
RTS-Tender uses PROXIES from config.runtime.py. Telegram uses a direct connection.
The runtime configuration is mounted read-only at /app/config.py and is excluded from the image.
SQLite lives at /opt/parser-tender/data/tenders.db; /data is the working directory.
Timezone: Europe/Moscow, matching the original process.

Commands (run from /opt/parser-tender):
- docker compose ps
- docker compose logs -f --tail=100
- docker compose stop
- docker compose up -d
- docker compose up -d --build (after code changes)
- docker compose up -d --force-recreate (after runtime config changes)

Do not start /root/parse-tender/main.py at the same time as this container.
Keep config.runtime.py private (root:10001, mode 0440).
The container runs as UID 10001 with a 600 MB RAM limit and at most 900 MB RAM+swap.
Existing VPS services are unchanged; Watchtower is disabled for this container.

One container-only reliability change: wait up to 60 seconds for visible tender titles before extracting cards. The original /root/parse-tender sources are unchanged.


Notification switches in compose.yaml:
- TELEGRAM_ENABLED defaults to true. Set to "false" to disable all Telegram messages without removing CHAT_ID or BOT_TOKEN.
- MAX_ENABLED controls MAX independently. Both switches accept true, 1, yes (case-insensitive) to enable.
- Apply changes with docker compose up -d --force-recreate.
- Telegram messages skipped while disabled are not queued for later delivery.

MAX integration:
- MAX_ENABLED=true enables MAX for newly discovered tenders only.
- MAX_CHAT_IDS and MAX_USER_IDS are comma-separated recipient IDs.
- MAX_TOKEN_FILE points to a read-only secret file, never baked into the image.
- MAX_CA_BUNDLE optionally points to a trusted PEM bundle for MAX only; TLS verification is always enabled.
- New tenders and MAX deliveries are inserted in one SQLite transaction.
- Pending deliveries retry at startup and after each parsed page, after a delay of at least 30 minutes on errors.
- A MAX outage does not discard the queue or change Telegram delivery state.
- Old tenders are not backfilled. Removing a target pauses its pending deliveries.
- Delivery is at-least-once: a lost API response or crash after acceptance can cause a duplicate retry.
- Telegram delivery behavior is unchanged from the native parser.
Tests: python -m unittest -v test_max (temporary databases and mocked API; no messages).

Telegram secret: secrets/telegram_token (root:10001, mode 0440), mounted read-only at /run/secrets/telegram_token. TELEGRAM_TOKEN_FILE sets the path. config.runtime.py reads it only when TELEGRAM_ENABLED is enabled. The token is excluded from the image.
