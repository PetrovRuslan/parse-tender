"""
Вспомогательные утилиты для парсера
"""

import asyncio
from typing import Callable, TypeVar, Optional
from datetime import datetime

import requests

T = TypeVar('T')


async def retry_async(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 2.0,
    exponential: bool = True,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None
) -> T:
    """
    Retry логика для асинхронных функций с экспоненциальной задержкой
    
    Args:
        func: Асинхронная функция для выполнения
        max_retries: Максимальное количество попыток
        base_delay: Базовая задержка в секундах
        exponential: Использовать экспоненциальную задержку
        exceptions: Какие исключения обрабатывать
        on_retry: Callback функция при повторной попытке
        
    Returns:
        Результат выполнения функции
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            
            if attempt < max_retries - 1:
                if exponential:
                    delay = base_delay * (2 ** attempt)
                else:
                    delay = base_delay
                
                print(f"⚠️  Попытка {attempt + 1}/{max_retries} не удалась: {str(e)[:100]}")
                print(f"⏳ Повтор через {delay:.1f} секунд...")
                
                if on_retry:
                    await on_retry(attempt, e)
                
                await asyncio.sleep(delay)
            else:
                print(f"❌ Все {max_retries} попытки исчерпаны")
    
    raise last_exception


def log_error(error: Exception, context: str = ""):
    """Логирует ошибку с контекстом"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_msg = f"[{timestamp}] ERROR in {context}: {type(error).__name__}: {str(error)}"
    print(error_msg)
    
    # Записываем в файл
    try:
        with open('errors.log', 'a', encoding='utf-8') as f:
            f.write(error_msg + '\n')
    except:
        pass

def parse_proxy(proxy_str: str) -> dict:
    """Парсит 'IP:PORT:ЛОГИН:ПАРОЛЬ' (или 'IP:PORT') в dict для Playwright."""
    parts = proxy_str.strip().split(':')
    if len(parts) == 4:
        ip, port, user, password = parts
        return {'server': f'http://{ip}:{port}', 'username': user, 'password': password}
    elif len(parts) == 2:
        ip, port = parts
        return {'server': f'http://{ip}:{port}'}
    raise ValueError(f"Неверный формат прокси: {proxy_str}")


def _proxy_to_requests(proxy: dict) -> dict:
    """Playwright-proxy -> формат для requests."""
    host = proxy['server'].replace('http://', '')
    if proxy.get('username'):
        url = f"http://{proxy['username']}:{proxy['password']}@{host}"
    else:
        url = proxy['server']
    return {'http': url, 'https': url}


def find_working_proxy(proxies_str: str, test_url: str, timeout: int = 15):
    """
    Проверяет прокси по очереди и возвращает первую рабочую (в формате Playwright).
    None — если рабочих нет.
    """
    if not proxies_str:
        return None

    proxy_strings = proxies_str.split()
    print(f"\n🔍 Проверка {len(proxy_strings)} прокси...")

    for i, proxy_str in enumerate(proxy_strings, 1):
        try:
            proxy = parse_proxy(proxy_str)
        except ValueError:
            print(f"   ⚠️  Прокси #{i}: неверный формат, пропускаем")
            continue

        ip_port = proxy['server'].replace('http://', '')
        try:
            resp = requests.get(test_url, proxies=_proxy_to_requests(proxy), timeout=timeout)
            # Любой HTTP-ответ = соединение установлено
            print(f"   ✅ Прокси #{i} ({ip_port}) работает (HTTP {resp.status_code})")
            return proxy
        except requests.exceptions.ProxyError:
            print(f"   ❌ Прокси #{i} ({ip_port}): ошибка прокси")
        except requests.exceptions.ConnectTimeout:
            print(f"   ❌ Прокси #{i} ({ip_port}): таймаут подключения")
        except requests.exceptions.Timeout:
            print(f"   ❌ Прокси #{i} ({ip_port}): таймаут")
        except Exception as e:
            print(f"   ❌ Прокси #{i} ({ip_port}): {type(e).__name__}")

    print("   ⚠️  Ни один прокси не ответил")
    return None
