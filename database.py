"""
Модуль для работы с SQLite базой данных
Хранит информацию об обработанных тендерах для избежания дубликатов
"""

import aiosqlite
import hashlib
from datetime import datetime
from typing import Optional, Dict, List
from config import DATABASE_PATH
from max_notify import format_tender


class TenderDatabase:
    """Класс для работы с базой данных тендеров"""
    
    def __init__(self, db_path: str = DATABASE_PATH, max_targets=()):
        self.db_path = db_path
        self.max_targets = tuple(max_targets)
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tenders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_hash TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    link TEXT,
                    deadline TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_to_telegram INTEGER DEFAULT 1
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS max_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tender_hash TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    next_attempt_at INTEGER NOT NULL DEFAULT 0,
                    sent_at TEXT,
                    UNIQUE(tender_hash, target_type, target_id)
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_max_pending ON max_deliveries(sent_at, next_attempt_at)")
            # Создаем индексы для быстрого поиска
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tender_hash 
                ON tenders(tender_hash)
            """)
            
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON tenders(created_at)
            """)
            
            await db.commit()
            print("✅ База данных инициализирована")
    
    @staticmethod
    def generate_tender_hash(title: str, link: str) -> str:
        """
        Генерирует уникальный хеш для тендера на основе названия и ссылки
        """
        unique_string = f"{title}|{link}"
        return hashlib.sha256(unique_string.encode()).hexdigest()
    
    async def is_tender_processed(self, title: str, link: str) -> bool:
        """
        Проверяет, был ли тендер уже обработан
        
        Args:
            title: Название тендера
            link: Ссылка на тендер
            
        Returns:
            True если тендер уже был обработан, False если новый
        """
        tender_hash = self.generate_tender_hash(title, link)
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM tenders WHERE tender_hash = ?",
                (tender_hash,)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] > 0
    
    async def add_tender(self, tender_data: Dict[str, str]) -> bool:
        """
        Добавляет новый тендер в базу данных
        
        Args:
            tender_data: Словарь с данными тендера (title, link, deadline, description)
            
        Returns:
            True если тендер успешно добавлен, False если уже существует
        """
        title = tender_data.get('title', '')
        link = tender_data.get('link', '')
        
        if not title or not link:
            print("⚠️  Невозможно добавить тендер: отсутствует название или ссылка")
            return False
        
        tender_hash = self.generate_tender_hash(title, link)
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO tenders (tender_hash, title, link, deadline, description)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    tender_hash,
                    title,
                    link,
                    tender_data.get('deadline', 'Не указано'),
                    tender_data.get('description', 'Не указано')
                ))
                await db.executemany(
                    "INSERT INTO max_deliveries(tender_hash,target_type,target_id,message) VALUES (?,?,?,?)",
                    [(tender_hash, kind, target, format_tender(tender_data)) for kind, target in self.max_targets]
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            # Тендер уже существует (нарушение UNIQUE constraint)
            return False
        except Exception as e:
            print(f"❌ Ошибка при добавлении тендера в БД: {e}")
            return False
    
    async def get_statistics(self) -> Dict[str, int]:
        """
        Получает статистику по обработанным тендерам
        
        Returns:
            Словарь со статистикой
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Общее количество
            async with db.execute("SELECT COUNT(*) FROM tenders") as cursor:
                total = (await cursor.fetchone())[0]
            
            # Сегодня
            async with db.execute("""
                SELECT COUNT(*) FROM tenders 
                WHERE DATE(created_at) = DATE('now')
            """) as cursor:
                today = (await cursor.fetchone())[0]
            
            # За последние 7 дней
            async with db.execute("""
                SELECT COUNT(*) FROM tenders 
                WHERE created_at >= datetime('now', '-7 days')
            """) as cursor:
                week = (await cursor.fetchone())[0]
            
            return {
                'total': total,
                'today': today,
                'week': week
            }
    
    async def get_recent_tenders(self, limit: int = 10) -> List[Dict]:
        """
        Получает последние обработанные тендеры
        
        Args:
            limit: Количество записей
            
        Returns:
            Список словарей с данными тендеров
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT title, link, deadline, created_at
                FROM tenders
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def cleanup_old_records(self, days: int = 90):
        """
        Удаляет старые записи из базы данных
        
        Args:
            days: Количество дней для хранения записей
        """
        async with aiosqlite.connect(self.db_path) as db:
            result = await db.execute("""
                DELETE FROM tenders 
                WHERE created_at < datetime('now', '-' || ? || ' days')
            """, (days,))
            await db.commit()
            deleted = result.rowcount
            if deleted > 0:
                print(f"🗑️  Удалено старых записей: {deleted}")
            return deleted

    async def pending_max_deliveries(self):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""SELECT * FROM max_deliveries
                WHERE sent_at IS NULL AND next_attempt_at <= CAST(strftime('%s','now') AS INTEGER)
                ORDER BY id LIMIT 100""") as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def record_max_result(self, delivery_id, success, error='', retry_after=1800):
        async with aiosqlite.connect(self.db_path) as db:
            if success:
                await db.execute("UPDATE max_deliveries SET sent_at=CURRENT_TIMESTAMP, attempts=attempts+1, last_error=NULL WHERE id=?", (delivery_id,))
            else:
                await db.execute("""UPDATE max_deliveries SET attempts=attempts+1, last_error=?,
                    next_attempt_at=CAST(strftime('%s','now') AS INTEGER)+? WHERE id=?""",
                    (error, max(60, retry_after), delivery_id))
            await db.commit()
