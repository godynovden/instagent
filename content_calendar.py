"""
Content Calendar Agent — Фаза 2.

14-дневный нарратив: планирует слоты, запрашивает фото через Telegram,
запускает генерацию контента по расписанию.

Запуск:
  python3 content_calendar.py --run-scheduled   # основной cron-режим
  python3 content_calendar.py --plan            # показать план на 14 дней
  python3 content_calendar.py --reset-cycle     # сбросить и начать новый цикл
  python3 content_calendar.py --photo-received <slot_date> <photo_path>

Cron (заменяет content_farm.py):
  0 9 * * * cd /root/Ecodisplays && python3 content_calendar.py --run-scheduled
"""

import os
import json
import time
import hashlib
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
CONTEXT_DB_PATH = Path("/root/Ecodisplays/context_db.json")
CALENDAR_STATE_FILE = OUTPUT_DIR / "calendar_state.json"
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", "/root/Ecodisplays/content"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

OUTPUT_DIR.mkdir(exist_ok=True)

# 14-дневный нарратив — 6 постов (Пн/Ср/Пт x 2 недели)
# needs_photo=True → агент запросит реальное фото через Telegram
# Только типы с высоким approval rate в AI-режиме:
#   comparison=75%, eco_fact=30%, urban_case=50%
# installation и product_shot требуют реальных фото — только с needs_photo=True
CYCLE_PATTERN = [
    {"content_type": "comparison",    "needs_photo": False, "label": "Сравнение e-ink vs LCD/LED — AI"},
    {"content_type": "eco_fact",      "needs_photo": False, "label": "Эко-факт — AI"},
    {"content_type": "behind_scenes", "needs_photo": True,  "label": "Команда / монтаж — реальное фото"},
    {"content_type": "eco_fact",      "needs_photo": False, "label": "Эко-факт 2 — AI"},
    {"content_type": "urban_case",    "needs_photo": False, "label": "Городской кейс — AI"},
    {"content_type": "installation",  "needs_photo": True,  "label": "Кейс — реальный объект"},
]

POSTING_DAYS = [0, 2, 4]  # Пн=0, Ср=2, Пт=4

PHOTO_REQUEST_LEAD_DAYS = 3   # за сколько дней до поста запрашивать фото
PHOTO_DEADLINE_HOURS = 20     # час дедлайна накануне поста (20:00)


# ─── context_db ──────────────────────────────────────────────────────────────

def _load_context_db() -> dict:
    if CONTEXT_DB_PATH.exists():
        with open(CONTEXT_DB_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _pick_project(slot_index: int, context_db: dict) -> str | None:
    """Детерминированный выбор проекта по индексу слота (только активные)."""
    projects = context_db.get("projects", {})
    active = [k for k, v in projects.items() if v.get("status", "active") not in ("inactive", "tender_inactive")]
    if not active:
        return None
    return sorted(active)[slot_index % len(active)]


# ─── state ───────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if CALENDAR_STATE_FILE.exists():
        with open(CALENDAR_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"slots": [], "cycle_start": None, "cycle_index": 0}


def save_state(state: dict):
    CALENDAR_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str)
    )


# ─── cycle planning ──────────────────────────────────────────────────────────

def _next_posting_days(from_date: date, count: int) -> list[date]:
    """Возвращает следующие N дат постинга (Пн/Ср/Пт)."""
    days = []
    d = from_date
    while len(days) < count:
        if d.weekday() in POSTING_DAYS:
            days.append(d)
        d += timedelta(days=1)
    return days


def generate_new_cycle(context_db: dict, from_date: date | None = None) -> dict:
    """Создаёт новый 14-дневный цикл начиная с from_date (или сегодня)."""
    start = from_date or date.today()
    posting_dates = _next_posting_days(start, len(CYCLE_PATTERN))

    slots = []
    photo_slot_idx = 0  # отдельный счётчик для ротации проектов по фото-слотам
    for i, (pattern, post_date) in enumerate(zip(CYCLE_PATTERN, posting_dates)):
        if pattern["needs_photo"]:
            project = _pick_project(photo_slot_idx, context_db)
            photo_slot_idx += 1
        else:
            project = None
        deadline = datetime.combine(
            post_date - timedelta(days=1),
            datetime.min.time()
        ).replace(hour=PHOTO_DEADLINE_HOURS)

        slots.append({
            "date": post_date.isoformat(),
            "content_type": pattern["content_type"],
            "label": pattern["label"],
            "project": project,
            "needs_photo": pattern["needs_photo"],
            "status": "planned",
            "photo_path": None,
            "request_sent": None,
            "telegram_msg_id": None,
            "deadline": deadline.isoformat(),
            "generated_package": None,
        })

    return {
        "slots": slots,
        "cycle_start": start.isoformat(),
        "cycle_index": 0,
    }


def ensure_cycle(state: dict, context_db: dict) -> dict:
    """Проверяет цикл и создаёт новый если все слоты прошли или цикл пустой."""
    if not state["slots"]:
        log.info("Нет активного цикла — создаю новый")
        return generate_new_cycle(context_db)

    last_date = date.fromisoformat(state["slots"][-1]["date"])
    if last_date < date.today():
        log.info(f"Цикл завершён (последний пост был {last_date}) — создаю новый")
        return generate_new_cycle(context_db)

    return state


# ─── Telegram helpers ─────────────────────────────────────────────────────────

def _tg_send(text: str, reply_markup: dict | None = None) -> dict | None:
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        resp = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
        if resp.ok:
            return resp.json().get("result")
        # Fallback без parse_mode если ошибка парсинга
        if "parse entities" in resp.text or "can't parse" in resp.text.lower():
            payload.pop("parse_mode", None)
            resp2 = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=10)
            if resp2.ok:
                return resp2.json().get("result")
        log.error(f"Telegram ошибка: {resp.text[:100]}")
    except Exception as e:
        log.error(f"Telegram недоступен: {e}")
    return None


def _tg_send_photo(photo_path: Path, caption: str) -> dict | None:
    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(
                f"{TG_API}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": f},
                timeout=30,
            )
        if resp.ok:
            return resp.json().get("result")
        # Fallback без parse_mode если ошибка парсинга
        if "parse entities" in resp.text or "can't parse" in resp.text.lower():
            with open(photo_path, "rb") as f2:
                resp2 = requests.post(
                    f"{TG_API}/sendPhoto",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                    files={"photo": f2},
                    timeout=30,
                )
            if resp2.ok:
                return resp2.json().get("result")
        log.error(f"Telegram sendPhoto ошибка: {resp.text[:100]}")
    except Exception as e:
        log.error(f"Telegram sendPhoto недоступен: {e}")
    return None


# ─── photo requests ───────────────────────────────────────────────────────────

def send_photo_request(slot: dict) -> int | None:
    """Отправляет запрос фото в Telegram, возвращает message_id."""
    post_date = date.fromisoformat(slot["date"])
    deadline_str = datetime.fromisoformat(slot["deadline"]).strftime("%d.%m в %H:%M")

    project_name = slot.get("project", "").capitalize()
    context_db = _load_context_db()
    proj_data = context_db.get("projects", {}).get(slot.get("project", ""), {})
    proj_display = proj_data.get("name", project_name) if proj_data else project_name

    text = (
        f"📷 *Нужно фото для поста*\n\n"
        f"📅 Дата поста: *{post_date.strftime('%d.%m.%Y (%A)')}*\n"
        f"📌 Тип: *{slot['label']}*\n"
        f"🏗 Проект: *{proj_display}*\n"
        f"⏰ Дедлайн: *{deadline_str}*\n\n"
        f"Пришли фото ответом на это сообщение, или нажми «Пропустить» — "
        f"агент сгенерирует AI-иллюстрацию."
    )

    keyboard = {"inline_keyboard": [[
        {"text": "⏭ Пропустить — AI контент", "callback_data": f"skip_photo:{slot['date']}"},
    ]]}

    result = _tg_send(text, reply_markup=keyboard)
    if result:
        return result["message_id"]
    return None


# ─── check upcoming slots ─────────────────────────────────────────────────────

def check_photo_requests(state: dict) -> dict:
    """Для слотов, которым нужно фото в ближайшие N дней — отправляет запросы."""
    today = date.today()
    changed = False

    for slot in state["slots"]:
        if not slot["needs_photo"]:
            continue
        if slot["status"] not in ("planned",):
            continue

        slot_date = date.fromisoformat(slot["date"])
        days_until = (slot_date - today).days

        if days_until <= PHOTO_REQUEST_LEAD_DAYS and slot["request_sent"] is None:
            log.info(f"Запрашиваю фото для слота {slot['date']} ({slot['content_type']})")
            msg_id = send_photo_request(slot)
            if msg_id:
                slot["request_sent"] = datetime.now().isoformat()
                slot["telegram_msg_id"] = msg_id
                slot["status"] = "waiting_photo"
                changed = True
                time.sleep(1)

    return state if changed else state


# ─── generate ready slots ────────────────────────────────────────────────────

def _run_content_farm(content_type: str, project: str | None,
                      source_image: Path | None, is_ai_illustration: bool) -> Path | None:
    """
    Запускает content_farm.py для конкретного слота.
    Возвращает путь к сгенерированному пакету.
    """
    cmd = [
        "python3", "content_farm.py",
        "--limit", "1",
        "--mode", "auto",
        "--content-type", content_type,
        "--no-notify",
    ]
    if project:
        cmd += ["--project", project]
    if source_image and source_image.exists():
        cmd += ["--source-image", str(source_image)]
    else:
        cmd += ["--topics"]
    if is_ai_illustration:
        cmd += ["--ai-illustration"]

    log.info(f"Запуск: {' '.join(cmd)}")
    before = set(p.name for p in OUTPUT_DIR.glob("2026*") if (p / "post_meta.json").exists())

    try:
        proc = subprocess.run(
            cmd,
            cwd="/root/Ecodisplays",
            capture_output=True, text=True, timeout=600
        )
        if proc.returncode != 0:
            log.error(f"content_farm вернул {proc.returncode}: {proc.stderr[-500:]}")
        elif not (set(p.name for p in OUTPUT_DIR.glob("2026*") if (p / "post_meta.json").exists()) - before):
            log.warning(f"content_farm завершился успешно, но пакет не создан. stdout: {proc.stdout[-300:]}")
    except subprocess.TimeoutExpired:
        log.error("content_farm timeout 600s")
        return None
    except Exception as e:
        log.error(f"content_farm ошибка: {e}")
        return None

    after = set(p.name for p in OUTPUT_DIR.glob("2026*") if (p / "post_meta.json").exists())
    new_pkgs = sorted(after - before)
    if new_pkgs:
        return OUTPUT_DIR / new_pkgs[-1]
    return None


def _notify_generated(slot: dict, pkg_path: Path):
    """Отправляет уведомление в Telegram о сгенерированном посте."""
    post_date = slot["date"]
    ct = slot["content_type"]
    is_ai = slot.get("is_ai_illustration", False)
    ai_tag = " _(AI иллюстрация)_" if is_ai else ""

    # Читаем медиа из пакета
    thumb = pkg_path / "post.jpg"
    if not thumb.exists():
        thumb = next(pkg_path.glob("frame_*.jpg"), None)

    caption = (
        f"✅ *Пост готов к одобрению*{ai_tag}\n"
        f"📅 Дата: {post_date}\n"
        f"📌 Тип: {ct}\n"
        f"📂 Пакет: `{pkg_path.name}`\n\n"
        f"Запусти `/send 1` чтобы отправить на одобрение."
    )

    if thumb and thumb.exists():
        _tg_send_photo(thumb, caption)
    else:
        _tg_send(caption)


def generate_ready_slots(state: dict) -> dict:
    """
    Генерирует контент для слотов которые готовы:
    - needs_photo=False и status=planned и дата сегодня или раньше
    - needs_photo=True и status=photo_received
    - needs_photo=True и status=waiting_photo и дедлайн прошёл → AI иллюстрация
    """
    today = date.today()
    context_db = _load_context_db()

    for slot in state["slots"]:
        slot_date = date.fromisoformat(slot["date"])

        if slot["status"] in ("approved", "published", "skipped"):
            continue

        should_generate = False
        is_ai_illustration = False
        source_image = None

        # AI-слот: генерируем в день поста или накануне
        # rejected — перегенерируем независимо от даты
        if not slot["needs_photo"] and slot["status"] in ("planned", "rejected"):
            if slot["status"] == "rejected" or slot_date <= today + timedelta(days=1):
                should_generate = True
                is_ai_illustration = False

        # Получили фото → генерируем
        elif slot["status"] == "photo_received" and slot.get("photo_path"):
            should_generate = True
            source_image = Path(slot["photo_path"])

        # Дедлайн прошёл, фото не пришло → AI иллюстрация
        elif slot["needs_photo"] and slot["status"] == "waiting_photo":
            deadline = datetime.fromisoformat(slot["deadline"])
            if datetime.now() > deadline:
                log.info(f"Дедлайн прошёл для {slot['date']} — генерирую AI иллюстрацию")
                should_generate = True
                is_ai_illustration = True

        if not should_generate:
            continue

        # Если AI-слот (без реального фото) запрашивает тип с низким approval rate →
        # автозамена на eco_fact (30% vs 7% для product_shot)
        effective_content_type = slot["content_type"]
        if not source_image and effective_content_type in ("product_shot", "installation"):
            log.info(f"Замена {effective_content_type} → eco_fact (AI-слот без реального фото)")
            effective_content_type = "eco_fact"

        log.info(f"Генерирую слот {slot['date']} ({effective_content_type}) "
                 f"{'[AI]' if is_ai_illustration else '[реальное фото]' if source_image else '[AI тема]'}")

        pkg = _run_content_farm(
            content_type=effective_content_type,
            project=slot.get("project"),
            source_image=source_image,
            is_ai_illustration=is_ai_illustration,
        )

        if pkg:
            slot["status"] = "generated"
            slot["generated_package"] = pkg.name
            slot["is_ai_illustration"] = is_ai_illustration
            log.info(f"Слот {slot['date']} → пакет {pkg.name}")
            _notify_generated(slot, pkg)
        else:
            log.error(f"Не удалось сгенерировать слот {slot['date']}")

        time.sleep(2)

    return state


# ─── photo received (вызывается из approval_bot.py) ──────────────────────────

def mark_photo_received(slot_date: str, photo_path: str):
    """Отмечает слот как photo_received с путём к фото."""
    state = load_state()
    for slot in state["slots"]:
        if slot["date"] == slot_date:
            slot["status"] = "photo_received"
            slot["photo_path"] = photo_path
            save_state(state)
            log.info(f"Фото получено для слота {slot_date}: {photo_path}")
            _tg_send(f"✅ Фото получено для поста *{slot_date}*! Генерирую контент...")
            return True
    log.warning(f"Слот {slot_date} не найден")
    return False


def mark_photo_skipped(slot_date: str):
    """Пользователь нажал 'Пропустить' — агент сгенерирует AI иллюстрацию."""
    state = load_state()
    for slot in state["slots"]:
        if slot["date"] == slot_date:
            slot["status"] = "waiting_photo"
            # Устанавливаем дедлайн в прошлое — generate_ready_slots подхватит
            slot["deadline"] = datetime.now().isoformat()
            save_state(state)
            log.info(f"Фото пропущено для {slot_date} — будет AI иллюстрация")
            _tg_send(f"⏭ Буду использовать AI-иллюстрацию для поста *{slot_date}*")
            return True
    return False


# ─── plan view ───────────────────────────────────────────────────────────────

def print_plan(state: dict):
    """Выводит план постов на 14 дней."""
    slots = state.get("slots", [])
    if not slots:
        print("Нет активного цикла. Запусти --run-scheduled для создания.")
        return

    print(f"\n📅 ПЛАН КОНТЕНТА — Ecodisplays Instagram")
    print(f"Цикл начался: {state.get('cycle_start', '?')}\n")
    print(f"{'Дата':<12} {'Тип':<16} {'Проект':<12} {'Статус':<18} {'Фото?'}")
    print("-" * 70)

    context_db = _load_context_db()
    for slot in slots:
        slot_date = slot["date"]
        ct = slot["content_type"]
        proj = slot.get("project") or "-"
        status = slot["status"]
        needs = "📷 нужно" if slot["needs_photo"] else "🤖 AI"
        is_past = date.fromisoformat(slot_date) < date.today()
        prefix = "✓ " if status in ("generated", "published") else "· "
        print(f"{prefix}{slot_date:<10} {ct:<16} {proj:<12} {status:<18} {needs}")

    print()


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Content Calendar Agent")
    parser.add_argument("--run-scheduled", action="store_true",
                        help="Основной cron-режим: проверка и генерация")
    parser.add_argument("--plan", action="store_true",
                        help="Показать план на 14 дней")
    parser.add_argument("--reset-cycle", action="store_true",
                        help="Сбросить цикл и создать новый")
    parser.add_argument("--photo-received", nargs=2, metavar=("SLOT_DATE", "PHOTO_PATH"),
                        help="Отметить фото как полученное (вызывается из бота)")
    parser.add_argument("--photo-skipped", metavar="SLOT_DATE",
                        help="Пропустить фото для слота (будет AI иллюстрация)")
    args = parser.parse_args()

    if args.photo_received:
        slot_date, photo_path = args.photo_received
        mark_photo_received(slot_date, photo_path)
        return

    if args.photo_skipped:
        mark_photo_skipped(args.photo_skipped)
        return

    context_db = _load_context_db()
    state = load_state()

    if args.reset_cycle:
        state = generate_new_cycle(context_db)
        save_state(state)
        print("Новый цикл создан:")
        print_plan(state)
        return

    if args.plan:
        state = ensure_cycle(state, context_db)
        save_state(state)
        print_plan(state)
        return

    if args.run_scheduled:
        log.info("=== Content Calendar: запуск по расписанию ===")
        state = ensure_cycle(state, context_db)
        state = check_photo_requests(state)
        state = generate_ready_slots(state)
        save_state(state)
        log.info("=== Content Calendar: завершено ===")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
