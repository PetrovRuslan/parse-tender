"""MAX notifications. No proxy inheritance, tokens only in Authorization."""
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
import requests

API_URL = 'https://platform-api2.max.ru'

@dataclass
class MaxSettings:
    enabled: bool = False
    token: str = field(default='', repr=False)
    targets: tuple = ()
    ca_bundle: object = True

    @classmethod
    def from_env(cls):
        if os.getenv('MAX_ENABLED', 'false').lower() not in ('true', '1', 'yes'):
            return cls()
        token = Path(os.getenv('MAX_TOKEN_FILE', '/run/secrets/max_token')).read_text().strip()
        targets = []
        for key, kind in [('MAX_CHAT_IDS', 'chat_id'), ('MAX_USER_IDS', 'user_id')]:
            for raw in os.getenv(key, '').split(','):
                if raw.strip():
                    target = (kind, int(raw.strip()))
                    if target not in targets:
                        targets.append(target)
        if not token or not targets:
            raise ValueError('MAX requires a token and at least one recipient')
        return cls(True, token, tuple(targets), os.getenv('MAX_CA_BUNDLE') or True)

@dataclass
class SendResult:
    success: bool
    error: str = ''
    retry_after: int = 1800
    stop_batch: bool = False


def format_tender(tender):
    # Plain text avoids HTML parsing failures; stay below MAX's 4000-char limit.
    return (f"🔔 Новый тендер\n\n📌 Название:\n{str(tender.get('title') or '')[:1600]}"
            f"\n\n📝 Цена:\n{str(tender.get('description') or '')[:500]}"
            f"\n\n⏰ Подать заявку до:\n{str(tender.get('deadline') or '')[:100]}"
            f"\n\n🔗 Ссылка:\n{str(tender.get('link') or '')[:1000]}")

class MaxNotifier:
    def __init__(self, settings=None):
        self.settings = settings or MaxSettings.from_env()

    def send(self, text, kind, recipient):
        if not self.settings.enabled:
            return SendResult(False, 'disabled', stop_batch=True)
        if kind not in ('chat_id', 'user_id'):
            raise ValueError('Invalid MAX recipient type')
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(
                    API_URL + '/messages',
                    params={kind: int(recipient)},
                    headers={'Authorization': self.settings.token},
                    json={'text': text[:4000], 'notify': True},
                    timeout=(10, 20), verify=self.settings.ca_bundle,
                    allow_redirects=False,
                )
                if response.status_code == 200:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get('message'), dict):
                        return SendResult(True)
                    return SendResult(False, 'invalid_response', stop_batch=True)
                delay = 1800
                if response.status_code == 429:
                    try:
                        delay = max(delay, int(response.headers.get('Retry-After', delay)))
                    except (TypeError, ValueError):
                        pass
                return SendResult(False, f'HTTP_{response.status_code}', delay,
                                  response.status_code in (401, 429) or response.status_code >= 500)
        except requests.RequestException as error:
            # Do not log raw responses, headers, tokens, or request exception URLs.
            return SendResult(False, type(error).__name__, stop_batch=True)
        except ValueError:
            return SendResult(False, 'invalid_json', stop_batch=True)

    async def flush(self, db):
        if not self.settings.enabled:
            return
        allowed = set(self.settings.targets)
        for row in await db.pending_max_deliveries():
            if (row['target_type'], int(row['target_id'])) not in allowed:
                continue
            result = await asyncio.to_thread(self.send, row['message'], row['target_type'], row['target_id'])
            await db.record_max_result(row['id'], result.success, result.error, result.retry_after)
            if result.success:
                print('✅ Уведомление MAX отправлено')
            else:
                print(f'⚠️ MAX: {result.error}; уведомление сохранено для повтора')
            if result.stop_batch:
                break
            await asyncio.sleep(1)
