"""
EcoDisplays Media Bot — новый упрощённый флоу:

1. Каждый день в 9:00 бот присылает промпт с темой дня → ждёт фото/видео
2. Пользователь присылает медиа
3. Бот генерирует caption через GPT-4o (vision — смотрит на само медиа)
4. Присылает превью с кнопками ✅ Опубликовать / ✏️ Изменить / ❌ Отмена
5. ✅ → Make webhook → Instagram

Запуск фонового polling:
  python3 media_bot.py

Отправить дневной промпт вручную:
  python3 media_bot.py --daily-prompt

Установить cron (9:00 каждый день):
  python3 media_bot.py --setup-cron
"""

import os
import sys
import json
import time
import logging
import argparse
import base64
import threading
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/root/Ecodisplays/media_bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
MAKE_WEBHOOK = os.getenv("MAKE_WEBHOOK_URL", "https://hook.eu1.make.com/h1pbu5veowi7s6ap1s8ramf6rqu4t8mx")

TG = f"https://api.telegram.org/bot{BOT_TOKEN}"
STATE_FILE = Path("/root/Ecodisplays/output/media_bot_state.json")
STATE_FILE.parent.mkdir(exist_ok=True)

# --- Темы дня (ротация по кругу) ---
#
# ВЫИГРЫШНАЯ ФОРМУЛА (пост "Montaža na gradskom stubu" собрал ~7x просмотров):
#   1. Живые люди + реальное действие (рабочие монтируют, техник обслуживает)
#   2. Процесс/трансформация — time-lapse, before→after, экран "оживает"
#   3. Документальная достоверность (НЕ split-screen реклама, НЕ абстрактная анимация)
#   4. ЛОКАЦИЯ — целевые рынки: Дубай/Залив (набережная, пальмы, небоскрёбы, smart-city
#      мегапроекты) и юг Европы/Средиземноморье (набережная, марина, старый город).
#      Сербские сцены (парк/улица Белграда) ОСТАВЛЕНЫ В РОТАЦИИ для локальной базы,
#      но это меньшинство. По умолчанию — Gulf/Med.
#   5. Медленный reveal камерой — zoom out на продукт в городском контексте
#   6. Осязаемый продукт в реальной среде (на столбе, на остановке, на набережной)
# Темы разные по смыслу (солар/IP65/ночь/навигация/smart-city), но КАЖДЫЙ промпт
# несёт эту ДНК. При добавлении новых тем — держись формулы выше и приоритета локаций.
DAILY_TOPICS = [
    {
        # Эталон формулы — победитель, переориентирован на набережную Дубая
        "theme": "Display installation on a waterfront pole (Dubai Marina)",
        "prompt": "Time-lapse of workers installing a sleek e-ink outdoor display on a metal pole along the Dubai Marina waterfront promenade. Modern minimalist design, matte gray housing. Palm trees, glass skyscrapers and blue sky in the background. Professional installation, safety vests. Camera slowly zooms out to show the display in the upscale waterfront landscape.",
    },
    {
        "theme": "Installation at a seaside bus stop (Mediterranean)",
        "prompt": "Time-lapse of two workers in safety vests installing an e-ink outdoor display at a bus stop on a sunny Mediterranean seaside promenade. They mount the bracket, secure the matte gray housing, connect the cable — the screen powers on showing the real-time bus schedule. Tourists and locals gather and look. Sea, stone old-town buildings and palm trees behind. Documentary realistic, warm morning light, camera slowly zooms out to the busy seafront.",
    },
    {
        "theme": "Technician services the display (Gulf smart-city park)",
        "prompt": "A technician in a branded vest opens the housing of an outdoor e-ink display mounted on a pole in a modern Gulf smart-city park with palm trees and clean stone paving. He checks the solar panel and cabling, closes the housing, and the screen refreshes with a clean transit map. Handheld documentary feel, soft morning light, camera slowly pulls back to reveal the landscaped plaza and skyline.",
    },
    {
        "theme": "Mounting the solar panel (Mediterranean marina)",
        "prompt": "Time-lapse of workers in safety vests mounting a solar panel above an e-ink display on a metal pole along a Mediterranean marina with yachts. From ground prep with tools to the panel catching the sun — the screen wakes up and shows a transit schedule. Blue sky, sea, palm trees, documentary realistic, camera slowly zooms out to the marina landscape.",
    },
    {
        "theme": "Tourist uses wayfinding display (Dubai waterfront)",
        "prompt": "A tourist walks up to an outdoor e-ink wayfinding display on a pole on a Dubai waterfront promenade. She studies the city map and points of interest, smiles, takes a photo, and continues walking. Palm trees, modern skyline, warm afternoon light, real people passing by, documentary realistic. Camera slowly orbits and zooms out to reveal the promenade and the city beyond.",
    },
    {
        "theme": "Night installation (Dubai skyline)",
        "prompt": "Night installation: a crew in safety vests with headlamps mounts an e-ink outdoor display on a pole on a quiet street with the illuminated Dubai skyline behind. They power it on and the screen glows with soft warm backlight showing the transit schedule, calm next to harsh LED billboards nearby. Reflections on polished pavement, documentary realistic, camera slowly zooms out.",
    },
    {
        "theme": "Installation in the rain — IP65 (Mediterranean)",
        "prompt": "Workers in raincoats finish installing an e-ink outdoor display on a pole as light rain begins on a Mediterranean seafront street. Water runs off the sealed IP65 housing while the screen keeps showing a clear bus schedule. Close, real details: drops on the glass, hands tightening the bracket. Sea and old-town facades behind. Documentary realistic, camera slowly zooms out to the wet promenade.",
    },
    {
        "theme": "Engineer configures the display (Gulf smart-city plaza)",
        "prompt": "An engineer with a laptop stands beside a freshly installed e-ink display on a pole in a modern Gulf smart-city plaza with palm trees and fountains. He pushes a content update and the screen refreshes to a new map and schedule. Golden hour light, glass towers behind, real documentary feel. Camera slowly orbits and pulls back to reveal the display in the urban plaza.",
    },
    {
        # Сербская сцена — оставлена в ротации для локальной базы
        "theme": "Carrying the display through a park (Belgrade — rotation)",
        "prompt": "Behind-the-scenes documentary shot: two installers in safety vests carry a new e-ink display through a green Belgrade park toward its pole, set down their tools, and begin mounting it. Natural daylight, trees, people walking by. Handheld realistic style, camera slowly follows them and zooms out to the park and city.",
    },
    {
        # Сербская сцена — оставлена в ротации для локальной базы
        "theme": "Morning at the bus stop (Belgrade — rotation)",
        "prompt": "Sunny morning at a Belgrade bus stop. Commuters with coffee read a crisp e-ink display showing real-time arrivals. A worker in a vest walks up and taps the display to update the info, then the bus arrives exactly as shown. Documentary realistic, slow push-in on the screen then zoom out to the arriving bus.",
    },
]


# ─────────────────────────── helpers ────────────────────────────

def tg_post(method: str, **kwargs) -> dict:
    r = requests.post(f"{TG}/{method}", json=kwargs, timeout=30)
    return r.json()


def tg_post_files(method: str, files: dict, data: dict) -> dict:
    r = requests.post(f"{TG}/{method}", files=files, data=data, timeout=120)
    return r.json()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"topic_index": 0, "pending": None}


def save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2))


# ─────────────────────────── GPT caption ────────────────────────

def generate_caption(media_url: str, media_type: str, topic: str) -> str:
    """Генерирует caption через LLM."""
    system = (
        "You are an Instagram content manager for EcoDisplays — a company selling e-ink outdoor displays "
        "(32\"/42\", IP65, solar-powered, 10-20x less energy than LCD). Primary target markets: the Gulf "
        "(Dubai / UAE) and Southern Europe / the Mediterranean. Relevant angles: tourism & waterfronts, "
        "smart-city megaprojects, energy savings & autonomy of solar. Website: www.ecodisplays.rs\n\n"
        "ENGLISH is the PRIMARY published language (Gulf and Mediterranean audiences do not read Serbian Cyrillic).\n"
        "Write the Instagram caption STRICTLY in this format:\n"
        "1. ENGLISH caption — 3-5 sentences. First line is a strong hook. Cover the product benefit and end "
        "with a clear call to action.\n"
        "2. One SHORT secondary line in Serbian (Latin script, 1 sentence) for the local Serbian audience — "
        "not a full translation.\n"
        "3. Hashtags: must include 2-3 of #dubai #uae #smartdubai #mydubai #mediterranean PLUS the brand tags "
        "#EcoDisplays #eink #smartcity #sustainability and 1 Serbian tag #Srbija\n\n"
        "IMPORTANT: English first and primary. Serbian only as one short Latin-script line. No Russian, no "
        "Cyrillic, no meta-commentary, no explanations. Output the post text directly."
    )

    if media_type == "photo":
        user_text = f"Topic: {topic}\n\nWrite an Instagram post for EcoDisplays based on this photo."
    else:
        user_text = (
            f"Topic: {topic}\n\n"
            "Write an Instagram post for EcoDisplays. "
            "The post accompanies a video showing this topic. "
            "Focus on the topic and EcoDisplays product benefits."
        )

    messages = [{"role": "user", "content": []}]

    if media_type == "photo" and media_url:
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {"url": media_url, "detail": "low"},
        })

    messages[0]["content"].append({"type": "text", "text": user_text})

    full_messages = [{"role": "system", "content": system}] + messages

    # Пробуем OpenRouter (claude / gemini) — основной
    if OPENROUTER_KEY:
        for model in ["anthropic/claude-haiku-4-5", "google/gemini-flash-1.5"]:
            try:
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                    json={"model": model, "messages": full_messages, "max_tokens": 600, "temperature": 0.8},
                    timeout=30,
                )
                if r.ok:
                    return r.json()["choices"][0]["message"]["content"].strip()
                log.warning(f"OpenRouter {model}: {r.status_code}")
            except Exception as e:
                log.warning(f"OpenRouter {model} exception: {e}")

    # Fallback: OpenAI
    if OPENAI_KEY:
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-4o", "messages": full_messages, "max_tokens": 600, "temperature": 0.8},
                timeout=30,
            )
            if r.ok:
                return r.json()["choices"][0]["message"]["content"].strip()
            log.error(f"OpenAI error: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.error(f"OpenAI exception: {e}")

    return _fallback_caption(topic)


def _fallback_caption(topic: str) -> str:
    return (
        f"🌿 Outdoor displays that run on sunlight — not your power bill.\n\n"
        f"EcoDisplays e-ink screens are perfectly readable in direct sun and use 10-20x less energy than "
        f"LCD. IP65, solar-powered, built for waterfronts, smart-city projects and public transport from "
        f"Dubai to the Mediterranean.\n"
        f"See more at www.ecodisplays.rs 👇\n\n"
        f"EcoDisplays — pametni e-ink displeji za održive gradove.\n\n"
        f"#EcoDisplays #eink #smartcity #sustainability #dubai #uae #mediterranean #Srbija"
    )


# ─────────────────────────── TG file download ───────────────────

def get_file_url(file_id: str) -> str:
    r = requests.get(f"{TG}/getFile", params={"file_id": file_id}, timeout=10)
    if r.ok and r.json().get("ok"):
        path = r.json()["result"]["file_path"]
        return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    return ""


# ─────────────────────────── daily prompt ───────────────────────

def send_daily_prompt():
    state = load_state()
    idx = state.get("topic_index", 0) % len(DAILY_TOPICS)
    topic = DAILY_TOPICS[idx]
    state["topic_index"] = idx + 1
    state["pending"] = {"topic": topic["theme"], "waiting_media": True}
    save_state(state)

    text = (
        f"🎬 *Sadržaj za danas* — {datetime.now().strftime('%d.%m.%Y')}\n"
        f"_Content for today_\n\n"
        f"Tema / Topic: *{topic['theme']}*\n\n"
        f"Prompt za Runway / Veo / Kling:\n"
        f"```\n{topic['prompt']}\n```\n\n"
        f"Generiši video i pošalji ovde — napraviću caption i poslati na odobrenje.\n"
        f"_Generate the video and send it here — I'll write the caption and send for approval._"
    )
    tg_post("sendMessage", chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    log.info(f"Daily prompt sent: {topic}")


# ─────────────────────────── send for approval ──────────────────

def send_for_approval(state: dict, file_id: str, caption: str, media_type: str):
    """Отправляет медиа обратно с caption и кнопками одобрения."""
    approval_data = {
        "file_id": file_id,
        "caption": caption,
        "media_type": media_type,
        "topic": (state.get("pending") or {}).get("topic", ""),
        "ts": int(time.time()),
    }
    state["pending"] = {"approval": approval_data, "waiting_media": False}
    save_state(state)

    markup = json.dumps({
        "inline_keyboard": [[
            {"text": "✅ Опубликовать", "callback_data": "pub:approve"},
            {"text": "✏️ Переписать", "callback_data": "pub:regen"},
            {"text": "❌ Отмена", "callback_data": "pub:cancel"},
        ]]
    })

    if media_type == "photo":
        tg_post("sendPhoto",
                chat_id=CHAT_ID,
                photo=file_id,
                caption=f"📝 *Предпросмотр поста:*\n\n{caption}",
                parse_mode="Markdown",
                reply_markup=markup)
    else:
        tg_post("sendVideo",
                chat_id=CHAT_ID,
                video=file_id,
                caption=f"📝 *Предпросмотр поста:*\n\n{caption}",
                parse_mode="Markdown",
                reply_markup=markup)

    log.info(f"Approval sent for {media_type}")


# ─────────────────────────── publish ────────────────────────────

def publish_to_make(approval: dict) -> bool:
    file_id = approval["file_id"]
    caption = approval["caption"]
    media_type = approval["media_type"]

    video_url = get_file_url(file_id)
    if not video_url:
        log.error("Failed to get file URL from Telegram")
        return False

    payload = {
        "type": "reel" if media_type == "video" else "photo",
        "video_url": video_url if media_type == "video" else None,
        "image_url": video_url if media_type == "photo" else None,
        "caption": caption,
        "package": f"manual_{int(time.time())}",
    }
    # убираем None
    payload = {k: v for k, v in payload.items() if v is not None}

    r = requests.post(MAKE_WEBHOOK, json=payload, timeout=15)
    log.info(f"Make response: {r.status_code} {r.text[:100]}")
    return r.ok


# ─────────────────────────── callback handler ───────────────────

def handle_callback(cb: dict):
    query_id = cb["id"]
    data = cb.get("data", "")
    msg = cb["message"]
    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]

    # Всегда отвечаем на callback
    requests.post(f"{TG}/answerCallbackQuery", json={"callback_query_id": query_id}, timeout=5)

    if not data.startswith("pub:"):
        return

    action = data.split(":")[1]
    state = load_state()
    approval = (state.get("pending") or {}).get("approval")

    if not approval:
        tg_post("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id, reply_markup=json.dumps({"inline_keyboard": []}))
        tg_post("sendMessage", chat_id=chat_id, text="⚠️ Нет активного поста для публикации.")
        return

    if action == "approve":
        tg_post("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                reply_markup=json.dumps({"inline_keyboard": [[{"text": "⏳ Публикуется...", "callback_data": "noop"}]]}))

        def do_publish():
            ok = publish_to_make(approval)
            if ok:
                tg_post("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                        reply_markup=json.dumps({"inline_keyboard": [[{"text": "✅ Опубликовано в Instagram!", "callback_data": "noop"}]]}))
                state["pending"] = None
                save_state(state)
                log.info("Published to Instagram via Make")
            else:
                tg_post("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                        reply_markup=json.dumps({"inline_keyboard": [[{"text": "❌ Ошибка Make — попробуй снова", "callback_data": "pub:approve"}]]}))

        threading.Thread(target=do_publish, daemon=True).start()

    elif action == "regen":
        tg_post("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                reply_markup=json.dumps({"inline_keyboard": [[{"text": "⏳ Генерирую новый текст...", "callback_data": "noop"}]]}))

        def do_regen():
            try:
                topic = approval.get("topic", "EcoDisplays e-ink дисплей")
                file_id = approval["file_id"]
                media_type = approval["media_type"]
                media_url = get_file_url(file_id) if media_type == "photo" else ""
                new_caption = generate_caption(media_url, media_type, topic)
                approval["caption"] = new_caption
                state["pending"]["approval"] = approval
                save_state(state)

                markup = json.dumps({
                    "inline_keyboard": [[
                        {"text": "✅ Опубликовать", "callback_data": "pub:approve"},
                        {"text": "✏️ Переписать", "callback_data": "pub:regen"},
                        {"text": "❌ Отмена", "callback_data": "pub:cancel"},
                    ]]
                })
                resp = tg_post("editMessageCaption", chat_id=chat_id, message_id=msg_id,
                        caption=f"📝 *Предпросмотр поста (новый вариант):*\n\n{new_caption}",
                        parse_mode="Markdown",
                        reply_markup=markup)
                if not resp.get("ok"):
                    log.error(f"editMessageCaption failed: {resp}")
                    # Попробуем без Markdown
                    tg_post("editMessageCaption", chat_id=chat_id, message_id=msg_id,
                            caption=f"📝 Предпросмотр поста (новый вариант):\n\n{new_caption}",
                            reply_markup=markup)
            except Exception as e:
                log.error(f"do_regen error: {e}", exc_info=True)
                tg_post("sendMessage", chat_id=chat_id,
                        text=f"❌ Greška pri prepisivanju: {e}")

        threading.Thread(target=do_regen, daemon=True).start()

    elif action == "cancel":
        state["pending"] = None
        save_state(state)
        tg_post("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                reply_markup=json.dumps({"inline_keyboard": [[{"text": "❌ Отменено", "callback_data": "noop"}]]}))
        tg_post("sendMessage", chat_id=chat_id, text="Пост отменён. Пришли новое медиа или подожди завтрашнего промпта.")


# ─────────────────────────── message handler ────────────────────

def handle_message(msg: dict):
    chat_id = msg["chat"]["id"]
    if chat_id != CHAT_ID:
        return

    text = msg.get("text", "")
    state = load_state()

    # Команды
    if text == "/prompt":
        send_daily_prompt()
        return

    if text == "/status":
        pending = state.get("pending")
        if not pending:
            tg_post("sendMessage", chat_id=chat_id,
                    text="Nema aktivnih zadataka. Čekam video.\n_No active tasks. Waiting for video._",
                    parse_mode="Markdown")
        elif pending.get("waiting_media"):
            tg_post("sendMessage", chat_id=chat_id,
                    text=f"⏳ Čekam video na temu:\n_{pending.get('topic', '?')}_",
                    parse_mode="Markdown")
        elif pending.get("approval"):
            tg_post("sendMessage", chat_id=chat_id,
                    text="📋 Post čeka odobrenje — pogledaj gore.\n_Post pending approval — check above._")
        return

    if text == "/help":
        tg_post("sendMessage", chat_id=chat_id, text=(
            "📱 *EcoDisplays Media Bot*\n\n"
            "Svaki dan u 9:00 šaljem prompt za generisanje videa.\n"
            "Generiši u Runway / Veo / Kling i pošalji ovde — napraviću caption i poslati na odobrenje.\n\n"
            "_Every day at 9:00 I send a video generation prompt._\n"
            "_Generate in Runway / Veo / Kling and send here — I'll write caption and send for approval._\n\n"
            "Komande / Commands:\n"
            "/prompt — prompt za danas / today's prompt\n"
            "/status — trenutno stanje / current status\n"
            "/help — ova pomoć / this help"
        ), parse_mode="Markdown")
        return

    # Получено фото
    if "photo" in msg:
        photos = msg["photo"]
        best = max(photos, key=lambda p: p.get("file_size", 0))
        file_id = best["file_id"]
        _process_media(state, chat_id, file_id, "photo")
        return

    # Получено видео
    if "video" in msg:
        file_id = msg["video"]["file_id"]
        _process_media(state, chat_id, file_id, "video")
        return

    # Получен document (видео как файл)
    if "document" in msg:
        doc = msg["document"]
        if doc.get("mime_type", "").startswith("video"):
            _process_media(state, chat_id, doc["file_id"], "video")
        return


def _process_media(state: dict, chat_id: int, file_id: str, media_type: str):
    """Скачивает медиа, генерирует caption, отправляет на одобрение."""
    topic = (state.get("pending") or {}).get("topic", "EcoDisplays e-ink displej u gradskom okruženju")

    tg_post("sendMessage", chat_id=chat_id,
            text="⏳ Generišem post... / Generating post...")

    def do_generate():
        try:
            media_url = get_file_url(file_id) if media_type == "photo" else ""
            caption = generate_caption(media_url, media_type, topic)
            send_for_approval(state, file_id, caption, media_type)
        except Exception as e:
            log.error(f"generate error: {e}")
            tg_post("sendMessage", chat_id=chat_id, text=f"❌ Greška pri generisanju / Generation error: {e}")

    threading.Thread(target=do_generate, daemon=True).start()


# ─────────────────────────── polling loop ───────────────────────

def run_polling():
    log.info("Media bot polling started")
    offset = 0
    while True:
        try:
            r = requests.get(f"{TG}/getUpdates",
                             params={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]},
                             timeout=40)
            if not r.ok:
                time.sleep(5)
                continue
            updates = r.json().get("result", [])
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    if "callback_query" in u:
                        handle_callback(u["callback_query"])
                    elif "message" in u:
                        handle_message(u["message"])
                except Exception as e:
                    log.error(f"Update error: {e}")
        except requests.Timeout:
            pass
        except Exception as e:
            log.error(f"Polling error: {e}")
            time.sleep(10)


# ─────────────────────────── cron setup ─────────────────────────

def setup_cron():
    cron_line = f"0 9 * * * cd /root/Ecodisplays && python3 media_bot.py --daily-prompt >> /root/Ecodisplays/media_bot.log 2>&1"
    import subprocess
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    if "media_bot.py --daily-prompt" in existing:
        print("Cron уже настроен.")
        return

    new_cron = existing.rstrip() + "\n" + cron_line + "\n"
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
    proc.communicate(new_cron)
    print(f"Cron добавлен: {cron_line}")


# ─────────────────────────── main ───────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-prompt", action="store_true", help="Отправить дневной промпт")
    parser.add_argument("--setup-cron", action="store_true", help="Добавить cron задачу")
    args = parser.parse_args()

    if args.daily_prompt:
        send_daily_prompt()
    elif args.setup_cron:
        setup_cron()
    else:
        run_polling()
