"""
Точка входа для парсера тендеров RTS-Tender
Непрерывная работа с заданным интервалом
"""

import asyncio
from datetime import datetime, timedelta
from parser import TenderParser
from config import STOP_ON_DUPLICATES, CHECK_INTERVAL_MINUTES


def format_time_remaining(seconds: int) -> str:
    """Форматирует оставшееся время"""
    if seconds <= 0:
        return "сейчас"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}ч")
    if minutes > 0:
        parts.append(f"{minutes}м")
    if secs > 0 or not parts:
        parts.append(f"{secs}с")
    
    return " ".join(parts)


async def main():
    """Главная функция с бесконечным циклом"""
    print("="*70)
    print("🚀 ПАРСЕР ТЕНДЕРОВ RTS-TENDER")
    print("="*70)
    print("🥷 Stealth режим включен")
    print("📱 Отправка в Telegram")
    print("💾 Дедупликация через SQLite")
    print(f"🛑 Автоостановка после {STOP_ON_DUPLICATES} дубликатов подряд")
    print(f"⏱️  Интервал проверки: {CHECK_INTERVAL_MINUTES} минут")
    print("💡 Для остановки нажмите Ctrl+C")
    print("="*70)
    
    run_count = 0
    
    while True:
        run_count += 1
        
        try:
            # Запускаем парсер
            print("\n" + "="*70)
            print(f"⏰ ЗАПУСК #{run_count}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*70)
            
            parser = TenderParser(stop_on_duplicates=STOP_ON_DUPLICATES)
            await parser.run()
            
            print(f"\n✅ Парсер завершил работу: {datetime.now().strftime('%H:%M:%S')}")
            
            # Вычисляем время следующего запуска
            next_run = datetime.now() + timedelta(minutes=CHECK_INTERVAL_MINUTES)
            wait_seconds = CHECK_INTERVAL_MINUTES * 60
            
            print("\n" + "-"*70)
            print(f"💤 ОЖИДАНИЕ СЛЕДУЮЩЕГО ЗАПУСКА")
            print(f"   Выполнено циклов: {run_count}")
            print(f"   Следующий запуск: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Ожидание: {CHECK_INTERVAL_MINUTES} минут")
            print("-"*70)
            
            # Ждем с обновлением таймера каждую минуту
            for elapsed in range(0, wait_seconds, 60):
                remaining = wait_seconds - elapsed
                if remaining > 0:
                    print(f"⏳ Осталось: {format_time_remaining(remaining)}", end='\r', flush=True)
                    await asyncio.sleep(min(60, remaining))
            
            print("\n")  # Новая строка после таймера
            
        except KeyboardInterrupt:
            print("\n\n🛑 Получен сигнал остановки (Ctrl+C)")
            print("👋 До свидания!")
            break
        except Exception as e:
            print(f"\n❌ Ошибка в цикле: {e}")
            print(f"⏳ Повтор через {CHECK_INTERVAL_MINUTES} минут...")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Программа остановлена")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
