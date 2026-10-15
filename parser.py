"""
Модуль парсинга тендеров с сайта RTS-Tender
"""

import asyncio
import os
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright.async_api import Error as PlaywrightError
import random
import requests
from datetime import datetime
from typing import List, Dict, Optional

from config import *
from database import TenderDatabase
from max_notify import MaxNotifier
from utils import retry_async, log_error, find_working_proxy



class TenderParser:
    """Класс для парсинга тендеров"""
    
    def __init__(self, stop_on_duplicates: int = 5):
        """
        Args:
            stop_on_duplicates: Количество подряд идущих дубликатов для остановки парсера
        """
        self.max_notifier = MaxNotifier()
        self.telegram_enabled = os.getenv('TELEGRAM_ENABLED', 'true').strip().lower() in ('true', '1', 'yes')
        self.db = TenderDatabase(max_targets=self.max_notifier.settings.targets)
        self.total_found = 0
        self.total_new = 0
        self.total_duplicates = 0
        self.consecutive_duplicates = 0
        self.stop_on_duplicates = stop_on_duplicates
        self.errors_count = 0
    
    def send_to_telegram(self, message: str) -> dict:
        """
        Отправка сообщения в Telegram с retry
        Поддерживает отправку одному или нескольким получателям
        
        Returns:
            dict: Статистика отправки {'success': int, 'failed': int, 'total': int}
        """
        if not self.telegram_enabled:
            return {'success': 0, 'failed': 0, 'total': 0}

        # Нормализуем CHAT_ID к списку
        if not CHAT_ID:
            print("⚠️  CHAT_ID не указан! Сообщение не отправлено.")
            return {'success': 0, 'failed': 0, 'total': 0}
        
        # Преобразуем в список, если передана строка
        chat_ids = CHAT_ID if isinstance(CHAT_ID, list) else [CHAT_ID]
        
        if not chat_ids:
            print("⚠️  Список CHAT_ID пуст! Сообщение не отправлено.")
            return {'success': 0, 'failed': 0, 'total': 0}
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        
        success_count = 0
        failed_count = 0
        
        for chat_id in chat_ids:
            data = {
                "chat_id": str(chat_id),
                "text": message,
                "parse_mode": "HTML"
            }
            
            # Retry логика для каждого получателя
            sent = False
            for attempt in range(3):
                try:
                    response = requests.post(url, json=data, timeout=10)
                    
                    if response.status_code == 200:
                        if len(chat_ids) > 1:
                            print(f"✅ Сообщение отправлено в Telegram (chat_id: {chat_id})")
                        else:
                            print("✅ Сообщение отправлено в Telegram")
                        success_count += 1
                        sent = True
                        break
                        
                    elif response.status_code == 429:  # Too Many Requests
                        retry_after = int(response.headers.get('Retry-After', 5))
                        print(f"⚠️  Rate limit для {chat_id}, ожидание {retry_after}с...")
                        import time
                        time.sleep(retry_after)
                        
                    elif response.status_code == 403:  # Forbidden
                        print(f"❌ Бот заблокирован пользователем {chat_id}")
                        failed_count += 1
                        break
                        
                    elif response.status_code == 400:  # Bad Request
                        error_desc = response.json().get('description', 'Unknown error')
                        print(f"❌ Ошибка для {chat_id}: {error_desc}")
                        failed_count += 1
                        break
                        
                    else:
                        print(f"⚠️  Ошибка отправки для {chat_id}: {response.status_code}")
                        if attempt < 2:
                            import time
                            time.sleep(2 ** attempt)
                            
                except requests.exceptions.Timeout:
                    print(f"⚠️  Timeout при отправке для {chat_id} (попытка {attempt + 1}/3)")
                    if attempt < 2:
                        import time
                        time.sleep(2 ** attempt)
                        
                except Exception as e:
                    log_error(e, f"send_to_telegram - chat_id: {chat_id}")
                    if attempt < 2:
                        import time
                        time.sleep(2 ** attempt)
            
            if not sent and attempt == 2:
                failed_count += 1
            
            # Небольшая задержка между отправками разным получателям
            if len(chat_ids) > 1 and chat_id != chat_ids[-1]:
                import time
                time.sleep(0.5)
        
        total = len(chat_ids)
        
        # Итоговое сообщение
        if total > 1:
            print(f"📊 Отправка завершена: успешно {success_count}/{total}, ошибок {failed_count}/{total}")
        
        return {
            'success': success_count,
            'failed': failed_count,
            'total': total
        }
    
    @staticmethod
    def parse_datetime_string(datetime_str: str) -> Optional[datetime]:
        """Парсинг строки datetime в объект datetime"""
        try:
            date_part = datetime_str.split()[0]
            parsed_date = datetime.strptime(date_part, "%d.%m.%Y")
            return parsed_date
        except Exception as e:
            log_error(e, f"parse_datetime_string: {datetime_str}")
            return None
    
    @staticmethod
    def is_date_before_today(datetime_str: str) -> bool:
        """Проверка, что дата раньше сегодняшнего дня"""
        parsed_date = TenderParser.parse_datetime_string(datetime_str)
        if not parsed_date:
            return False
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return parsed_date.date() < today.date()
    
    async def smooth_scroll_down(self, page, duration_seconds=SCROLL_DURATION):
        """Плавный скроллинг вниз с обработкой ошибок"""
        try:
            print(f"📜 Плавный скроллинг вниз за {duration_seconds} сек...")
            
            scroll_height = await page.evaluate("document.body.scrollHeight")
            viewport_height = await page.evaluate("window.innerHeight")
            
            steps = 50
            step_duration = duration_seconds / steps
            pixels_per_step = (scroll_height - viewport_height) / steps
            
            for i in range(steps):
                await page.evaluate(f"window.scrollBy(0, {pixels_per_step})")
                await asyncio.sleep(step_duration)
            
            print("✅ Скроллинг завершен")
        except Exception as e:
            log_error(e, "smooth_scroll_down")
            print("⚠️  Ошибка скроллинга, пропускаем")
    
    async def check_cards_for_old_dates(self, page) -> bool:
        """Проверяет наличие карточек с датой раньше сегодняшнего дня"""
        try:
            cards = await retry_async(
                lambda: page.query_selector_all('.cards'),
                max_retries=2,
                base_delay=1
            )
            
            for card in cards:
                try:
                    info_main = await card.query_selector('.card-item__info-main')
                    if info_main:
                        time_elem = await info_main.query_selector('time')
                        if time_elem:
                            datetime_value = await time_elem.get_attribute('datetime')
                            if datetime_value and self.is_date_before_today(datetime_value):
                                print(f"🛑 Найдена карточка с датой раньше сегодняшнего: {datetime_value}")
                                return True
                except Exception as e:
                    log_error(e, "check_cards_for_old_dates - single card")
                    continue
            
            return False
        except Exception as e:
            log_error(e, "check_cards_for_old_dates")
            return False
    
    async def parse_tender_cards(self, page) -> List[Dict[str, str]]:
        """Парсинг карточек с тендерами с retry логикой"""
        print("\n📋 Начинаем парсинг карточек...")
        
        try:
            await page.locator(".card-item__title").first.wait_for(state="visible", timeout=60000)
            # Retry для поиска карточек
            cards = await retry_async(
                lambda: page.query_selector_all('.cards'),
                max_retries=3,
                base_delay=2
            )
            
            print(f"🔍 Найдено карточек: {len(cards)}")
            
            if len(cards) == 0:
                print("⚠️  Карточки не найдены!")
                return []
            
            all_tenders = []
            skipped_count = 0
            
            for index, card in enumerate(cards, 1):
                try:
                    tender_data = await self._parse_single_card(card, index)
                    
                    if tender_data is None:
                        skipped_count += 1
                        continue
                    
                    self.total_found += 1
                    all_tenders.append(tender_data)
                    print(f"✅ Карточка {index} обработана: {tender_data['title'][:50]}...")
                    
                except Exception as e:
                    log_error(e, f"parse_tender_cards - card {index}")
                    self.errors_count += 1
                    print(f"⚠️  Ошибка обработки карточки {index}: {str(e)[:50]}")
                    continue
            
            if skipped_count > 0:
                print(f"⏭️  Всего пропущено карточек: {skipped_count}")
            
            return all_tenders
            
        except Exception as e:
            log_error(e, "parse_tender_cards")
            print(f"❌ Критическая ошибка парсинга: {e}")
            return []
    
    async def _parse_single_card(self, card, index: int) -> Optional[Dict[str, str]]:
        """Парсинг одной карточки с обработкой ошибок"""
        tender_data = {}
        
        # 1. Название
        try:
            title_elem = await card.query_selector('.card-item__title')
            if title_elem:
                title_text = await title_elem.inner_text()
                tender_data['title'] = title_text.strip() if title_text else "Не указано"
            else:
                tender_data['title'] = "Не указано"
        except Exception as e:
            log_error(e, f"_parse_single_card - title (card {index})")
            tender_data['title'] = "Не указано"
        
        # Пропускаем карточки без названия
        if tender_data['title'] == "Не указано" or not tender_data['title']:
            print(f"⏭️  Карточка {index} пропущена: название не указано")
            return None
        
        # 2. Описание
        try:
            desc_elem = await card.query_selector('.card-item__properties-desc')
            if desc_elem:
                content = await desc_elem.get_attribute('content')
                tender_data['description'] = content if content else await desc_elem.inner_text()
            else:
                tender_data['description'] = "Не указано"
        except Exception as e:
            log_error(e, f"_parse_single_card - description (card {index})")
            tender_data['description'] = "Не указано"
        
        # 3. Дата окончания
        try:
            date_block = await card.query_selector('.card-item__info-end-date')
            if date_block:
                time_elem = await date_block.query_selector('time')
                if time_elem:
                    datetime_value = await time_elem.get_attribute('datetime')
                    tender_data['deadline'] = datetime_value if datetime_value else "Не указано"
                else:
                    tender_data['deadline'] = "Не указано"
            else:
                tender_data['deadline'] = "Не указано"
        except Exception as e:
            log_error(e, f"_parse_single_card - deadline (card {index})")
            tender_data['deadline'] = "Не указано"
        
        # 4. Ссылка
        try:
            link_elem = await card.query_selector('a.button-red')
            if link_elem:
                href = await link_elem.get_attribute('href')
                if href:
                    if href.startswith('/'):
                        tender_data['link'] = f"https://www.rts-tender.ru{href}"
                    else:
                        tender_data['link'] = href
                else:
                    tender_data['link'] = "Не указано"
            else:
                tender_data['link'] = "Не указано"
        except Exception as e:
            log_error(e, f"_parse_single_card - link (card {index})")
            tender_data['link'] = "Не указано"
        
        return tender_data
    
    async def process_tenders(self, tenders: List[Dict], page_number: int) -> bool:
        """Обработка и отправка тендеров с проверкой на дубликаты"""
        if not tenders:
            return True
        
        for i, tender in enumerate(tenders, 1):
            try:
                # Проверяем, есть ли тендер в базе
                is_duplicate = await self.db.is_tender_processed(
                    tender['title'],
                    tender['link']
                )
                
                if is_duplicate:
                    self.total_duplicates += 1
                    self.consecutive_duplicates += 1
                    print(f"⏭️  Тендер #{i} пропущен (дубликат #{self.consecutive_duplicates}): {tender['title'][:50]}...")
                    
                    if self.consecutive_duplicates >= self.stop_on_duplicates:
                        print(f"\n🛑 ОСТАНОВКА ПАРСЕРА!")
                        print(f"📊 Найдено {self.consecutive_duplicates} дубликатов подряд")
                        return False
                    
                    continue
                
                # Сбрасываем счетчик последовательных дубликатов
                self.consecutive_duplicates = 0
                
                # Добавляем в базу
                added = await self.db.add_tender(tender)
                
                if added:
                    self.total_new += 1
                    
                    # Отправляем в Telegram
                    message = f"""
🔔 <b>Новый тендер (стр. {page_number}, #{self.total_new})</b>

📌 <b>Название:</b>
{tender['title']}

📝 <b>Цена:</b>
{tender['description'][:500]}{'...' if len(tender['description']) > 500 else ''}

⏰ <b>Подать заявку до:</b>
{tender['deadline']}

🔗 <b>Ссылка:</b>
{tender['link']}
                    """.strip()
                    
                    self.send_to_telegram(message)
                    await asyncio.sleep(1)
                    
            except Exception as e:
                log_error(e, f"process_tenders - tender {i}")
                self.errors_count += 1
                print(f"⚠️  Ошибка обработки тендера {i}: {str(e)[:50]}")
                continue
        
        return True
    
    async def goto_with_retry(self, page, url: str):
        last_error = None

        for attempt in range(3):
            try:
                print(f"🌐 Открытие страницы, попытка {attempt + 1}/3")

                response = await page.goto(
                    url,
                    wait_until="commit",
                    timeout=TIMEOUT
                )

                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=30000
                )

                return response

            except PlaywrightError as e:
                last_error = e
                error_text = str(e)

                print(f"⚠️ Ошибка перехода: {error_text[:200]}")

                if "ERR_CONNECTION_RESET" in error_text:
                    print(
                        "🔌 Соединение сброшено сервером или прокси. "
                        "Ожидание перед повтором..."
                    )
                else:
                    print("⚠️ Ошибка Playwright, повторяем попытку...")

                if attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))

        raise last_error
    
    async def click_with_retry(self, element):
        """Клик по элементу с retry логикой"""
        async def _click():
            await element.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await element.click()
        
        return await retry_async(_click, max_retries=2, base_delay=2)
    
    async def run(self):
        """Основной метод запуска парсера с улучшенной обработкой ошибок"""
        # Инициализируем базу данных
        try:
            await self.db.init_db()
        except Exception as e:
            log_error(e, "db.init_db")
            print("❌ Не удалось инициализировать БД")
            return
        
        await self.max_notifier.flush(self.db)

        # Получаем статистику
        try:
            stats = await self.db.get_statistics()
            print(f"\n📊 Статистика БД:")
            print(f"   Всего тендеров: {stats['total']}")
            print(f"   Сегодня: {stats['today']}")
            print(f"   За неделю: {stats['week']}")
        except Exception as e:
            log_error(e, "db.get_statistics")
            print("⚠️  Не удалось получить статистику")
        
        print(f"\n⚙️  Настройки:")
        print(f"   Остановка после {self.stop_on_duplicates} дубликатов подряд")
        
        # Проверяем настройки Telegram
        if not self.telegram_enabled:
            print("   📱 Telegram: отключен (TELEGRAM_ENABLED=false)")
        elif CHAT_ID:
            chat_ids = CHAT_ID if isinstance(CHAT_ID, list) else [CHAT_ID]
            print(f"   📱 Telegram получателей: {len(chat_ids)}")
        else:
            print(f"   📱 Telegram: отключен (CHAT_ID не указан)")
        
        # Подбираем рабочий прокси
        active_proxy = await asyncio.to_thread(
            find_working_proxy, PROXIES, PROXY_CHECK_URL, PROXY_CHECK_TIMEOUT
        )
        if active_proxy:
            ip_port = active_proxy['server'].replace('http://', '')
            print(f"🌐 Используем прокси: {ip_port}")
        else:
            print("🌐 Рабочих прокси нет — прямое подключение")
        
        browser = None
        
        async with async_playwright() as p:
            try:
                launch_options = {
                    'headless': HEADLESS_MODE,
                    'args': [
                        '--disable-blink-features=AutomationControlled',
                        '--exclude-switches=enable-automation',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                    ]
                }
                
                browser = await p.chromium.launch(**launch_options)
                selected_ua = random.choice(USER_AGENTS)
                
                context_options = {
                    'user_agent': selected_ua,
                    'viewport': {'width': random.randint(1024, 1920), 'height': random.randint(768, 1080)},
                    'locale': 'ru-RU',
                    'timezone_id': 'Europe/Moscow',
                }
                if active_proxy:
                    context_options['proxy'] = active_proxy

                context = await browser.new_context(**context_options)
                
                context.set_default_timeout(TIMEOUT)
                context.set_default_navigation_timeout(TIMEOUT)
                page = await context.new_page()
                
                # Stealth скрипты
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
                """)
                
                print(f"\n📍 Переходим на сайт: {TARGET_URL}")
                await asyncio.sleep(random.uniform(1, 3))
                
                # Переход на сайт с retry
                await self.goto_with_retry(page, TARGET_URL)
                print("✅ Страница загружена")
                
                # Ожидание
                print(f"⏳ Ожидаем {WAIT_TIME/1000} секунд...")
                await page.wait_for_timeout(WAIT_TIME)
                
                # Парсинг с пагинацией
                page_number = 1
                stop_reason = None
                
                while True:
                    print(f"\n{'='*70}")
                    print(f"📄 СТРАНИЦА #{page_number}")
                    print(f"{'='*70}")
                    
                    # Парсим карточки
                    tenders = await self.parse_tender_cards(page)
                    
                    if not tenders and page_number == 1:
                        print("⚠️  На первой странице не найдено карточек")
                        stop_reason = "no_cards"
                        break
                    
                    # Обрабатываем тендеры
                    should_continue = await self.process_tenders(tenders, page_number)
                    await self.max_notifier.flush(self.db)
                    
                    if not should_continue:
                        stop_reason = "duplicates"
                        break
                    
                    # Проверка на старые даты
                    if await self.check_cards_for_old_dates(page):
                        stop_reason = "old_dates"
                        print("\n🎯 ПАРСИНГ ЗАВЕРШЕН: найдена старая дата")
                        break
                    
                    # Переход на следующую страницу
                    try:
                        print(f"\n⏳ Ожидаем {PAGE_WAIT_TIME} секунд перед переходом...")
                        await asyncio.sleep(PAGE_WAIT_TIME)
                        
                        await self.smooth_scroll_down(page)
                        
                        # Ищем кнопку следующей страницы
                        next_button = await page.query_selector('a.page-link.next')
                        
                        if not next_button:
                            stop_reason = "no_next_button"
                            print("\n🎯 ПАРСИНГ ЗАВЕРШЕН: нет кнопки 'Далее'")
                            break
                        
                        # Проверяем, активна ли кнопка
                        is_disabled = await next_button.evaluate(
                            "el => el.classList.contains('disabled') || el.hasAttribute('disabled')"
                        )
                        
                        if is_disabled:
                            stop_reason = "disabled_button"
                            print("\n🎯 ПАРСИНГ ЗАВЕРШЕН: кнопка 'Далее' неактивна")
                            break
                        
                        print("\n🔄 Переход на следующую страницу...")
                        await self.click_with_retry(next_button)
                        
                        # Ждем загрузки новой страницы
                        await page.wait_for_load_state('domcontentloaded', timeout=30000)
                        await asyncio.sleep(3)
                        
                        page_number += 1
                        
                    except PlaywrightTimeout:
                        log_error(Exception("Timeout при переходе на следующую страницу"), "pagination")
                        print("⚠️  Timeout при пагинации, завершаем")
                        stop_reason = "timeout"
                        break
                        
                    except Exception as e:
                        log_error(e, "pagination")
                        print(f"⚠️  Ошибка при переходе на следующую страницу: {str(e)[:50]}")
                        stop_reason = "pagination_error"
                        break
                
                # Итоговая статистика
                print(f"\n{'='*70}")
                print(f"✅ ПАРСИНГ ЗАВЕРШЕН!")
                print(f"{'='*70}")
                print(f"📊 Статистика:")
                print(f"   Обработано страниц: {page_number}")
                print(f"   Найдено тендеров: {self.total_found}")
                print(f"   🆕 Новых тендеров: {self.total_new}")
                print(f"   ⏭️  Дубликатов: {self.total_duplicates}")
                print(f"   ⚠️  Ошибок: {self.errors_count}")
                
                if stop_reason == "duplicates":
                    print(f"\n🛑 Причина остановки: Найдено {self.consecutive_duplicates} дубликатов подряд")
                elif stop_reason == "old_dates":
                    print(f"\n🛑 Причина остановки: Достигнуты тендеры старше сегодняшнего дня")
                elif stop_reason == "no_next_button":
                    print(f"\n🛑 Причина остановки: Достигнута последняя страница")
                elif stop_reason == "no_cards":
                    print(f"\n🛑 Причина остановки: Карточки не найдены")
                elif stop_reason == "timeout":
                    print(f"\n🛑 Причина остановки: Timeout при пагинации")
                elif stop_reason == "pagination_error":
                    print(f"\n🛑 Причина остановки: Ошибка при пагинации")
                else:
                    print(f"\n✅ Парсинг завершен успешно")
                
                print(f"{'='*70}")
                
    #             # Отправляем итоговое уведомление в Telegram
    #             if CHAT_ID and self.total_new > 0:
    #                 summary_message = f"""
    # 📊 <b>Парсинг завершен</b>

    # 📄 Обработано страниц: {page_number}
    # 🔍 Найдено тендеров: {self.total_found}
    # 🆕 Новых тендеров: {self.total_new}
    # ⏭️ Дубликатов: {self.total_duplicates}
    # ⚠️ Ошибок: {self.errors_count}

    # {'🛑 Остановлено: найдены дубликаты' if stop_reason == 'duplicates' else '✅ Парсинг завершен'}
    #                 """.strip()
                    
    #                 result = self.send_to_telegram(summary_message)
                    
    #                 # Логируем результат отправки
    #                 if result['total'] > 1:
    #                     print(f"\n📨 Итоговое уведомление отправлено {result['success']}/{result['total']} получателям")
                
    #             # Если новых тендеров не было, отправляем короткое уведомление
    #             elif CHAT_ID and self.total_new == 0 and self.total_found > 0:
    #                 short_message = f"""
    # ℹ️ <b>Парсинг завершен</b>

    # Новых тендеров не найдено.
    # Все {self.total_found} тендеров уже были обработаны ранее.
    #                 """.strip()
                    
    #                 result = self.send_to_telegram(short_message)
                
            except Exception as e:
                log_error(e, "parser.run")
                print(f"❌ Критическая ошибка: {e}")
                import traceback
                traceback.print_exc()
                
                # Отправляем уведомление об ошибке
                if CHAT_ID:
                    error_message = f"""
    ❌ <b>Ошибка парсера</b>

    Произошла критическая ошибка:
    {str(e)[:200]}

    Парсер будет перезапущен при следующем цикле.
                    """.strip()
                    
                    try:
                        self.send_to_telegram(error_message)
                    except:
                        pass
                        
            finally:
                # Гарантированно закрываем браузер
                if browser:
                    try:
                        await browser.close()
                        print("🔒 Браузер закрыт")
                    except Exception as e:
                        log_error(e, "browser.close")
                        print(f"⚠️  Ошибка при закрытии браузера: {e}")
