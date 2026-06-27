"""
View Tracker — проверяет просмотры опубликованных трендовых видео через 12 часов.

Как работает:
  1. approval_bot.py при одобрении trending-видео сохраняет запись в pending_views.json
  2. view_tracker запускается по cron каждый час
  3. Для готовых записей (now >= check_at) запрашивает Instagram Graph API
  4. Отправляет отчёт в Telegram
  5. Архивирует запись в views_history.json

Запуск:
  python3 view_tracker.py --check-pending      # проверить все готовые записи
  python3 view_tracker.py --status             # показать что ожидает проверки
  python3 view_tracker.py --manual PKG_NAME    # проверить конкретный пакет сейчас

Cron (каждый час):
  0 * * * * cd /root/Ecodisplays && python3 view_tracker.py --check-pending >> /var/log/view_tracker.log 2>&1
"""

import os
import json
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
PENDING_VIEWS_FILE = OUTPUT_DIR / "pending_views.json"
VIEWS_HISTORY_FILE = OUTPUT_DIR / "views_history.json"
TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GRAPH_API = "https://graph.facebook.com/v21.0"


# ─── Persistence ──────────────────────────────────────────────────────────────

def load_pending() -> list:
    if PENDING_VIEWS_FILE.exists():
        try:
            return json.loads(PENDING_VIEWS_FILE.read_text())
        except Exception:
            pass
    return []


def save_pending(records: list):
    PENDING_VIEWS_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def append_history(record: dict):
    history = []
    if VIEWS_HISTORY_FILE.exists():
        try:
            history = json.loads(VIEWS_HISTORY_FILE.read_text())
        except Exception:
            pass
    history.append(record)
    VIEWS_HISTORY_FILE.write_text(json.dumps(history[-200:], ensure_ascii=False, indent=2))


# ─── Instagram Graph API ──────────────────────────────────────────────────────

def get_recent_media(limit: int = 10) -> list:
    """Возвращает последние N медиа из Instagram аккаунта."""
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_USER_ID:
        print("  ⚠️  Instagram API не настроен (нет токена или user_id)")
        return []

    resp = requests.get(
        f"{GRAPH_API}/{INSTAGRAM_USER_ID}/media",
        params={
            "fields": "id,media_type,timestamp,like_count,comments_count,caption",
            "limit": limit,
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"  ❌ Instagram API ошибка: {resp.status_code} {resp.text[:150]}")
        return []
    return resp.json().get("data", [])


def get_media_insights(media_id: str) -> dict:
    """Запрашивает insights (views, reach, plays) для конкретного медиа."""
    resp = requests.get(
        f"{GRAPH_API}/{media_id}/insights",
        params={
            "metric": "plays,reach,likes,comments,shares,saved",
            "access_token": INSTAGRAM_ACCESS_TOKEN,
        },
        timeout=15,
    )
    if not resp.ok:
        # Для некоторых типов медиа insights недоступны
        err_msg = resp.json().get("error", {}).get("message", resp.text[:100])
        print(f"  ⚠️  Insights для {media_id}: {err_msg}")
        return {}

    data = resp.json().get("data", [])
    result = {}
    for item in data:
        result[item["name"]] = item.get("values", [{}])[-1].get("value", 0)
    return result


def find_media_by_time(published_at_iso: str, window_minutes: int = 30) -> dict | None:
    """
    Ищет опубликованное медиа по времени публикации.
    Возвращает первое медиа в пределах window_minutes от published_at.
    """
    try:
        pub_ts = datetime.fromisoformat(published_at_iso.replace("Z", "+00:00"))
        pub_epoch = pub_ts.timestamp()
    except ValueError:
        print(f"  ⚠️  Не удалось распарсить время: {published_at_iso}")
        return None

    media_list = get_recent_media(limit=20)
    for m in media_list:
        try:
            m_ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).timestamp()
            if abs(m_ts - pub_epoch) <= window_minutes * 60:
                return m
        except Exception:
            continue
    return None


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    try:
        requests.post(
            f"{TG_API}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"  ❌ Telegram ошибка: {e}")


def format_report(record: dict, insights: dict, media: dict | None) -> str:
    topic_id = record.get("topic_id", "unknown")
    hook = record.get("hook", "")[:80]
    approved_at = record.get("approved_at", "")[:16]

    plays = insights.get("plays", 0)
    reach = insights.get("reach", 0)
    likes = insights.get("likes", 0)
    comments = insights.get("comments", 0)
    shares = insights.get("shares", 0)
    saved = insights.get("saved", 0)

    # Оценка результата
    if plays >= 500:
        verdict = "🔥 Отличный результат!"
    elif plays >= 200:
        verdict = "✅ Хороший результат"
    elif plays >= 50:
        verdict = "📊 Средний результат"
    else:
        verdict = "📉 Низкий охват — проанализируй тему"

    ig_url = f"https://www.instagram.com/p/{media.get('id', '')}" if media else "недоступно"

    report = (
        f"📊 *Трендовое видео — 12-часовой отчёт*\n\n"
        f"🎬 Тема: `{topic_id}`\n"
        f"💬 Hook: _{hook}_\n"
        f"📅 Опубликовано: {approved_at}\n\n"
        f"*Результаты:*\n"
        f"  ▶️ Просмотры (plays): *{plays:,}*\n"
        f"  👁️ Охват (reach): *{reach:,}*\n"
        f"  ❤️ Лайки: *{likes}*\n"
        f"  💬 Комментарии: *{comments}*\n"
        f"  🔁 Репосты: *{shares}*\n"
        f"  🔖 Сохранено: *{saved}*\n\n"
        f"{verdict}\n"
    )

    if media:
        report += f"🔗 [Открыть в Instagram]({ig_url})\n"

    return report


# ─── Основная логика ──────────────────────────────────────────────────────────

def check_record(record: dict) -> bool:
    """Проверяет один pending-record. Возвращает True если успешно."""
    pkg_name = record.get("pkg_name", "unknown")
    topic_id = record.get("topic_id", "unknown")
    published_at = record.get("published_at")
    media_id = record.get("instagram_media_id")

    print(f"\n  🔍 Проверяю: {pkg_name} (тема: {topic_id})")

    insights = {}
    media = None

    if media_id:
        # Прямой запрос по media_id (если был сохранён)
        insights = get_media_insights(media_id)
        if insights:
            media = {"id": media_id}
            print(f"  ✅ Insights по media_id: {insights}")
    elif published_at:
        # Поиск по времени публикации
        print(f"  🔎 Ищу медиа по времени публикации: {published_at}")
        media = find_media_by_time(published_at, window_minutes=45)
        if media:
            print(f"  ✅ Найдено медиа: {media['id']}")
            insights = get_media_insights(media["id"])
        else:
            print(f"  ⚠️  Медиа не найдено в Instagram (возможно не опубликовано)")

    report = format_report(record, insights, media)
    print(f"\n{report}")
    send_telegram(report)

    return True


def check_pending():
    """Проверяет все записи у которых наступило время проверки."""
    pending = load_pending()
    if not pending:
        print("  ℹ️  Нет pending-записей для проверки")
        return

    now = datetime.now(timezone.utc).timestamp()
    remaining = []
    checked_count = 0

    for record in pending:
        check_at_str = record.get("check_at", "")
        try:
            check_at = datetime.fromisoformat(check_at_str.replace("Z", "+00:00")).timestamp()
        except ValueError:
            print(f"  ⚠️  Неверный check_at: {check_at_str} — пропускаю")
            remaining.append(record)
            continue

        if now >= check_at:
            ok = check_record(record)
            if ok:
                record["checked_at"] = datetime.now(timezone.utc).isoformat()
                append_history(record)
                checked_count += 1
            else:
                remaining.append(record)
        else:
            remaining.append(record)

    save_pending(remaining)
    if checked_count:
        print(f"\n✅ Проверено: {checked_count} видео. Осталось в очереди: {len(remaining)}")
    else:
        print(f"  ℹ️  Нет готовых к проверке. Следующая: "
              + (min(r.get("check_at", "?") for r in remaining) if remaining else "нет"))


def show_status():
    """Показывает текущее состояние очереди."""
    pending = load_pending()
    if not pending:
        print("  Очередь пуста\n")
        return

    now = datetime.now(timezone.utc).timestamp()
    print(f"\n📋 Pending Views ({len(pending)} шт):\n")
    for r in pending:
        pkg = r.get("pkg_name", "?")
        topic = r.get("topic_id", "?")
        check_at = r.get("check_at", "?")
        try:
            ca = datetime.fromisoformat(check_at.replace("Z", "+00:00"))
            delta = int(ca.timestamp() - now)
            if delta > 0:
                eta = f"через {delta//3600}ч {(delta%3600)//60}мин"
            else:
                eta = "ГОТОВО К ПРОВЕРКЕ"
        except Exception:
            eta = "?"

        print(f"  • {pkg}: тема={topic}, check_at={check_at[:16]} ({eta})")


def add_pending(pkg_name: str, topic_id: str, hook: str, approved_at: str,
                published_at: str | None = None, media_id: str | None = None):
    """Добавляет запись в pending_views (вызывается из approval_bot.py)."""
    from datetime import timedelta
    try:
        approved_dt = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError:
        approved_dt = datetime.now(timezone.utc)

    check_dt = approved_dt + timedelta(hours=12)

    record = {
        "pkg_name": pkg_name,
        "topic_id": topic_id,
        "hook": hook,
        "approved_at": approved_at,
        "published_at": published_at or approved_at,
        "check_at": check_dt.isoformat(),
        "instagram_media_id": media_id,
    }

    pending = load_pending()
    # Не дублируем
    if not any(r.get("pkg_name") == pkg_name for r in pending):
        pending.append(record)
        save_pending(pending)
        print(f"  📅 View check запланирован: {check_dt.strftime('%Y-%m-%d %H:%M UTC')}")


def main():
    parser = argparse.ArgumentParser(description="View Tracker для трендовых видео")
    parser.add_argument("--check-pending", action="store_true", help="Проверить готовые записи")
    parser.add_argument("--status", action="store_true", help="Показать очередь")
    parser.add_argument("--manual", type=str, help="Проверить конкретный пакет сейчас")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.manual:
        # Ищем пакет в pending или создаём временную запись
        pending = load_pending()
        record = next((r for r in pending if r["pkg_name"] == args.manual), None)
        if not record:
            # Пробуем загрузить из post_meta.json
            pkg_path = OUTPUT_DIR / args.manual
            meta_file = pkg_path / "post_meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text())
                record = {
                    "pkg_name": args.manual,
                    "topic_id": meta.get("topic_id", "unknown"),
                    "hook": meta.get("hook", ""),
                    "approved_at": meta.get("generated_at", datetime.now().isoformat()),
                    "published_at": meta.get("generated_at", datetime.now().isoformat()),
                    "check_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                print(f"  ❌ Пакет не найден: {args.manual}")
                return
        check_record(record)
    elif args.check_pending:
        check_pending()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
