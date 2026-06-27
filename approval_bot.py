"""
Telegram Approval Bot — бот для одобрения и публикации Reels.

Функции:
  - Отправляет готовые пакеты на одобрение с кнопками
  - При нажатии ✅ — публикует в Instagram
  - При нажатии ❌ — пропускает
  - /pending  — показать неотправленные пакеты
  - /send N   — отправить N последних пакетов на одобрение

Запуск (фоновый):
  python3 approval_bot.py &

Или разово отправить все новые:
  python3 approval_bot.py --send-pending
"""

import os
import json
import time
import logging
import argparse
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
SENT_LOG = OUTPUT_DIR / "sent_to_telegram.json"
QUALITY_LOG = OUTPUT_DIR / "quality_feedback.json"
PENDING_FEEDBACK_FILE = OUTPUT_DIR / "pending_feedback.json"
CONTEXT_DB = Path(__file__).parent / "context_db.json"


def load_sent() -> dict:
    if SENT_LOG.exists():
        return json.loads(SENT_LOG.read_text())
    return {}


def save_sent(sent: dict):
    SENT_LOG.write_text(json.dumps(sent, ensure_ascii=False, indent=2))


def load_quality() -> dict:
    if QUALITY_LOG.exists():
        return json.loads(QUALITY_LOG.read_text())
    return {"batches": [], "total_approved": 0, "total_skipped": 0}


def save_quality(q: dict):
    QUALITY_LOG.write_text(json.dumps(q, ensure_ascii=False, indent=2))


def load_pending_feedback() -> dict:
    if PENDING_FEEDBACK_FILE.exists():
        return json.loads(PENDING_FEEDBACK_FILE.read_text())
    return {}


def save_pending_feedback(pf: dict):
    PENDING_FEEDBACK_FILE.write_text(json.dumps(pf, ensure_ascii=False, indent=2))


def adjust_content_weights() -> str:
    """Пересчитывает content_weights в context_db.json на основе истории решений."""
    q = load_quality()
    decisions = q.get("decisions", [])
    if len(decisions) < 5:
        return "Нужно минимум 5 решений для пересчёта весов."

    by_type: dict[str, dict] = {}
    for d in decisions:
        ct = d.get("content_type", "unknown")
        if ct == "unknown":
            continue
        by_type.setdefault(ct, {"approved": 0, "skipped": 0, "feedback": []})
        by_type[ct][d["decision"]] += 1
        if d.get("skip_reason"):
            by_type[ct]["feedback"].append(d["skip_reason"])

    if not by_type:
        return "Нет данных по типам контента."

    db = json.loads(CONTEXT_DB.read_text())
    old_weights = dict(db.get("content_weights", {}))
    new_weights = dict(old_weights)

    changes = []
    for ct, counts in by_type.items():
        total = counts["approved"] + counts["skipped"]
        if total < 2:
            continue
        rate = counts["approved"] / total
        cur = new_weights.get(ct, 2)

        if rate >= 0.8 and cur < 5:
            new_weights[ct] = min(cur + 1, 5)
            changes.append(f"↑ {ct}: {cur} → {new_weights[ct]} (одобрено {rate:.0%})")
        elif rate <= 0.3 and cur > 1:
            new_weights[ct] = max(cur - 1, 1)
            changes.append(f"↓ {ct}: {cur} → {new_weights[ct]} (одобрено {rate:.0%})")

    if changes:
        db["content_weights"] = new_weights
        CONTEXT_DB.write_text(json.dumps(db, ensure_ascii=False, indent=2))
        return "Веса обновлены:\n" + "\n".join(changes)
    return "Веса не изменились — статистика в норме."


def record_decision(pkg_name: str, decision: str, batch_id: str | None = None, skip_reason: str | None = None):
    """Записывает решение (approved/skipped) и обновляет статистику качества."""
    q = load_quality()
    q["total_approved"] += 1 if decision == "approved" else 0
    q["total_skipped"] += 1 if decision == "skipped" else 0

    # Читаем метаданные пакета для аналитики
    pkg_path = OUTPUT_DIR / pkg_name
    meta = {}
    try:
        meta = json.loads((pkg_path / "post_meta.json").read_text())
    except Exception:
        pass

    entry = {
        "pkg": pkg_name,
        "decision": decision,
        "content_type": meta.get("content_type", "unknown"),
        "batch_id": batch_id,
        "skip_reason": skip_reason,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    q.setdefault("decisions", []).append(entry)
    save_quality(q)

    # Автопересчёт весов каждые 10 решений
    total = q["total_approved"] + q["total_skipped"]
    if total > 0 and total % 10 == 0:
        adjust_content_weights()


def get_quality_report(chat_id: str):
    """Формирует отчёт о качестве и выводах агента."""
    q = load_quality()
    total = q["total_approved"] + q["total_skipped"]
    if total == 0:
        return "Нет данных для анализа — одобри или пропусти несколько видео."

    rate = q["total_approved"] / total * 100
    decisions = q.get("decisions", [])

    # Статистика по типам контента
    by_type = {}
    for d in decisions:
        ct = d.get("content_type", "unknown")
        by_type.setdefault(ct, {"approved": 0, "skipped": 0})
        by_type[ct][d["decision"]] += 1

    type_lines = []
    for ct, counts in sorted(by_type.items()):
        t = counts["approved"] + counts["skipped"]
        r = counts["approved"] / t * 100 if t else 0
        bar = "🟢" if r >= 60 else "🟡" if r >= 40 else "🔴"
        type_lines.append(f"{bar} {ct}: {counts['approved']}/{t} ({r:.0f}%)")

    # Вывод агента
    worst = [ct for ct, c in by_type.items() if c["approved"] == 0 and c["skipped"] > 0]
    best = [ct for ct, c in by_type.items() if c["skipped"] == 0 and c["approved"] > 0]

    conclusions = []
    if best:
        conclusions.append(f"✅ Лучшие типы: {', '.join(best)} — продолжаю генерировать")
    if worst:
        conclusions.append(f"🚫 Не работают: {', '.join(worst)} — буду избегать")
    if rate >= 80:
        conclusions.append("🎯 Отличный результат! Промпты точные.")
    elif rate >= 60:
        conclusions.append("📈 Хороший результат, есть куда расти.")
    elif rate < 40:
        conclusions.append("⚠️ Много отказов — нужно пересмотреть промпты.")

    msg = (
        f"📊 Анализ качества контента\n\n"
        f"Одобрено: {q['total_approved']}/{total} ({rate:.0f}%)\n"
        f"Цель: 5/5 = 100% 🏆\n\n"
        f"По типам контента:\n" + "\n".join(type_lines) +
        "\n\nВыводы агента:\n" + "\n".join(conclusions)
    )
    return msg


def get_pending_packages() -> list[Path]:
    """Пакеты которые ещё не отправлены на одобрение (видео или фото)."""
    sent = load_sent()
    packages = []
    for pkg in sorted(OUTPUT_DIR.glob("2026*")):
        has_media = (pkg / "reel.mp4").exists() or (pkg / "post.jpg").exists()
        if has_media and (pkg / "post_meta.json").exists():
            if pkg.name not in sent:
                packages.append(pkg)
    return packages


def _extract_video_frame(video_path: Path, out_path: Path) -> bool:
    """Достаёт репрезентативный кадр из видео через ffmpeg (для vision-подписи).

    Берёт кадр на ~1.5с (избегаем чёрного интро). Возвращает True при успехе.
    """
    import subprocess
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", "1.5", "-i", str(video_path),
             "-frames:v", "1", "-q:v", "2", str(out_path)],
            capture_output=True, timeout=60,
        )
        if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return True
        # Фолбэк: самый первый кадр (короткое видео <1.5с)
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path),
             "-frames:v", "1", "-q:v", "2", str(out_path)],
            capture_output=True, timeout=60,
        )
        return r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        log.error(f"_extract_video_frame error: {e}")
        return False


def _escape_md(text: str) -> str:
    """Экранирует спецсимволы Markdown для Telegram."""
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _build_tg_caption(meta: dict, pkg_name: str) -> str:
    """Собирает подпись для Telegram-сообщения одобрения из post_meta."""
    pkg_path = OUTPUT_DIR / pkg_name
    is_photo = (pkg_path / "post.jpg").exists() and not (pkg_path / "reel.mp4").exists()
    ct = meta.get("content_type", "")
    ai_tag = " 🤖" if meta.get("ai_illustration") else ""
    title = _escape_md(meta.get("post_title", pkg_name))
    en = _escape_md(meta.get("caption_en", "")[:800])
    sr = _escape_md(meta.get("caption_sr", "")[:300])
    tags = _escape_md(" ".join(meta.get("hashtags", [])[:8]))
    return (
        f"{'🖼' if is_photo else '🎬'} *{title}*  `[{ct}]{ai_tag}`\n\n"
        f"🇬🇧 {en}\n\n"
        f"🇷🇸 {sr}\n\n"
        f"📌 {tags}"
    )


def _approval_keyboard(pkg_name: str) -> dict:
    """Клавиатура одобрения поста."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Опубликовать в Instagram", "callback_data": f"approve:{pkg_name}"},
                {"text": "❌ Пропустить", "callback_data": f"skip:{pkg_name}"},
            ],
            [
                {"text": "✏️ Изменить текст", "callback_data": f"edit_cap:{pkg_name}"},
                {"text": "🔄 Перегенерировать подпись", "callback_data": f"regen_cap:{pkg_name}"},
            ]
        ]
    }


def send_for_approval(package_dir: Path) -> bool:
    """Отправляет видео или фото в Telegram с кнопками одобрения."""
    meta = json.loads((package_dir / "post_meta.json").read_text())
    video = package_dir / "reel.mp4"
    photo = package_dir / "post.jpg"
    is_photo = not video.exists() and photo.exists()

    caption = _build_tg_caption(meta, package_dir.name)
    keyboard = _approval_keyboard(package_dir.name)

    if is_photo:
        with open(photo, "rb") as pf:
            resp = requests.post(
                f"{TG_API}/sendPhoto",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "MarkdownV2",
                    "reply_markup": json.dumps(keyboard),
                },
                files={"photo": pf},
                timeout=60
            )
        media_key = "photo"
    else:
        with open(video, "rb") as vf:
            resp = requests.post(
                f"{TG_API}/sendVideo",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "MarkdownV2",
                    "reply_markup": json.dumps(keyboard),
                },
                files={"video": vf},
                timeout=60
            )
        media_key = "video"

    if resp.ok:
        result = resp.json()["result"]
        msg_id = result["message_id"]
        media_obj = result.get(media_key, {})
        if isinstance(media_obj, list):
            media_obj = media_obj[-1] if media_obj else {}
        file_id = media_obj.get("file_id", "")
        sent = load_sent()
        sent[package_dir.name] = {
            "message_id": msg_id, "file_id": file_id,
            "media_type": media_key,
            "status": "pending", "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
        save_sent(sent)
        log.info(f"Отправлено на одобрение: {package_dir.name} (msg_id={msg_id}, type={media_key})")
        return True
    else:
        log.error(f"Ошибка отправки {package_dir.name}: {resp.text[:150]}")
        return False


MAKE_WEBHOOK_URL = "https://hook.eu1.make.com/h1pbu5veowi7s6ap1s8ramf6rqu4t8mx"
TELEGRAM_BOT_TOKEN_FOR_URL = os.getenv("TELEGRAM_BOT_TOKEN")


PUBLIC_BASE_URL = "http://146.103.111.13/ecodisplays/reels"


def _get_telegram_https_url(file_id: str) -> str:
    """Получает HTTPS download URL через Telegram getFile API."""
    if not file_id:
        return ""
    try:
        resp = requests.get(
            f"{TG_API}/getFile",
            params={"file_id": file_id},
            timeout=10
        )
        if resp.ok and resp.json().get("ok"):
            fp = resp.json()["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fp}"
    except Exception as e:
        log.warning(f"getFile failed: {e}")
    return ""


def send_to_make(pkg_name: str, file_id: str, caption: str) -> bool:
    """Отправляет данные в Make.com для публикации в Instagram.
    Использует HTTPS Telegram URL для видео (Instagram требует HTTPS).
    Для фото — HTTP URL с сервера."""
    pkg_path = OUTPUT_DIR / pkg_name
    has_photo = (pkg_path / "post.jpg").exists()
    has_video = (pkg_path / "reel.mp4").exists()

    if has_photo and not has_video:
        # Фото → публикуем в ленту (feed)
        image_url = f"{PUBLIC_BASE_URL}/{pkg_name}/post.jpg"
        payload = {
            "type": "photo",
            "image_url": image_url,
            "caption": caption,
            "package": pkg_name,
        }
        log.info(f"Make.com feed (photo): {image_url}")
    else:
        # Видео → публикуем в Reels
        video_url = _get_telegram_https_url(file_id)
        if not video_url:
            # fallback на HTTP сервер
            video_url = f"{PUBLIC_BASE_URL}/{pkg_name}/reel.mp4"
            log.warning(f"Telegram getFile failed, fallback to HTTP: {video_url}")
        payload = {
            "type": "reel",
            "video_url": video_url,
            "caption": caption,
            "package": pkg_name,
        }
        log.info(f"Make.com reel (video): {video_url[:80]}...")

    resp = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=15)
    if resp.ok:
        log.info(f"Отправлено в Make.com: {pkg_name} ({payload['type']})")
        return True
    else:
        log.error(f"Make.com ошибка: {resp.status_code} {resp.text[:100]}")
        return False


CONTENT_TYPES = ["installation", "eco_fact", "behind_scenes", "comparison", "urban_case", "product_shot"]
CONTENT_TYPE_LABELS = {
    "installation": "🔧 Монтаж",
    "eco_fact": "🌿 Эко-факт",
    "behind_scenes": "🎬 За кулисами",
    "comparison": "⚖️ Сравнение",
    "urban_case": "🏙 Кейс",
    "product_shot": "📦 Продукт",
}


def _load_calendar_state() -> dict:
    state_file = OUTPUT_DIR / "calendar_state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {"slots": []}


def _save_calendar_state(state: dict):
    state_file = OUTPUT_DIR / "calendar_state.json"
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _send_calendar_plan(chat_id):
    """Отправляет план контента — каждый слот отдельным сообщением с кнопками."""
    state = _load_calendar_state()
    slots = state.get("slots", [])

    if not slots:
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id, "text": "📅 Нет активного плана. Запусти cron или /generate."
        }, timeout=5)
        return

    requests.post(f"{TG_API}/sendMessage", json={
        "chat_id": chat_id, "text": "📅 *План контента на 14 дней:*",
        "parse_mode": "Markdown"
    }, timeout=5)

    for slot in slots:
        date = slot["date"]
        ct = slot.get("content_type", "eco_fact")
        status = slot.get("status", "planned")
        pkg = slot.get("generated_package")

        status_icon = {"planned": "⏳", "generated": "✅", "published": "📤", "waiting_photo": "📷"}.get(status, "❓")
        ct_label = CONTENT_TYPE_LABELS.get(ct, ct)

        text = f"{status_icon} *{date}* — {ct_label}"
        if pkg:
            text += f"\n📦 `{pkg}`"

        buttons = []
        if status == "planned":
            # Можно сменить тип или пропустить
            type_row = [{"text": CONTENT_TYPE_LABELS[t], "callback_data": f"cal_type:{date}:{t}"}
                        for t in CONTENT_TYPES if t != ct][:3]
            buttons.append(type_row)
            buttons.append([
                {"text": "🔄 Сменить тип", "callback_data": f"cal_showtypes:{date}"},
                {"text": "⏭ Пропустить слот", "callback_data": f"cal_skip:{date}"},
            ])
        elif status == "generated":
            buttons.append([
                {"text": "📤 Отправить на одобрение", "callback_data": f"cal_send:{date}"},
                {"text": "🔄 Перегенерировать", "callback_data": f"cal_regen:{date}"},
            ])
        elif status == "waiting_photo":
            buttons.append([
                {"text": "⏭ Пропустить (AI вместо фото)", "callback_data": f"skip_photo:{date}"},
            ])

        keyboard = {"inline_keyboard": buttons} if buttons else None
        payload = {
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
        }
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard)
        requests.post(f"{TG_API}/sendMessage", json=payload, timeout=5)
        time.sleep(0.3)


def handle_callback(callback: dict):
    """Обрабатывает нажатие кнопки."""
    query_id = callback["id"]
    data = callback.get("data", "")
    chat_id = callback["message"]["chat"]["id"]
    msg_id = callback["message"]["message_id"]

    if data == "noop":
        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)
        return

    # ── Управление календарём ────────────────────────────────────────────────
    if data.startswith("cal_"):
        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)
        parts = data.split(":", 2)
        cal_action = parts[0]  # cal_skip / cal_type / cal_showtypes / cal_send / cal_regen
        slot_date = parts[1] if len(parts) > 1 else ""

        state = _load_calendar_state()
        slot = next((s for s in state["slots"] if s["date"] == slot_date), None)

        if cal_action == "cal_skip":
            if slot:
                slot["status"] = "skipped"
                _save_calendar_state(state)
            requests.post(f"{TG_API}/editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": msg_id,
                "reply_markup": json.dumps({"inline_keyboard": [[{"text": "⏭ Слот пропущен", "callback_data": "noop"}]]})
            }, timeout=5)

        elif cal_action == "cal_showtypes":
            # Показываем все типы для выбора
            rows = []
            for t in CONTENT_TYPES:
                rows.append([{"text": CONTENT_TYPE_LABELS[t], "callback_data": f"cal_type:{slot_date}:{t}"}])
            rows.append([{"text": "❌ Отмена", "callback_data": "noop"}])
            requests.post(f"{TG_API}/editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": msg_id,
                "reply_markup": json.dumps({"inline_keyboard": rows})
            }, timeout=5)

        elif cal_action == "cal_type":
            new_type = parts[2] if len(parts) > 2 else ""
            if slot and new_type:
                slot["content_type"] = new_type
                slot["label"] = CONTENT_TYPE_LABELS.get(new_type, new_type)
                _save_calendar_state(state)
            ct_label = CONTENT_TYPE_LABELS.get(new_type, new_type)
            requests.post(f"{TG_API}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": f"✏️ *{slot_date}* — тип изменён на {ct_label}",
                "parse_mode": "Markdown",
                "reply_markup": json.dumps({"inline_keyboard": [[
                    {"text": "⏭ Пропустить слот", "callback_data": f"cal_skip:{slot_date}"},
                ]]})
            }, timeout=5)

        elif cal_action == "cal_send":
            # Найти пакет и отправить на одобрение
            pkg_name = slot.get("generated_package") if slot else None
            if pkg_name and (OUTPUT_DIR / pkg_name).exists():
                ok = send_for_approval(OUTPUT_DIR / pkg_name)
                text = "📤 Отправлено на одобрение!" if ok else "❌ Ошибка отправки"
            else:
                text = "⚠️ Пакет не найден — сначала перегенерируй"
            requests.post(f"{TG_API}/editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": msg_id,
                "reply_markup": json.dumps({"inline_keyboard": [[{"text": text, "callback_data": "noop"}]]})
            }, timeout=5)

        elif cal_action == "cal_regen":
            ct = slot.get("content_type", "eco_fact") if slot else "eco_fact"
            requests.post(f"{TG_API}/editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": msg_id,
                "reply_markup": json.dumps({"inline_keyboard": [[{"text": "⏳ Генерирую...", "callback_data": "noop"}]]})
            }, timeout=5)

            def do_regen(chat_id=chat_id, slot_date=slot_date, ct=ct):
                try:
                    before = {p.name for p in OUTPUT_DIR.glob("2026*") if (p / "post_meta.json").exists()}
                    proc = subprocess.run(
                        ["python3", "content_farm.py", "--topics", "--content-type", ct,
                         "--limit", "1", "--no-notify"],
                        cwd="/root/Ecodisplays", capture_output=True, text=True, timeout=300
                    )
                    after = sorted(OUTPUT_DIR.glob("2026*"), key=lambda p: p.stat().st_mtime, reverse=True)
                    new_pkg = next((p for p in after if p.name not in before and (p / "post_meta.json").exists()), None)
                    if new_pkg:
                        # Обновляем calendar_state свежей загрузкой (не из замыкания)
                        fresh_state = _load_calendar_state()
                        for s in fresh_state.get("slots", []):
                            if s["date"] == slot_date:
                                s["generated_package"] = new_pkg.name
                                s["status"] = "generated"
                                break
                        _save_calendar_state(fresh_state)
                        send_for_approval(new_pkg)
                        requests.post(f"{TG_API}/sendMessage", json={
                            "chat_id": chat_id,
                            "text": f"✅ Перегенерировано для *{slot_date}*!\nОтправлено на одобрение. Если не подойдёт — нажми ❌ снова.",
                            "parse_mode": "Markdown"
                        }, timeout=5)
                    else:
                        requests.post(f"{TG_API}/sendMessage", json={
                            "chat_id": chat_id, "text": "❌ Перегенерация не удалась."
                        }, timeout=5)
                except Exception as e:
                    requests.post(f"{TG_API}/sendMessage", json={
                        "chat_id": chat_id, "text": f"❌ Ошибка: {e}"
                    }, timeout=5)

            threading.Thread(target=do_regen, daemon=True).start()
        return

    if data.startswith("skip_photo:"):
        slot_date = data.split(":", 1)[1]
        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)
        import subprocess as _sp
        _sp.run(
            ["python3", "content_calendar.py", "--photo-skipped", slot_date],
            cwd="/root/Ecodisplays", timeout=30
        )
        requests.post(f"{TG_API}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": msg_id,
            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "⏭ Пропущено — будет AI", "callback_data": "noop"}]]})
        }, timeout=5)
        return

    if data == "pending:send_all":
        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)
        requests.post(f"{TG_API}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": msg_id, "reply_markup": json.dumps({"inline_keyboard": []})
        }, timeout=5)
        pending = get_pending_packages()
        requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": f"📤 Отправляю {len(pending)} пакетов..."}, timeout=5)
        for pkg in pending:
            send_for_approval(pkg)
            time.sleep(2)
        return

    if data == "pending:cancel_all":
        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)
        import shutil as _shutil
        pending = get_pending_packages()
        count = len(pending)
        for pkg in pending:
            _shutil.rmtree(pkg, ignore_errors=True)
        requests.post(f"{TG_API}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": msg_id, "reply_markup": json.dumps({"inline_keyboard": []})
        }, timeout=5)
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id, "text": f"🗑 Удалено {count} неотправленных пакетов"
        }, timeout=5)
        return

    if data.startswith("regen_cap:"):
        pkg_name = data.split(":", 1)[1]
        pkg_path = OUTPUT_DIR / pkg_name
        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id, "text": "⏳ Генерирую подпись..."}, timeout=5)
        requests.post(f"{TG_API}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": msg_id,
            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "⏳ Генерирую подпись...", "callback_data": "noop"}]]})
        }, timeout=5)

        def _do_regen_cap(chat_id=chat_id, msg_id=msg_id, pkg_name=pkg_name, pkg_path=pkg_path):
            try:
                from generate_reel import generate_caption
                meta = json.loads((pkg_path / "post_meta.json").read_text())
                ct = meta.get("content_type", "eco_fact")
                photo = pkg_path / "post.jpg"
                reel = pkg_path / "reel.mp4"
                # Для видео-пакета без кадра — извлекаем его, чтобы подпись была по картинке
                if not photo.exists() and reel.exists():
                    _extract_video_frame(reel, photo)
                image_path = photo if photo.exists() else None
                new_cap = generate_caption(
                    image_path=image_path,
                    topic=meta.get("post_title"),
                    content_type=ct if ct != "user_video" else "eco_fact",
                    avoid_caption=meta.get("caption_en") or meta.get("caption_sr"),
                )
                meta["caption_sr"] = new_cap.get("caption_sr", meta["caption_sr"])
                meta["caption_en"] = new_cap.get("caption_en", meta.get("caption_en", ""))
                meta["hashtags"] = new_cap.get("hashtags", meta["hashtags"])
                (pkg_path / "post_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

                # Пересобираем caption для Telegram
                requests.post(f"{TG_API}/editMessageCaption", json={
                    "chat_id": chat_id, "message_id": msg_id,
                    "caption": _build_tg_caption(meta, pkg_name),
                    "parse_mode": "MarkdownV2",
                    "reply_markup": json.dumps(_approval_keyboard(pkg_name)),
                }, timeout=10)
            except Exception as e:
                log.error(f"regen_cap error: {e}")
                requests.post(f"{TG_API}/editMessageReplyMarkup", json={
                    "chat_id": chat_id, "message_id": msg_id,
                    "reply_markup": json.dumps(_approval_keyboard(pkg_name))
                }, timeout=5)
                requests.post(f"{TG_API}/sendMessage", json={
                    "chat_id": chat_id, "text": f"❌ Ошибка генерации подписи: {e}"
                }, timeout=5)

        threading.Thread(target=_do_regen_cap, daemon=True).start()
        return

    if data.startswith("edit_cap:"):
        pkg_name = data.split(":", 1)[1]
        requests.post(f"{TG_API}/answerCallbackQuery",
                      json={"callback_query_id": query_id, "text": "✏️ Пришли новый текст"}, timeout=5)
        # Запоминаем, что ждём от пользователя новый текст описания для этого поста
        pf = load_pending_feedback()
        pf[str(chat_id)] = {"pkg": pkg_name, "edit_caption": True, "msg_id": msg_id}
        save_pending_feedback(pf)
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": ("✏️ Пришли новый текст описания одним сообщением. "
                     "Английский → заменит основную подпись, кириллица → сербскую строку. "
                     "Хэштеги сохранятся.")
        }, timeout=5)
        return

    # reason:pkg:key has 3 parts; approve/skip have 2
    data_parts = data.split(":")
    action = data_parts[0]
    pkg_name = data_parts[1] if len(data_parts) > 1 else ""
    pkg_path = OUTPUT_DIR / pkg_name

    # Подтверждаем получение callback
    requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)

    sent = load_sent()

    if action == "approve":
        # Редактируем кнопки
        requests.post(f"{TG_API}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": msg_id,
            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "⏳ Публикуется в Instagram...", "callback_data": "noop"}]]})
        }, timeout=5)

        # Формируем caption
        meta = json.loads((pkg_path / "post_meta.json").read_text())
        # Английский основной + краткий SR + хэштеги
        caption_sr = meta.get("caption_sr", "")
        sr_line = f"\n\n{caption_sr}" if caption_sr else ""
        caption = (
            meta.get("caption_en", "") + sr_line + "\n\n" +
            " ".join(meta["hashtags"])
        )[:2200]

        file_id = sent.get(pkg_name, {}).get("file_id", "")
        log.info(f"Отправляю в Make.com: {pkg_name} (file_id={file_id[:20]}...)")

        ok = send_to_make(pkg_name, file_id, caption)

        if ok:
            requests.post(f"{TG_API}/editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": msg_id,
                "reply_markup": json.dumps({"inline_keyboard": [[{"text": "✅ Отправлено в Instagram", "callback_data": "noop"}]]})
            }, timeout=5)
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"✅ Reel отправлен в Make.com → Instagram!\n📂 `{pkg_name}`",
                "parse_mode": "Markdown"
            }, timeout=5)
            sent[pkg_name]["status"] = "published"
            record_decision(pkg_name, "approved")

            # Если это трендовое видео — планируем проверку просмотров через 12 часов
            if meta.get("is_trending"):
                try:
                    import sys as _sys
                    _sys.path.insert(0, "/root/Ecodisplays")
                    from view_tracker import add_pending
                    add_pending(
                        pkg_name=pkg_name,
                        topic_id=meta.get("topic_id", "unknown"),
                        hook=meta.get("hook", ""),
                        approved_at=datetime.now().isoformat(),
                        published_at=datetime.now().isoformat(),
                    )
                except Exception as _e:
                    log.warning(f"view_tracker: не удалось добавить pending: {_e}")

        else:
            requests.post(f"{TG_API}/editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": msg_id,
                "reply_markup": json.dumps({"inline_keyboard": [[{"text": "❌ Ошибка — попробуй снова", "callback_data": f"approve:{pkg_name}"}]]})
            }, timeout=5)
            sent[pkg_name]["status"] = "error"

    elif action == "skip":
        requests.post(f"{TG_API}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": msg_id,
            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "⏭ Пропущено", "callback_data": "noop"}]]})
        }, timeout=5)
        # Сразу показываем что получили отказ
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": "❌ Пост отклонён. Укажи причину — агент учтёт и перегенерирует 👇"
        }, timeout=5)
        sent[pkg_name]["status"] = "skipped"
        record_decision(pkg_name, "skipped")
        log.info(f"Пропущено: {pkg_name}")
        _mark_slot_rejected(pkg_name)

        # Спрашиваем причину — выбор причины автоматически запускает перегенерацию
        reason_keyboard = {"inline_keyboard": [
            [
                {"text": "📝 Текст не тот", "callback_data": f"reason:{pkg_name}:bad_text"},
                {"text": "🖼 Фото не подходит", "callback_data": f"reason:{pkg_name}:bad_photo"},
            ],
            [
                {"text": "🎯 Не тот тип", "callback_data": f"reason:{pkg_name}:wrong_type"},
                {"text": "📐 Неверные спеки", "callback_data": f"reason:{pkg_name}:wrong_specs"},
            ],
            [
                {"text": "✏️ Написать причину", "callback_data": f"reason:{pkg_name}:freetext"},
                {"text": "🚫 Без причины — не надо", "callback_data": f"reason:{pkg_name}:none"},
            ],
        ]}
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": "Почему не подошло? Агент перегенерирует после ответа 🔄",
            "reply_markup": json.dumps(reason_keyboard)
        }, timeout=5)

    elif action == "reason":
        parts = data.split(":", 2)
        pkg_name = parts[1]
        reason_key = parts[2] if len(parts) > 2 else "none"

        requests.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)
        requests.post(f"{TG_API}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": msg_id, "reply_markup": json.dumps({"inline_keyboard": []})
        }, timeout=5)

        reason_labels = {
            "bad_text": "Текст не тот",
            "bad_photo": "Фото не подходит",
            "wrong_type": "Не тот тип контента",
            "wrong_specs": "Неверные спеки продукта",
            "none": None,
        }

        if reason_key == "freetext":
            # Ждём свободный текст от пользователя, после которого перегенерируем
            pf = load_pending_feedback()
            pf[str(chat_id)] = {"pkg": pkg_name, "waiting": True, "regen": True}
            save_pending_feedback(pf)
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": "Напиши причину — агент учтёт её и перегенерирует:"
            }, timeout=5)
        else:
            reason_text = reason_labels.get(reason_key)
            # Обновляем последнее решение с причиной
            q = load_quality()
            content_type_for_regen = "eco_fact"
            for entry in reversed(q.get("decisions", [])):
                if entry["pkg"] == pkg_name and entry["decision"] == "skipped":
                    entry["skip_reason"] = reason_text
                    content_type_for_regen = entry.get("content_type", "eco_fact")
                    break
            save_quality(q)

            msg = f"📝 Понял: {reason_text}. " if reason_text else ""

            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"{msg}🧠 Обновляю промпты... 🔄 Перегенерирую..."
            }, timeout=5)

            # Self-improve ДО перегенерации — последовательно в одном потоке
            import threading as _th
            def _improve_then_regen(ct=content_type_for_regen, reason=reason_text,
                                    _chat_id=chat_id, _pkg=pkg_name):
                if reason:
                    try:
                        from generate_reel import apply_rejection_to_prompts
                        apply_rejection_to_prompts(ct, reason)
                    except Exception as e:
                        log.warning(f"Self-improve ошибка: {e}")
                _trigger_regen(_chat_id, _pkg)
            _th.Thread(target=_improve_then_regen, daemon=True).start()
        return

    save_sent(sent)


def _download_telegram_photo(file_id: str, dest_path: Path) -> bool:
    """Скачивает фото из Telegram по file_id."""
    try:
        resp = requests.get(f"{TG_API}/getFile", params={"file_id": file_id}, timeout=10)
        if not resp.ok:
            return False
        file_path = resp.json()["result"]["file_path"]
        dl = requests.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}",
            timeout=30
        )
        if dl.ok:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(dl.content)
            return True
    except Exception as e:
        log.error(f"Ошибка скачивания фото: {e}")
    return False


def _trigger_regen(chat_id: int, pkg_name: str):
    """Запускает перегенерацию контента в фоновом потоке."""
    pkg_path = OUTPUT_DIR / pkg_name
    content_type = "eco_fact"
    # Ищем слот для обновления calendar_state
    slot_date = None
    state_file = OUTPUT_DIR / "calendar_state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        for slot in state.get("slots", []):
            if slot.get("generated_package") == pkg_name or slot.get("status") == "rejected":
                slot_date = slot["date"]
                content_type = slot.get("content_type", "eco_fact")
                break

    meta_file = pkg_path / "post_meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            content_type = meta.get("content_type", content_type)
        except Exception:
            pass

    def do_regen(chat_id=chat_id, content_type=content_type, slot_date=slot_date):
        try:
            before = {p.name for p in OUTPUT_DIR.glob("2026*") if (p / "post_meta.json").exists()}
            proc = subprocess.run(
                ["python3", "content_farm.py", "--topics", "--content-type", content_type,
                 "--limit", "1", "--no-notify"],
                cwd="/root/Ecodisplays", capture_output=True, text=True, timeout=300
            )
            after = sorted(OUTPUT_DIR.glob("2026*"), key=lambda p: p.stat().st_mtime, reverse=True)
            new_pkg = next((p for p in after if p.name not in before and (p / "post_meta.json").exists()), None)
            if new_pkg:
                # Обновляем calendar_state — связываем новый пакет со слотом
                if slot_date and state_file.exists():
                    state = json.loads(state_file.read_text())
                    for slot in state.get("slots", []):
                        if slot["date"] == slot_date:
                            slot["status"] = "generated"
                            slot["generated_package"] = new_pkg.name
                            break
                    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
                send_for_approval(new_pkg)
                requests.post(f"{TG_API}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "✅ Перегенерировано! Проверяй выше 👆\n\nЕсли снова не подойдёт — нажми ❌ и агент перегенерирует ещё раз."
                }, timeout=5)
            else:
                requests.post(f"{TG_API}/sendMessage", json={
                    "chat_id": chat_id, "text": "❌ Перегенерация не удалась."
                }, timeout=5)
        except Exception as e:
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id, "text": f"❌ Ошибка перегенерации: {e}"
            }, timeout=5)

    threading.Thread(target=do_regen, daemon=True).start()


def _mark_slot_rejected(pkg_name: str):
    """Помечает слот в calendar_state как rejected чтобы cron перегенерировал."""
    state_file = OUTPUT_DIR / "calendar_state.json"
    if not state_file.exists():
        return
    state = json.loads(state_file.read_text())
    for slot in state.get("slots", []):
        if slot.get("generated_package") == pkg_name:
            slot["status"] = "rejected"
            slot.pop("generated_package", None)
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
            log.info(f"Слот {slot['date']} → rejected (пакет {pkg_name} отклонён)")
            return


def _find_waiting_slot() -> str | None:
    """Находит ближайший слот в статусе waiting_photo."""
    state_file = OUTPUT_DIR / "calendar_state.json"
    if not state_file.exists():
        return None
    state = json.loads(state_file.read_text())
    from datetime import date
    today = date.today().isoformat()
    waiting = [
        s for s in state.get("slots", [])
        if s["status"] == "waiting_photo" and s["date"] >= today
    ]
    if waiting:
        return min(waiting, key=lambda s: s["date"])["date"]
    return None


def handle_message(message: dict):
    """Обрабатывает входящие фото и видео."""
    chat_id = message["chat"]["id"]

    # Определяем file_id и тип медиа
    file_id = None
    is_video = False

    if "photo" in message:
        photos = message["photo"]
        best = max(photos, key=lambda p: p.get("file_size", 0))
        file_id = best["file_id"]
        log.info(f"📷 Входящее фото от chat_id={chat_id}, file_id={file_id[:20]}...")
    elif "video" in message:
        file_id = message["video"]["file_id"]
        is_video = True
        log.info(f"🎬 Входящее видео от chat_id={chat_id}, file_id={file_id[:20]}...")
    elif "document" in message:
        doc = message["document"]
        mime = doc.get("mime_type", "")
        if mime.startswith("image/"):
            file_id = doc["file_id"]
            log.info(f"📷 Входящий документ-фото от chat_id={chat_id}")
        elif mime.startswith("video/"):
            file_id = doc["file_id"]
            is_video = True
            log.info(f"🎬 Входящий документ-видео от chat_id={chat_id}")

    if file_id and is_video:
        # Видео → сразу формируем Reel и отправляем на одобрение
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id, "text": "🎬 Видео получено! Генерирую пост..."
        }, timeout=5)

        def _make_video_post(file_id=file_id, chat_id=chat_id):
            try:
                tmp = OUTPUT_DIR / "received_photos" / f"user_video_{int(time.time())}.mp4"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                if not _download_telegram_photo(file_id, tmp):
                    requests.post(f"{TG_API}/sendMessage", json={
                        "chat_id": chat_id, "text": "❌ Не удалось скачать видео."
                    }, timeout=5)
                    return
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                package_dir = OUTPUT_DIR / f"{ts}_user_video"
                package_dir.mkdir(exist_ok=True)
                import shutil as _shutil
                _shutil.copy(tmp, package_dir / "reel.mp4")

                # Достаём кадр и генерируем уникальную подпись по нему (vision)
                frame = package_dir / "post.jpg"
                caption_sr = "EcoDisplays — паметни е-инк дисплеји за одрживу будућност 🌿"
                caption_en = "EcoDisplays — smart e-ink displays for a sustainable future"
                hashtags = ["#ecodisplays", "#eink", "#sustainability", "#smartcity"]
                try:
                    from generate_reel import generate_caption
                    image_for_caption = frame if _extract_video_frame(package_dir / "reel.mp4", frame) else None
                    cap = generate_caption(
                        image_path=image_for_caption,
                        topic="e-ink display in real urban environment",
                        content_type="eco_fact",
                    )
                    caption_sr = cap.get("caption_sr") or caption_sr
                    caption_en = cap.get("caption_en") or caption_en
                    hashtags = cap.get("hashtags") or hashtags
                except Exception as e:
                    log.error(f"video caption generation failed, using fallback: {e}")

                meta = {
                    "generated_at": datetime.now().isoformat(),
                    "source": "user_video",
                    "status": "pending_approval",
                    "post_type": "reel",
                    "post_title": f"user_video_{ts}",
                    "caption_sr": caption_sr,
                    "caption_en": caption_en,
                    "hashtags": hashtags,
                    "content_type": "user_video",
                }
                (package_dir / "post_meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2)
                )
                ok = send_for_approval(package_dir)
                if not ok:
                    requests.post(f"{TG_API}/sendMessage", json={
                        "chat_id": chat_id, "text": "❌ Ошибка отправки на одобрение."
                    }, timeout=5)
            except Exception as e:
                log.error(f"_make_video_post ошибка: {e}")
                requests.post(f"{TG_API}/sendMessage", json={
                    "chat_id": chat_id, "text": f"❌ Ошибка: {e}"
                }, timeout=5)

        threading.Thread(target=_make_video_post, daemon=True).start()
        return

    if "photo" in message or (file_id and not is_video):

        # Приоритет 1: ответ на comic-запрос (pending_comic.json)
        pending_comic_file = OUTPUT_DIR / "pending_comic.json"
        if pending_comic_file.exists():
            try:
                pending = json.loads(pending_comic_file.read_text())
            except Exception:
                pending = None

            if pending and pending.get("caption_data"):
                dest = OUTPUT_DIR / "received_photos" / f"comic_{int(time.time())}.jpg"
                if _download_telegram_photo(file_id, dest):
                    requests.post(f"{TG_API}/sendMessage", json={
                        "chat_id": chat_id,
                        "text": "✅ Фото получено! Создаю пост-пакет..."
                    }, timeout=5)

                    def _make_comic_post(dest=dest, pending=pending, chat_id=chat_id):
                        try:
                            from generate_reel import save_image_package
                            caption_data = pending["caption_data"]
                            package_dir = save_image_package(dest, caption_data, "comic_user_photo")
                            # Помечаем как comic в мета
                            meta_file = package_dir / "post_meta.json"
                            if meta_file.exists():
                                meta = json.loads(meta_file.read_text())
                                meta["ai_illustration"] = True
                                meta["media_source"] = "comic_user"
                                meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
                            # Удаляем pending_comic — запрос выполнен
                            pending_comic_file.unlink(missing_ok=True)
                            # Отправляем на одобрение
                            ok = send_for_approval(package_dir)
                            if not ok:
                                requests.post(f"{TG_API}/sendMessage", json={
                                    "chat_id": chat_id,
                                    "text": "❌ Ошибка отправки на одобрение."
                                }, timeout=5)
                        except Exception as e:
                            log.error(f"_make_comic_post ошибка: {e}")
                            requests.post(f"{TG_API}/sendMessage", json={
                                "chat_id": chat_id, "text": f"❌ Ошибка: {e}"
                            }, timeout=5)

                    threading.Thread(target=_make_comic_post, daemon=True).start()
                else:
                    requests.post(f"{TG_API}/sendMessage", json={
                        "chat_id": chat_id, "text": "❌ Не удалось скачать фото. Попробуй ещё раз."
                    }, timeout=5)
                return

        # Приоритет 2: генерируем пост из фото и сразу отправляем на одобрение
        ext = ".jpg"
        dest = OUTPUT_DIR / "received_photos" / f"user_{int(time.time())}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if _download_telegram_photo(file_id, dest):
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": "📷 Фото получено! Генерирую пост..."
            }, timeout=5)

            def _make_photo_post(dest=dest, chat_id=chat_id):
                try:
                    from generate_reel import save_image_package, generate_caption
                    caption_data = generate_caption(dest, "eco_fact")
                    package_dir = save_image_package(dest, caption_data, "user_photo")
                    ok = send_for_approval(package_dir)
                    if not ok:
                        requests.post(f"{TG_API}/sendMessage", json={
                            "chat_id": chat_id, "text": "❌ Ошибка отправки на одобрение."
                        }, timeout=5)
                except Exception as e:
                    log.error(f"_make_photo_post ошибка: {e}")
                    requests.post(f"{TG_API}/sendMessage", json={
                        "chat_id": chat_id, "text": f"❌ Ошибка: {e}"
                    }, timeout=5)

            threading.Thread(target=_make_photo_post, daemon=True).start()
        else:
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id, "text": "❌ Не удалось скачать фото. Попробуй ещё раз."
            }, timeout=5)
        return

    # Игнорируем всё остальное (текст, стикеры и т.д.)
    if not file_id:
        return

    text = message.get("text", "").strip()

    # Ручное редактирование подписи перед публикацией
    if text and not text.startswith("/"):
        pf = load_pending_feedback()
        if pf.get(str(chat_id), {}).get("edit_caption"):
            entry = pf.pop(str(chat_id))
            save_pending_feedback(pf)
            pkg_name = entry.get("pkg", "")
            edit_msg_id = entry.get("msg_id")
            pkg_path = OUTPUT_DIR / pkg_name
            meta_file = pkg_path / "post_meta.json"
            if not meta_file.exists():
                requests.post(f"{TG_API}/sendMessage", json={
                    "chat_id": chat_id, "text": f"❌ Пакет `{pkg_name}` не найден.",
                    "parse_mode": "Markdown"
                }, timeout=5)
                return
            try:
                meta = json.loads(meta_file.read_text())
                # Авто-роутинг по алфавиту: кириллица → SR, латиница → основной EN
                cyr = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
                lat = sum(1 for c in text if c.isalpha() and c.isascii())
                if cyr >= lat:
                    meta["caption_sr"] = text
                else:
                    meta["caption_en"] = text
                meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
                # Пересобираем сообщение одобрения с новым текстом
                requests.post(f"{TG_API}/editMessageCaption", json={
                    "chat_id": chat_id, "message_id": edit_msg_id,
                    "caption": _build_tg_caption(meta, pkg_name),
                    "parse_mode": "MarkdownV2",
                    "reply_markup": json.dumps(_approval_keyboard(pkg_name)),
                }, timeout=10)
                requests.post(f"{TG_API}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "✅ Текст обновлён. Проверь пост выше и жми «Опубликовать»."
                }, timeout=5)
            except Exception as e:
                log.error(f"edit_cap error: {e}")
                requests.post(f"{TG_API}/sendMessage", json={
                    "chat_id": chat_id, "text": f"❌ Не удалось обновить текст: {e}"
                }, timeout=5)
            return

    # Свободный текст как причина пропуска
    if text and not text.startswith("/"):
        pf = load_pending_feedback()
        if str(chat_id) in pf:
            entry = pf.pop(str(chat_id))
            save_pending_feedback(pf)
            pkg_name = entry.get("pkg", "")
            q = load_quality()
            for dec in reversed(q.get("decisions", [])):
                if dec["pkg"] == pkg_name and dec["decision"] == "skipped":
                    dec["skip_reason"] = text
                    break
            save_quality(q)
            should_regen = entry.get("regen", False)
            content_type = "eco_fact"
            for dec in q.get("decisions", []):
                if dec.get("pkg") == pkg_name:
                    content_type = dec.get("content_type", "eco_fact")
            msg = f"✏️ Записал: «{text[:200]}»\n"
            msg += "🧠 Обновляю промпты... 🔄 Перегенерирую..." if should_regen else "Агент учтёт это в следующем цикле."
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": chat_id, "text": msg
            }, timeout=5)
            if should_regen:
                # Self-improve ДО перегенерации — последовательно в одном потоке
                def _improve_then_regen(ct=content_type, reason=text,
                                        _chat_id=chat_id, _pkg=pkg_name):
                    try:
                        from generate_reel import apply_rejection_to_prompts
                        apply_rejection_to_prompts(ct, reason)
                    except Exception as e:
                        log.warning(f"Self-improve ошибка: {e}")
                    # Только после обновления промптов запускаем перегенерацию
                    _trigger_regen(_chat_id, _pkg)
                import threading as _th
                _th.Thread(target=_improve_then_regen, daemon=True).start()
            return

    # Игнорируем текстовые сообщения и команды


def run_polling():
    """Запускает бота в режиме polling."""
    log.info("Бот запущен (polling mode)...")
    offset = None

    # Сообщение о запуске
    requests.post(f"{TG_API}/sendMessage", json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "🤖 Бот запущен!\n\n📷 Пришли фото → бот сформирует пост и отправит на одобрение\n🎬 Пришли видео → бот сформирует Reel и отправит на одобрение\n\nКонтент также публикуется автоматически в 9:00 и 15:00."
    }, timeout=5)

    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset
            resp = requests.get(f"{TG_API}/getUpdates", params=params, timeout=35)
            if not resp.ok:
                time.sleep(5)
                continue

            updates = resp.json().get("result", [])
            if updates:
                log.info(f"Получено апдейтов: {len(updates)}")
            for update in updates:
                offset = update["update_id"] + 1
                log.info(f"Апдейт #{update['update_id']}: keys={list(update.keys())}")
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                elif "message" in update:
                    log.info(f"Message keys: {list(update['message'].keys())}")
                    handle_message(update["message"])

        except KeyboardInterrupt:
            log.info("Бот остановлен")
            break
        except Exception as e:
            log.error(f"Ошибка polling: {e}")
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Approval Bot")
    parser.add_argument("--send-pending", action="store_true", help="Отправить все неотправленные пакеты и выйти")
    parser.add_argument("--send", type=int, metavar="N", help="Отправить N последних пакетов")
    parser.add_argument("--poll", action="store_true", help="Запустить бота в режиме polling")
    args = parser.parse_args()

    if args.send_pending or args.send:
        limit = args.send or 3
        pending = get_pending_packages()[:limit]
        print(f"Отправляю {len(pending)} пакетов на одобрение...")
        for pkg in pending:
            if send_for_approval(pkg):
                print(f"  ✓ {pkg.name}")
            time.sleep(2)
        print("Готово!")

    elif args.poll:
        run_polling()

    else:
        parser.print_help()
