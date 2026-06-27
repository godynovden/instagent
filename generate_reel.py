"""
Генерирует один Instagram Reel для Ecodisplays.

Режимы:
  1. Veo mode:  берёт фото из /content, генерирует видео через Veo 2 API
  2. Video mode: берёт готовое видео из /content, добавляет субтитры через ffmpeg
  3. Photo mode: берёт фото, делает слайд-шоу (fallback)

Запуск:
  python3 generate_reel.py --mode veo --source content/1.jpg
  python3 generate_reel.py --mode video --source "content/FILE 2025-09-15 17:20:50.mp4"
  python3 generate_reel.py --mode photo --source content/1.jpg
"""

import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
FAL_KEY = os.getenv("FAL_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")
LUMA_API_KEY = os.getenv("LUMA_API_KEY")
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

# Бесплатные модели OpenRouter (в порядке приоритета)
OPENROUTER_TEXT_MODELS = [
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
]
OPENROUTER_VISION_MODELS = [
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-4-31b-it:free",
]
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", "/root/Ecodisplays/content"))
SERVICE_HEALTH_FILE = OUTPUT_DIR / "service_health.json"

OUTPUT_DIR.mkdir(exist_ok=True)


# ─── service health cache ─────────────────────────────────────────────────────

def _load_service_health() -> dict:
    if SERVICE_HEALTH_FILE.exists():
        try:
            return json.loads(SERVICE_HEALTH_FILE.read_text())
        except Exception:
            pass
    return {}


def _mark_service_down(name: str, reason: str, ttl: int = 86400):
    """Помечает сервис как недоступный на ttl секунд (по умолчанию 24ч)."""
    health = _load_service_health()
    health[name] = {"down_until": time.time() + ttl, "reason": reason}
    SERVICE_HEALTH_FILE.write_text(json.dumps(health, indent=2))
    hours = ttl // 3600
    mins = (ttl % 3600) // 60
    label = f"{hours}ч" if hours else f"{mins}мин"
    print(f"  ⚠️  {name} помечен как недоступный на {label} ({reason})")


def _is_service_down(name: str) -> bool:
    health = _load_service_health()
    entry = health.get(name)
    if not entry:
        return False
    if time.time() < entry.get("down_until", 0):
        print(f"  ⏭  {name} пропущен (недоступен до {time.strftime('%H:%M', time.localtime(entry['down_until']))}): {entry.get('reason','?')}")
        return True
    return False


def _mark_service_up(name: str):
    """Снимает пометку недоступности при успехе."""
    health = _load_service_health()
    if name in health:
        del health[name]
        SERVICE_HEALTH_FILE.write_text(json.dumps(health, indent=2))

# Контекст бренда Ecodisplays для GPT
BRAND_CONTEXT = """
EcoDisplays (capital E, capital D) — company selling e-ink displays for urban infrastructure:
bus stops, parks, embankments, tourist trails, municipal facilities.

PRODUCT LINE:
- Outdoor 32" Color (RGB RGBW): 760x460x32mm, 8kg — COLOR available
- Outdoor 32" Greyscale: 760x460x32mm, 8kg — greyscale only
- Outdoor 42" Greyscale: 750x950x32mm, 11kg — greyscale ONLY, NO color
- Indoor 32" Color/Greyscale: same dimensions as outdoor, VESA mount
- Indoor 42" Greyscale: same dimensions as outdoor, Embedded VESA
- Video Wall: up to 8m², 4K, greyscale

KEY FACTS (use exact numbers):
- 111x less energy than conventional displays
- Up to 10 years warranty, no screen burn-in
- Solar-powered 20–250W polycrystalline panels
- IP65 rated, tempered glass, aluminum case, 32mm thin
- Installation 3x faster — as fast as 1 minute (thin magnet mounting)
- Saves up to 65% of client's operating costs
- Sun rays enhance image — 180° viewing angle, readable 24/7
- Cloud CMS, full API integration, WiFi/Mobile/Ethernet

Target Instagram audience (PRIMARY focus — Gulf & Southern Europe):
- Dubai / UAE / Gulf: smart-city authorities, real-estate & megaproject developers, ESG-driven
  municipalities, premium urban infrastructure buyers.
- Southern Europe / Mediterranean: coastal & resort towns, tourism boards, historic city centres,
  waterfront promenades, island municipalities.
- Also: AV integrators, urban planners, tech enthusiasts worldwide (and the existing Serbian base).

MARKET ANGLES TO LEAD WITH (hook these audiences):
- TOURISM & WATERFRONTS: seafront promenades, tourist trails, resort wayfinding, historic centres —
  clean info & navigation that fits a premium/heritage setting without ugly glowing screens.
- SMART-CITY MEGAPROJECTS: Dubai Smart City / sustainable-city vision, premium city infrastructure,
  Gulf ESG agenda — position EcoDisplays as the screen for flagship government & developer projects.
- ECONOMY & AUTONOMY: solar-powered, 111x less energy, no wiring needed — perfect for remote beaches,
  desert routes, Mediterranean islands and any off-grid or low-maintenance deployment.

Tone: professional but alive, internationally premium. Show real objects, technology, sustainability.
"""

# Instagram Curator agent (agency-agents)
INSTAGRAM_CURATOR_PROMPT = """
You are an Instagram Curator specialist — a visual storyteller who transforms brands into Instagram sensations.

Your caption writing rules:
- Apply the 1/3 rule: rotate between brand content, educational content, and community content
- Write for 3.5%+ engagement rate — open with a hook that stops the scroll
- ENGLISH is the PRIMARY caption (this is what most of the Gulf & Mediterranean audience reads):
  full, polished international English, 3-5 sentences, strong scroll-stopping hook in the first line,
  end with a question or CTA to boost comments. Native UK/US English, premium B2B tone.
- SERBIAN is the SECONDARY caption: a SHORT conversational Cyrillic version (1-2 sentences) for the
  local Serbian base — not a full duplicate, just a localized hook/summary.
- Frame the hook around the market angles when relevant: Mediterranean/Gulf waterfronts & tourism,
  smart-city megaprojects, or solar autonomy & energy savings.
- Hashtag strategy: mix 5 broad (#smartcity, #sustainability, #urbandesign), 5 mid-tier
  (#einkdisplay, #outdoorsignage, #digitalsignage), 5 niche (#ecodisplays, #solardigitalsign) — total 15-20 tags
- ALWAYS include geo/market tags for the target audience: at least 2-3 of
  #dubai #uae #smartdubai #mydubai #mediterranean #southerneurope #smartcity, PLUS one Serbian tag
  (#srbija / #beograd) to keep the local base.
- Reels-optimized: first 3 words of the ENGLISH caption must be attention-grabbing
"""

# Image Prompt Engineer — specialized for Stability AI SD3.5 photorealistic stills
# Primary goal: generate a cinematic 9:16 photo that LOOKS like a real photo of an e-ink display
IMAGE_PROMPT_ENGINEER = """
You are a cinematic storyboard artist and Stability AI SD3.5 prompt engineer.
You create STORY MOMENTS — single cinematic frames that tell a narrative, like a movie still.
The EcoDisplays e-ink display is a PROP in the story, not the hero.

STORYTELLING APPROACH:
- Every image must have a CHARACTER with an EMOTION and a SITUATION
- The story should be immediately readable in one glance — like a great comic panel
- The e-ink display appears naturally in the scene as part of the world
- Viewer should feel something: surprise, recognition, humor, relief, curiosity

STORY ARCHETYPES TO USE:
1. THE PROBLEM MOMENT: character facing a frustrating situation that the display solves
   (e.g. confused tourist, sweating city worker staring at broken LCD, bus missed)
2. THE DISCOVERY: character seeing/reading the e-ink display for the first time, reaction of surprise
3. THE CONTRAST: two situations side by side in one frame (chaos vs. calm, old vs. new)
4. THE EVERYDAY MAGIC: mundane urban moment made special by the display being there
5. THE SOCIAL PROOF: multiple people gathered around or benefiting from the display

PREFERRED LOCATIONS (lead with Gulf & Mediterranean settings to hook those markets):
- Dubai / Gulf: sleek modern waterfront, palm-lined boulevard, desert highway rest stop,
  premium smart-city plaza, bright desert sun (e-ink stays perfectly readable in harsh light).
- Southern Europe / Mediterranean: seaside promenade, old-town cobbled square, marina,
  coastal tourist trail, sun-drenched piazza, resort beachfront.
- Keep the existing Belgrade/Serbian park & street scenes in rotation too.

E-INK DISPLAY VISUAL RULES (always apply):
- Screen is MATTE, paper-like, ZERO glow, ZERO reflection — looks like a newspaper board
- Thin flat aluminum frame, 32mm, matte grey, mounted on slim pole or wall
- Screen shows simple bold black/white graphics — maps, large numbers, icons
- In direct sunlight: screen is MORE readable, not washed out (this is the magic moment to show)

PROMPT FORMAT:
"Cinematic movie still, [camera], [f-stop]. [CHARACTER description and emotion]. [SCENE/LOCATION].
[The e-ink display in scene: position, what's on screen]. [LIGHTING — specific].
[MOOD/ATMOSPHERE]. Photorealistic, NOT CGI, NOT render. 9:16 vertical."

CRITICAL DON'TS:
- NO product photography angles (no centered display on clean background)
- NO "LCD screen", "glowing screen", "digital billboard", "LED"
- NO faces shown clearly — side/back view keeps it universal and cinematic
- NO text readable on screen in the image
"""


def _patch_video_prompt(data: dict) -> dict:
    """Добавляет запрет текста на экране — AI-генераторы галлюцинируют названия компаний."""
    vp = data.get("video_prompt", "")
    if vp and VIDEO_PROMPT_NO_TEXT.strip() not in vp:
        # Убираем упоминания текста/расписаний/вывесок из промпта
        import re
        vp = re.sub(r'showing\s+(a\s+)?(clear\s+)?(static\s+)?[\w\s]+schedule', 'showing abstract content', vp, flags=re.IGNORECASE)
        vp = re.sub(r'displaying\s+[\w\s]+(information|text|content|schedule|menu)', 'displaying abstract visual patterns', vp, flags=re.IGNORECASE)
        data["video_prompt"] = vp + VIDEO_PROMPT_NO_TEXT
    return data


def _fix_brand_name(text: str) -> str:
    """Исправляет все варианты написания бренда на 'EcoDisplays'."""
    import re
    # Все варианты латиницей → EcoDisplays
    pattern = r'\b[Ee][Cc Kk][Oo][- ]?[Dd][Ii][Ss][Pp][Ll][AaEeEеЕе][Yy Јј][Ss]?\b'
    text = re.sub(pattern, 'EcoDisplays', text)
    # Кириллические варианты → EcoDisplays
    cyrillic_pattern = r'\b[ЕeEЕе][кКkK][оОoO][- ]?[дДdD][иИiI][сСsS][пПpP][лЛlL][еЕeE][јЈjJ][иИ]?\b'
    text = re.sub(cyrillic_pattern, 'EcoDisplays', text)
    return text


def _fix_brand_in_caption(data: dict) -> dict:
    """Применяет исправление бренда ко всем текстовым полям caption."""
    for field in ("caption_sr", "caption_en"):
        if field in data:
            fixed = _fix_brand_name(data[field])
            if fixed != data[field]:
                print(f"  🔤 Исправлено название бренда в {field}")
            data[field] = fixed
    return data


def _validate_caption(data: dict) -> bool:
    """Проверяет что caption на правильных языках и не мусор."""
    sr = data.get("caption_sr", "")
    en = data.get("caption_en", "")

    # EN не должен содержать кириллицу
    cyrillic_in_en = sum(1 for c in en if 'Ѐ' <= c <= 'ӿ')
    if cyrillic_in_en > 5:
        return False

    # SR должен содержать кириллицу
    cyrillic_in_sr = sum(1 for c in sr if 'Ѐ' <= c <= 'ӿ')
    if cyrillic_in_sr < 10:
        return False

    # SR не должен содержать латиницу больше 40% (смесь языков — мусор)
    latin_in_sr = sum(1 for c in sr if c.isalpha() and c.isascii())
    total_alpha = sum(1 for c in sr if c.isalpha())
    if total_alpha > 0 and latin_in_sr / total_alpha > 0.4:
        return False

    # EN теперь основной — должен быть содержательным; SR вторичный, может быть коротким
    if len(en) < 60 or len(sr) < 15:
        return False

    return True


def _call_openrouter(messages: list, models: list, max_tokens: int = 1200) -> str:
    """Вызывает OpenRouter с авто-fallback по моделям."""
    import requests as req
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ecodisplays.com",
        "X-Title": "Ecodisplays Content Farm",
    }
    for model in models:
        try:
            r = req.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "max_tokens": max_tokens},
                timeout=45,
            )
            if r.ok:
                data = r.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if not content:
                    print(f"  {model} вернул пустой ответ, пробую следующую...")
                    continue
                return content
            if r.status_code in (429, 503):
                print(f"  {model} rate-limited/unavailable, пробую следующую...")
                time.sleep(3)
                continue
            print(f"  {model} ошибка {r.status_code}, пробую следующую...")
        except Exception as e:
            print(f"  {model} исключение: {e}, пробую следующую...")
    raise RuntimeError("Все OpenRouter модели недоступны")


def _parse_json_response(text: str) -> dict:
    """Надёжный парсинг JSON из ответа LLM."""
    text = text.strip()
    # Убираем markdown блоки
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except Exception:
                continue
    # Ищем JSON объект в тексте
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    return json.loads(text)


# Runway/Kling/Veo галлюцинируют текст на экранах — всегда добавляем запрет
VIDEO_PROMPT_NO_TEXT = (
    " No readable text, no words, no letters, no brand names, no signage text on any screen or surface. "
    "E-ink displays show only abstract geometric patterns or blurred content."
)

CONTENT_TYPE_TEMPLATES = {
    "product_shot": {
        "sr_tone": "Опиши детаље производа, квалитет материјала и дизајн. Тон: стручан, поносан.",
        "en_hint": "1 sentence about build quality or screen clarity.",
        "hashtags_extra": ["#einkdisplay", "#industrialdesign", "#outdoortech", "#displaytech"],
        "video_hint": "Slow macro dolly push-in showing e-ink screen texture and enclosure detail",
    },
    "installation": {
        "sr_tone": "Покажи где и зашто је постављен дисплеј. Тон: кејс-студи, конкретно место и корист.",
        "en_hint": "1 sentence: where installed and what problem it solves.",
        "hashtags_extra": ["#smartcity", "#urbantech", "#municipaltech", "#outdoorsignage"],
        "video_hint": "Wide establishing shot of display installed in urban environment, people interacting",
    },
    "eco_fact": {
        "sr_tone": "Образовни пост: зашто e-ink троши мање енергије него LCD/LED. Стил: занимљива чињеница.",
        "en_hint": "1 sentence with the key sustainability stat.",
        "hashtags_extra": ["#sustainability", "#greentech", "#solarpowered", "#lowpower"],
        "video_hint": "Split-screen comparison: bright LED screen vs e-ink in sunlight, energy meter overlay",
    },
    "comparison": {
        "sr_tone": "Упореди e-ink са LCD/LED: видљивост, потрошња, трајност. Тон: аргументован, технички.",
        "en_hint": "1 sentence: the decisive advantage of e-ink.",
        "hashtags_extra": ["#einkvsled", "#displaytech", "#sunlightreadable", "#outdoorvideo"],
        "video_hint": "Side-by-side outdoor screens in bright sunlight, one clearly visible, one washed out",
    },
    "behind_scenes": {
        "sr_tone": "Покажи процес: монтажа, тим, производња. Тон: аутентичан, топао.",
        "en_hint": "1 sentence about the team or installation process.",
        "hashtags_extra": ["#behindthescenes", "#teamwork", "#installation", "#madeinserbia"],
        "video_hint": "Handheld documentary-style shot of installation crew working, warm natural light",
    },
    "urban_case": {
        "sr_tone": "Урбани кејс: дисплеј у граду, на улици, у парку. Тон: поносан, инспиративан.",
        "en_hint": "1 sentence: city and use-case.",
        "hashtags_extra": ["#smartcity", "#urbanism", "#citytech", "#publicdisplay", "#wayfinding"],
        "video_hint": "Aerial or wide shot of display in city square, pedestrians, golden hour light",
    },
}

def detect_content_type(image_path: Path | None, topic: str | None) -> str:
    """Определяет тип контента по имени файла или теме."""
    name = (image_path.stem if image_path else (topic or "")).lower()
    if any(k in name for k in ["install", "монтаж", "setup", "deploy"]):
        return "installation"
    if any(k in name for k in ["eco", "solar", "energy", "green", "sustainability"]):
        return "eco_fact"
    if any(k in name for k in ["compare", "vs", "lcd", "led"]):
        return "comparison"
    if any(k in name for k in ["team", "behind", "build", "factory", "production"]):
        return "behind_scenes"
    if any(k in name for k in ["city", "urban", "park", "street", "plaza", "square"]):
        return "urban_case"
    # Чередуем типы на основе хэша имени файла для разнообразия
    types = ["product_shot", "installation", "eco_fact", "urban_case", "comparison", "behind_scenes"]
    idx = hash(name) % len(types)
    return types[idx]


def _load_context_db() -> dict:
    """Загружает базу знаний проектов и фактов."""
    db_path = Path("/root/Ecodisplays/context_db.json")
    if db_path.exists():
        with open(db_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ─── prompt overrides (self-improving loop) ──────────────────────────────────

PROMPT_OVERRIDES_FILE = OUTPUT_DIR / "prompt_overrides.json"
PROMPT_OVERRIDES_MAX_HISTORY = 5


def _load_prompt_overrides() -> dict:
    """Загружает переопределения промптов из prompt_overrides.json."""
    if PROMPT_OVERRIDES_FILE.exists():
        try:
            return json.loads(PROMPT_OVERRIDES_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_prompt_overrides(overrides: dict):
    PROMPT_OVERRIDES_FILE.write_text(json.dumps(overrides, ensure_ascii=False, indent=2))


def get_effective_template(content_type: str) -> dict:
    """Возвращает шаблон для content_type с учётом overrides."""
    base = dict(CONTENT_TYPE_TEMPLATES.get(content_type, CONTENT_TYPE_TEMPLATES["eco_fact"]))
    overrides = _load_prompt_overrides()
    ct_override = overrides.get(content_type, {}).get("current", {})
    base.update({k: v for k, v in ct_override.items() if v})
    return base


def apply_rejection_to_prompts(content_type: str, skip_reason: str) -> bool:
    """После rejection — LLM переписывает sr_tone/en_hint/video_hint для этого типа.

    Сохраняет историю (до 5 версий). Использует Gemini или OpenRouter.
    Возвращает True если промпты обновлены.
    """
    if not skip_reason or skip_reason.strip() == "none":
        return False

    base = CONTENT_TYPE_TEMPLATES.get(content_type, {})
    overrides = _load_prompt_overrides()
    current = overrides.get(content_type, {}).get("current", {})

    # Текущие значения (с учётом предыдущих overrides)
    current_sr_tone = current.get("sr_tone") or base.get("sr_tone", "")
    current_en_hint = current.get("en_hint") or base.get("en_hint", "")
    current_video_hint = current.get("video_hint") or base.get("video_hint", "")

    rewrite_prompt = f"""You are a prompt engineer for an Instagram content agent for EcoDisplays (e-ink outdoor displays, Serbia).

A post of type "{content_type}" was rejected with this reason: "{skip_reason}"

Current prompts for this content type:
- sr_tone (Serbian caption guidance): {current_sr_tone}
- en_hint (English caption guidance): {current_en_hint}
- video_hint (image/scene description): {current_video_hint}

Your task: rewrite these prompts to PREVENT the rejection reason from happening again.

Rules:
- Keep changes minimal and targeted — only fix what caused the rejection
- sr_tone must guide Serbian B2B caption writing
- en_hint must guide English subtitle writing
- video_hint must guide atmospheric scene generation (no product rendering)
- If the rejection is about photo quality — update video_hint
- If the rejection is about text/language — update sr_tone or en_hint
- If the rejection is about wrong content type — update all three

Respond ONLY with valid JSON:
{{"sr_tone": "...", "en_hint": "...", "video_hint": "...", "change_summary": "one line what changed and why"}}"""

    result = None

    # Пробуем Gemini
    if GOOGLE_API_KEY:
        try:
            from google import genai
            from google.genai import types as gtypes
            client = genai.Client(api_key=GOOGLE_API_KEY)
            for model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]:
                if _is_service_down(f"gemini_{model}"):
                    continue
                try:
                    resp = client.models.generate_content(
                        model=model,
                        contents=[gtypes.Part.from_text(text=rewrite_prompt)],
                        config=gtypes.GenerateContentConfig(
                            response_mime_type="application/json",
                            max_output_tokens=512,
                        )
                    )
                    result = _parse_json_response(resp.text)
                    break
                except Exception as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        _mark_service_down(f"gemini_{model}", "429")
        except Exception:
            pass

    # Fallback на OpenRouter
    if not result and OPENROUTER_API_KEY:
        try:
            text = _call_openrouter(
                [{"role": "user", "content": rewrite_prompt}],
                OPENROUTER_TEXT_MODELS
            )
            result = _parse_json_response(text)
        except Exception:
            pass

    if not result or not result.get("sr_tone"):
        print(f"  ⚠️  Self-improve: не удалось переписать промпты для {content_type}")
        return False

    change_summary = result.get("change_summary", "updated")
    new_entry = {
        "sr_tone": result["sr_tone"],
        "en_hint": result["en_hint"],
        "video_hint": result["video_hint"],
        "reason": skip_reason,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "change_summary": change_summary,
    }

    # Сохраняем с историей
    if content_type not in overrides:
        overrides[content_type] = {"current": {}, "history": []}
    if overrides[content_type].get("current"):
        hist = overrides[content_type].setdefault("history", [])
        hist.append(overrides[content_type]["current"])
        overrides[content_type]["history"] = hist[-PROMPT_OVERRIDES_MAX_HISTORY:]
    overrides[content_type]["current"] = new_entry
    _save_prompt_overrides(overrides)

    print(f"  🧠 Self-improve [{content_type}]: {change_summary}")
    return True


def reset_prompt_overrides(content_type: str | None = None):
    """Сбрасывает overrides к дефолтам. content_type=None сбрасывает все."""
    if content_type:
        overrides = _load_prompt_overrides()
        overrides.pop(content_type, None)
        _save_prompt_overrides(overrides)
        print(f"  🔄 Промпты {content_type} сброшены к дефолтам")
    else:
        PROMPT_OVERRIDES_FILE.unlink(missing_ok=True)
        print(f"  🔄 Все промпты сброшены к дефолтам")


def _build_context_snippet(ct: str, context_db: dict, project_override: str | None = None) -> str:
    """Выбирает релевантные факты из context_db для текущего типа поста."""
    if not context_db:
        return ""

    lines = ["REAL PROJECT DATA (use specific facts, names, numbers from here):"]

    projects = context_db.get("projects", {})
    brand = context_db.get("brand_facts", {})
    contrast = context_db.get("competitors_contrast", {})

    # Для кейс-постов — подставляем реальный проект (active или tender_active)
    if ct in ("installation", "urban_case", "behind_scenes"):
        relevant = {k: v for k, v in projects.items()
                    if v.get("status") in ("active", "tender_active")}
        # project_override задан calendar agent — используем его; иначе ротация по хэшу
        if project_override and project_override in projects:
            p = projects[project_override]
        else:
            import hashlib
            import datetime
            day_hash = int(hashlib.md5(datetime.date.today().isoformat().encode()).hexdigest(), 16)
            proj_list = sorted(relevant.values(), key=lambda x: x.get("name", ""))
            p = proj_list[day_hash % len(proj_list)] if proj_list else None
        if p:
            lines.append(f"PROJECT: {p.get('name')} ({p.get('location')})")
            lines.append(f"DISPLAYS: {p.get('displays')} units, {p.get('type')}, power: {p.get('power')}")
            if p.get("park_context"):
                lines.append(f"CONTEXT: {p.get('park_context')}")
            if p.get("rollout"):
                lines.append(f"ROLLOUT: {p.get('rollout')}")
            if p.get("display_note"):
                lines.append(f"DISPLAY FEATURE: {p.get('display_note')}")
            for fact in p.get("key_facts_sr", [])[:3]:
                lines.append(f"FACT (SR): {fact}")
            for fact in p.get("key_facts_en", [])[:3]:
                lines.append(f"FACT (EN): {fact}")
            lines.append(f"HASHTAGS: {' '.join(p.get('instagram_hashtags', []))}")

    # Для eco/comparison — конкретные цифры
    if ct in ("eco_fact", "comparison"):
        lines.append(f"ENERGY: {brand.get('energy')} / {brand.get('energy_en')}")
        lines.append(f"SUNLIGHT: {brand.get('sunlight')} / {brand.get('sunlight_en')}")
        if ct == "comparison":
            lines.append(f"VS LCD: {contrast.get('lcd_sunlight_en')}")
            lines.append(f"VS LED: {contrast.get('led_power_en')}")

    # Для product_shot — технические характеристики
    if ct == "product_shot":
        lines.append(f"IP65: {brand.get('ip65_en')}")
        lines.append(f"SOLAR: {brand.get('solar_en')}")
        lines.append(f"LIFESPAN: {brand.get('lifespan_en')}")
        lines.append(f"CERTS: {brand.get('certs')}")

    return "\n".join(lines)


def _load_recent_skip_reasons(n: int = 8) -> list[str]:
    """Возвращает последние N причин отклонений из quality_feedback.json."""
    feedback_path = OUTPUT_DIR / "quality_feedback.json"
    if not feedback_path.exists():
        return []
    try:
        data = json.loads(feedback_path.read_text())
        # Формат: {"decisions": [...], "batches": [...], ...}
        if isinstance(data, dict):
            entries = data.get("decisions", [])
        else:
            entries = data
        reasons = [
            e.get("skip_reason", "")
            for e in entries[-40:]
            if e.get("decision") == "skipped" and e.get("skip_reason")
        ]
        return reasons[-n:]
    except Exception:
        return []


"""Промпты сцен для Pollinations.

Устройство EcoDisplays НЕ рисуем — Pollinations не знает как оно выглядит и галлюцинирует.
Вместо этого: красивая атмосферная сцена (город, природа, архитектура) + сильный баннер снизу.
Фон задаёт настроение, весь брендинг и информация — в тексте оверлея.
"""
SCENE_PROMPTS = {
    "eco_fact": (
        "sunny urban park in Belgrade, trees and benches, golden hour light, "
        "warm sunlight through leaves, photorealistic, no people, wide angle, "
        "clean composition, no text, no logos, no signs"
    ),
    "comparison": (
        "bright European city street, modern architecture, direct midday sunlight, "
        "Belgrade urban plaza, warm tones, photorealistic, "
        "clean composition, no text, no logos, no signs"
    ),
    "urban_case": (
        "modern tram stop in Belgrade, city street, daytime, clean urban environment, "
        "people walking in background (blurred), photorealistic, "
        "no text, no logos, no signs on buildings"
    ),
    "installation": (
        "outdoor urban environment, Belgrade street corner, sunny day, "
        "pole and sidewalk, clean urban infrastructure, photorealistic, "
        "no text, no logos"
    ),
    "behind_scenes": (
        "outdoor urban setting, construction workers in safety vests, "
        "Belgrade city background, warm daylight, photorealistic, "
        "no text, no logos"
    ),
    "product_shot": (
        "clean minimalist urban background, Belgrade architecture, soft natural light, "
        "photorealistic, no text, no logos, no signs, wide angle"
    ),
}


def _build_product_photo_prompt(content_type: str, context_snippet: str, video_prompt: str) -> str:
    """Возвращает промпт атмосферной сцены для Pollinations.

    Не рисуем устройство — генерируем фон. Брендинг идёт в overlay.
    """
    base = SCENE_PROMPTS.get(content_type, SCENE_PROMPTS["product_shot"])
    prompt = (
        f"{base}. "
        "4:5 portrait format 1080x1350px. "
        "No watermarks, no artifacts, no distortion, sharp focus."
    )
    return prompt


def generate_caption(image_path: Path | None = None, topic: str | None = None,
                     content_type: str | None = None, content_type_hint: str | None = None,
                     project_hint: str | None = None, avoid_caption: str | None = None) -> dict:
    """Генерирует подпись через OpenRouter (бесплатно) или Gemini (fallback).

    avoid_caption — если передан предыдущий вариант подписи, модель обязана
    написать заметно другой текст (используется кнопкой перегенерации).
    """

    ct = content_type or content_type_hint or detect_content_type(image_path, topic)
    tmpl = get_effective_template(ct)
    extra_tags = " ".join(tmpl["hashtags_extra"])

    context_db = _load_context_db()
    context_snippet = _build_context_snippet(ct, context_db, project_override=project_hint)

    example_tags = ["#ecodisplays", "#eink"] + tmpl["hashtags_extra"] + ["#dubai", "#uae", "#smartdubai", "#mediterranean", "#smartcity", "#sustainability", "#srbija"]

    # Feedback loop: инжектируем последние причины отклонений
    skip_reasons = _load_recent_skip_reasons(8)
    feedback_block = ""
    if skip_reasons:
        reasons_list = "\n".join(f"- {r}" for r in skip_reasons)
        feedback_block = f"""
PAST REJECTION REASONS (learn from these — do NOT repeat these mistakes):
{reasons_list}
Fix these specific issues in the current generation.
"""

    # Anti-repetition: при перегенерации запрещаем повторять прошлый вариант
    variation_block = ""
    if avoid_caption:
        variation_block = f"""
REGENERATION MODE — the user asked for a DIFFERENT caption.
Previous caption (DO NOT reproduce, paraphrase, or reuse its hook/structure):
\"\"\"{avoid_caption[:600]}\"\"\"
Write a genuinely fresh caption: different opening hook, different angle, different sentence structure and CTA. It must read as a new idea, not a rewrite of the above.
"""

    system_prompt = f"""You are a dual-role AI agent combining two specializations:

ROLE 1 — INSTAGRAM CURATOR:
{INSTAGRAM_CURATOR_PROMPT}

ROLE 2 — IMAGE PROMPT ENGINEER:
{IMAGE_PROMPT_ENGINEER}

BRAND:
{BRAND_CONTEXT}

{context_snippet}

CURRENT POST:
- Content type: {ct}
- Serbian tone: {tmpl["sr_tone"]}
- English hint: {tmpl["en_hint"]}
- Video scene hint: {tmpl["video_hint"]}
{feedback_block}{variation_block}
GROUNDING RULE: If REAL PROJECT DATA is provided above, you MUST reference specific facts, project names, locations, or numbers in the caption. Generic "e-ink technology for smart cities" phrases are NOT acceptable when real data is available.

Apply BOTH roles: write captions as Instagram Curator, write video_prompt as Image Prompt Engineer.

BRAND NAME RULE — NO EXCEPTIONS:
- Always write the brand as exactly "EcoDisplays" — capital E, capital D, one word
- WRONG: Ecodisplays, ecodisplays, ECOdisplays, Eco Displays, EcoDisplay, ECODISPLAYS
- RIGHT: EcoDisplays

PRODUCT SPECS — USE CORRECT MODEL:
- 32" models (760x460x32mm, 8kg): available in COLOR (RGB) and Greyscale
- 42" models (750x950x32mm, 11kg): Greyscale ONLY — NEVER mention color for 42"
- When mentioning a specific model, use correct specs from context above

CRITICAL LANGUAGE RULES — NO EXCEPTIONS:
- caption_en is the PRIMARY caption: full polished international English, 3-5 sentences, strong hook in the first line, ends with a question or CTA. Native UK/US English ONLY. Do NOT write Russian or Serbian here. Example start: "Discover how...", "Built for...", "While the rest of the world melts in the sun...". This is the main text most readers see.
- caption_sr is SECONDARY and SHORT: 1-2 sentence Serbian Cyrillic version for the local base (a localized hook, NOT a full translation). Serbian (Српски) is NOT Russian (Русский). Write як бисте писали у Србији. Example start: "Представљамо...", "Да ли знате...", "Поносни смо..."

Respond ONLY with a valid JSON object. No markdown. No explanation:
{{
  "caption_en": "<PRIMARY caption. Strong hook first line! Real polished ENGLISH, 3-5 sentences, ends with question or CTA. Lead with a Gulf/Mediterranean/tourism/smart-city/solar angle when relevant. MUST reference real project or specific number if available. ENGLISH ONLY>",
  "caption_sr": "<SECONDARY. Short SERBIAN Cyrillic version, 1-2 sentences, localized hook — NOT a full translation>",
  "hashtags": {json.dumps(example_tags)},
  "video_prompt": "<5-layer Runway prompt: SUBJECT + ENVIRONMENT + LIGHTING + CAMERA + STYLE. 9:16 vertical, 5 seconds, photorealistic cinematic 4K>",
  "content_type": "{ct}",
  "post_title": "<3-4 word latin title with underscores>",
  "used_real_data": true/false
}}
Replace ALL angle-bracket placeholders with real generated content. Use 15-20 hashtags."""

    # --- Gemini (основной) ---
    from google import genai
    from google.genai import types as gtypes
    client = genai.Client(api_key=GOOGLE_API_KEY)
    parts = []
    if image_path and image_path.exists():
        import base64
        with open(image_path, "rb") as f:
            img_bytes = f.read()
        ext = image_path.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "image/jpeg")
        parts.append(gtypes.Part.from_bytes(data=img_bytes, mime_type=mime))
        parts.append(gtypes.Part.from_text(text=f"Create Instagram {ct} content for this Ecodisplays e-ink display image."))
    else:
        parts.append(gtypes.Part.from_text(text=f"Create Instagram {ct} content for Ecodisplays. Topic: {topic or 'e-ink display technology'}"))

    for model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]:
        if _is_service_down(f"gemini_{model}"):
            continue
        try:
            response = client.models.generate_content(
                model=model, contents=parts,
                config=gtypes.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=4096,
                    temperature=1.25 if avoid_caption else 0.95,
                )
            )
            result = _parse_json_response(response.text)
            if _validate_caption(result):
                used_real = result.get("used_real_data", False)
                tag = "📍 реальные данные" if used_real else "🎨 generic"
                print(f"  Caption сгенерирован ({model}) [{tag}], запускаю редактора...")
                result = _patch_video_prompt(result)
                return _fix_brand_in_caption(review_caption(result))
            print(f"  Gemini {model} вернул невалидный caption, пробую следующую модель...")
        except Exception as e:
            err = str(e)
            if "RESOURCE_EXHAUSTED" in err or "429" in err:
                _mark_service_down(f"gemini_{model}", "429 quota exhausted")
            else:
                print(f"  Gemini {model} ошибка: {err[:80]}, пробую следующую...")
            time.sleep(2)
            continue
    # --- OpenRouter (резервный) ---
    if OPENROUTER_API_KEY:
        try:
            user_text = f"Create Instagram Reel ({ct}) content for Ecodisplays. Topic: {topic or 'e-ink display technology for smart cities'}"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ]
            text = _call_openrouter(messages, OPENROUTER_TEXT_MODELS)
            result = _parse_json_response(text)
            if _validate_caption(result):
                used_real = result.get("used_real_data", False)
                tag = "📍 реальные данные" if used_real else "🎨 generic"
                print(f"  Caption сгенерирован (OpenRouter) [{tag}], запускаю редактора...")
                result = _patch_video_prompt(result)
                return _fix_brand_in_caption(review_caption(result))
            print("  OpenRouter вернул невалидный caption")
        except Exception as e:
            print(f"  OpenRouter ошибка: {e}")

    raise RuntimeError("Все модели вернули невалидный caption")


REVIEW_PROMPT = """You are a B2B marketing editor for EcoDisplays — a company selling e-ink outdoor displays to smart-city authorities, developers, tourism boards and municipalities, with a PRIMARY focus on the Gulf (Dubai/UAE) and Southern Europe / Mediterranean markets, plus the local Serbian base.

caption_en is the PRIMARY caption (most readers see it). caption_sr is a SHORT secondary localized version.

Review the Instagram caption below and fix it. Apply ALL rules:

BRAND NAME: Always "EcoDisplays" — capital E, capital D, one word.

PRODUCT SPECS: 32" models: color (RGB) and greyscale. 42" models: greyscale ONLY.

SERBIAN LANGUAGE — CRITICAL RULES (caption_sr):
This must be standard Serbian (Srpski), written in Cyrillic script.
Serbian is NOT Ukrainian. Serbian is NOT Russian. Do NOT mix languages.

FORBIDDEN Ukrainian words — if any appear, replace with correct Serbian:
  приказује → приказује is OK only in Serbian context; радіо → радио; підходить → одговара
  NEVER write: і (Ukrainian 'і') — use Serbian и
  NEVER write: є (Ukrainian 'є') — use Serbian је
  NEVER write: ї, ґ — these letters do not exist in Serbian
  NEVER write soft sign ь in Serbian nouns where it does not belong
  NEVER write: знали ли ви — this is Ukrainian; write: знали ли сте

CORRECT Serbian opening phrases:
  "Знали ли сте да..." (Did you know that...)
  "Да ли сте знали да..." (Did you know that...)
  "Поносни смо..." (We are proud...)
  "Представљамо..." (We present...)
  "Замислите град..." (Imagine a city...)

CORRECT Serbian examples for e-ink content:
  "е-инк дисплеј приказује садржај" ✓
  "штеди до 65% трошкова" ✓
  "читљиво 24/7 чак и на директном сунцу" ✓

ENGLISH (caption_en) — PRIMARY, polish this most:
  Native international English, hook in the first line, 3-5 sentences, end with a question or CTA, max 2 emojis.
  Lead with a Gulf / Mediterranean / tourism / smart-city / solar-autonomy angle when it fits the image.
  Premium B2B tone. English ONLY. No Serbian, no Russian.
  Good hooks: "While LED screens wash out in the desert sun, ours get sharper.",
  "Built for the Mediterranean waterfront — solar, wireless, zero glow."
  Bad: "innovative", "revolutionary", "amazing" — remove these empty words.

SERBIAN (caption_sr) — SECONDARY, keep it SHORT:
  1-2 sentence Cyrillic version for the local base, a localized hook, NOT a full translation.

STYLE: Professional B2B, no hype words, real facts/numbers when available.

If caption_sr contains ANY Ukrainian words or wrong grammar — rewrite it fully in correct Serbian.
If caption_en contains non-English words — rewrite it in English.

Respond ONLY with valid JSON:
{"caption_sr": "...", "caption_en": "...", "changed": true/false, "issues": "what was fixed or OK"}"""


def review_caption(caption_data: dict) -> dict:
    """Второй проход: бизнес-редактор проверяет и улучшает caption."""
    from google import genai
    from google.genai import types as gtypes

    review_input = json.dumps({
        "caption_sr": caption_data.get("caption_sr", ""),
        "caption_en": caption_data.get("caption_en", ""),
        "content_type": caption_data.get("content_type", ""),
    }, ensure_ascii=False)

    # Добавляем прошлые ошибки в промпт редактора
    skip_reasons = _load_recent_skip_reasons(5)
    dynamic_review_prompt = REVIEW_PROMPT
    if skip_reasons:
        reasons_list = "\n".join(f"- {r}" for r in skip_reasons)
        dynamic_review_prompt += f"\n\nPAST REJECTION REASONS — fix these if present:\n{reasons_list}"

    def _apply_result(result: dict) -> bool:
        changed = result.get("changed", False)
        issues = result.get("issues", "")
        sr = result.get("caption_sr", "")
        en = result.get("caption_en", "")
        if sr and en:
            if changed:
                print(f"  ✏️  Редактор улучшил caption: {issues}")
            else:
                print(f"  ✅ Редактор: caption OK — {issues}")
            caption_data["caption_sr"] = sr
            caption_data["caption_en"] = en
            return True
        return False

    # --- Gemini (основной) ---
    client = genai.Client(api_key=GOOGLE_API_KEY)
    gemini_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    for model in gemini_models:
        if _is_service_down(f"gemini_{model}"):
            continue
        try:
            response = client.models.generate_content(
                model=model,
                contents=[gtypes.Part.from_text(text=review_input)],
                config=gtypes.GenerateContentConfig(
                    system_instruction=dynamic_review_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=1024,
                )
            )
            result = _parse_json_response(response.text)
            if _apply_result(result):
                return caption_data
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Редактор {model} невалидный JSON: {str(e)[:60]}")
        except Exception as e:
            err = str(e)
            if "RESOURCE_EXHAUSTED" in err or "429" in err:
                _mark_service_down(f"gemini_{model}", "429 quota exhausted")
            else:
                print(f"  Редактор {model} ошибка: {err[:80]}")

    # --- OpenRouter (резервный) ---
    if OPENROUTER_API_KEY:
        try:
            messages = [
                {"role": "system", "content": dynamic_review_prompt},
                {"role": "user", "content": review_input},
            ]
            text = _call_openrouter(messages, OPENROUTER_TEXT_MODELS)
            result = _parse_json_response(text)
            if _apply_result(result):
                print(f"  (через OpenRouter)")
                return caption_data
        except Exception as e:
            print(f"  Редактор OpenRouter ошибка: {str(e)[:80]}")

    print(f"  Редактор пропущен — все модели недоступны")
    return caption_data


def generate_video_hf(prompt: str, source_image: Path | None = None) -> Path | None:
    """Генерирует видео через HuggingFace Inference API (бесплатно)."""
    if not HF_TOKEN:
        print("  HF_TOKEN не задан в .env")
        return None

    import requests as req
    import base64

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    # Пробуем image-to-video если есть исходник, иначе text-to-video
    if source_image and source_image.exists():
        print(f"  Генерирую видео через HF SVD (image-to-video): {source_image.name}")
        model_url = "https://api-inference.huggingface.co/models/stabilityai/stable-video-diffusion-img2vid-xt"

        with open(source_image, "rb") as f:
            img_bytes = f.read()

        # SVD принимает изображение напрямую как bytes
        resp = req.post(model_url, headers=headers, data=img_bytes,
                        params={"motion_bucket_id": 127, "fps": 6},
                        timeout=180)
    else:
        print(f"  Генерирую видео через HF CogVideoX (text-to-video): {prompt[:60]}...")
        model_url = "https://api-inference.huggingface.co/models/THUDM/CogVideoX-5b"
        resp = req.post(model_url, headers=headers,
                        json={"inputs": prompt, "parameters": {"num_frames": 49, "fps": 8}},
                        timeout=300)

    if resp.status_code == 503:
        # Модель грузится — ждём и повторяем
        wait_time = resp.json().get("estimated_time", 30)
        print(f"  Модель загружается, жду {int(wait_time)}с...")
        time.sleep(min(wait_time + 5, 60))
        if source_image and source_image.exists():
            with open(source_image, "rb") as f:
                resp = req.post(model_url, headers=headers, data=f.read(), timeout=180)
        else:
            resp = req.post(model_url, headers=headers,
                            json={"inputs": prompt, "parameters": {"num_frames": 49}},
                            timeout=300)

    if not resp.ok:
        print(f"  HF ошибка {resp.status_code}: {resp.text[:200]}")
        return None

    # Сохраняем результат
    content_type = resp.headers.get("content-type", "")
    ext = ".mp4" if "mp4" in content_type else ".gif" if "gif" in content_type else ".mp4"
    out_path = OUTPUT_DIR / f"hf_{int(time.time())}{ext}"
    out_path.write_bytes(resp.content)

    if out_path.stat().st_size < 1000:
        print(f"  HF вернул слишком маленький файл ({out_path.stat().st_size}B)")
        out_path.unlink()
        return None

    # Конвертируем в правильный формат для Reels если нужно
    if ext != ".mp4" or True:
        converted = OUTPUT_DIR / f"hf_conv_{int(time.time())}.mp4"
        cmd = [
            "ffmpeg", "-i", str(out_path),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-y", str(converted)
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and converted.exists():
            out_path.unlink()
            out_path = converted

    print(f"  HF видео сохранено: {out_path} ({out_path.stat().st_size // 1024}KB)")
    return out_path


def generate_video_runway(prompt: str, source_image: Path | None = None) -> Path | None:
    """Генерирует видео через Runway ML Gen-3 Alpha (125 бесплатных кредитов)."""
    if not RUNWAY_API_KEY:
        print("  RUNWAY_API_KEY не задан в .env")
        return None

    import requests as req

    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }

    # Чисто text-to-video — фото не используем
    payload = {
        "model": "gen4.5",
        "promptText": prompt[:980],
        "ratio": "720:1280",  # 9:16 вертикальное для Instagram Reels
        "duration": 5,
    }

    print(f"  Runway: отправляю text-to-video запрос gen4.5...")
    print(f"  Промпт: {prompt[:100]}...")
    resp = req.post("https://api.dev.runwayml.com/v1/text_to_video", headers=headers, json=payload, timeout=30)

    if not resp.ok:
        err = resp.text[:200]
        print(f"  Runway ошибка: {resp.status_code} {err}")
        if "not enough credits" in err.lower() or "do not have enough" in err.lower():
            _mark_service_down("runway", "Кредиты исчерпаны")
        elif resp.status_code in (401, 403):
            _mark_service_down("runway", f"{resp.status_code} auth error")
        return None

    task_id = resp.json().get("id")
    if not task_id:
        print(f"  Runway: нет task ID: {resp.text[:100]}")
        return None

    print(f"  Runway: задача запущена (id={task_id}), жду...")

    # Polling до 5 минут
    for i in range(30):
        time.sleep(10)
        poll = req.get(f"https://api.dev.runwayml.com/v1/tasks/{task_id}", headers=headers, timeout=15)
        if not poll.ok:
            continue
        data = poll.json()
        status = data.get("status")
        progress = data.get("progress", 0)
        print(f"  Runway статус: {status} {int(progress*100)}% ({i+1}/30)")
        if status == "SUCCEEDED":
            video_url = (data.get("output") or [None])[0]
            if not video_url:
                print("  Runway: нет URL видео в ответе")
                return None
            out_path = OUTPUT_DIR / f"runway_{int(time.time())}.mp4"
            video_resp = req.get(video_url, timeout=120, stream=True)
            with open(out_path, "wb") as f:
                for chunk in video_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            # Конвертируем в 1080x1920
            converted = OUTPUT_DIR / f"runway_conv_{int(time.time())}.mp4"
            cmd = [
                "ffmpeg", "-i", str(out_path),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-y", str(converted)
            ]
            subprocess.run(cmd, capture_output=True)
            if converted.exists():
                out_path.unlink(missing_ok=True)
                out_path = converted
            print(f"  Runway видео: {out_path} ({out_path.stat().st_size // 1024}KB)")
            return out_path
        elif status == "FAILED":
            print(f"  Runway: задача провалилась — {data.get('failure', '')}")
            return None

    print("  Runway: таймаут (5 минут)")
    return None


def generate_video_luma(prompt: str, source_image: Path | None = None) -> Path | None:
    """Генерирует видео через Luma Dream Machine API (30 бесплатных генераций)."""
    if not LUMA_API_KEY:
        print("  LUMA_API_KEY не задан в .env")
        return None

    import requests as req
    import base64

    headers = {
        "Authorization": f"Bearer {LUMA_API_KEY}",
        "Content-Type": "application/json",
    }

    # Загрузить изображение как data URL
    image_url = None
    if source_image and source_image.exists():
        with open(source_image, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        ext = source_image.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "image/jpeg")
        image_url = f"data:{mime};base64,{img_b64}"

    payload = {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "loop": False,
    }
    if image_url:
        payload["keyframes"] = {
            "frame0": {"type": "image", "url": image_url}
        }

    print(f"  Luma: отправляю запрос на генерацию...")
    resp = req.post("https://api.lumalabs.ai/dream-machine/v1/generations", headers=headers, json=payload, timeout=30)

    if not resp.ok:
        err = resp.text[:150]
        print(f"  Luma ошибка: {resp.status_code} {err}")
        if resp.status_code in (401, 403) or "not authenticated" in err.lower():
            _mark_service_down("luma", f"{resp.status_code} Not authenticated — API недоступен на free tier")
        return None

    gen_id = resp.json().get("id")
    if not gen_id:
        print(f"  Luma: нет ID в ответе: {resp.text[:100]}")
        return None

    print(f"  Luma: генерация запущена (id={gen_id}), жду...")

    # Polling — ждём до 5 минут
    for i in range(30):
        time.sleep(10)
        poll = req.get(f"https://api.lumalabs.ai/dream-machine/v1/generations/{gen_id}", headers=headers, timeout=15)
        if not poll.ok:
            continue
        data = poll.json()
        state = data.get("state")
        print(f"  Luma статус: {state} ({i+1}/30)")
        if state == "completed":
            video_url = data.get("assets", {}).get("video")
            if not video_url:
                print("  Luma: нет ссылки на видео в ответе")
                return None
            # Скачиваем
            out_path = OUTPUT_DIR / f"luma_{int(time.time())}.mp4"
            video_resp = req.get(video_url, timeout=120, stream=True)
            with open(out_path, "wb") as f:
                for chunk in video_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            # Конвертируем в 1080x1920
            converted = OUTPUT_DIR / f"luma_conv_{int(time.time())}.mp4"
            cmd = [
                "ffmpeg", "-i", str(out_path),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-y", str(converted)
            ]
            subprocess.run(cmd, capture_output=True)
            if converted.exists():
                out_path.unlink(missing_ok=True)
                out_path = converted
            print(f"  Luma видео сохранено: {out_path} ({out_path.stat().st_size // 1024}KB)")
            return out_path
        elif state == "failed":
            print(f"  Luma: генерация провалилась — {data.get('failure_reason', '')}")
            return None

    print("  Luma: таймаут (5 минут)")
    return None


def generate_video_kling(prompt: str, source_image: Path | None = None) -> Path | None:
    """Генерирует видео через Kling AI (fal.ai) — бесплатный кредит $5."""
    if not FAL_KEY:
        print("  FAL_KEY не задан в .env")
        return None

    try:
        import fal_client
        import base64
        import requests as req

        os.environ["FAL_KEY"] = FAL_KEY
        print(f"  Генерирую видео через Kling AI: {prompt[:80]}...")

        if source_image and source_image.exists():
            # Image-to-video: загружаем фото, Kling оживляет его
            print("  Загружаю исходное изображение на fal.ai...")
            with open(source_image, "rb") as f:
                img_url = fal_client.upload(f.read(), "image/jpeg")

            result = fal_client.subscribe(
                "fal-ai/kling-video/v2.1/pro/image-to-video",
                arguments={
                    "prompt": prompt,
                    "image_url": img_url,
                    "duration": "5",
                    "aspect_ratio": "9:16",
                },
                with_logs=False,
            )
        else:
            # Text-to-video
            result = fal_client.subscribe(
                "fal-ai/kling-video/v2.1/standard/text-to-video",
                arguments={
                    "prompt": prompt,
                    "duration": "5",
                    "aspect_ratio": "9:16",
                },
                with_logs=False,
            )

        video_url = result.get("video", {}).get("url") or result.get("videos", [{}])[0].get("url")
        if not video_url:
            print(f"  Kling не вернул URL видео: {result}")
            return None

        print(f"  Скачиваю видео: {video_url[:60]}...")
        resp = req.get(video_url, timeout=60)
        out_path = OUTPUT_DIR / f"kling_{int(time.time())}.mp4"
        out_path.write_bytes(resp.content)
        print(f"  Видео сохранено: {out_path} ({out_path.stat().st_size // 1024}KB)")
        return out_path

    except Exception as e:
        err = str(e)
        if "exhausted balance" in err.lower() or "locked" in err.lower() or "User is locked" in err:
            _mark_service_down("kling", "Баланс исчерпан")
        elif "403" in err or "Forbidden" in err:
            _mark_service_down("kling", "403 Forbidden — нет доступа к fal.ai")
        else:
            print(f"  Kling ошибка: {e}")
        return None


def generate_video_replicate(prompt: str, source_image: Path | None = None) -> Path | None:
    """Генерирует видео через Replicate (Seedance 2.0 → Minimax Video-01 fallback)."""
    import requests as req
    import base64

    token = REPLICATE_API_TOKEN
    if not token:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }

    # Пробуем модели по очереди
    models = [
        ("bytedance/seedance-2.0", {
            "prompt": prompt,
            "duration": 5,
            "resolution": "480p",
            "aspect_ratio": "9:16",
            "generate_audio": False,
        }),
        ("minimax/video-01", {
            "prompt": prompt,
            "prompt_optimizer": True,
        }),
    ]

    for model_name, payload in models:
        try:
            print(f"  Replicate {model_name}...")

            # Добавляем image если есть source_image
            if source_image and source_image.exists():
                with open(source_image, "rb") as f:
                    img_b64 = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
                if model_name == "bytedance/seedance-2.0":
                    payload["image"] = img_b64
                elif model_name == "minimax/video-01":
                    payload["first_frame_image"] = img_b64

            resp = req.post(
                f"https://api.replicate.com/v1/models/{model_name}/predictions",
                headers=headers,
                json={"input": payload},
                timeout=90,
            )

            if resp.status_code == 402:
                _mark_service_down("replicate", "Баланс исчерпан")
                return None

            if resp.status_code not in (200, 201):
                print(f"  Replicate {model_name} ответ {resp.status_code}: {resp.text[:120]}")
                continue

            data = resp.json()
            prediction_id = data.get("id")

            # Polling если не сразу succeeded
            for _ in range(60):
                status = data.get("status")
                if status == "succeeded":
                    break
                if status in ("failed", "canceled"):
                    print(f"  Replicate {model_name} статус: {status} — {data.get('error','')[:80]}")
                    break
                time.sleep(5)
                poll = req.get(
                    f"https://api.replicate.com/v1/predictions/{prediction_id}",
                    headers=headers, timeout=15,
                )
                data = poll.json()

            if data.get("status") != "succeeded":
                continue

            output = data.get("output")
            video_url = output[0] if isinstance(output, list) else output
            if not video_url:
                continue

            # Скачиваем видео
            video_resp = req.get(video_url, timeout=60, stream=True)
            if video_resp.status_code != 200:
                continue

            out_path = OUTPUT_DIR / f"replicate_{int(time.time())}.mp4"
            with open(out_path, "wb") as f:
                for chunk in video_resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            if out_path.exists() and out_path.stat().st_size > 10000:
                print(f"  Replicate {model_name} ✅ {out_path.name}")
                return out_path

        except Exception as e:
            print(f"  Replicate {model_name} исключение: {e}")
            continue

    return None


def generate_video_veo(prompt: str, source_image: Path | None = None) -> Path | None:
    """Генерирует видео через Veo 2.

    Пробует два метода:
    1. Vertex AI REST API (с VERTEX_API_KEY)
    2. Google AI Studio genai SDK (с GOOGLE_API_KEY, требует billing)
    """
    vertex_key = os.getenv("VERTEX_API_KEY")
    project_id = os.getenv("VERTEX_PROJECT_ID", "n8n-integrations-460911")
    location = os.getenv("VERTEX_LOCATION", "us-central1")

    print(f"  Генерирую видео через Veo 2: {prompt[:80]}...")

    # --- Метод 1: Vertex AI REST API ---
    if vertex_key and project_id:
        try:
            import requests as req
            import base64

            url = (
                f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}"
                f"/locations/{location}/publishers/google/models/veo-2.0-generate-001"
                f":predictLongRunning"
            )
            headers = {
                "Authorization": f"Bearer {vertex_key}",
                "Content-Type": "application/json",
                "x-goog-user-project": project_id,
            }

            instance: dict = {
                "prompt": prompt,
                "videoGenerationConfig": {
                    "aspectRatio": "9:16",
                    "durationSeconds": 8,
                    "sampleCount": 1,
                }
            }

            if source_image and source_image.exists():
                with open(source_image, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                instance["image"] = {
                    "bytesBase64Encoded": img_b64,
                    "mimeType": "image/jpeg"
                }

            resp = req.post(url, headers=headers, json={"instances": [instance]}, timeout=30)

            if resp.status_code == 200:
                op_name = resp.json().get("name", "")
                print(f"  Операция запущена: {op_name}")
                print("  Ожидаю генерацию видео (2-4 минуты)...")

                # Polling operation
                op_url = f"https://{location}-aiplatform.googleapis.com/v1/{op_name}"
                for _ in range(30):
                    time.sleep(10)
                    op_resp = req.get(op_url, headers=headers, timeout=15)
                    op_data = op_resp.json()
                    if op_data.get("done"):
                        break
                    print("  ...", end="", flush=True)
                print()

                # Extract video
                videos = (op_data.get("response", {})
                          .get("predictions", [{}])[0]
                          .get("videoResponses", []))
                if videos:
                    video_b64 = videos[0].get("bytesBase64Encoded", "")
                    if video_b64:
                        out_path = OUTPUT_DIR / f"veo_{int(time.time())}.mp4"
                        out_path.write_bytes(base64.b64decode(video_b64))
                        print(f"  Видео сохранено: {out_path}")
                        return out_path

                err = op_data.get("error", {})
                print(f"  Vertex AI Veo ошибка: {err.get('message', op_data)[:150]}")
            else:
                print(f"  Vertex AI ответ {resp.status_code}: {resp.text[:200]}")

        except Exception as e:
            print(f"  Vertex AI ошибка: {e}")

    # --- Метод 2: AI Studio SDK (fallback) ---
    try:
        from google import genai
        from google.genai import types

        if not GOOGLE_API_KEY:
            return None

        client = genai.Client(api_key=GOOGLE_API_KEY)
        if source_image and source_image.exists():
            with open(source_image, "rb") as f:
                image_bytes = f.read()
            image = types.Image(image_bytes=image_bytes, mime_type="image/jpeg")
            operation = client.models.generate_videos(
                model="veo-2.0-generate-001", prompt=prompt, image=image,
                config=types.GenerateVideosConfig(aspect_ratio="9:16", number_of_videos=1, duration_seconds=8)
            )
        else:
            operation = client.models.generate_videos(
                model="veo-2.0-generate-001", prompt=prompt,
                config=types.GenerateVideosConfig(aspect_ratio="9:16", number_of_videos=1, duration_seconds=8)
            )

        print("  Ожидаю через AI Studio SDK...")
        while not operation.done:
            time.sleep(10)
            operation = client.operations.get(operation)
            print("  ...", end="", flush=True)
        print()

        if operation.response and operation.response.generated_videos:
            video = operation.response.generated_videos[0]
            out_path = OUTPUT_DIR / f"veo_{int(time.time())}.mp4"
            client.files.download(file=video.video, download_path=str(out_path))
            print(f"  Видео сохранено: {out_path}")
            return out_path
        else:
            print(f"  AI Studio Veo ошибка: {operation.error}")
            return None

    except Exception as e:
        print(f"  Veo API ошибка: {e}")
        return None


def _build_background_prompt(video_prompt: str) -> str:
    """
    Извлекает из видео-промпта только описание окружения (ENVIRONMENT/LIGHTING),
    убирает всё про устройство и продукт — чистая фоновая сцена для Pollinations.
    """
    import re
    # Вытаскиваем ENVIRONMENT секцию
    env_match = re.search(r'ENVIRONMENT[:\s]+([^.]+\.)', video_prompt, re.IGNORECASE)
    light_match = re.search(r'LIGHTING[:\s]+([^.]+\.)', video_prompt, re.IGNORECASE)

    parts = []
    if env_match:
        parts.append(env_match.group(1).strip())
    if light_match:
        parts.append(light_match.group(1).strip())

    if parts:
        bg = " ".join(parts)
    else:
        # Fallback — убираем слова про устройство
        bg = re.sub(
            r'\b(display|screen|e-ink|panel|device|ecodisplays|pylon|totem|signage|billboard|kiosk)\b',
            '', video_prompt, flags=re.IGNORECASE
        )[:200]

    bg += " Photorealistic, natural light, no text, no signs, no logos, clean composition, 4:5 portrait."
    return bg.strip()


def _pick_real_photo(exclude: Path | None = None) -> Path | None:
    """Выбирает случайное фото из /content/ для использования как база поста."""
    import random
    photos = [
        p for p in CONTENT_DIR.glob("*.jpg")
        if p != exclude and p.stat().st_size > 50000
    ]
    photos += [
        p for p in CONTENT_DIR.glob("*.jpeg")
        if p != exclude and p.stat().st_size > 50000
    ]
    if photos:
        return random.choice(photos)
    return None


EINK_REFERENCE_DIR = Path(os.getenv("CONTENT_DIR", "/root/Ecodisplays/content")) / "eink_reference"

# Поисковые запросы для реальных фото e-ink технологий и реализаций
EINK_SEARCH_QUERIES = [
    "e-ink display 32 inch outdoor installation real photo",
    "42 inch e-paper display outdoor signage installation",
    "electronic paper display outdoor bus stop installation",
    "e-ink outdoor signage smart city real deployment",
    "e-paper outdoor display panel urban installation photo",
    "e-ink digital signage outdoor weatherproof installation",
    "32 inch epaper outdoor information display",
    "42 inch electronic paper outdoor advertising display",
    "e-ink display kiosk public transport real photo",
    "e-paper outdoor wayfinding display installation",
]


def search_eink_reference_photos(max_per_query: int = 3, max_total: int = 15) -> list[Path]:
    """
    Ищет реальные фото e-ink технологий через DuckDuckGo Images (с задержками).
    Fallback: Google Custom Search API если есть GOOGLE_API_KEY + GOOGLE_CSE_ID.
    Кэширует в content/eink_reference/.
    Возвращает список путей к скачанным фото.
    """
    import random
    import requests as req

    EINK_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)

    # Уже скачанные — возвращаем если их достаточно
    existing = sorted(EINK_REFERENCE_DIR.glob("*.jpg"))
    if len(existing) >= max_total:
        print(f"  Используем кэш e-ink фото ({len(existing)} шт.)")
        return existing

    downloaded: list[Path] = list(existing)
    existing_names = {p.name for p in existing}

    def _download_image(url: str) -> Path | None:
        """Скачивает и валидирует изображение."""
        fname = f"eink_{abs(hash(url)) % 10**8:08d}.jpg"
        if fname in existing_names:
            return None
        try:
            resp = req.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and len(resp.content) > 20000:
                out = EINK_REFERENCE_DIR / fname
                out.write_bytes(resp.content)
                check = subprocess.run(["identify", str(out)], capture_output=True)
                if check.returncode == 0:
                    existing_names.add(fname)
                    print(f"    ✓ {fname} ({len(resp.content)//1024}KB)")
                    return out
                out.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    # --- Метод 1: DuckDuckGo Images (с задержкой между запросами) ---
    try:
        try:
            from ddgs import DDGS as _DDGS
        except ImportError:
            from duckduckgo_search import DDGS as _DDGS

        queries = random.sample(EINK_SEARCH_QUERIES, k=min(len(EINK_SEARCH_QUERIES), 5))
        print(f"  Ищу e-ink фото через DuckDuckGo ({len(queries)} запросов)...")

        for query in queries:
            if len(downloaded) >= max_total:
                break
            time.sleep(2)  # Задержка между запросами чтобы не попасть в rate-limit
            try:
                results = list(_DDGS().images(
                    query,
                    max_results=max_per_query * 2,
                    type_image="photo",
                    size="Large",
                ))
                for r in results[:max_per_query]:
                    if len(downloaded) >= max_total:
                        break
                    url = r.get("image", "")
                    if not url or not url.startswith("http"):
                        continue
                    p = _download_image(url)
                    if p:
                        downloaded.append(p)
            except Exception as e:
                print(f"  DDG ошибка '{query[:35]}': {str(e)[:80]}")
                time.sleep(3)
                continue

    except ImportError:
        print("  ddgs/duckduckgo-search не установлен")

    # --- Метод 2: Google Custom Search API (fallback) ---
    GOOGLE_KEY = os.getenv("GOOGLE_API_KEY")
    GOOGLE_CSE = os.getenv("GOOGLE_CSE_ID", "")
    if len(downloaded) < max_total and GOOGLE_KEY and GOOGLE_CSE:
        needed = max_total - len(downloaded)
        queries_g = EINK_SEARCH_QUERIES[:3]
        print(f"  Fallback: Google Custom Search (нужно ещё {needed} фото)...")
        for query in queries_g:
            if len(downloaded) >= max_total:
                break
            try:
                resp = req.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": GOOGLE_KEY,
                        "cx": GOOGLE_CSE,
                        "q": query,
                        "searchType": "image",
                        "num": max_per_query,
                        "imgSize": "large",
                        "imgType": "photo",
                    },
                    timeout=15,
                )
                if resp.ok:
                    for item in resp.json().get("items", []):
                        url = item.get("link", "")
                        if url and len(downloaded) < max_total:
                            p = _download_image(url)
                            if p:
                                downloaded.append(p)
            except Exception as e:
                print(f"  Google CSE ошибка: {e}")

    print(f"  Итого e-ink reference фото: {len(downloaded)}")
    return downloaded


def pick_eink_reference_photo(exclude: Path | None = None) -> Path | None:
    """Выбирает случайное фото из кэша e-ink reference фото."""
    import random
    photos = [
        p for p in EINK_REFERENCE_DIR.glob("*.jpg")
        if p != exclude and p.stat().st_size > 20000
    ]
    return random.choice(photos) if photos else None


def _make_text_overlay(base_image: Path, caption_data: dict, output_path: Path) -> bool:
    """
    Накладывает текстовую карточку на фото через ffmpeg drawtext.
    Полупрозрачный тёмный баннер снизу + белый текст + EcoDisplays брендинг.
    """
    sr_text = caption_data.get("caption_sr", "")[:120].replace("'", "\\'").replace(":", "\\:").replace("[", "\\[").replace("]", "\\]")
    ct = caption_data.get("content_type", "")
    fact = ""
    # Добавляем ключевой факт в зависимости от типа
    try:
        cdb = _load_context_db()
        bf = cdb.get("brand_facts", {})
        if ct == "eco_fact":
            fact = bf.get("energy_en", "111x less energy than conventional displays")
        elif ct == "comparison":
            fact = cdb.get("competitors_contrast", {}).get("ecodisplays_advantage", "")[:80]
        elif ct in ("installation", "urban_case"):
            proj_key = caption_data.get("project") or ""
            proj = cdb.get("projects", {}).get(proj_key, {})
            if proj.get("key_facts_en"):
                fact = proj["key_facts_en"][0][:80]
    except Exception:
        pass

    fact_clean = fact.replace("'", "\\'").replace(":", "\\:").replace("[", "\\[").replace("]", "\\]")

    # ffmpeg: resize → баннер снизу → текст
    vf_parts = [
        "scale=1080:1350:force_original_aspect_ratio=decrease",
        "pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=black",
        # Полностью непрозрачный баннер снизу (перекрывает Pollinations watermark)
        "drawbox=x=0:y=1065:w=1080:h=285:color=black:t=fill",
        # Брендинг EcoDisplays сверху баннера
        "drawtext=text='EcoDisplays':fontcolor=white:fontsize=34:x=40:y=1082:font=Sans",
        # Зелёная линия под брендингом
        "drawbox=x=40:y=1125:w=200:h=3:color=0x4CAF50:t=fill",
    ]

    if fact_clean:
        vf_parts.append(
            f"drawtext=text='{fact_clean[:90]}':fontcolor=0x90EE90:fontsize=24:x=40:y=1140:font=Sans"
        )

    # Первые ~70 символов caption_sr (без w= — не поддерживается этой версией ffmpeg)
    if sr_text:
        vf_parts.append(
            f"drawtext=text='{sr_text[:70]}':fontcolor=white@0.9:fontsize=22:x=40:y=1185:font=Sans"
        )

    vf = ",".join(vf_parts)

    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(base_image), "-vf", vf,
             "-frames:v", "1", "-update", "1", "-y", str(output_path)],
            capture_output=True, text=True
        )
        if output_path.exists() and output_path.stat().st_size > 10000:
            return True
        else:
            print(f"  ffmpeg overlay ошибка: {result.stderr[-200:]}")
            return False
    except Exception as e:
        print(f"  ffmpeg overlay исключение: {e}")
        return False


def _generate_photo_ai_only(prompt: str, source_image: Path | None = None,
                            caption_data: dict | None = None,
                            content_type: str | None = None) -> Path | None:
    """
    Генерирует фото ТОЛЬКО через AI-сервисы (без реальных фото).
    Порядок: HF Flux → OpenAI → Pollinations (с продуктом в промпте)
    """
    import requests as req

    # --- Промпт с продуктом для HF/OpenAI ---
    photo_prompt = (
        prompt
        .replace("9:16 vertical frame, Instagram Reels format. ", "")
        .replace("9:16 vertical frame, Instagram Reels format.", "")
        .replace("Instagram Reels format", "Instagram post format")
        .replace("Camera movement", "Composition")
        .replace("dolly", "static")
        .replace("pan", "static")
        .replace("tilt", "static")
    )
    photo_prompt += (
        " High resolution product photography, professional lighting, sharp focus."
        " Clean minimalist style, photorealistic, no text, no letters, no words, no logos,"
        " no brand names rendered on screen surface, no artifacts, no distortion."
        " E-ink display screen shows only abstract map shapes or blurred geometric patterns."
        " EcoDisplays device: flat aluminum panel 32mm thin, tempered glass front, modern clean design."
    )

    # Загружаем правила из context_db
    try:
        _cdb = _load_context_db()
        _rules = _cdb.get("image_generation_rules", {})
        if _rules.get("CRITICAL_no_text"):
            photo_prompt += f" IMPORTANT: {_rules['CRITICAL_no_text']}"
    except Exception:
        pass

    # Промпт для Pollinations — описывает продукт в сцене
    ct = content_type or (caption_data.get("content_type") if caption_data else None) or "product_shot"
    context_snippet = ""
    try:
        context_snippet = _build_context_snippet(ct, _load_context_db())
    except Exception:
        pass
    pollinations_prompt = _build_product_photo_prompt(ct, context_snippet, prompt)

    def _resize_to_instagram(raw: Path, prefix: str) -> Path | None:
        out = OUTPUT_DIR / f"{prefix}_{int(time.time())}.jpg"
        cmd = [
            "ffmpeg", "-i", str(raw),
            "-vf", "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=white",
            "-frames:v", "1", "-update", "1", "-y", str(out)
        ]
        subprocess.run(cmd, capture_output=True)
        raw.unlink(missing_ok=True)
        return out if out.exists() and out.stat().st_size > 5000 else None

    # --- HuggingFace Flux.1-schnell (лучшее бесплатное) ---
    if HF_TOKEN:
        hf_models = [
            ("black-forest-labs/FLUX.1-schnell", {"inputs": photo_prompt[:500]}),
            ("stabilityai/stable-diffusion-xl-base-1.0", {
                "inputs": photo_prompt[:500],
                "parameters": {"width": 1080, "height": 1350, "num_inference_steps": 25}
            }),
        ]
        for model_id, payload in hf_models:
            svc_key = f"hf_photo_{model_id.split('/')[-1]}"
            if _is_service_down(svc_key):
                continue
            try:
                print(f"  Генерирую фото через HF {model_id.split('/')[-1]}...")
                resp = req.post(
                    f"https://api-inference.huggingface.co/models/{model_id}",
                    headers={"Authorization": f"Bearer {HF_TOKEN}"},
                    json=payload, timeout=120,
                )
                if resp.status_code == 503:
                    wait = resp.json().get("estimated_time", 20)
                    print(f"  Модель загружается, жду {int(wait)}с...")
                    time.sleep(min(wait + 5, 60))
                    resp = req.post(
                        f"https://api-inference.huggingface.co/models/{model_id}",
                        headers={"Authorization": f"Bearer {HF_TOKEN}"},
                        json=payload, timeout=120,
                    )
                if resp.ok and len(resp.content) > 5000:
                    raw = OUTPUT_DIR / f"photo_raw_{int(time.time())}.jpg"
                    raw.write_bytes(resp.content)
                    out = _resize_to_instagram(raw, "photo")
                    if out:
                        _mark_service_up(svc_key)
                        print(f"  Фото готово: {out} ({out.stat().st_size // 1024}KB)")
                        return out
                else:
                    err_text = resp.text[:100]
                    if resp.status_code in (401, 403):
                        _mark_service_down(svc_key, f"{resp.status_code} {err_text}")
                    else:
                        print(f"  HF {model_id.split('/')[-1]} ошибка {resp.status_code}: {err_text}")
            except Exception as e:
                err = str(e)
                if "NameResolutionError" in err or "Failed to resolve" in err:
                    _mark_service_down(svc_key, "DNS недоступен")
                else:
                    print(f"  HF {model_id.split('/')[-1]} исключение: {e}")

    # --- OpenAI image generation ---
    if OPENAI_API_KEY and not _is_service_down("openai_image"):
        # Пробуем gpt-image-1 (новая), fallback на dall-e-3
        for img_model in ("gpt-image-1", "dall-e-3"):
            if _is_service_down(f"openai_{img_model}"):
                continue
            try:
                print(f"  Генерирую фото через OpenAI {img_model}...")
                resp = req.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                    json={"model": img_model, "prompt": photo_prompt[:1000], "n": 1, "size": "1024x1024"},
                    timeout=60,
                )
                if resp.ok:
                    data = resp.json()["data"][0]
                    img_url = data.get("url") or data.get("b64_json")
                    if data.get("b64_json"):
                        import base64
                        raw = OUTPUT_DIR / f"openai_raw_{int(time.time())}.jpg"
                        raw.write_bytes(base64.b64decode(data["b64_json"]))
                    else:
                        img_resp = req.get(img_url, timeout=60)
                        raw = OUTPUT_DIR / f"openai_raw_{int(time.time())}.jpg"
                        raw.write_bytes(img_resp.content)
                    out = _resize_to_instagram(raw, "openai")
                    if out:
                        _mark_service_up(f"openai_{img_model}")
                        print(f"  OpenAI {img_model} фото готово: {out}")
                        return out
                else:
                    err_text = resp.text[:150]
                    if "does not exist" in err_text or "not found" in err_text.lower():
                        _mark_service_down(f"openai_{img_model}", "модель недоступна")
                    elif "billing" in err_text.lower() or "hard limit" in err_text.lower():
                        _mark_service_down("openai_image", "Billing limit reached")
                        break
                    elif resp.status_code in (401, 403):
                        _mark_service_down("openai_image", f"{resp.status_code}")
                        break
                    else:
                        print(f"  OpenAI {img_model} ошибка: {err_text}")
            except Exception as e:
                print(f"  OpenAI {img_model} исключение: {e}")
                break

    # --- Pollinations.ai — продукт в сцене ---
    if not _is_service_down("pollinations"):
        try:
            import urllib.parse
            bg_prompt = pollinations_prompt
            print(f"  Генерирую продукт через Pollinations.ai: {bg_prompt[:80]}...")
            encoded = urllib.parse.quote(bg_prompt)
            poll_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1350&nologo=true&model=flux-realism&seed={int(time.time())}"
            resp = req.get(poll_url, timeout=90)
            if resp.ok and len(resp.content) > 5000:
                raw = OUTPUT_DIR / f"poll_raw_{int(time.time())}.jpg"
                raw.write_bytes(resp.content)
                out = OUTPUT_DIR / f"pollinations_{int(time.time())}.jpg"
                # Overlay текста если есть caption_data
                if caption_data:
                    tmp = OUTPUT_DIR / f"poll_base_{int(time.time())}.jpg"
                    subprocess.run(
                        ["ffmpeg", "-i", str(raw), "-vf",
                         "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=black",
                         "-frames:v", "1", "-update", "1", "-y", str(tmp)], capture_output=True
                    )
                    raw.unlink(missing_ok=True)
                    if tmp.exists() and _make_text_overlay(tmp, caption_data, out):
                        tmp.unlink(missing_ok=True)
                        _mark_service_up("pollinations")
                        print(f"  Pollinations + overlay готово: {out} ({out.stat().st_size // 1024}KB)")
                        return out
                    tmp.rename(out)
                else:
                    subprocess.run(
                        ["ffmpeg", "-i", str(raw), "-vf",
                         "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=black",
                         "-frames:v", "1", "-update", "1", "-y", str(out)], capture_output=True
                    )
                    raw.unlink(missing_ok=True)
                if out.exists() and out.stat().st_size > 5000:
                    _mark_service_up("pollinations")
                    print(f"  Pollinations фон готово: {out} ({out.stat().st_size // 1024}KB)")
                    return out
            elif resp.status_code == 402:
                _mark_service_down("pollinations", "402 rate limit", ttl=1800)
                print(f"  Pollinations rate limit (402) — сервис заблокирован на 30 мин")
            else:
                print(f"  Pollinations ошибка: {resp.status_code}")
        except Exception as e:
            err = str(e)
            if "NameResolutionError" in err or "Failed to resolve" in err:
                _mark_service_down("pollinations", "DNS недоступен")
            else:
                print(f"  Pollinations исключение: {e}")

    print("  Все AI-фото генераторы недоступны")
    return None


def generate_photo_ai(prompt: str, source_image: Path | None = None,
                      caption_data: dict | None = None) -> Path | None:
    """Публичная обёртка: сначала AI, потом реальные фото как резерв."""
    ct = caption_data.get("content_type") if caption_data else None
    result = _generate_photo_ai_only(prompt, source_image, caption_data=caption_data, content_type=ct)
    if result:
        return result
    # Резерв: реальное фото из /content/
    real_photo = source_image if (source_image and source_image.exists()) else _pick_real_photo()
    if real_photo:
        out = OUTPUT_DIR / f"photo_real_{int(time.time())}.jpg"
        subprocess.run(
            ["ffmpeg", "-i", str(real_photo),
             "-vf", "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2:color=black",
             "-frames:v", "1", "-update", "1", "-y", str(out)], capture_output=True
        )
        if out.exists() and out.stat().st_size > 5000:
            return out
    return None


def _generate_ambient_scipy(duration: int = 15) -> Path | None:
    """Ambient music via numpy/scipy — многослойные пэды, пентатоника C-maj, хорус-эффект.

    Звучит как реальный ambient: тихий пад, тёплый бас-дрон, медленный хорус,
    мягкие высокочастотные атаки. Полностью без внешних зависимостей.
    """
    import numpy as np
    import struct
    import wave

    print(f"  🎵 Генерирую ambient музыку scipy ({duration}s)...")
    sr = 44100
    N = sr * duration
    t = np.linspace(0, duration, N, endpoint=False)

    # Пентатоника C-maj: C2 C3 G3 A3 E4 G4 A4 C5
    NOTES = [65.41, 130.81, 196.00, 220.00, 329.63, 392.00, 440.00, 523.25]

    def pad(freq, amp, detune=0.003):
        """Тёплый пад: 3 слегка расстроенных осциллятора + мягкий треугольник."""
        s = (np.sin(2 * np.pi * freq * t)
             + 0.5 * np.sin(2 * np.pi * freq * (1 + detune) * t)
             + 0.5 * np.sin(2 * np.pi * freq * (1 - detune) * t))
        # Треугольная составляющая для тепла
        s += 0.3 * (2 / np.pi) * np.arcsin(np.sin(2 * np.pi * freq * t))
        return amp * s / 2.3

    def slow_envelope(attack=3.0, release=3.0):
        """Плавная огибающая."""
        env = np.ones(N)
        a = int(attack * sr)
        r = int(release * sr)
        env[:a] = np.linspace(0, 1, a)
        env[N - r:] = np.linspace(1, 0, r)
        return env

    def chorus(sig, rate=0.4, depth=0.003):
        """Хорус через numpy — без Python-цикла."""
        lfo_samples = (depth * sr * (0.5 + 0.5 * np.sin(2 * np.pi * rate * t))).astype(int)
        indices = np.arange(N)
        delayed_idx = np.clip(indices - lfo_samples, 0, N - 1)
        return 0.65 * sig + 0.35 * sig[delayed_idx]

    def simple_reverb(sig, delay_s=0.04, decay=0.3):
        """Короткий reverb через суммирование задержанных копий."""
        out = sig.copy()
        for d_s, d_amp in [(delay_s, decay), (delay_s*2, decay*0.5), (delay_s*3, decay*0.25)]:
            d = int(d_s * sr)
            if d < N:
                out[d:] += d_amp * sig[:N-d]
        peak = np.max(np.abs(out))
        return out * (0.85 / peak) if peak > 0 else out

    # Слои
    env = slow_envelope(attack=2.5, release=3.0)

    # Бас-дрон C2 очень тихий
    bass = pad(NOTES[0], 0.08) * env

    # Пад C3 + G3 — основа
    layer1 = (pad(NOTES[1], 0.18) + pad(NOTES[2], 0.15)) * env

    # Средний пад A3 + E4 — гармония
    layer2 = (pad(NOTES[3], 0.12) + pad(NOTES[4], 0.10)) * env

    # Высокий G4 + A4 — воздух, появляется позже
    hi_env = np.zeros(N)
    hi_start = int(3.5 * sr)
    hi_env[hi_start:] = slow_envelope(attack=4.0, release=2.5)[hi_start:]
    layer3 = (pad(NOTES[5], 0.07) + pad(NOTES[6], 0.06)) * hi_env

    # Очень тихий C5 shimmer
    layer4 = pad(NOTES[7], 0.04) * hi_env

    # Ритм-секция 128 BPM: kick + hihat (subtle, ambient-style)
    bpm = 128
    beat_interval = int(sr * 60 / bpm)  # samples per beat

    # Kick drum: short noise burst with exponential decay, low-pass character
    def make_kick(amp=0.18):
        kick_len = int(sr * 0.12)
        kick_t = np.linspace(0, 0.12, kick_len)
        # Sub-bass punch + body
        kick = (np.sin(2 * np.pi * 60 * kick_t * np.exp(-kick_t * 40))
                + 0.4 * np.sin(2 * np.pi * 120 * kick_t))
        kick *= np.exp(-kick_t * 25)  # fast decay
        return amp * kick / np.max(np.abs(kick) + 1e-8)

    # Hi-hat: high-freq noise burst, very short
    def make_hihat(amp=0.06):
        hat_len = int(sr * 0.025)
        noise = np.random.randn(hat_len)
        # High-pass: remove low frequencies via simple difference filter
        noise = np.diff(noise, prepend=noise[:1])
        env = np.exp(-np.linspace(0, 8, hat_len))
        return amp * noise * env / (np.max(np.abs(noise * env)) + 1e-8)

    kick_sample = make_kick()
    hat_sample = make_hihat()

    rhythm = np.zeros(N)
    # Kick on beats 1 & 3 (every 2 beats), hihat on every beat
    for beat_idx in range(int(duration * bpm / 60)):
        pos = beat_idx * beat_interval
        # Hihat every beat
        end_hat = min(pos + len(hat_sample), N)
        rhythm[pos:end_hat] += hat_sample[:end_hat - pos]
        # Kick on beats 1 & 3 (0-indexed: 0, 2, 4, ...)
        if beat_idx % 2 == 0:
            end_kick = min(pos + len(kick_sample), N)
            rhythm[pos:end_kick] += kick_sample[:end_kick - pos]

    # Fade rhythm in/out (enters at 4s, fades at last 3s)
    rhythm_env = np.zeros(N)
    fade_in_start = int(4.0 * sr)
    fade_in_end = int(6.0 * sr)
    fade_out_start = int((duration - 3.0) * sr)
    rhythm_env[fade_in_start:fade_in_end] = np.linspace(0, 1, fade_in_end - fade_in_start)
    rhythm_env[fade_in_end:fade_out_start] = 1.0
    rhythm_env[fade_out_start:] = np.linspace(1, 0, N - fade_out_start)
    rhythm *= rhythm_env

    mix = bass + layer1 + layer2 + layer3 + layer4 + rhythm

    # Хорус + reverb на весь микс
    mix = chorus(mix, rate=0.3, depth=0.002)
    mix = simple_reverb(mix, delay_s=0.035, decay=0.25)

    # Нормализация с headroom
    peak = np.max(np.abs(mix))
    if peak > 0:
        mix = mix * (0.82 / peak)

    # Экспорт WAV → конвертируем через ffmpeg в mp3
    tmp_wav = OUTPUT_DIR / f"_tmp_ambient_{int(time.time())}.wav"
    out_mp3 = OUTPUT_DIR / f"music_ambient_{int(time.time())}.mp3"
    try:
        pcm = (mix * 32767).astype(np.int16)
        with wave.open(str(tmp_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp_wav),
             "-codec:a", "libmp3lame", "-q:a", "3", str(out_mp3)],
            capture_output=True
        )
        tmp_wav.unlink(missing_ok=True)

        if result.returncode == 0 and out_mp3.exists() and out_mp3.stat().st_size > 5000:
            print(f"  ✅ Ambient scipy: {out_mp3.name} ({out_mp3.stat().st_size // 1024}KB)")
            return out_mp3
    except Exception as e:
        print(f"  ⚠️  Ambient scipy ошибка: {e}")
        tmp_wav.unlink(missing_ok=True)
    return None


def generate_music_ai(prompt: str, duration: int = 15) -> Path | None:
    """
    Генерирует фоновую музыку для Reels.
    Цепочка: Mubert → ffmpeg-ambient (всегда работает).
    Возвращает путь к mp3/wav файлу или None.
    """
    import requests as req

    mubert_pat = os.getenv("MUBERT_PAT")
    if mubert_pat and not _is_service_down("mubert"):
        try:
            print(f"  🎵 Генерирую музыку через Mubert ({duration}s)...")
            # Шаг 1: получить access token
            r = req.post("https://api.mubert.com/v2/GetServiceAccess",
                json={"method": "GetServiceAccess", "params": {
                    "pat": mubert_pat, "mode": "loop",
                }}, timeout=15)
            data = r.json()
            access_token = data.get("data", {}).get("token")
            if not access_token:
                raise ValueError(f"Mubert auth fail: {data.get('error', {}).get('text', '')}")

            # Шаг 2: запросить трек
            r2 = req.post("https://api.mubert.com/v2/RecordTrackTTM",
                json={"method": "RecordTrackTTM", "params": {
                    "token": access_token,
                    "prompt": prompt,
                    "duration": duration,
                    "format": "mp3",
                    "bitrate": "128",
                }}, timeout=30)
            track_data = r2.json().get("data", {})
            track_url = track_data.get("tasks", [{}])[0].get("download_link", "")
            if not track_url:
                raise ValueError(f"Mubert no track URL: {r2.text[:200]}")

            # Шаг 3: скачать
            r3 = req.get(track_url, timeout=60)
            if r3.ok and len(r3.content) > 10000:
                out = OUTPUT_DIR / f"music_mubert_{int(time.time())}.mp3"
                out.write_bytes(r3.content)
                _mark_service_up("mubert")
                print(f"  ✅ Mubert: {out.name} ({out.stat().st_size // 1024}KB)")
                return out
        except Exception as e:
            err = str(e)
            if any(x in err.lower() for x in ("401", "403", "unauthorized", "quota")):
                _mark_service_down("mubert", err[:80])
            else:
                print(f"  Mubert ошибка: {err[:100]}")

    # Fallback: scipy ambient (многослойные пэды, пентатоника, хорус)
    return _generate_ambient_scipy(duration)


def _add_music_to_video(video_path: Path, music_path: Path) -> Path:
    """Накладывает музыку на видео: нормализация + fade in/out."""
    out = OUTPUT_DIR / f"reel_music_{int(time.time())}.mp4"
    # Получаем длину видео для fade out
    import json as _j, subprocess as _sp
    _pr = _sp.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
                  capture_output=True, text=True)
    _vdur = float(_j.loads(_pr.stdout).get("format", {}).get("duration", 28))
    fade_start = max(_vdur - 2.0, _vdur * 0.85)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-af", f"volume=0.55,afade=t=in:d=1.2,afade=t=out:st={fade_start:.1f}:d=2.0",
        str(out)
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and out.exists() and out.stat().st_size > 10000:
        return out
    print(f"  ⚠️  Не удалось добавить музыку: {result.stderr[-80:]}")
    return video_path


STORY_SCENES = [
    # ══════════════════════════════════════════════════════════════
    # ESG: ЭНЕРГИЯ И УСТОЙЧИВОСТЬ
    # ══════════════════════════════════════════════════════════════
    {
        "ct": ["eco_fact", "comparison", "product_shot"],
        "story": "SOLAR CITY MORNING",
        "prompt": (
            "Documentary photograph, Canon R5, 24mm f/4, golden hour. "
            "Wide shot: Belgrade city square, early morning sun at 15 degrees. "
            "Foreground: solar panel array on a modern pole, glass panels catching first light, "
            "warm orange reflections. Mid-ground: a city maintenance worker in green vest "
            "checks a tablet — she's monitoring energy output, calm professional expression. "
            "Background: clean modern Serbian city architecture, trees, empty plaza. "
            "Mood: quiet city awakening, clean energy already working while citizens sleep. "
            "Color palette: warm gold, muted greens, grey concrete. "
            "No screens visible. No brand names. Shot on location, NOT staged. "
            "National Geographic style. 9:16 vertical."
        ),
    },
    {
        "ct": ["eco_fact", "comparison"],
        "story": "111x ENERGY CONTRAST",
        "prompt": (
            "Editorial split photograph, 35mm lens. "
            "LEFT HALF: night scene, a traditional LED billboard glowing intensely, "
            "power cables visible, heat haze, harsh blue-white light, "
            "electric meter spinning fast in foreground. "
            "RIGHT HALF: same street, dawn, a slim pole-mounted information panel, "
            "small solar panel on top, no cables, calm matte surface reading clearly "
            "in morning light — a woman in coat walks past, glances up naturally. "
            "The contrast is obvious without explanation. "
            "Film photography aesthetic, slight grain, documentary. 9:16 vertical."
        ),
    },
    {
        "ct": ["eco_fact"],
        "story": "RAIN AND POWER",
        "prompt": (
            "Cinematic still, 50mm f/2, overcast soft light. "
            "Belgrade park after heavy rain. Puddles on stone paths, wet leaves, "
            "grey-green atmosphere. Everything is damp. "
            "Center of frame: a slim modern information totem on a pole, "
            "small solar panel angled upward, droplets on the glass — "
            "but the panel still captures diffuse light. "
            "A young father with child in rain jacket stands nearby looking at it. "
            "Background: dripping trees, empty benches, misty city. "
            "The totem is powered. Working. Unbothered by weather. "
            "Leica documentary style, natural color. 9:16 vertical."
        ),
    },
    # ══════════════════════════════════════════════════════════════
    # ESG: УМНЫЙ ТРАНСПОРТ И ГОРОД
    # ══════════════════════════════════════════════════════════════
    {
        "ct": ["urban_case"],
        "story": "COMMUTER RELIEF",
        "prompt": (
            "Street photography, 35mm f/1.8, morning rush hour. "
            "Belgrade bus terminal, 7:45am. Overcast grey sky. "
            "A tired office worker — blazer, bag on shoulder — looks up at "
            "an information display panel on a pole, reads the departure time. "
            "His posture shifts: shoulders drop, slight exhale of relief. "
            "He has enough time. He puts his phone back in his pocket. "
            "Around him: blurred commuters in motion, buses, city movement. "
            "He is the still point. The display gave him certainty. "
            "Fujifilm X-T4 aesthetic, slight warm grade. 9:16 vertical."
        ),
    },
    {
        "ct": ["urban_case"],
        "story": "SCHOOL KIDS AND THE SCHEDULE",
        "prompt": (
            "Documentary photograph, 35mm f/2.8. "
            "Serbian town bus stop, afternoon. Three school kids aged 10-12 "
            "with backpacks crowd around an outdoor information display. "
            "One points at something on the screen, another laughs, third checks watch. "
            "Normal kid interaction with city infrastructure — natural, unposed. "
            "Background: residential street, trees in autumn colors, parked cars. "
            "Soft afternoon light from left. "
            "Warm tones, slightly desaturated. Documentary, NOT advertising. 9:16 vertical."
        ),
    },
    {
        "ct": ["urban_case", "installation"],
        "story": "NIGHT CITY INFORMATION",
        "prompt": (
            "Cinematic night photography, 50mm f/1.4, available light only. "
            "Belgrade side street, 22:30. Amber streetlights, wet pavement, quiet. "
            "A slim information totem stands on the sidewalk — "
            "its panel visible, matte surface, no glow emanating outward, "
            "just clear information readable in ambient light. "
            "A nurse in scrubs, end of night shift, bag over shoulder, "
            "reads the display. Small moment in a big city. "
            "Background: blurred car headlights as bokeh, apartment windows with warm light. "
            "Moody, human, real. Magnum Photos aesthetic. 9:16 vertical."
        ),
    },
    # ══════════════════════════════════════════════════════════════
    # ESG: ПРИРОДА И НАЦИОНАЛЬНЫЕ ПАРКИ
    # ══════════════════════════════════════════════════════════════
    {
        "ct": ["installation", "urban_case"],
        "story": "DJERDAP TRAIL DISCOVERY",
        "prompt": (
            "Nature documentary photograph, 35mm f/4, morning golden light. "
            "Djerdap national park, Serbia. Rocky trail above the Danube river, "
            "green forest, dramatic gorge view in background. "
            "Center of path: a wooden post with a slim weatherproof information panel, "
            "solar cell integrated on top, showing a trail map in bold black lines. "
            "A hiker in 30s — backpack, trekking poles — studies it carefully, "
            "finger tracing a route on the screen. "
            "Behind him: endless green forest, Danube far below catching sunlight. "
            "National Geographic quality. Real location feel. 9:16 vertical."
        ),
    },
    {
        "ct": ["eco_fact", "installation"],
        "story": "ZERO CABLES IN NATURE",
        "prompt": (
            "Wide environmental portrait, 24mm f/5.6, midday clear sky. "
            "Serbian national park clearing. Blue sky, white clouds, tall pine trees. "
            "A park ranger in uniform stands beside a slim autonomous information totem — "
            "no power cables, no internet cables, just a pole with a solar panel on top "
            "and a clean display panel showing park rules and wildlife info. "
            "The ranger's hand rests casually on the pole, looking into the distance. "
            "The message: technology that belongs in nature. "
            "Clean, wide, honest. Not a product photo. An environmental portrait. "
            "Documentary style. 9:16 vertical."
        ),
    },
    # ══════════════════════════════════════════════════════════════
    # ESG: МУНИЦИПАЛЬНОЕ УПРАВЛЕНИЕ
    # ══════════════════════════════════════════════════════════════
    {
        "ct": ["comparison", "eco_fact"],
        "story": "PAPER IS OVER",
        "prompt": (
            "Editorial documentary, 35mm f/2.8, overcast flat light. "
            "Serbian municipal building exterior. "
            "A city worker removes a stack of old paper notices from a noticeboard — "
            "yellowed, rain-damaged, some half-torn. His expression: matter-of-fact. "
            "Behind him on the wall: a newly installed slim digital panel, "
            "clean, showing current municipal announcements, readable at 10 meters. "
            "The pile of old paper is large. The new panel is small and neat. "
            "Story told without words. "
            "Color: muted, slightly cold. Documentary, real. 9:16 vertical."
        ),
    },
    {
        "ct": ["urban_case", "behind_scenes"],
        "story": "MAYOR APPROVES",
        "prompt": (
            "Press photography style, 50mm f/2.8, natural indoor-outdoor light. "
            "Serbian city square, official ceremony atmosphere. "
            "A city official in a suit — 50s, confident posture — stands "
            "beside a freshly installed public information display. "
            "He looks at it, not at the camera. One hand gestures toward it "
            "as if explaining something to someone off-frame. "
            "Background: blurred city hall architecture, Serbian flag, "
            "a small crowd of local residents watching. "
            "Feels like a Reuters photo. Completely real. "
            "Color grading: neutral, professional. 9:16 vertical."
        ),
    },
    # ══════════════════════════════════════════════════════════════
    # ESG: ИНКЛЮЗИВНОСТЬ И ДОСТУПНОСТЬ
    # ══════════════════════════════════════════════════════════════
    {
        "ct": ["urban_case"],
        "story": "ELDERLY INDEPENDENCE",
        "prompt": (
            "Intimate documentary photograph, 85mm f/2, warm afternoon light. "
            "Belgrade park, autumn. "
            "An elderly woman — 70s, elegant coat, walking stick — stands at "
            "an outdoor information kiosk reading the screen. "
            "She holds reading glasses to her eyes. Her expression: focused, independent. "
            "She doesn't need to ask anyone for help. The information is there, "
            "clear and readable in full daylight. "
            "Background: fallen leaves, park benches, blurred walkers. "
            "Humanist photography style — Cartier-Bresson quiet moment. "
            "Warm autumn palette. 9:16 vertical."
        ),
    },
    {
        "ct": ["urban_case", "eco_fact"],
        "story": "TOURIST CONFIDENCE",
        "prompt": (
            "Travel documentary photograph, 35mm f/2.8, bright daylight. "
            "Novi Sad old town, cobblestone square. "
            "Two tourists — 30s couple, different nationalities — stand at "
            "a city information point. One points at the panel screen, "
            "the other types something on phone (cross-referencing). "
            "They're smiling, oriented, not lost. "
            "Background: Novi Sad architecture, cafe umbrellas, other tourists passing. "
            "Bright summer light, warm colors. "
            "Feels like a Lonely Planet editorial photo. 9:16 vertical."
        ),
    },
    # ══════════════════════════════════════════════════════════════
    # ESG: АТМОСФЕРНЫЕ / ЭМОЦИОНАЛЬНЫЕ
    # ══════════════════════════════════════════════════════════════
    {
        "ct": ["eco_fact", "product_shot"],
        "story": "THE QUIET CITY",
        "prompt": (
            "Fine art photography, 24mm f/8, blue hour. "
            "Belgrade empty boulevard at 6am, before the city wakes. "
            "Wide angle: beautiful symmetrical street, bare trees in fog, "
            "street lights still on, faint blue dawn sky. "
            "On the right side of the frame: a single slim information totem "
            "standing on the sidewalk, autonomous, quiet, already working. "
            "No people. Just the city and its infrastructure. "
            "The totem is a small detail — but it's there. Permanent. Reliable. "
            "Long exposure feel, very still. Moody, cinematic. "
            "Wim Wenders visual language. 9:16 vertical."
        ),
    },
    {
        "ct": ["comparison", "eco_fact"],
        "story": "HOT SUMMER READ",
        "prompt": (
            "Street photography, 35mm f/2, harsh summer noon. "
            "Serbian city street, 38 degrees, full sun. "
            "A man in short sleeves squints at his phone — screen washed out "
            "by direct sunlight, hand shielding screen, frustrated. "
            "Two meters behind him: a woman reads an outdoor information panel "
            "without any shade, no squinting, screen clearly visible. She moves on. "
            "Same sun. Different experience. "
            "No staging — this is just life. Documentary. "
            "Hard light, deep shadows, intense summer color. 9:16 vertical."
        ),
    },
]


def _build_stability_prompt(caption_data: dict) -> str:
    """Выбирает кинематографическую story-сцену под content_type.
    Если в caption_data уже задан video_prompt — использует его напрямую.
    """
    explicit = caption_data.get("video_prompt") or caption_data.get("_scene_prompt")
    if explicit:
        return explicit
    return pick_esg_scene_prompt(caption_data)


def pick_esg_scene_prompt(caption_data: dict) -> str:
    """Публичная функция: возвращает ESG story-сцену из STORY_SCENES под content_type.

    Используется как для Stability AI изображений, так и для видео-генераторов
    (Runway, Luma, Kling и т.д.) — вместо свободного LLM-генерированного video_prompt.
    """
    import random
    ct = caption_data.get("content_type", "urban_case")

    matching = [s for s in STORY_SCENES if ct in s["ct"]]
    if not matching:
        matching = STORY_SCENES  # fallback — любая сцена

    scene = random.choice(matching)
    print(f"  📖 Story: {scene['story']}")
    return scene["prompt"]


def generate_image_stability(prompt: str = "", caption_data: dict | None = None) -> Path | None:
    """Генерирует AI-изображение через Stability AI SD3.5 (9:16).
    Если передан caption_data — строит специализированный e-ink промпт.
    """
    if not STABILITY_API_KEY or _is_service_down("stability"):
        return None
    import requests as req

    final_prompt = (
        _build_stability_prompt(caption_data)
        if caption_data
        else prompt
    )
    print(f"  🎨 Stability SD3.5: {final_prompt[:100]}...")
    try:
        r = req.post(
            "https://api.stability.ai/v2beta/stable-image/generate/sd3",
            headers={"Authorization": f"Bearer {STABILITY_API_KEY}", "Accept": "image/*"},
            files={"none": ""},
            data={
                "prompt": final_prompt,
                "negative_prompt": (
                    "LCD screen, glowing screen, backlit display, LED billboard, neon signs, "
                    "CGI render, 3D visualization, plastic frame, shiny reflective surface, "
                    "text on screen, brand logo, watermark, ugly, blurry, distorted, "
                    "overexposed, underexposed, grainy, low quality, amateur, snapshot, "
                    "cartoon, illustration, painting, drawing, anime, synthetic"
                ),
                "model": "sd3.5-large",
                "output_format": "jpeg",
                "aspect_ratio": "9:16",
            },
            timeout=120,
        )
        if r.status_code == 200 and len(r.content) > 10000:
            out = OUTPUT_DIR / f"stability_{int(time.time())}.jpg"
            out.write_bytes(r.content)
            _mark_service_up("stability")
            print(f"  ✅ Stability: {out.name} ({out.stat().st_size // 1024}KB)")
            return out
        elif r.status_code in (402, 429):
            _mark_service_down("stability", f"{r.status_code} credits/quota exhausted")
            print(f"  ⚠️  Stability: кредиты исчерпаны")
        else:
            print(f"  Stability ошибка: {r.status_code} {r.text[:100]}")
    except Exception as e:
        print(f"  Stability исключение: {e}")
    return None


def _ai_image_to_reel(image_path: Path, caption_data: dict | None = None) -> Path | None:
    """AI-изображение → Reel через Ken Burns + музыка."""
    kb = create_ken_burns_reel(image_path, duration=15)
    if not kb or not kb.exists():
        return None
    music_prompt = (
        caption_data.get("music_hint", "") if caption_data else ""
    ) or "upbeat ambient electronic music eco smart city positive energy"
    music = generate_music_ai(music_prompt, duration=16)
    if music:
        result = _add_music_to_video(kb, music)
        kb.unlink(missing_ok=True)
        music.unlink(missing_ok=True)
        return result
    return kb


def generate_media_with_fallback(
    video_prompt: str,
    source_image: Path | None = None,
    preferred_mode: str = "auto",
    caption_data: dict | None = None,
) -> tuple[Path | None, str]:
    """
    Пайплайн генерации медиа:
      1. AI-видео + AI-музыка  → video
      2. Комикс (AI рисунок)   → photo (comic)
      3. AI-фото Pollinations  → photo
      Реальные фото из /content/ НЕ используются.

    Возвращает (path, media_type) где media_type = "video" | "comic" | "photo" | "none"
    """
    video_chain = []
    if preferred_mode in ("auto", "video"):
        video_chain = [
            ("replicate", lambda: generate_video_replicate(video_prompt, source_image)),
            ("veo",       lambda: generate_video_veo(video_prompt, source_image)),
            ("hf",        lambda: generate_video_hf(video_prompt, source_image)),
            ("luma",      lambda: generate_video_luma(video_prompt, source_image)),
            ("kling",     lambda: generate_video_kling(video_prompt, source_image)),
            ("runway",    lambda: generate_video_runway(video_prompt, source_image)),
        ]
    elif preferred_mode == "runway":
        video_chain = [("runway", lambda: generate_video_runway(video_prompt, source_image)),
                       ("luma",   lambda: generate_video_luma(video_prompt, source_image)),
                       ("kling",  lambda: generate_video_kling(video_prompt, source_image)),
                       ("hf",     lambda: generate_video_hf(video_prompt, source_image))]
    elif preferred_mode == "luma":
        video_chain = [("luma",   lambda: generate_video_luma(video_prompt, source_image)),
                       ("hf",     lambda: generate_video_hf(video_prompt, source_image)),
                       ("kling",  lambda: generate_video_kling(video_prompt, source_image)),
                       ("runway", lambda: generate_video_runway(video_prompt, source_image))]
    elif preferred_mode == "kling":
        video_chain = [("kling",  lambda: generate_video_kling(video_prompt, source_image)),
                       ("hf",     lambda: generate_video_hf(video_prompt, source_image)),
                       ("luma",   lambda: generate_video_luma(video_prompt, source_image)),
                       ("runway", lambda: generate_video_runway(video_prompt, source_image))]
    elif preferred_mode == "hf":
        video_chain = [("hf",     lambda: generate_video_hf(video_prompt, source_image)),
                       ("kling",  lambda: generate_video_kling(video_prompt, source_image)),
                       ("luma",   lambda: generate_video_luma(video_prompt, source_image)),
                       ("runway", lambda: generate_video_runway(video_prompt, source_image))]
    elif preferred_mode == "veo":
        video_chain = [("veo",    lambda: generate_video_veo(video_prompt, source_image)),
                       ("hf",     lambda: generate_video_hf(video_prompt, source_image)),
                       ("luma",   lambda: generate_video_luma(video_prompt, source_image)),
                       ("runway", lambda: generate_video_runway(video_prompt, source_image))]

    # === ФАЗА 1: AI-видео + музыка ===
    for provider_name, generator in video_chain:
        if _is_service_down(provider_name):
            print(f"  ⏭  {provider_name} пропущен (недоступен)")
            continue
        print(f"  🎬 Пробую видео: {provider_name}...")
        try:
            path = generator()
            if path and path.exists() and path.stat().st_size > 10000:
                print(f"  ✅ Видео готово через {provider_name}")
                _mark_service_up(provider_name)
                # Добавляем AI-музыку
                music_prompt = (
                    caption_data.get("music_hint", "")
                    or "upbeat ambient electronic music, eco smart city, positive energy, 15 seconds"
                ) if caption_data else "upbeat ambient electronic music eco city"
                music = generate_music_ai(music_prompt, duration=15)
                if music:
                    path = _add_music_to_video(path, music)
                    music.unlink(missing_ok=True)
                return path, "video"
        except Exception as e:
            err = str(e)
            if any(x in err.lower() for x in ("403", "401", "not authenticated", "exhausted balance",
                                               "no credits", "no enough credits", "resource_exhausted", "insufficient")):
                _mark_service_down(provider_name, err[:80])
            else:
                print(f"  {provider_name} исключение: {e}")

    # === ФАЗА 2: Stability SD3.5 × 3 → Multi-photo reel + музыка ===
    print("  ⚠️  Все видео-генераторы недоступны — генерирую 3 AI-фото (Stability)...")
    stab_imgs = []
    # Генерируем 3 фото с разными scene_hint для разнообразия
    # Берём 3 разные сцены из STORY_SCENES без повторов
    import random as _rnd
    ct = (caption_data or {}).get("content_type", "urban_case")
    matching_scenes = [s for s in STORY_SCENES if ct in s["ct"]] or STORY_SCENES
    chosen_scenes = _rnd.sample(matching_scenes, min(3, len(matching_scenes)))
    if len(chosen_scenes) < 3:
        # дополняем из полного пула если типов мало
        extras = [s for s in STORY_SCENES if s not in chosen_scenes]
        chosen_scenes += _rnd.sample(extras, min(3 - len(chosen_scenes), len(extras)))

    pan_labels = ["wide establishing shot", "close-up detail shot", "human interaction shot"]
    for i, scene in enumerate(chosen_scenes):
        cd_variant = dict(caption_data or {})
        cd_variant["video_prompt"] = scene["prompt"] + f", {pan_labels[i]}"
        cd_variant["_scene_story"] = scene["story"]
        print(f"  📖 Story {i+1}: {scene['story']}")
        img = generate_image_stability(prompt=scene["prompt"], caption_data=cd_variant)
        if img:
            stab_imgs.append(img)

    if stab_imgs:
        if len(stab_imgs) >= 2:
            kb = create_multi_photo_reel(stab_imgs, duration=28)
        else:
            kb = create_ken_burns_reel(stab_imgs[0], duration=28)
        for img in stab_imgs:
            img.unlink(missing_ok=True)
        if kb and kb.exists():
            music_prompt = (caption_data.get("music_hint", "") if caption_data else "") or "ambient electronic eco city"
            music = generate_music_ai(music_prompt, duration=29)
            if music:
                result = _add_music_to_video(kb, music)
                kb.unlink(missing_ok=True)
                music.unlink(missing_ok=True)
                if result and result.exists():
                    print(f"  ✅ Multi-photo Reel из Stability: {result.name}")
                    return result, "video"
            print(f"  ✅ Reel из Stability: {kb.name}")
            return kb, "video"

    # === ФАЗА 3: Pollinations → Ken Burns + музыка ===
    print("  ⚠️  Stability недоступен — пробую Pollinations...")
    ct = caption_data.get("content_type") if caption_data else None
    poll_img = _generate_photo_ai_only(video_prompt, source_image=None,
                                        caption_data=caption_data, content_type=ct)
    if poll_img and poll_img.exists():
        reel = _ai_image_to_reel(poll_img, caption_data)
        poll_img.unlink(missing_ok=True)
        if reel and reel.exists():
            print(f"  ✅ Reel из Pollinations: {reel.name}")
            return reel, "video"

    # === ФАЗА 4: lavfi animated gradient (без API) ===
    print("  ⚠️  Все фото-генераторы недоступны — lavfi animated gradient...")
    lavfi = create_lavfi_motion_reel(caption_data=caption_data, duration=28)
    if lavfi and lavfi.exists():
        music_prompt = (caption_data.get("music_hint", "") if caption_data else "") or "ambient electronic eco city"
        music = generate_music_ai(music_prompt, duration=29)
        if music:
            result = _add_music_to_video(lavfi, music)
            lavfi.unlink(missing_ok=True)
            music.unlink(missing_ok=True)
            if result and result.exists():
                print(f"  ✅ Lavfi reel с музыкой: {result.name}")
                return result, "video"
        return lavfi, "video"

    return None, "none"


def save_image_package(image_path: Path, caption_data: dict, source: str) -> Path:
    """Сохраняет пакет фото-поста (для Instagram карусели/одиночного фото)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    title_slug = caption_data.get("post_title", "photo_post").replace(" ", "_")[:30]
    package_dir = OUTPUT_DIR / f"{ts}_{title_slug}"
    package_dir.mkdir(exist_ok=True)

    # Накладываем логотип на фото
    dest = package_dir / "post.jpg"
    logo_path = Path("/root/Ecodisplays/image006.png")
    if logo_path.exists():
        cmd = [
            "ffmpeg", "-i", str(image_path), "-i", str(logo_path),
            "-filter_complex",
            "[1:v]scale=iw*0.15:-1[logo];[0:v][logo]overlay=W-w-30:H-h-30",
            "-y", str(dest)
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            shutil.copy(image_path, dest)
        else:
            print("  Логотип на фото наложен ✓")
    else:
        shutil.copy(image_path, dest)

    meta = {
        "generated_at": datetime.now().isoformat(),
        "source": source,
        "status": "pending_approval",
        "post_type": "photo",
        **caption_data,
    }
    with open(package_dir / "post_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    caption_text = f"{caption_data['caption_sr']}\n\n{caption_data['caption_en']}\n\n{' '.join(caption_data['hashtags'])}"
    (package_dir / "caption.txt").write_text(caption_text, encoding="utf-8")

    print(f"\n✅ Фото-пакет сохранён: {package_dir}")
    print(f"   Фото: {dest.name}")
    print(f"   Подпись (SR): {caption_data['caption_sr'][:80]}...")

    return package_dir


def process_existing_video(video_path: Path, caption_text: str) -> Path:
    """Конвертирует видео в H.264 для Reels без изменения размера (сохраняет оригинальные пропорции)."""
    out_path = OUTPUT_DIR / f"reel_{int(time.time())}.mp4"

    # Перекодируем без изменения размера — rotation metadata сохраняется как есть.
    # Принудительный scale=1080:1920 растягивает видео если пиксели хранятся в другой ориентации.
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-t", "60",
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-y", str(out_path)
    ]

    print(f"  Обрабатываю видео: {video_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ffmpeg ошибка, копирую исходник: {result.stderr[-200:]}")
        shutil.copy(video_path, out_path)

    return out_path


def create_ken_burns_reel(image_path: Path, duration: int = 8) -> Path | None:
    """
    Ken Burns Reel из одного фото — zoom + pan через ffmpeg.
    Формат 9:16 (1080x1920) для Instagram Reels.
    Не требует внешних API, работает всегда.
    """
    out_path = OUTPUT_DIR / f"reel_kb_{int(time.time())}.mp4"

    # zoompan: медленный zoom in — кинематографично, 9:16 для Reels
    d = duration * 25
    vf = (
        f"scale=1920:1920:force_original_aspect_ratio=increase,"
        f"crop=1920:1920,"
        f"zoompan=z='min(zoom+0.0008,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s=1080x1920:fps=25"
    )

    cmd = [
        "ffmpeg", "-loop", "1", "-i", str(image_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "25",
        "-an", "-y", str(out_path)
    ]

    print(f"  Ken Burns Reel из: {image_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if out_path.exists() and out_path.stat().st_size > 50000:
        print(f"  Ken Burns готово: {out_path} ({out_path.stat().st_size // 1024}KB)")
        return out_path
    print(f"  Ken Burns ошибка: {result.stderr[-150:]}")
    return None


def create_photo_slideshow(image_path: Path, duration: int = 10) -> Path:
    """Создаёт короткое видео из одного фото (legacy fallback)."""
    return create_ken_burns_reel(image_path, duration) or (OUTPUT_DIR / "empty.mp4")


def create_multi_photo_reel(images: list[Path], duration: int = 28) -> Path | None:
    """
    Несколько фото → Reel с Ken Burns на каждом + xfade между ними.
    Намного живее одиночного zoom. duration распределяется равномерно.
    """
    images = [p for p in images if p.exists() and p.stat().st_size > 5000]
    if not images:
        return None
    if len(images) == 1:
        return create_ken_burns_reel(images[0], duration)

    out_path = OUTPUT_DIR / f"reel_multi_{int(time.time())}.mp4"
    n = len(images)
    per_clip = duration / n          # секунд на фото
    xfade_dur = min(0.8, per_clip * 0.2)  # длительность перехода
    fps = 25

    # Шаг 1: генерируем Ken Burns клип для каждого фото
    clips = []
    for i, img in enumerate(images):
        clip = OUTPUT_DIR / f"_kb_{i}_{int(time.time())}.mp4"
        d = int(per_clip + xfade_dur)  # чуть длиннее для xfade
        frames = d * fps
        # Разные направления pan для разнообразия
        if i % 4 == 0:
            pan = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"  # centre zoom
        elif i % 4 == 1:
            pan = "x='iw/2-(iw/zoom/2)':y=0"  # zoom + pan down
        elif i % 4 == 2:
            pan = "x=0:y='ih/2-(ih/zoom/2)'"  # zoom + pan right
        else:
            pan = "x='iw-(iw/zoom)':y='ih-(ih/zoom)'"  # zoom + pan diagonal (bottom-right)
        vf = (
            f"scale=1920:1920:force_original_aspect_ratio=increase,"
            f"crop=1920:1920,"
            f"zoompan=z='min(zoom+0.0010,1.35)':{pan}:d={frames}:s=1080x1920:fps={fps}"
        )
        r = subprocess.run([
            "ffmpeg", "-loop", "1", "-i", str(img),
            "-t", str(d), "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-an", "-y", str(clip),
        ], capture_output=True)
        if clip.exists() and clip.stat().st_size > 10000:
            clips.append(clip)

    if not clips:
        return None
    if len(clips) == 1:
        clips[0].rename(out_path)
        return out_path

    # Шаг 2: склеиваем через xfade
    # Строим filter_complex: [0][1]xfade → [01]; [01][2]xfade → [012] ...
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]

    XFADE_TRANSITIONS = ["fade", "wipeleft", "wiperight", "slideleft", "dissolve", "fadegrays"]
    filter_parts = []
    offset = per_clip - xfade_dur
    prev = "[0:v]"
    for i in range(1, len(clips)):
        tag = f"[v{i}]"
        tr = XFADE_TRANSITIONS[(i - 1) % len(XFADE_TRANSITIONS)]
        filter_parts.append(
            f"{prev}[{i}:v]xfade=transition={tr}:duration={xfade_dur:.2f}:offset={offset:.2f}{tag}"
        )
        prev = tag
        offset += per_clip - xfade_dur

    filter_str = ";".join(filter_parts)
    final_tag = prev

    cmd = ["ffmpeg"] + inputs + [
        "-filter_complex", filter_str,
        "-map", final_tag,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(fps), "-an", "-y", str(out_path),
    ]
    print(f"  📽  Multi-photo reel: {len(clips)} фото с xfade...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    for c in clips:
        c.unlink(missing_ok=True)

    if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 50000:
        print(f"  ✅ Multi-photo reel готов: {out_path.name} ({out_path.stat().st_size // 1024}KB)")
        return out_path
    print(f"  ⚠️  Multi-photo xfade ошибка: {r.stderr[-200:]}")
    return None


def create_lavfi_motion_reel(caption_data: dict | None = None, duration: int = 28) -> Path | None:
    """
    Чистый ffmpeg lavfi motion-reel — animated gradient (geq filter).
    Палитра: тёмно-зелёный/бирюзовый — eco тематика.
    Не требует никаких API. Абсолютный последний fallback.
    """
    out_path = OUTPUT_DIR / f"reel_lavfi_{int(time.time())}.mp4"
    geq_expr = (
        "r='80+40*sin(2*PI*(X/1080+T*0.12))*cos(2*PI*(Y/1920+T*0.07))':"
        "g='120+60*sin(2*PI*(X/540+T*0.09)+1.2)*sin(2*PI*(Y/960+T*0.05))':"
        "b='100+50*cos(2*PI*(X/720+T*0.15)+2.4)'"
    )
    cmd = [
        "ffmpeg",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=25",
        "-vf", f"geq={geq_expr}",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "25", "-an", "-y", str(out_path),
    ]
    print("  🌊 Lavfi motion reel (animated gradient)...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 10000:
        print(f"  ✅ Lavfi reel готов: {out_path.name}")
        return out_path
    print(f"  ⚠️  Lavfi ошибка: {r.stderr[-100:]}")
    return None


def save_post_package(video_path: Path, caption_data: dict, source: str) -> Path:
    """Сохраняет пакет поста: видео + JSON с подписью."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    title_slug = caption_data.get("post_title", "post").replace(" ", "_")[:30]
    package_dir = OUTPUT_DIR / f"{ts}_{title_slug}"
    package_dir.mkdir(exist_ok=True)

    # Накладываем логотип и сохраняем как reel.mp4
    video_dest = package_dir / "reel.mp4"
    logo_path = Path("/root/Ecodisplays/image006.png")  # логотип компании
    if logo_path.exists():
        # Логотип в правом нижнем углу, 20% ширины видео, отступ 40px
        cmd = [
            "ffmpeg", "-i", str(video_path), "-i", str(logo_path),
            "-filter_complex",
            "[1:v]scale=iw*0.18:-1[logo];[0:v][logo]overlay=W-w-40:H-h-40",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-c:a", "copy", "-movflags", "+faststart",
            "-y", str(video_dest)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  Логотип overlay ошибка, копирую без лого: {result.stderr[-100:]}")
            shutil.copy(video_path, video_dest)
        else:
            print(f"  Логотип наложен ✓")
    else:
        shutil.copy(video_path, video_dest)

    # Сохраняем метаданные
    meta = {
        "generated_at": datetime.now().isoformat(),
        "source": source,
        "status": "pending_approval",
        **caption_data
    }
    with open(package_dir / "post_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Удобный текстовый файл для копипасты
    caption_text = f"{caption_data['caption_sr']}\n\n{caption_data['caption_en']}\n\n{' '.join(caption_data['hashtags'])}"
    (package_dir / "caption.txt").write_text(caption_text, encoding="utf-8")

    print(f"\n✅ Пакет поста сохранён: {package_dir}")
    print(f"   Видео: {video_dest.name}")
    print(f"   Подпись (SR): {caption_data['caption_sr'][:80]}...")
    print(f"   Хештегов: {len(caption_data['hashtags'])}")

    return package_dir


def main():
    parser = argparse.ArgumentParser(description="Генератор Reels для Ecodisplays")
    parser.add_argument("--mode", choices=["runway", "luma", "hf", "kling", "veo", "video", "photo"], default="video",
                        help="runway=Runway ML Gen-3, luma=Luma Dream Machine, hf=HuggingFace, kling=Kling AI, veo=Google Veo 2, video=готовое видео, photo=фото→слайд")
    parser.add_argument("--source", type=str, help="Путь к исходному файлу")
    parser.add_argument("--topic", type=str, help="Тема поста (если нет исходника)")
    args = parser.parse_args()

    # Определяем исходник
    source_path = None
    if args.source:
        source_path = Path(args.source)
        if not source_path.is_absolute():
            source_path = Path("/root/Ecodisplays") / source_path
        if not source_path.exists():
            print(f"Файл не найден: {source_path}")
            sys.exit(1)

    print(f"\n🎬 Генерирую Reel (mode={args.mode})")
    print("=" * 50)

    # Шаг 1: Генерируем caption
    print("1. Генерирую подпись через GPT-4o...")
    image_for_gpt = source_path if source_path and source_path.suffix.lower() in [".jpg", ".jpeg", ".png"] else None
    caption_data = generate_caption(image_path=image_for_gpt, topic=args.topic)
    print(f"   Тип контента: {caption_data.get('content_type')}")
    print(f"   Video prompt: {caption_data.get('video_prompt', '')[:80]}...")

    # Шаг 2: Генерируем/обрабатываем видео
    print("\n2. Подготавливаю видео...")
    video_path = None

    video_prompt = caption_data.get("video_prompt", "E-ink outdoor display in urban environment, cinematic 9:16")

    if args.mode == "runway":
        video_path = generate_video_runway(prompt=video_prompt, source_image=image_for_gpt)
        if not video_path:
            print("   Runway недоступен, переключаюсь на photo mode...")
            args.mode = "photo"

    if args.mode == "luma":
        video_path = generate_video_luma(prompt=video_prompt, source_image=image_for_gpt)
        if not video_path:
            print("   Luma недоступен, переключаюсь на photo mode...")
            args.mode = "photo"

    if args.mode == "hf":
        video_path = generate_video_hf(prompt=video_prompt, source_image=image_for_gpt)
        if not video_path:
            print("   HF недоступен, переключаюсь на photo mode...")
            args.mode = "photo"

    if args.mode == "kling":
        video_path = generate_video_kling(prompt=video_prompt, source_image=image_for_gpt)
        if not video_path:
            print("   Kling недоступен, переключаюсь на photo mode...")
            args.mode = "photo"

    if args.mode == "veo":
        video_path = generate_video_veo(prompt=video_prompt, source_image=image_for_gpt)
        if not video_path:
            print("   Veo недоступен, переключаюсь на photo mode...")
            args.mode = "photo"

    if args.mode == "video" and source_path:
        video_path = process_existing_video(source_path, caption_data.get("caption_en", ""))


    if args.mode == "photo" or (not video_path and source_path):
        img_path = image_for_gpt or source_path
        if img_path:
            video_path = create_photo_slideshow(img_path)
        else:
            print("Нет исходника для photo mode. Укажи --source path/to/image.jpg")
            sys.exit(1)

    if not video_path or not video_path.exists():
        print("Не удалось создать видео")
        sys.exit(1)

    # Шаг 3: Сохраняем пакет
    print("\n3. Сохраняю пакет поста...")
    package_dir = save_post_package(video_path, caption_data, str(source_path or "generated"))

    print(f"\n📂 Готово! Открой папку: {package_dir}")
    print("   Следующий шаг: проверь caption.txt, затем опубликуй reel.mp4 вручную или через Meta API")


PENDING_COMIC_FILE = OUTPUT_DIR / "pending_comic.json"


def send_comic_prompt_to_telegram(caption_data: dict, video_prompt: str) -> bool:
    """Отправляет промпт для комикса в Telegram и сохраняет состояние ожидания.

    Вызывается когда все видео-генераторы недоступны.
    Пользователь генерирует изображение и отправляет его обратно в бот.
    Бот создаёт пост-пакет из присланного фото.
    """
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID")
    if not tg_token or not tg_chat:
        print("  Telegram не настроен — не могу отправить comic-запрос")
        return False

    try:
        import requests as req

        ct = caption_data.get("content_type", "urban_case")
        sr_preview = caption_data.get("caption_sr", "")[:120]
        en_preview = caption_data.get("caption_en", "")[:80]

        # Адаптируем промпт под иллюстрацию / комикс-стиль
        comic_prompt = (
            f"{video_prompt.rstrip('.')}. "
            "Comic illustration style, bold outlines, vibrant colors, "
            "4-panel comic strip layout, clean white gutters between panels, "
            "professional graphic novel art, 1:1 square format."
        )

        msg = (
            "🎨 *Все видео-генераторы недоступны* — нужна твоя помощь!\n\n"
            f"📋 Тип контента: `{ct}`\n\n"
            "Вот промпт для Midjourney / DALL-E / любого AI:\n\n"
            f"`{comic_prompt[:600]}`\n\n"
            f"🇷🇸 _{sr_preview}_\n\n"
            f"🇬🇧 _{en_preview}_\n\n"
            "Сгенерируй изображение и пришли его сюда — я автоматически сделаю пост и отправлю на одобрение ✅"
        )

        resp = req.post(
            f"https://api.telegram.org/bot{tg_token}/sendMessage",
            json={"chat_id": tg_chat, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        if not resp.ok:
            print(f"  Telegram comic-запрос ошибка: {resp.text[:100]}")
            return False

        # Сохраняем состояние — caption_data ждёт фото от пользователя
        PENDING_COMIC_FILE.write_text(json.dumps({
            "caption_data": caption_data,
            "video_prompt": video_prompt,
            "comic_prompt": comic_prompt,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=2))

        print("  📨 Comic-запрос отправлен в Telegram — жду фото от пользователя")
        return True

    except Exception as e:
        print(f"  send_comic_prompt_to_telegram ошибка: {e}")
        return False


if __name__ == "__main__":
    main()
