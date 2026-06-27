"""
EcoDisplays Comic Strip Generator

Генерирует 4-панельные комикс-стрипы о продукте EcoDisplays.
Каждая панель генерируется через Pollinations (flux), затем склеивается
в единое изображение 1080x1080 через Pillow.

Запуск:
  python3 generate_comic.py                   # случайный сценарий
  python3 generate_comic.py --scenario 2      # конкретный сценарий (1-N)
  python3 generate_comic.py --list            # список сценариев
  python3 generate_comic.py --output /tmp/out # своя папка вывода
"""

import os
import sys
import time
import json
import random
import argparse
import textwrap
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
OUTPUT_DIR.mkdir(exist_ok=True)

HF_TOKEN = os.getenv("HF_TOKEN")

OPENROUTER_TEXT_MODELS = [
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
]

# ── Размеры итогового изображения ──────────────────────────────────────────
COMIC_W = 1080
COMIC_H = 1080
PANEL_W = 540   # 2 колонки
PANEL_H = 540   # 2 строки
BORDER = 6      # толщина рамки панели
BUBBLE_PADDING = 14
FONT_SIZE = 22
CAPTION_FONT_SIZE = 18

# ── Палитра бренда ─────────────────────────────────────────────────────────
COLOR_BG = (15, 15, 20)          # фон комикса
COLOR_BORDER = (0, 200, 120)     # зелёная рамка EcoDisplays
COLOR_BUBBLE_BG = (255, 255, 255)
COLOR_BUBBLE_TEXT = (20, 20, 20)
COLOR_CAPTION_BG = (0, 0, 0, 180)
COLOR_CAPTION_TEXT = (255, 255, 255)
COLOR_PANEL_NUM = (0, 200, 120)

# ── Сценарии комиксов ──────────────────────────────────────────────────────
SCENARIOS = [
    {
        "id": 1,
        "title": "Счёт за электричество",
        "caption_sr": "EcoDisplays — 111 пута мање потрошње него LCD! ☀️",
        "caption_en": "111x less energy than LCD. Solar-powered outdoor display.",
        "panels": [
            {
                "scene": "shocked city official huge electricity bill LED billboard night comic bold outlines",
                "bubble": "€500 за струjу?! Сваки месец?!",
                "label": "1. Problem",
            },
            {
                "scene": "salesman presents slim e-ink outdoor display city park sunny comic bold outlines",
                "bubble": "Погледајте EcoDisplays — само 3W!",
                "label": "2. Rešenje",
            },
            {
                "scene": "outdoor e-ink display solar panel no wires sunny plaza comic bold outlines green",
                "bubble": "Соларно! Без кабла!",
                "label": "3. Solarna energija",
            },
            {
                "scene": "smiling official holds tiny bill EcoDisplays screen city background comic bold outlines",
                "bubble": "€12 месечно. Невероватно!",
                "label": "4. Rezultat",
            },
        ],
    },
    {
        "id": 2,
        "title": "Турист в национальном парке",
        "caption_sr": "EcoDisplays ради на сунцу — без струје, без интернета! 🌿",
        "caption_en": "Solar e-ink trail signs. No grid, no glare, always readable.",
        "panels": [
            {
                "scene": "confused tourist national park faded wooden trail sign forest comic bold outlines",
                "bubble": "Где је стаза? Таблa је нечитљива...",
                "label": "1. Stara tabla",
            },
            {
                "scene": "park ranger installs modern e-ink display trail forest mountains sunny comic bold outlines",
                "bubble": "Инсталирамо EcoDisplays!",
                "label": "2. Instalacija",
            },
            {
                "scene": "e-ink trail display solar panel clear map bright sunlight tourist smiling comic bold",
                "bubble": "Јасно на директном сунцу!",
                "label": "3. Čitljivost",
            },
            {
                "scene": "park manager at computer outdoor display forest updates instantly split screen comic bold",
                "bubble": "Ажурирам са компјутера — одмах!",
                "label": "4. Daljinsko upravljanje",
            },
        ],
    },
    {
        "id": 3,
        "title": "Автобусная остановка",
        "caption_sr": "Паметна аутобуска станица са e-ink дисплејом — без одржавања! 🚌",
        "caption_en": "Smart bus stop. Real-time schedule, no maintenance for 10 years.",
        "panels": [
            {
                "scene": "frustrated commuters bus stop broken LCD glare summer heat comic bold outlines urban",
                "bubble": "Опет се прегреjо екран!",
                "label": "1. LCD se pregrejao",
            },
            {
                "scene": "city workers install thin e-ink display bus stop busy street comic bold outlines",
                "bubble": "Монтирамо e-ink дисплеj!",
                "label": "2. Zamena",
            },
            {
                "scene": "e-ink bus stop display real-time schedule bright sunlight commuters smiling comic bold",
                "bubble": "Распоред — савршено јасно!",
                "label": "3. Jasan ekran",
            },
            {
                "scene": "official points to 10 years calendar e-ink bus stop display perfect comic bold outlines",
                "bubble": "10 година — нула одржавања!",
                "label": "4. 10 god. bez održavanja",
            },
        ],
    },
    {
        "id": 4,
        "title": "E-ink vs LED: дуэль",
        "caption_sr": "E-ink против LED-а: ко побеђује на улици? 🥊",
        "caption_en": "E-ink vs LED outdoor. Sunlight wins every time.",
        "panels": [
            {
                "scene": "boxing ring city plaza LED billboard character glowing vs slim e-ink calm comic bold",
                "bubble": "LED: 300W и сјаjим!",
                "label": "1. Duel počinje",
            },
            {
                "scene": "bright sunlight LCD washed out unreadable e-ink display clear winner comic bold dramatic",
                "bubble": "Сунце? E-ink побеђује!",
                "label": "2. Test na suncu",
            },
            {
                "scene": "electricity meter spinning LED display e-ink solar panel zero consumption comic bold contrast",
                "bubble": "300W vs 3W. Хм...",
                "label": "3. Brojilo struje",
            },
            {
                "scene": "mayor awards trophy to e-ink display LED character defeated happy citizens comic bold",
                "bubble": "Победник: EcoDisplays! 🏆",
                "label": "4. Pobednik",
            },
        ],
    },
    {
        "id": 5,
        "title": "Restoran bez papira",
        "caption_sr": "E-ink jelovnik: uvek svež, bez papira, bez struje! 🍽️",
        "caption_en": "E-ink restaurant menu. Update prices in 3 sec. Zero paper waste.",
        "panels": [
            {
                "scene": "stressed waiter carrying huge stack of paper menus restaurant busy comic bold",
                "bubble": "Svaki dan štampamo 200 jelovnika!",
                "label": "1. Problem",
            },
            {
                "scene": "technician installs slim e-ink display on restaurant table modern interior comic bold",
                "bubble": "E-ink jelovnici na svakom stolu!",
                "label": "2. Instalacija",
            },
            {
                "scene": "restaurant manager updates menu on tablet all displays change instantly comic bold",
                "bubble": "Cene ažurirane za 3 sekunde!",
                "label": "3. Ažuriranje",
            },
            {
                "scene": "full happy restaurant zero paper waste owner smiles e-ink displays comic bold",
                "bubble": "Nula papira. Nula struje. Pun restoran!",
                "label": "4. Rezultat",
            },
        ],
    },
    {
        "id": 6,
        "title": "Pametni parking",
        "caption_sr": "Pametni parking са e-ink tablama — vozači više ne lutaju! 🅿️",
        "caption_en": "Smart parking with e-ink signs. Always visible. Solar powered.",
        "panels": [
            {
                "scene": "angry drivers lost in parking lot broken LCD sign glare sun chaos comic bold",
                "bubble": "Gde je slobodno mesto?! Tablica se ne vidi!",
                "label": "1. Haos",
            },
            {
                "scene": "workers install e-ink parking guidance signs solar panel parking lot comic bold",
                "bubble": "Postavljamo e-ink table EcoDisplays!",
                "label": "2. Instalacija",
            },
            {
                "scene": "e-ink parking sign shows available spots bright sunlight crystal clear comic bold",
                "bubble": "Slobodnih mesta: 14. Jasno na suncu!",
                "label": "3. Čitljivost",
            },
            {
                "scene": "parking operator at desk tablet updates signs remotely happy driver comic bold",
                "bubble": "Upravljam sa jednog mesta — odmah!",
                "label": "4. Kontrola",
            },
        ],
    },
    {
        "id": 8,
        "title": "EcoHero — Čuvar Čiste Energije",
        "caption_sr": "EcoHero štiti grad od rasipanja energije! Superheroj e-ink technologije! ⚡🌿",
        "caption_en": "EcoHero saves the city with e-ink power. 111x less energy. Always readable.",
        "panels": [
            {
                "scene": "superhero in futuristic green suit with e-ink display shield flies over night city",
                "bubble": "Ja sam EcoHero! Čuvam grad od rasipanja!",
                "label": "1. EcoHero se pojavljuje",
            },
            {
                "scene": "superhero fights giant glowing LED billboard monster villain with solar energy beam",
                "bubble": "300W naspram 3W? Pobediću te!",
                "label": "2. Bitka sa LED zlobnikom",
            },
            {
                "scene": "superhero installs e-ink outdoor display on city street sunny day citizens cheer",
                "bubble": "EcoDisplays — čitljivo i na suncu!",
                "label": "3. Grad se transformiše",
            },
            {
                "scene": "superhero victory pose city skyline e-ink displays everywhere green energy saved",
                "bubble": "Grad sačuvan! EcoDisplays pobedio! 🏆",
                "label": "4. Pobeda čiste energije",
            },
        ],
    },
    {
        "id": 10,
        "title": "Simpsonovi i EcoDisplays",
        "caption_sr": "Homerova porodica otkrila tajnu: e-ink štedi 111x više struje! 🟡⚡",
        "caption_en": "The Simpsons discover e-ink: €500 bill → €12. D'oh... why not sooner?",
        "panels": [
            {
                "scene": "Homer Simpson shocked huge electricity bill LED billboard Springfield",
                "bubble": "€500 za struju?! D'oh!!",
                "label": "1. Homer u šoku",
            },
            {
                "scene": "Marge Simpson explains EcoDisplays e-ink TV living room couch",
                "bubble": "Homere, postoji rešenje — EcoDisplays!",
                "label": "2. Marge zna bolje",
            },
            {
                "scene": "Homer installs EcoDisplays outdoor display solar panel happy tools",
                "bubble": "Samo 3W?! Čak i ja mogu ovo!",
                "label": "3. Montaža",
            },
            {
                "scene": "Simpson family happy e-ink display small electricity bill €12 sunset",
                "bubble": "€12 mesečno. Woo-hoo! 🎉",
                "label": "4. Porodični uspeh",
            },
        ],
    },
    {
        "id": 9,
        "title": "Detektiv energije",
        "caption_sr": "Detektiv otkriva istinu: e-ink troši 111 puta manje energije! 🕵️",
        "caption_en": "Energy detective solves the city's power mystery. E-ink wins.",
        "panels": [
            {
                "scene": "noir detective rainy night Belgrade LED billboards 300W energy meter glowing harsh light",
                "bubble": "Nekо troši struju kao lud... Naći ću ga!",
                "label": "1. Istraga počinje",
            },
            {
                "scene": "detective discovers e-ink display dark alley magnifying glass green glow solar no cables",
                "bubble": "Evo! E-ink — bez struje, bez kablova!",
                "label": "2. Ključni trag",
            },
            {
                "scene": "detective city hall meeting presents LCD vs e-ink evidence shocked councilors spotlight",
                "bubble": "Krivac je pronađen — rasipanje energije!",
                "label": "3. Rešenje slučaja",
            },
            {
                "scene": "sunrise Belgrade e-ink displays everywhere detective satisfied city transformed low energy",
                "bubble": "Grad spasen. Slučaj zatvoren. ✅",
                "label": "4. Grad se menja",
            },
        ],
    },
    {
        "id": 7,
        "title": "Muzej bez papira",
        "caption_sr": "E-ink u muzeju: svaka etiketa uvek tačna, bez štampanja! 🏛️",
        "caption_en": "E-ink museum labels. Always accurate. Zero printing. Solar powered.",
        "panels": [
            {
                "scene": "museum worker printing hundreds of paper labels frustrated expiring exhibits comic bold",
                "bubble": "Štampamo 500 etiketa mesečno — i menjamo ih svake nedelje!",
                "label": "1. Problem",
            },
            {
                "scene": "technician installs slim e-ink display next to museum exhibit artifact comic bold",
                "bubble": "E-ink etiketa — solarna, bez kablova!",
                "label": "2. Instalacija",
            },
            {
                "scene": "curator updates all museum labels from laptop instantly digital displays comic bold",
                "bubble": "Sve etikete ažurirane za 10 sekundi!",
                "label": "3. Ažuriranje",
            },
            {
                "scene": "happy museum director zero paper waste visitors admire displays comic bold",
                "bubble": "Nula papira. Nula grešaka. Puni muzeji!",
                "label": "4. Rezultat",
            },
        ],
    },
]


# ── Утилиты ────────────────────────────────────────────────────────────────

def _call_openrouter(messages: list, max_tokens: int = 800) -> str:
    import requests as req
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ecodisplays.com",
        "X-Title": "Ecodisplays Comic Generator",
    }
    for model in OPENROUTER_TEXT_MODELS:
        try:
            r = req.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "max_tokens": max_tokens},
                timeout=45,
            )
            if r.ok:
                content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if content:
                    return content
        except Exception as e:
            print(f"  OpenRouter {model}: {e}")
    return ""


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_SVG_MODELS = [
    "moonshotai/kimi-k2.6:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "openai/gpt-oss-20b:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
]


def _generate_svg_panel(scene_description: str, panel_idx: int) -> bytes | None:
    """Генерирует SVG комикс-панель через бесплатный LLM, рендерит через rsvg-convert."""
    import requests as req
    import subprocess
    import tempfile

    svg_prompt = f"""Create an SVG illustration (540x540px) of a comic book panel.

SCENE: {scene_description}

REQUIREMENTS:
- Output ONLY valid SVG code, nothing else, no markdown, no explanation
- Start exactly with: <svg width="540" height="540" viewBox="0 0 540 540" xmlns="http://www.w3.org/2000/svg">
- End exactly with: </svg>
- Classic American comic book style: bold black stroke-width="4" outlines, vibrant colors
- Add halftone dots pattern (small circles in defs/pattern)
- Add yellow/orange starburst or action background
- Draw human characters with head, body, arms
- NO text elements, NO letters, NO words anywhere in the SVG
- Use bright comic colors: #FFEB3B yellow, #1976D2 blue, #D32F2F red, #FFCCAA skin, #4CAF50 green"""

    if not OPENROUTER_API_KEY:
        return None

    svg_text = ""
    for model in OPENROUTER_SVG_MODELS:
        try:
            print(f"  Панель {panel_idx+1}: LLM SVG ({model.split('/')[1]})...")
            r = req.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "user", "content": svg_prompt}],
                      "max_tokens": 4000},
                timeout=90)
            if r.ok:
                content = r.json()["choices"][0]["message"]["content"].strip()
                if "<svg" in content and "</svg>" in content:
                    # Берём только первый SVG блок
                    svg_start = content.index("<svg")
                    svg_end = content.index("</svg>", svg_start) + 6
                    candidate = content[svg_start:svg_end]
                    # Проверяем валидность
                    from xml.etree import ElementTree as ET
                    try:
                        ET.fromstring(candidate)
                        svg_text = candidate
                        print(f"  Панель {panel_idx+1}: SVG {len(svg_text)} символов")
                        break
                    except ET.ParseError as e:
                        print(f"  Панель {panel_idx+1}: {model.split('/')[1]} — невалидный SVG: {e}")
                else:
                    print(f"  Панель {panel_idx+1}: {model.split('/')[1]} — нет SVG в ответе")
            else:
                print(f"  Панель {panel_idx+1}: {model.split('/')[1]} — {r.status_code}")
        except Exception as e:
            print(f"  Панель {panel_idx+1}: {model.split('/')[1]} — {e}")

    if not svg_text:
        return None

    # Валидация и чистка SVG перед рендерингом
    try:
        from xml.etree import ElementTree as ET
        ET.fromstring(svg_text)
    except ET.ParseError as e:
        # Пробуем вырезать только до последнего валидного тега
        print(f"  Панель {panel_idx+1}: XML ошибка, пробуем починить: {e}")
        last_svg = svg_text.rfind("</svg>")
        if last_svg > 0:
            svg_text = svg_text[:last_svg + 6]
        try:
            ET.fromstring(svg_text)
        except ET.ParseError:
            print(f"  Панель {panel_idx+1}: SVG невалиден, пропускаем")
            return None

    # Рендерим SVG → PNG через rsvg-convert
    try:
        with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False, encoding="utf-8") as svg_f:
            svg_f.write(svg_text)
            svg_path = svg_f.name

        png_path = svg_path.replace(".svg", ".png")
        result = subprocess.run(
            ["rsvg-convert", "-w", str(PANEL_W), "-h", str(PANEL_H), svg_path, "-o", png_path],
            capture_output=True, timeout=30
        )
        Path(svg_path).unlink(missing_ok=True)

        if result.returncode == 0 and Path(png_path).exists():
            data = Path(png_path).read_bytes()
            Path(png_path).unlink(missing_ok=True)
            if len(data) > 5000:
                print(f"  Панель {panel_idx+1}: OK {len(data)//1024}KB")
                return data
        print(f"  Панель {panel_idx+1}: rsvg-convert ошибка: {result.stderr.decode()[:100]}")
    except Exception as e:
        print(f"  Панель {panel_idx+1}: рендер SVG — {e}")
    return None


import math as _math


def _starburst(draw, cx, cy, r_inner, r_outer, n, color):
    import math
    pts = []
    for i in range(n * 2):
        r = r_outer if i % 2 == 0 else r_inner
        a = math.radians(i * 180 / n - 90)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    draw.polygon(pts, fill=color)


def _stick_person(draw, cx, cy, scale=1.0, shirt=(30, 100, 200), skin=(255, 200, 150), shocked=False, happy=False):
    s = scale
    # Голова
    hr = int(38 * s)
    draw.ellipse([cx-hr, cy-hr, cx+hr, cy+hr], fill=skin, outline=(20,20,20), width=3)
    # Глаза
    ew = int(8*s)
    ex = int(14*s)
    ey = int(8*s)
    draw.ellipse([cx-ex-ew, cy-ey-ew, cx-ex+ew, cy-ey+ew], fill=(20,20,20))
    draw.ellipse([cx+ex-ew, cy-ey-ew, cx+ex+ew, cy-ey+ew], fill=(20,20,20))
    if shocked:
        draw.ellipse([cx-int(10*s), cy+int(5*s), cx+int(10*s), cy+int(18*s)], fill=(20,20,20))
    elif happy:
        draw.arc([cx-int(14*s), cy+int(2*s), cx+int(14*s), cy+int(16*s)], start=0, end=180, fill=(20,20,20), width=3)
    else:
        draw.line([cx-int(12*s), cy+int(10*s), cx+int(12*s), cy+int(10*s)], fill=(20,20,20), width=3)
    # Тело
    body_top = cy + hr
    body_bot = cy + int(130*s)
    bw = int(36*s)
    draw.rectangle([cx-bw, body_top, cx+bw, body_bot], fill=shirt, outline=(20,20,20), width=3)
    # Руки
    draw.line([cx-bw, body_top+int(20*s), cx-bw-int(50*s), body_top+int(70*s)], fill=skin, width=int(8*s))
    draw.line([cx+bw, body_top+int(20*s), cx+bw+int(50*s), body_top+int(70*s)], fill=skin, width=int(8*s))
    # Ноги
    draw.rectangle([cx-bw+int(5*s), body_bot, cx-int(5*s), body_bot+int(70*s)], fill=(50,50,150), outline=(20,20,20), width=3)
    draw.rectangle([cx+int(5*s), body_bot, cx+bw-int(5*s), body_bot+int(70*s)], fill=(50,50,150), outline=(20,20,20), width=3)


def _draw_eink_display(draw, x, y, w, h, label="EcoDisplays"):
    """Рисует e-ink дисплей."""
    from PIL import ImageFont
    # Корпус
    draw.rectangle([x, y, x+w, y+h], fill=(220,225,230), outline=(20,20,20), width=4)
    # Экран
    sx, sy = x+10, y+10
    draw.rectangle([sx, sy, x+w-10, y+h-30], fill=(240,245,250), outline=(50,50,50), width=2)
    # Строки текста на экране
    for i in range(3):
        ly = sy + 15 + i*20
        draw.rectangle([sx+10, ly, sx+10+int((w-40)*(0.9-i*0.15)), ly+8], fill=(30,30,30))
    # Солнечная панель
    sp_y = y + h - 22
    draw.rectangle([x+5, sp_y, x+w-5, sp_y+14], fill=(30,60,150), outline=(20,20,20), width=2)
    for j in range(4):
        draw.line([x+5+j*(w-10)//4, sp_y, x+5+j*(w-10)//4, sp_y+14], fill=(100,130,200), width=1)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except:
        font = ImageFont.load_default()
    draw.text((x + w//2, y+h+5), label, font=font, fill=(0, 180, 100), anchor="mt")


def _draw_scenario_panel(scenario_id: int, panel_idx: int) -> bytes:
    """Детальные сцены для каждого сценария и панели."""
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO

    W, H = PANEL_W, PANEL_H
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Цветовые темы для каждой панели
    bg_colors = [
        (255, 240, 180),   # панель 1 — тёплый жёлтый
        (200, 235, 255),   # панель 2 — небесный
        (200, 240, 215),   # панель 3 — зелёный
        (230, 220, 255),   # панель 4 — фиолетовый
    ]
    bg = bg_colors[panel_idx % 4]
    draw.rectangle([0, 0, W, H], fill=bg)

    # Starburst фон
    accent_colors = [(255,180,0), (0,140,255), (0,180,80), (160,80,220)]
    accent = accent_colors[panel_idx % 4]
    _starburst(draw, W//2, H//2+50, 100, 340, 16, accent + (60,) if False else accent)

    # Пол
    draw.rectangle([0, H-120, W, H], fill=(180,160,130), outline=(100,80,60), width=2)
    # Горизонт (здание/лес/улица)
    draw.rectangle([0, H-240, W, H-120], fill=(bg[0]-20, bg[1]-20, bg[2]-20))

    # Сцены по сценарию
    if scenario_id == 1:  # Счёт за электричество
        if panel_idx == 0:  # Шокированный чиновник с огромным счётом
            # LED рекламный щит
            draw.rectangle([320, 80, 490, 240], fill=(255,80,80), outline=(20,20,20), width=4)
            draw.rectangle([330, 90, 480, 180], fill=(255,200,50))
            for r in range(4):
                draw.rectangle([340+r*35, 100, 365+r*35, 165], fill=(255,120,0))
            draw.text_if_available = False
            draw.rectangle([395, 240, 415, 300], fill=(80,80,80), outline=(20,20,20), width=2)
            # Счёт - бумага
            bill_x, bill_y = 120, 200
            draw.rectangle([bill_x, bill_y, bill_x+130, bill_y+160], fill=(255,255,255), outline=(20,20,20), width=3)
            for i in range(5):
                draw.rectangle([bill_x+15, bill_y+20+i*25, bill_x+115, bill_y+30+i*25], fill=(200,200,200))
            draw.rectangle([bill_x+15, bill_y+130, bill_x+115, bill_y+148], fill=(255,50,50))
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
                draw.text((bill_x+65, bill_y+132), "€500!", font=font, fill=(255,255,255), anchor="mm")
            except: pass
            # Персонаж — шокированный
            _stick_person(draw, 200, H-280, scale=0.9, shirt=(0,80,160), shocked=True)
            # Молнии шока
            for angle in [30, 60, 120, 150]:
                a = _math.radians(angle)
                draw.line([(200+60*_math.cos(a), H-330+60*_math.sin(a)),
                           (200+100*_math.cos(a), H-330+100*_math.sin(a))],
                          fill=(255,220,0), width=4)

        elif panel_idx == 1:  # Продавец показывает дисплей
            # Продавец
            _stick_person(draw, 150, H-280, scale=0.9, shirt=(0,160,80), happy=True)
            # Рука указывает
            draw.line([(185, H-200), (290, H-280)], fill=(255,200,150), width=8)
            # E-ink дисплей на стойке
            _draw_eink_display(draw, 290, H-380, 180, 140)
            # Значок "3W"
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
                draw.text((420, H-360), "3W", font=font, fill=(0,200,80), anchor="mm")
                font2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                draw.text((420, H-335), "eco", font=font2, fill=(0,150,60), anchor="mm")
            except: pass
            # Слушатель
            _stick_person(draw, 390, H-280, scale=0.8, shirt=(100,50,150))

        elif panel_idx == 2:  # Солнечная панель без кабелей
            # Солнце
            _starburst(draw, 420, 100, 40, 90, 12, (255,220,0))
            draw.ellipse([380, 60, 460, 140], fill=(255,235,0), outline=(220,180,0), width=3)
            # Дисплей с солнечной панелью
            _draw_eink_display(draw, 180, H-400, 200, 160)
            # Перечёркнутый кабель
            cable_x = 160
            draw.line([(cable_x, H-180), (cable_x+60, H-120)], fill=(80,80,80), width=5)
            draw.line([(cable_x, H-120), (cable_x+60, H-180)], fill=(255,50,50), width=5)
            draw.ellipse([cable_x-5, H-185, cable_x+65, H-115], outline=(255,50,50), width=4)
            # Луч от солнца к дисплею
            draw.line([(400, 140), (310, H-400)], fill=(255,200,0), width=4)
            # Персонаж
            _stick_person(draw, 120, H-270, scale=0.85, shirt=(0,120,60), happy=True)

        elif panel_idx == 3:  # Маленький счёт, улыбка
            # Персонаж
            _stick_person(draw, 170, H-280, scale=0.9, shirt=(0,80,160), happy=True)
            # Маленький счёт
            bill_x, bill_y = 250, 200
            draw.rectangle([bill_x, bill_y, bill_x+100, bill_y+120], fill=(255,255,255), outline=(0,180,80), width=3)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
                draw.text((bill_x+50, bill_y+55), "€12", font=font, fill=(0,180,80), anchor="mm")
                font2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
                draw.text((bill_x+50, bill_y+80), "за месяц", font=font2, fill=(50,50,50), anchor="mm")
            except: pass
            # Зелёные звезды
            for sx, sy in [(370,180),(420,220),(400,160)]:
                _starburst(draw, sx, sy, 8, 18, 5, (0,220,80))

    elif scenario_id == 2:  # Турист в нацпарке
        if panel_idx == 0:  # Запутанный турист
            # Деревья
            for tx in [60, 350, 430, 500]:
                draw.rectangle([tx+15, H-300, tx+35, H-120], fill=(101,67,33), outline=(20,20,20), width=2)
                draw.ellipse([tx-20, H-380, tx+70, H-260], fill=(34,139,34), outline=(20,20,20), width=2)
            # Старый указатель
            draw.rectangle([220, H-350, 230, H-140], fill=(101,67,33), outline=(20,20,20), width=2)
            draw.rectangle([220, H-360, 310, H-320], fill=(139,90,43), outline=(20,20,20), width=2)
            # Карта в руках персонажа
            draw.rectangle([260, H-290, 340, H-220], fill=(255,255,200), outline=(20,20,20), width=2)
            _stick_person(draw, 180, H-280, scale=0.85, shirt=(210,130,30), shocked=True)

        elif panel_idx == 1:  # Рейнджер устанавливает дисплей
            # Деревья
            for tx in [40, 380, 460]:
                draw.rectangle([tx+15, H-280, tx+35, H-120], fill=(101,67,33), outline=(20,20,20), width=2)
                draw.ellipse([tx-15, H-360, tx+65, H-250], fill=(34,139,34), outline=(20,20,20), width=2)
            # Опора дисплея
            draw.rectangle([255, H-380, 275, H-120], fill=(80,80,80), outline=(20,20,20), width=2)
            _draw_eink_display(draw, 200, H-440, 140, 100)
            # Рейнджер
            _stick_person(draw, 170, H-280, scale=0.9, shirt=(40,160,40), happy=True)
            # Инструменты
            draw.rectangle([200, H-200, 260, H-185], fill=(200,180,30), outline=(20,20,20), width=2)

        elif panel_idx == 2:  # Чёткий дисплей на солнце
            # Солнце
            _starburst(draw, 430, 90, 35, 80, 12, (255,220,0))
            draw.ellipse([395, 55, 465, 125], fill=(255,235,0), outline=(220,180,0), width=3)
            # Дисплей
            _draw_eink_display(draw, 200, H-400, 160, 130)
            # Лучи от солнца
            draw.line([(395, 125), (310, H-400)], fill=(255,200,0), width=3)
            # Турист рад
            _stick_person(draw, 380, H-270, scale=0.8, shirt=(210,130,30), happy=True)

        elif panel_idx == 3:  # Удалённое управление
            # Компьютер
            draw.rectangle([60, H-320, 200, H-200], fill=(40,40,40), outline=(20,20,20), width=3)
            draw.rectangle([70, H-310, 190, H-220], fill=(100,160,255))
            draw.rectangle([90, H-200, 170, H-185], fill=(80,80,80))
            draw.rectangle([70, H-185, 190, H-175], fill=(60,60,60))
            _stick_person(draw, 140, H-280, scale=0.8, shirt=(0,80,160), happy=True)
            # Стрелка wifi к дисплею
            draw.line([(200, H-260), (330, H-260)], fill=(0,200,100), width=4)
            for i in range(3):
                draw.arc([225+i*30, H-275, 245+i*30, H-245], start=210, end=330, fill=(0,200,100), width=3)
            # Дисплей в лесу
            _draw_eink_display(draw, 340, H-390, 140, 110)

    elif scenario_id == 3:  # Автобусная остановка
        if panel_idx == 0:  # Сломанный LCD
            # Остановка
            draw.rectangle([100, H-380, 430, H-120], fill=(200,200,200), outline=(20,20,20), width=3)
            draw.rectangle([100, H-380, 430, H-340], fill=(50,50,80))
            # Сломанный LCD экран
            draw.rectangle([180, H-320, 350, H-200], fill=(255,50,50), outline=(20,20,20), width=3)
            # Трещины
            draw.line([(200, H-320), (240, H-200)], fill=(20,20,20), width=3)
            draw.line([(260, H-310), (290, H-210)], fill=(20,20,20), width=2)
            # Солнце (перегрев)
            _starburst(draw, 430, 80, 30, 70, 10, (255,150,0))
            draw.ellipse([400, 50, 460, 110], fill=(255,200,0))
            # Злые пассажиры
            _stick_person(draw, 160, H-270, scale=0.75, shirt=(150,50,50), shocked=True)
            _stick_person(draw, 360, H-270, scale=0.75, shirt=(80,80,180), shocked=True)

        elif panel_idx == 1:  # Установка e-ink
            # Рабочие с инструментами
            _stick_person(draw, 170, H-270, scale=0.85, shirt=(255,140,0))
            _stick_person(draw, 330, H-270, scale=0.85, shirt=(255,140,0))
            # Фургон
            draw.rectangle([30, H-240, 130, H-130], fill=(255,165,0), outline=(20,20,20), width=3)
            draw.ellipse([45, H-140, 75, H-115], fill=(30,30,30))
            draw.ellipse([95, H-140, 125, H-115], fill=(30,30,30))
            # Новый дисплей (несут)
            _draw_eink_display(draw, 220, H-360, 150, 110)
            # Болты/инструменты
            draw.rectangle([180, H-200, 210, H-190], fill=(200,180,30), outline=(20,20,20), width=2)

        elif panel_idx == 2:  # Чёткое расписание
            # Остановка
            draw.rectangle([80, H-380, 460, H-120], fill=(220,220,220), outline=(20,20,20), width=3)
            draw.rectangle([80, H-380, 460, H-340], fill=(0,80,160))
            # E-ink дисплей с расписанием
            _draw_eink_display(draw, 160, H-330, 200, 150)
            # Солнце
            _starburst(draw, 430, 80, 25, 60, 10, (255,220,0))
            draw.ellipse([405, 55, 455, 105], fill=(255,235,0))
            # Довольные пассажиры
            _stick_person(draw, 150, H-265, scale=0.7, shirt=(180,80,180), happy=True)
            _stick_person(draw, 390, H-265, scale=0.7, shirt=(50,150,50), happy=True)

        elif panel_idx == 3:  # 10 лет без обслуживания
            # Дисплей на фоне
            _draw_eink_display(draw, 280, H-380, 170, 130)
            # Чиновник с плакатом "10 лет"
            _stick_person(draw, 180, H-270, scale=0.9, shirt=(0,80,160), happy=True)
            # Плакат
            draw.rectangle([240, H-360, 380, H-260], fill=(255,255,200), outline=(0,180,80), width=3)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
                draw.text((310, H-320), "10", font=font, fill=(0,180,80), anchor="mm")
                font2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                draw.text((310, H-290), "лет", font=font2, fill=(50,50,50), anchor="mm")
            except: pass
            # Иконка галочки
            draw.line([(345, H-320), (360, H-300), (390, H-340)], fill=(0,180,80), width=5)

    elif scenario_id == 4:  # E-ink vs LED дуэль
        if panel_idx == 0:  # Ринг
            # Ринг
            draw.rectangle([60, H-220, 480, H-120], fill=(180,140,80), outline=(20,20,20), width=3)
            draw.line([(60, H-180), (480, H-180)], fill=(255,255,255), width=2)
            # LED персонаж (большой, яркий)
            draw.rectangle([80, H-380, 200, H-220], fill=(255,80,80), outline=(20,20,20), width=4)
            draw.rectangle([85, H-375, 195, H-255], fill=(255,200,50))
            # Молнии вокруг LED
            for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
                a = _math.radians(angle)
                cx_l, cy_l = 140, H-300
                draw.line([(int(cx_l+65*_math.cos(a)), int(cy_l+65*_math.sin(a))),
                           (int(cx_l+90*_math.cos(a)), int(cy_l+90*_math.sin(a)))],
                          fill=(255,220,0), width=3)
            # E-ink персонаж (тонкий, спокойный)
            _draw_eink_display(draw, 310, H-400, 130, 180)
            # VS
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
                draw.text((260, H-290), "VS", font=font, fill=(255,50,50), anchor="mm")
            except: pass

        elif panel_idx == 1:  # Солнечный тест
            # Солнце огромное
            _starburst(draw, 270, 120, 60, 180, 16, (255,230,0))
            draw.ellipse([190, 40, 350, 200], fill=(255,240,50), outline=(220,180,0), width=4)
            # LCD — размытый, нечитаемый
            draw.rectangle([60, H-350, 200, H-200], fill=(200,150,150), outline=(20,20,20), width=3)
            draw.rectangle([70, H-340, 190, H-220], fill=(255,200,200))
            # Крест "нет"
            draw.line([(70, H-340), (190, H-220)], fill=(255,50,50), width=6)
            draw.line([(190, H-340), (70, H-220)], fill=(255,50,50), width=6)
            # E-ink — чёткий
            _draw_eink_display(draw, 310, H-360, 160, 140)
            # Галочка "победа"
            draw.line([(400, H-230), (420, H-205), (460, H-260)], fill=(0,200,80), width=6)
            _starburst(draw, 420, H-240, 20, 45, 8, (0,200,80))

        elif panel_idx == 2:  # Счётчик электричества
            # Счётчик слева (LED)
            draw.rectangle([60, H-380, 200, H-150], fill=(240,240,230), outline=(20,20,20), width=3)
            draw.ellipse([80, H-360, 180, H-260], fill=(200,200,200), outline=(20,20,20), width=2)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
                draw.text((130, H-310), "300W", font=font, fill=(255,50,50), anchor="mm")
            except: pass
            # Стрелка счётчика вправо (много)
            draw.arc([80, H-360, 180, H-260], start=200, end=20, fill=(255,50,50), width=5)
            # Счётчик справа (e-ink)
            draw.rectangle([310, H-380, 450, H-150], fill=(240,240,230), outline=(20,20,20), width=3)
            draw.ellipse([330, H-360, 430, H-260], fill=(220,240,220), outline=(0,180,80), width=2)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
                draw.text((380, H-310), "3W", font=font, fill=(0,180,80), anchor="mm")
            except: pass
            draw.arc([330, H-360, 430, H-260], start=200, end=210, fill=(0,180,80), width=5)
            # VS в центре
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
                draw.text((260, H-280), "VS", font=font, fill=(100,100,100), anchor="mm")
            except: pass

        elif panel_idx == 3:  # Победитель
            # Подиум
            draw.rectangle([170, H-220, 370, H-120], fill=(255,215,0), outline=(20,20,20), width=3)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
                draw.text((270, H-180), "1", font=font, fill=(20,20,20), anchor="mm")
            except: pass
            # E-ink дисплей победитель
            _draw_eink_display(draw, 195, H-420, 150, 130)
            # Трофей
            _starburst(draw, 380, H-300, 20, 50, 8, (255,215,0))
            draw.ellipse([355, H-330, 405, H-270], fill=(255,215,0), outline=(180,140,0), width=3)
            # Мэр
            _stick_person(draw, 120, H-265, scale=0.8, shirt=(0,60,140), happy=True)
            # Побеждённый LED (грустный)
            draw.rectangle([390, H-250, 470, H-120], fill=(255,80,80), outline=(20,20,20), width=3)
            draw.line([(390+10, H-240), (470-10, H-140)], fill=(20,20,20), width=3)
            draw.line([(470-10, H-240), (390+10, H-140)], fill=(20,20,20), width=3)
            # Конфетти
            import random as _rand
            _rand.seed(42)
            for _ in range(20):
                cx = _rand.randint(50, 490)
                cy = _rand.randint(50, H-250)
                col = _rand.choice([(255,50,50),(0,200,80),(50,50,255),(255,200,0)])
                draw.ellipse([cx-5, cy-5, cx+5, cy+5], fill=col)

    out = BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _draw_pil_fallback(panel_idx: int) -> bytes:
    """Запасная панель."""
    from PIL import Image, ImageDraw
    from io import BytesIO
    bg_colors = [(255,240,180), (200,235,255), (200,240,215), (230,220,255)]
    bg = bg_colors[panel_idx % 4]
    img = Image.new("RGB", (PANEL_W, PANEL_H), bg)
    draw = ImageDraw.Draw(img)
    _starburst(draw, PANEL_W//2, PANEL_H//2 + 50, 80, 200, 14, (200,200,200))
    _stick_person(draw, PANEL_W//2, PANEL_H-200, scale=0.9, shirt=(30,100,200))
    out = BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _fetch_pollinations_image(prompt: str, width: int = 540, height: int = 540,
                               seed: int | None = None) -> bytes | None:
    """Получает AI-изображение с Pollinations.ai (бесплатно, без ключа).
    Модель: flux — даёт фотореалистичные/3D-render качество."""
    import urllib.request, urllib.parse, time
    encoded = urllib.parse.quote(prompt)
    seed_part = f"&seed={seed}" if seed is not None else ""
    url = (f"https://image.pollinations.ai/prompt/{encoded}"
           f"?width={width}&height={height}&model=flux&nologo=true{seed_part}")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EcoDisplays/1.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
                if len(data) > 5000:
                    return data
        except Exception as e:
            print(f"    Pollinations попытка {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5)
    return None


# Реалистичные 3D-промпты для сценария 4 (E-ink vs LED дуэль)
_HERO3D_PROMPTS = [
    # Панель 0: LED злодей объявляет войну
    ("Menacing giant LED billboard robot villain standing in dark futuristic city at night, "
     "glowing orange LED eyes, sparking electricity bolts, dramatic cinematic lighting, "
     "smoke and red glow, power cables as arms, \"300W\" text glowing on chest, "
     "comic book 3D render style, high detail, photorealistic CGI, dark atmosphere, "
     "no text in image except 300W on villain chest"),
    # Панель 1: Герой летит к солнцу, LCD горит
    ("E-ink display superhero in sleek blue suit flying toward blazing sun in clear sky, "
     "green letter E emblem on chest, red cape flowing, energy beam from hand, "
     "burning melting LCD billboard in background with red X on it, "
     "bright dramatic lighting, photorealistic CGI 3D render, cinematic composition, "
     "outdoor daylight scene, solar power beams"),
    # Панель 2: Дуэль — взрыв энергий
    ("Epic collision between e-ink hero in blue suit and LED robot villain in red, "
     "massive energy explosion between them showing \"3W\" on left side blue and \"300W\" on right red, "
     "dramatic shockwave, sparks and lightning, dark city background, "
     "cinematic 3D render superhero comic style, high contrast, epic composition"),
    # Панель 3: Победа — герой с трофеем
    ("E-ink superhero in blue suit standing in victory pose on podium holding golden trophy, "
     "red cape flowing, defeated broken LED robot villain lying at feet with X on screen, "
     "golden light rays from above, city skyline at sunset background, "
     "photorealistic CGI 3D render, triumphant cinematic lighting, "
     "\"EcoDisplays\" e-ink display glowing green in background showing 3W"),
]


_SUPERHERO_AI_PROMPTS = [
    # Панель 1: EcoHero появляется над городом
    ("Epic cinematic superhero in sleek green and black armored suit flying over dark futuristic Belgrade city skyline at night, "
     "hero holds glowing e-ink display shield with green EcoDisplays logo, "
     "dramatic god rays of green light, lightning and energy particles, dynamic camera angle from below, "
     "photorealistic CGI 3D render, Marvel/DC movie quality, 8K, ultra-detailed, dramatic rim lighting, "
     "no text in image"),
    # Панель 2: Битва с LED-злодеем
    ("Epic battle between EcoHero in green suit and a massive glowing orange LED billboard robot villain in dark city, "
     "hero fires green solar energy beam from hand, villain shoots red electric bolts from cable arms, "
     "massive explosion of orange vs green energy in center, buildings in background, dramatic shockwave, "
     "cinematic superhero movie quality, photorealistic CGI, 8K render, extreme action composition, "
     "no text labels"),
    # Панель 3: Герой устанавливает дисплеи
    ("EcoHero superhero in green armored suit landing gracefully in sunny city plaza, "
     "installs futuristic slim e-ink outdoor display on pole, citizens cheering around him, "
     "bright sunny day, solar panels glowing, e-ink displays appearing on buildings and bus stops, "
     "golden hour lighting, photorealistic CGI 3D render, hopeful triumphant mood, "
     "cinematic wide shot, ultra-detailed, no text"),
    # Панель 4: Победа
    ("EcoHero superhero in green suit standing in triumphant victory pose on top of Belgrade fortress, "
     "city skyline behind filled with glowing e-ink displays instead of LED billboards, "
     "green aurora energy light in sky, golden trophy in raised fist, cape flowing, "
     "defeated broken LED robot villain in rubble below, citizens celebrating, "
     "epic cinematic CGI 3D render, golden and green dramatic lighting, 8K ultra quality, "
     "no text in scene"),
]


# Сценарий 9: Детектив энергии — нуар, фотореалистичный стиль
_DETECTIVE_NOIR_PROMPTS = [
    # Панель 1: Ночной город, детектив смотрит на LED-рекламу
    ("Cinematic noir detective in long dark trenchcoat and fedora hat standing on rainy Belgrade "
     "street at night, facing massive glowing LED billboard wall that illuminates him in harsh orange light, "
     "rain-soaked cobblestones reflecting neon glow, energy meter in detective's hand showing 300W, "
     "dramatic high-contrast chiaroscuro lighting, photorealistic CGI, moody film noir atmosphere, "
     "deep shadows, cinematic 8K render, no text in image"),
    # Панель 2: Детектив нашёл улику — e-ink дисплей в тёмном переулке
    ("Noir detective kneeling in dark alley discovering a slim elegant e-ink outdoor display on wall "
     "that glows softly without power cables, detective uses magnifying glass to inspect it, "
     "soft diffused green light from display illuminates detective's face in contrast to harsh LED glow beyond alley entrance, "
     "raindrops on display surface but image remains crisp, photorealistic cinematic CGI, 8K quality, "
     "dramatic lighting, mystery atmosphere, no text"),
    # Панель 3: Детектив в городском совете раскрывает правду
    ("Cinematic scene: sharp-dressed noir detective presenting evidence at a dramatic Belgrade city hall meeting, "
     "pointing at two side-by-side displays — glowing power-hungry LCD billboard model vs slim powered-off e-ink display, "
     "city councilors in suits lean forward with shocked expressions, green projection light on detective's face, "
     "dark wood-paneled room, single spotlight from above, photorealistic CGI movie quality, 8K ultra-detailed, "
     "tension and revelation atmosphere, no text"),
    # Панель 4: Город преображён — детектив доволен
    ("Golden sunrise over transformed Belgrade city skyline, rows of slim elegant e-ink EcoDisplays "
     "on bus stops and city pillars, noir detective stands at street corner with satisfied smile, "
     "trenchcoat open in morning breeze, city energy meters in background showing near-zero, "
     "residents walking past clean readable displays, warm golden light replacing harsh neon, "
     "cinematic wide shot, photorealistic CGI 8K render, hopeful triumphant atmosphere, no text in scene"),
]


def _render_svg(svg_text: str) -> bytes | None:
    """Рендерит SVG строку через rsvg-convert → PNG байты."""
    import subprocess, tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False, encoding="utf-8") as f:
            f.write(svg_text)
            svg_path = f.name
        png_path = svg_path.replace(".svg", ".png")
        r = subprocess.run(
            ["rsvg-convert", "-w", str(PANEL_W), "-h", str(PANEL_H), svg_path, "-o", png_path],
            capture_output=True, timeout=30
        )
        Path(svg_path).unlink(missing_ok=True)
        if r.returncode == 0 and Path(png_path).exists():
            data = Path(png_path).read_bytes()
            Path(png_path).unlink(missing_ok=True)
            if len(data) > 3000:
                return data
        print(f"    rsvg-convert: {r.stderr.decode()[:80]}")
    except Exception as e:
        print(f"    SVG render error: {e}")
    return None


def _svg_scenario4(panel_idx: int) -> bytes | None:
    """3D-стиль SVG для сценария 4 (E-ink vs LED дуэль)."""

    W, H = 540, 540

    def defs_block():
        return """
  <defs>
    <!-- Персонаж градиент кожи (3D сфера) -->
    <radialGradient id="skin" cx="38%" cy="32%" r="58%">
      <stop offset="0%" stop-color="#FFE8CC"/>
      <stop offset="60%" stop-color="#FFCB8A"/>
      <stop offset="100%" stop-color="#D4935A"/>
    </radialGradient>
    <!-- Тень под объектами -->
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="4" dy="6" stdDeviation="5" flood-color="#000" flood-opacity="0.35"/>
    </filter>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="8" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <!-- Градиенты объектов -->
    <linearGradient id="ledGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF6B35"/>
      <stop offset="50%" stop-color="#FF3A00"/>
      <stop offset="100%" stop-color="#CC1100"/>
    </linearGradient>
    <radialGradient id="ledGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFD700" stop-opacity="0.8"/>
      <stop offset="100%" stop-color="#FF6B00" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="einkGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#E8EDF2"/>
      <stop offset="40%" stop-color="#D0D8E0"/>
      <stop offset="100%" stop-color="#A8B4C0"/>
    </linearGradient>
    <linearGradient id="screenGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#F0F5FF"/>
      <stop offset="30%" stop-color="#E8EFFA"/>
      <stop offset="100%" stop-color="#C8D8F0"/>
    </linearGradient>
    <linearGradient id="podiumGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFE566"/>
      <stop offset="100%" stop-color="#CCA800"/>
    </linearGradient>
    <linearGradient id="floorGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#8B7355"/>
      <stop offset="100%" stop-color="#5C4A2A"/>
    </linearGradient>
    <linearGradient id="skyGrad1" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#1A1A2E"/>
      <stop offset="100%" stop-color="#16213E"/>
    </linearGradient>
    <linearGradient id="skyGrad2" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#87CEEB"/>
      <stop offset="60%" stop-color="#B8E4FF"/>
      <stop offset="100%" stop-color="#E0F4FF"/>
    </linearGradient>
    <linearGradient id="meterGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#D0D8E0"/>
      <stop offset="100%" stop-color="#909BA8"/>
    </linearGradient>
    <radialGradient id="sunGrad" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="30%" stop-color="#FFFF80"/>
      <stop offset="70%" stop-color="#FFD700"/>
      <stop offset="100%" stop-color="#FF8C00"/>
    </radialGradient>
    <linearGradient id="shirtBlue" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#5B8FD4"/>
      <stop offset="100%" stop-color="#1A4A9C"/>
    </linearGradient>
    <linearGradient id="shirtGreen" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4DC97A"/>
      <stop offset="100%" stop-color="#1A7A3C"/>
    </linearGradient>
    <linearGradient id="pantsGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#3A4A7A"/>
      <stop offset="100%" stop-color="#1A2040"/>
    </linearGradient>
  </defs>"""

    def char3d(cx, cy, scale=1.0, shirt="shirtBlue", shocked=False, happy=False, raise_arm=False):
        """3D-персонаж с градиентами и тенью."""
        s = scale
        hr = int(40 * s)
        # Тень
        sh_y = cy + int(200 * s)
        shadow = f'<ellipse cx="{cx}" cy="{sh_y}" rx="{int(50*s)}" ry="{int(12*s)}" fill="#000" opacity="0.25"/>'
        # Голова
        head = f'<circle cx="{cx}" cy="{cy}" r="{hr}" fill="url(#skin)" filter="url(#shadow)"/>'
        # Глаза
        ex = int(14 * s)
        ey = int(12 * s)
        er = int(7 * s)
        eyes = (f'<circle cx="{cx-ex}" cy="{cy-ey}" r="{er}" fill="#1A1A2A"/>'
                f'<circle cx="{cx+ex}" cy="{cy-ey}" r="{er}" fill="#1A1A2A"/>'
                f'<circle cx="{cx-ex+3}" cy="{cy-ey-3}" r="{int(er*0.3)}" fill="white"/>'
                f'<circle cx="{cx+ex+3}" cy="{cy-ey-3}" r="{int(er*0.3)}" fill="white"/>')
        # Рот
        if shocked:
            mouth = f'<ellipse cx="{cx}" cy="{cy+int(14*s)}" rx="{int(10*s)}" ry="{int(12*s)}" fill="#2A1010"/>'
        elif happy:
            mouth = (f'<path d="M{cx-int(16*s)} {cy+int(8*s)} '
                     f'Q{cx} {cy+int(24*s)} {cx+int(16*s)} {cy+int(8*s)}" '
                     f'stroke="#2A1010" stroke-width="3" fill="none" stroke-linecap="round"/>')
        else:
            mouth = f'<line x1="{cx-int(10*s)}" y1="{cy+int(12*s)}" x2="{cx+int(10*s)}" y2="{cy+int(12*s)}" stroke="#2A1010" stroke-width="3"/>'
        # Тело
        bw = int(38 * s)
        bt = cy + hr - int(5*s)
        bb = cy + int(140 * s)
        body = f'<rect x="{cx-bw}" y="{bt}" width="{bw*2}" height="{bb-bt}" rx="{int(8*s)}" fill="url(#{shirt})" filter="url(#shadow)"/>'
        # Шея
        nw = int(14 * s)
        neck = f'<rect x="{cx-nw}" y="{cy+hr-int(6*s)}" width="{nw*2}" height="{int(20*s)}" fill="url(#skin)"/>'
        # Руки
        arm_y = bt + int(25 * s)
        if raise_arm:
            # Одна рука поднята
            arms = (f'<line x1="{cx-bw}" y1="{arm_y}" x2="{cx-bw-int(55*s)}" y2="{arm_y+int(60*s)}" stroke="url(#skin)" stroke-width="{int(16*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{arm_y}" x2="{cx+bw+int(30*s)}" y2="{arm_y-int(60*s)}" stroke="url(#skin)" stroke-width="{int(16*s)}" stroke-linecap="round"/>')
        else:
            arms = (f'<line x1="{cx-bw}" y1="{arm_y}" x2="{cx-bw-int(50*s)}" y2="{arm_y+int(65*s)}" stroke="url(#skin)" stroke-width="{int(16*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{arm_y}" x2="{cx+bw+int(50*s)}" y2="{arm_y+int(65*s)}" stroke="url(#skin)" stroke-width="{int(16*s)}" stroke-linecap="round"/>')
        # Брюки и ноги
        lw = int(20 * s)
        lh = int(75 * s)
        legs = (f'<rect x="{cx-bw+int(4*s)}" y="{bb}" width="{lw*2-int(4*s)}" height="{lh}" rx="{int(6*s)}" fill="url(#pantsGrad)" filter="url(#shadow)"/>'
                f'<rect x="{cx+int(4*s)}" y="{bb}" width="{lw*2-int(4*s)}" height="{lh}" rx="{int(6*s)}" fill="url(#pantsGrad)" filter="url(#shadow)"/>')
        return shadow + neck + body + arms + legs + head + eyes + mouth

    def eink_display3d(x, y, w, h, label="EcoDisplays"):
        """3D e-ink дисплей с тенью и отражением."""
        # Корпус
        frame = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
                 f'fill="url(#einkGrad)" filter="url(#shadow)"/>')
        # Экран
        sx, sy, sw, sh2 = x+8, y+8, w-16, h-32
        screen = (f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh2}" rx="4" '
                  f'fill="url(#screenGrad)" stroke="#8899AA" stroke-width="1.5"/>')
        # Блик на экране
        glare = (f'<rect x="{sx+4}" y="{sy+4}" width="{int(sw*0.35)}" height="{int(sh2*0.25)}" '
                 f'rx="3" fill="white" opacity="0.5"/>')
        # Строки контента на экране
        lines_svg = ""
        for i in range(3):
            lw2 = int(sw * (0.85 - i * 0.18))
            ly = sy + 18 + i * int(sh2 / 3.5)
            lines_svg += f'<rect x="{sx+10}" y="{ly}" width="{lw2}" height="8" rx="4" fill="#334455" opacity="{0.85 - i*0.1}"/>'
        # Солнечная панель
        sp_y = y + h - 20
        solar = (f'<rect x="{x+4}" y="{sp_y}" width="{w-8}" height="14" rx="3" '
                 f'fill="#1E3A6E" stroke="#4466AA" stroke-width="1"/>')
        for j in range(5):
            gx = x + 4 + j * (w - 8) // 5
            solar += f'<line x1="{gx}" y1="{sp_y}" x2="{gx}" y2="{sp_y+14}" stroke="#3355AA" stroke-width="1"/>'
        # Метка
        lbl = f'<text x="{x+w//2}" y="{y+h+18}" font-family="Arial,sans-serif" font-size="13" font-weight="bold" fill="#00C878" text-anchor="middle">{label}</text>'
        return frame + screen + glare + lines_svg + solar + lbl

    def led_billboard3d(x, y, w, h):
        """3D LED-билборд с свечением."""
        glow = (f'<rect x="{x-20}" y="{y-20}" width="{w+40}" height="{h+40}" rx="10" '
                f'fill="url(#ledGlow)" opacity="0.7"/>')
        frame = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
                 f'fill="url(#ledGrad)" filter="url(#shadow)"/>')
        # Пиксели LED
        pixels = ""
        cols, rows = 6, 4
        pw = (w - 20) // cols
        ph = (h - 20) // rows
        for r in range(rows):
            for c in range(cols):
                px2 = x + 10 + c * pw + 2
                py2 = y + 10 + r * ph + 2
                bright = 1.0 if (r + c) % 2 == 0 else 0.6
                pixels += f'<rect x="{px2}" y="{py2}" width="{pw-4}" height="{ph-4}" rx="2" fill="#FFD700" opacity="{bright}"/>'
        # Блик
        glare2 = (f'<rect x="{x+6}" y="{y+6}" width="{int(w*0.3)}" height="{int(h*0.2)}" '
                  f'rx="3" fill="white" opacity="0.3"/>')
        return glow + frame + pixels + glare2

    # ── Панель 1: Дуэль ─────────────────────────────────────────────────────
    if panel_idx == 0:
        # Тёмный фон арены
        bg = f'<rect width="{W}" height="{H}" fill="url(#skyGrad1)"/>'
        # Прожектор
        spotlight = (f'<radialGradient id="spot" cx="50%" cy="0%" r="80%">'
                     f'<stop offset="0%" stop-color="#FFF8E0" stop-opacity="0.3"/>'
                     f'<stop offset="100%" stop-color="#000" stop-opacity="0"/>'
                     f'</radialGradient>'
                     f'<rect width="{W}" height="{H}" fill="url(#spot)"/>')
        # Пол ринга
        floor = f'<rect x="0" y="410" width="{W}" height="130" fill="url(#floorGrad)"/>'
        # Канаты ринга (перспектива)
        ropes = ""
        for ry in [370, 395, 418]:
            ropes += f'<line x1="20" y1="{ry}" x2="{W-20}" y2="{ry}" stroke="#CC9900" stroke-width="4" stroke-linecap="round"/>'
        # Столбы
        for px2 in [30, W-30]:
            ropes += f'<rect x="{px2-8}" y="290" width="16" height="140" rx="4" fill="#AA8800"/>'

        # LED билборд (левый боец)
        led = led_billboard3d(50, 190, 160, 190)

        # Молнии вокруг LED
        lightning = ""
        for angle_deg in range(0, 360, 45):
            a = _math.radians(angle_deg)
            x1, y1 = 130 + 90*_math.cos(a), 285 + 90*_math.sin(a)
            x2, y2 = 130 + 130*_math.cos(a), 285 + 130*_math.sin(a)
            lightning += f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#FFD700" stroke-width="3" opacity="0.8"/>'

        # E-ink дисплей (правый боец — стройный, спокойный)
        eink = eink_display3d(330, 190, 160, 190)

        # VS
        vs = ('<text x="270" y="295" font-family="Arial Black,sans-serif" font-size="52" '
              'font-weight="900" fill="#FF3300" text-anchor="middle" filter="url(#shadow)">VS</text>'
              '<text x="270" y="295" font-family="Arial Black,sans-serif" font-size="52" '
              'font-weight="900" fill="#FF6600" text-anchor="middle" opacity="0.4">VS</text>')

        # Метки
        labels = ('<text x="130" y="170" font-family="Arial,sans-serif" font-size="16" '
                  'font-weight="bold" fill="#FFD700" text-anchor="middle">LED 300W</text>'
                  '<text x="410" y="170" font-family="Arial,sans-serif" font-size="16" '
                  'font-weight="bold" fill="#00C878" text-anchor="middle">E-ink 3W</text>')

        svg = (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
               + defs_block() + f'<defs>{spotlight.split("<defs>")[0] if False else ""}</defs>'
               + bg
               + f'<defs><radialGradient id="spot" cx="50%" cy="0%" r="80%"><stop offset="0%" stop-color="#FFF8E0" stop-opacity="0.3"/><stop offset="100%" stop-color="#000" stop-opacity="0"/></radialGradient></defs>'
               + f'<rect width="{W}" height="{H}" fill="url(#spot)"/>'
               + floor + ropes + lightning + led + eink + vs + labels
               + f'</svg>')

    # ── Панель 2: Солнечный тест ─────────────────────────────────────────────
    elif panel_idx == 1:
        bg = f'<rect width="{W}" height="{H}" fill="url(#skyGrad2)"/>'
        floor = f'<rect x="0" y="420" width="{W}" height="120" fill="url(#floorGrad)"/>'
        # Солнце
        sun_rays = ""
        for angle_deg in range(0, 360, 20):
            a = _math.radians(angle_deg)
            x1, y1 = 270 + 75*_math.cos(a), 100 + 75*_math.sin(a)
            x2, y2 = 270 + 130*_math.cos(a), 100 + 130*_math.sin(a)
            sun_rays += f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#FFD700" stroke-width="5" stroke-linecap="round"/>'
        sun = (sun_rays +
               f'<circle cx="270" cy="100" r="68" fill="url(#sunGrad)" filter="url(#shadow)"/>'
               f'<circle cx="255" cy="85" r="18" fill="white" opacity="0.4"/>')

        # LCD (слева) — засвеченный, нечитаемый
        lcd_frame = (f'<rect x="35" y="185" width="180" height="200" rx="8" '
                     f'fill="#C8B090" filter="url(#shadow)"/>'
                     # экран засвечен белым
                     f'<rect x="45" y="195" width="160" height="170" rx="4" fill="#FFFAF0" opacity="0.95"/>'
                     # размытые блики
                     f'<rect x="45" y="195" width="160" height="170" rx="4" fill="#FFFFFF" opacity="0.7"/>'
                     f'<ellipse cx="125" cy="280" rx="70" ry="60" fill="white" opacity="0.5"/>')
        # Красный крест
        cross = (f'<line x1="55" y1="205" x2="205" y2="355" stroke="#CC0000" stroke-width="10" stroke-linecap="round" opacity="0.9"/>'
                 f'<line x1="205" y1="205" x2="55" y2="355" stroke="#CC0000" stroke-width="10" stroke-linecap="round" opacity="0.9"/>'
                 f'<circle cx="130" cy="280" r="75" fill="none" stroke="#CC0000" stroke-width="6" opacity="0.8"/>')
        lcd_label = f'<text x="125" y="405" font-family="Arial,sans-serif" font-size="15" fill="#880000" font-weight="bold" text-anchor="middle">LCD — zaslepljen</text>'

        # E-ink (справа) — чёткий
        eink = eink_display3d(325, 185, 180, 200, "E-ink — jasno!")
        # Зелёная галочка победы
        check = (f'<circle cx="415" cy="175" r="30" fill="#00C878" filter="url(#shadow)"/>'
                 f'<polyline points="400,175 410,188 432,160" stroke="white" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')

        svg = (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
               + defs_block() + bg + floor + sun + lcd_frame + cross + lcd_label + eink + check
               + f'</svg>')

    # ── Панель 3: Счётчик электричества ──────────────────────────────────────
    elif panel_idx == 2:
        bg = (f'<rect width="{W}" height="{H}" fill="#2A3040"/>'
              f'<rect x="0" y="340" width="{W}" height="200" fill="url(#floorGrad)"/>')

        def meter3d(x, y, w, h, value, label, color, needle_angle):
            """3D электрический счётчик."""
            # Корпус
            frame = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
                     f'fill="url(#meterGrad)" stroke="#667788" stroke-width="2" filter="url(#shadow)"/>')
            # Циферблат
            dial = (f'<circle cx="{x+w//2}" cy="{y+int(h*0.42)}" r="{int(w*0.36)}" '
                    f'fill="#F0F5FF" stroke="#8899AA" stroke-width="2"/>'
                    # Дуга измерения
                    f'<path d="M {x+w//2-int(w*0.3)} {y+int(h*0.42)} '
                    f'A {int(w*0.3)} {int(w*0.3)} 0 0 1 {x+w//2+int(w*0.3)} {y+int(h*0.42)}" '
                    f'stroke="#CCCCCC" stroke-width="3" fill="none"/>')
            # Стрелка (угол от 180° = пусто до 0° = полный)
            import math
            na = _math.radians(needle_angle)
            nx = x + w//2 + int(w * 0.3 * _math.cos(na))
            ny = y + int(h * 0.42) + int(w * 0.3 * _math.sin(na))
            needle = (f'<line x1="{x+w//2}" y1="{y+int(h*0.42)}" x2="{nx:.0f}" y2="{ny:.0f}" '
                      f'stroke="{color}" stroke-width="4" stroke-linecap="round"/>'
                      f'<circle cx="{x+w//2}" cy="{y+int(h*0.42)}" r="6" fill="{color}"/>')
            # Цифровой дисплей
            disp = (f'<rect x="{x+10}" y="{y+int(h*0.68)}" width="{w-20}" height="{int(h*0.16)}" rx="4" fill="#0A1020"/>'
                    f'<text x="{x+w//2}" y="{y+int(h*0.68+h*0.12)}" font-family="Courier,monospace" '
                    f'font-size="22" font-weight="bold" fill="{color}" text-anchor="middle">{value}</text>')
            # Метка снизу
            lbl = (f'<text x="{x+w//2}" y="{y+h+28}" font-family="Arial,sans-serif" '
                   f'font-size="16" font-weight="bold" fill="{color}" text-anchor="middle">{label}</text>')
            return frame + dial + needle + disp + lbl

        # Левый счётчик (LED, максимум)
        m1 = meter3d(50, 140, 190, 220, "300W", "LED Billboard", "#FF4444", -15)
        # Правый счётчик (e-ink, почти ноль)
        m2 = meter3d(300, 140, 190, 220, "3W", "EcoDisplays", "#00C878", -165)

        # VS по центру
        vs = ('<text x="270" y="265" font-family="Arial Black,sans-serif" font-size="36" '
              'font-weight="900" fill="#AAAAAA" text-anchor="middle">VS</text>')

        # Молния "дорого!" над левым
        expensive = ('<text x="145" y="118" font-family="Arial,sans-serif" font-size="14" '
                     'fill="#FF6666" font-weight="bold" text-anchor="middle">skupo!</text>')
        cheap = ('<text x="395" y="118" font-family="Arial,sans-serif" font-size="14" '
                 'fill="#00C878" font-weight="bold" text-anchor="middle">ekonomicno!</text>')

        svg = (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
               + defs_block() + bg + m1 + m2 + vs + expensive + cheap
               + f'</svg>')

    # ── Панель 4: Победитель ──────────────────────────────────────────────────
    else:
        bg = (f'<rect width="{W}" height="{H}" fill="#1A0A2E"/>'
              f'<rect x="0" y="380" width="{W}" height="160" fill="url(#floorGrad)"/>')

        # Конфетти
        confetti = ""
        import random as _rand
        _rand.seed(77)
        colors_conf = ["#FF4444", "#44FF88", "#4488FF", "#FFD700", "#FF44FF", "#44FFFF"]
        for _ in range(35):
            cx2 = _rand.randint(20, W-20)
            cy2 = _rand.randint(30, 360)
            c = _rand.choice(colors_conf)
            shape = _rand.randint(0, 1)
            if shape == 0:
                confetti += f'<circle cx="{cx2}" cy="{cy2}" r="{_rand.randint(5,10)}" fill="{c}" opacity="0.85"/>'
            else:
                w2 = _rand.randint(8, 16)
                confetti += f'<rect x="{cx2-w2//2}" y="{cy2-4}" width="{w2}" height="8" rx="2" fill="{c}" opacity="0.85" transform="rotate({_rand.randint(0,60)},{cx2},{cy2})"/>'

        # Пьедестал
        podium = (f'<rect x="175" y="310" width="190" height="90" rx="10" fill="url(#podiumGrad)" filter="url(#shadow)"/>'
                  f'<text x="270" y="368" font-family="Arial Black,sans-serif" font-size="46" '
                  f'font-weight="900" fill="#AA7700" text-anchor="middle">1</text>')

        # E-ink дисплей победитель (на пьедестале)
        eink = eink_display3d(190, 170, 160, 130, "EcoDisplays ✓")

        # Трофей / звезда
        trophy = (f'<polygon points="390,90 400,120 430,120 408,138 418,168 390,150 362,168 372,138 350,120 380,120" '
                  f'fill="#FFD700" filter="url(#shadow)"/>'
                  f'<circle cx="390" cy="128" r="18" fill="#FFED80" opacity="0.6"/>')

        # Мэр (персонаж радостный)
        mayor = char3d(100, 290, scale=0.82, shirt="shirtBlue", happy=True, raise_arm=True)

        # Побеждённый LED (грустный, маленький)
        defeated_led = (f'<rect x="415" y="295" width="90" height="105" rx="6" fill="#883322" filter="url(#shadow)"/>'
                        f'<rect x="421" y="301" width="78" height="80" rx="4" fill="#AA3300" opacity="0.6"/>'
                        f'<line x1="425" y1="305" x2="495" y2="375" stroke="#661100" stroke-width="5"/>'
                        f'<line x1="495" y1="305" x2="425" y2="375" stroke="#661100" stroke-width="5"/>'
                        f'<text x="460" y="420" font-family="Arial,sans-serif" font-size="13" fill="#AA6644" text-anchor="middle">LED 😵</text>')

        svg = (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
               + defs_block() + bg + confetti + podium + eink + trophy + mayor + defeated_led
               + f'</svg>')

    return _render_svg(svg)


def _svg_popart(scenario_id: int, panel_idx: int) -> bytes | None:
    """Стиль B: плоский поп-арт. Жирные контуры, яркие плашки, halftone dots, никаких градиентов."""

    W, H = 540, 540

    # Палитра плоских цветов для каждой панели
    palettes = [
        {"bg": "#FFE600", "accent": "#0057FF", "pop": "#FF2D55", "light": "#FFFFFF"},
        {"bg": "#00C2FF", "accent": "#FF2D55", "pop": "#FFE600", "light": "#FFFFFF"},
        {"bg": "#FF2D55", "accent": "#00C2FF", "pop": "#FFE600", "light": "#FFFFFF"},
        {"bg": "#7B2FFF", "accent": "#FFE600", "pop": "#00C2FF", "light": "#FFFFFF"},
    ]
    p = palettes[panel_idx % 4]

    def halftone(x, y, w, h, color, r=4, gap=14):
        dots = ""
        cy2 = y
        row = 0
        while cy2 < y + h:
            cx2 = x + (gap // 2 if row % 2 else 0)
            while cx2 < x + w:
                dots += f'<circle cx="{cx2}" cy="{cy2}" r="{r}" fill="{color}" opacity="0.18"/>'
                cx2 += gap
            cy2 += gap
            row += 1
        return dots

    def starburst_flat(cx, cy, r_in, r_out, n, color, opacity=1.0):
        pts = []
        for i in range(n * 2):
            r = r_out if i % 2 == 0 else r_in
            a = _math.radians(i * 180 / n - 90)
            pts.append(f"{cx + r*_math.cos(a):.1f},{cy + r*_math.sin(a):.1f}")
        return f'<polygon points="{" ".join(pts)}" fill="{color}" opacity="{opacity}"/>'

    def flat_person(cx, cy, s=1.0, shirt_col="#0057FF", mood="neutral"):
        """Плоский персонаж без градиентов — поп-арт стиль."""
        OUT = "#111111"
        sw = 3  # stroke-width
        hr = int(36 * s)
        # Голова
        head = (f'<circle cx="{cx}" cy="{cy}" r="{hr}" fill="#FFCB8A" stroke="{OUT}" stroke-width="{sw}"/>')
        # Глаза
        ex, ey, er = int(13*s), int(10*s), int(7*s)
        eyes = (f'<circle cx="{cx-ex}" cy="{cy-ey}" r="{er}" fill="{OUT}"/>'
                f'<circle cx="{cx+ex}" cy="{cy-ey}" r="{er}" fill="{OUT}"/>'
                f'<circle cx="{cx-ex+2}" cy="{cy-ey-2}" r="2" fill="white"/>'
                f'<circle cx="{cx+ex+2}" cy="{cy-ey-2}" r="2" fill="white"/>')
        if mood == "shocked":
            mouth = f'<ellipse cx="{cx}" cy="{cy+int(14*s)}" rx="{int(9*s)}" ry="{int(11*s)}" fill="{OUT}"/>'
        elif mood == "happy":
            mouth = (f'<path d="M{cx-int(15*s)} {cy+int(8*s)} Q{cx} {cy+int(22*s)} {cx+int(15*s)} {cy+int(8*s)}"'
                     f' stroke="{OUT}" stroke-width="3" fill="none" stroke-linecap="round"/>')
        else:
            mouth = f'<line x1="{cx-int(10*s)}" y1="{cy+int(12*s)}" x2="{cx+int(10*s)}" y2="{cy+int(12*s)}" stroke="{OUT}" stroke-width="3"/>'
        # Тело
        bw, bt = int(36*s), cy + hr - int(4*s)
        bb = bt + int(115*s)
        body = f'<rect x="{cx-bw}" y="{bt}" width="{bw*2}" height="{bb-bt}" rx="{int(8*s)}" fill="{shirt_col}" stroke="{OUT}" stroke-width="{sw}"/>'
        # Руки
        arm_y = bt + int(22*s)
        arms = (f'<line x1="{cx-bw}" y1="{arm_y}" x2="{cx-bw-int(48*s)}" y2="{arm_y+int(58*s)}" stroke="#FFCB8A" stroke-width="{int(14*s)}" stroke-linecap="round"/>'
                f'<line x1="{cx+bw}" y1="{arm_y}" x2="{cx+bw+int(48*s)}" y2="{arm_y+int(58*s)}" stroke="#FFCB8A" stroke-width="{int(14*s)}" stroke-linecap="round"/>')
        # Ноги
        lw = int(18*s)
        legs = (f'<rect x="{cx-bw+int(4*s)}" y="{bb}" width="{lw*2}" height="{int(65*s)}" rx="{int(5*s)}" fill="#1A2A6C" stroke="{OUT}" stroke-width="{sw}"/>'
                f'<rect x="{cx+int(2*s)}" y="{bb}" width="{lw*2}" height="{int(65*s)}" rx="{int(5*s)}" fill="#1A2A6C" stroke="{OUT}" stroke-width="{sw}"/>')
        # Тень (плоская эллипс)
        shadow = f'<ellipse cx="{cx}" cy="{bb+int(70*s)+6}" rx="{int(42*s)}" ry="{int(10*s)}" fill="#00000022"/>'
        return shadow + body + arms + legs + head + eyes + mouth

    def flat_eink(x, y, w, h, label="EcoDisplays"):
        OUT = "#111111"
        frame = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#E8EDF2" stroke="{OUT}" stroke-width="3"/>'
        screen = f'<rect x="{x+8}" y="{y+8}" width="{w-16}" height="{h-28}" rx="3" fill="white" stroke="{OUT}" stroke-width="2"/>'
        lines = ""
        sw2 = w - 36
        for i in range(3):
            lw2 = int(sw2 * (0.9 - i * 0.2))
            ly = y + 18 + i * int((h - 36) / 3.2)
            lines += f'<rect x="{x+18}" y="{ly}" width="{lw2}" height="7" rx="3" fill="#334455"/>'
        solar = f'<rect x="{x+6}" y="{y+h-18}" width="{w-12}" height="11" rx="2" fill="#1E3A6E" stroke="{OUT}" stroke-width="2"/>'
        lbl = f'<text x="{x+w//2}" y="{y+h+16}" font-family="Arial Black,sans-serif" font-size="12" font-weight="900" fill="#00C878" text-anchor="middle" stroke="white" stroke-width="3" paint-order="stroke">{label}</text>'
        return frame + screen + lines + solar + lbl

    def pow_badge(cx, cy, text, bg="#FF2D55", fg="white", size=22):
        """POW/ZAP бейдж — поп-арт эффект."""
        star = starburst_flat(cx, cy, int(size*0.7), int(size*1.5), 8, bg)
        txt = (f'<text x="{cx}" y="{cy+size//3}" font-family="Arial Black,sans-serif" '
               f'font-size="{size}" font-weight="900" fill="{fg}" text-anchor="middle"'
               f' stroke="{bg}" stroke-width="2" paint-order="stroke">{text}</text>')
        return star + txt

    def action_lines(cx, cy, n=16, length=220, color="#111111", opacity=0.08):
        lines = ""
        for i in range(n):
            a = _math.radians(i * 360 / n)
            lines += f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{cx+length*_math.cos(a):.0f}" y2="{cy+length*_math.sin(a):.0f}" stroke="{color}" stroke-width="2" opacity="{opacity}"/>'
        return lines

    OUT = "#111111"

    # ── Сценарий 5: Ресторан ────────────────────────────────────────────────
    if scenario_id == 5:
        if panel_idx == 0:  # Стопки бумажных меню
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            burst = starburst_flat(W//2, H//2+40, 80, 300, 18, p["accent"], 0.15)
            # Стол
            table = f'<rect x="160" y="340" width="220" height="20" rx="4" fill="#8B5E3C" stroke="{OUT}" stroke-width="3"/>'
            table += f'<rect x="190" y="358" width="20" height="80" rx="4" fill="#6B4423" stroke="{OUT}" stroke-width="2"/>'
            table += f'<rect x="330" y="358" width="20" height="80" rx="4" fill="#6B4423" stroke="{OUT}" stroke-width="2"/>'
            # Стопки бумаги (меню)
            stack = ""
            for i in range(8):
                stack += f'<rect x="{230+i*3}" y="{220-i*8}" width="80" height="110" rx="2" fill="white" stroke="{OUT}" stroke-width="2"/>'
                stack += f'<line x1="{240+i*3}" y1="{240-i*8}" x2="{300+i*3}" y2="{240-i*8}" stroke="#CCC" stroke-width="1.5"/>'
                stack += f'<line x1="{240+i*3}" y1="{255-i*8}" x2="{300+i*3}" y2="{255-i*8}" stroke="#CCC" stroke-width="1.5"/>'
            # Официант в ужасе
            person = flat_person(130, 290, s=0.85, shirt_col=p["accent"], mood="shocked")
            # POW
            badge = pow_badge(390, 230, "200×", p["pop"], "white", 20)
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + dots + burst + table + stack + person + badge + f'</svg>')

        elif panel_idx == 1:  # Установка e-ink
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            burst = starburst_flat(W//2, H//2+30, 70, 280, 16, p["accent"], 0.12)
            # Стол ресторана
            table = f'<rect x="140" y="350" width="260" height="18" rx="4" fill="#8B5E3C" stroke="{OUT}" stroke-width="3"/>'
            # E-ink дисплей на столе
            eink = flat_eink(210, 220, 160, 120)
            # Технический специалист
            person = flat_person(110, 295, s=0.82, shirt_col="#FF6600", mood="happy")
            # Инструменты
            tools = (f'<rect x="90" y="365" width="50" height="12" rx="3" fill="#FFD700" stroke="{OUT}" stroke-width="2"/>'
                     f'<rect x="150" y="368" width="30" height="8" rx="3" fill="#CCC" stroke="{OUT}" stroke-width="2"/>')
            badge = pow_badge(400, 200, "NEW!", p["pop"], "white", 20)
            # Стрела монтажа
            arrow = (f'<path d="M 175 285 L 215 250" stroke="{OUT}" stroke-width="3" fill="none" '
                     f'marker-end="url(#arr)"/>'
                     f'<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">'
                     f'<path d="M0,0 L0,6 L8,3 z" fill="{OUT}"/></marker></defs>')
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + dots + burst + table + eink + person + tools + arrow + badge + f'</svg>')

        elif panel_idx == 2:  # Менеджер обновляет с планшета
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            burst = starburst_flat(W//2, H//2+30, 60, 260, 14, p["accent"], 0.12)
            # Планшет слева
            tablet = (f'<rect x="60" y="200" width="140" height="190" rx="12" fill="#1A1A2E" stroke="{OUT}" stroke-width="3"/>'
                      f'<rect x="70" y="212" width="120" height="155" rx="6" fill="#2244AA"/>'
                      # Кнопки на экране планшета
                      f'<rect x="80" y="225" width="100" height="28" rx="5" fill="#00C878" stroke="{OUT}" stroke-width="2"/>'
                      f'<rect x="80" y="262" width="100" height="28" rx="5" fill="#FFE600" stroke="{OUT}" stroke-width="2"/>'
                      f'<rect x="80" y="299" width="100" height="28" rx="5" fill="#FF2D55" stroke="{OUT}" stroke-width="2"/>'
                      f'<text x="130" y="244" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="white" text-anchor="middle">AŽURIRAJ</text>'
                      f'<text x="130" y="281" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="{OUT}" text-anchor="middle">CENA</text>'
                      f'<text x="130" y="318" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="white" text-anchor="middle">MENI</text>')
            # Wi-Fi стрела к дисплеям
            wifi = (f'<path d="M 200 295 Q 270 240 320 260" stroke="{p["pop"]}" stroke-width="4" fill="none" stroke-dasharray="8,5"/>'
                    f'<text x="255" y="232" font-family="Arial,sans-serif" font-size="13" fill="{p["pop"]}" font-weight="bold" text-anchor="middle">Wi-Fi ⚡</text>')
            # Два e-ink дисплея справа
            e1 = flat_eink(320, 195, 120, 90)
            e2 = flat_eink(320, 305, 120, 90)
            person = flat_person(130, 300, s=0.75, shirt_col=p["accent"], mood="happy")
            badge = pow_badge(450, 175, "3 sec", "#00C878", "white", 18)
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + dots + burst + tablet + wifi + e1 + e2 + person + badge + f'</svg>')

        elif panel_idx == 3:  # Полный ресторан, счастье
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            # Конфетти
            import random as _rand
            _rand.seed(55)
            conf = ""
            for _ in range(30):
                cx2, cy2 = _rand.randint(20, W-20), _rand.randint(160, H-100)
                col = _rand.choice([p["accent"], p["pop"], p["light"], "#00C878"])
                conf += f'<circle cx="{cx2}" cy="{cy2}" r="{_rand.randint(4,9)}" fill="{col}"/>'
            # Три столика с e-ink
            for ti, tx in enumerate([60, 200, 340]):
                table_col = "#8B5E3C"
                conf += f'<rect x="{tx}" y="340" width="130" height="14" rx="4" fill="{table_col}" stroke="{OUT}" stroke-width="2"/>'
                conf += flat_eink(tx + 10, 255, 110, 78)
                # Персонаж за столом
                conf += flat_person(tx + 65, 320, s=0.62,
                                    shirt_col=[p["accent"], p["pop"], "#00C878"][ti], mood="happy")
            # Большой значок "ZERO PAPER"
            badge = pow_badge(270, 190, "0 PAPIRA!", "#00C878", "white", 19)
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + conf + badge + f'</svg>')

    # ── Сценарий 6: Умный паркинг ────────────────────────────────────────────
    elif scenario_id == 6:
        if panel_idx == 0:  # Хаос на парковке
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            burst = starburst_flat(W//2, H//2+30, 70, 300, 18, p["pop"], 0.2)
            # Машины в хаосе
            def flat_car(x, y, col, angle=0):
                return (f'<g transform="rotate({angle},{x+40},{y+25})">'
                        f'<rect x="{x}" y="{y}" width="80" height="50" rx="8" fill="{col}" stroke="{OUT}" stroke-width="3"/>'
                        f'<rect x="{x+10}" y="{y-15}" width="60" height="30" rx="5" fill="{col}" stroke="{OUT}" stroke-width="2"/>'
                        f'<circle cx="{x+15}" cy="{y+50}" r="12" fill="{OUT}"/><circle cx="{x+65}" cy="{y+50}" r="12" fill="{OUT}"/>'
                        f'<circle cx="{x+15}" cy="{y+50}" r="6" fill="#777"/><circle cx="{x+65}" cy="{y+50}" r="6" fill="#777"/>'
                        f'</g>')
            cars = flat_car(50, 250, "#FF4444", -8) + flat_car(200, 270, "#4488FF", 5) + flat_car(360, 255, "#44AA44", -3)
            # Сломанный LCD знак
            lcd = (f'<rect x="230" y="160" width="80" height="60" rx="4" fill="#882222" stroke="{OUT}" stroke-width="3"/>'
                   f'<rect x="236" y="166" width="68" height="42" rx="2" fill="#FF6666" opacity="0.7"/>'
                   f'<line x1="240" y1="170" x2="300" y2="202" stroke="{OUT}" stroke-width="4"/>'
                   f'<line x1="300" y1="170" x2="240" y2="202" stroke="{OUT}" stroke-width="4"/>'
                   f'<rect x="264" y="218" width="12" height="40" rx="3" fill="#555" stroke="{OUT}" stroke-width="2"/>')
            badge = pow_badge(420, 230, "HAOS!", p["pop"], "white", 22)
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + dots + burst + cars + lcd + badge + f'</svg>')

        elif panel_idx == 1:  # Установка e-ink знаков
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            burst = starburst_flat(W//2, H//2+40, 60, 260, 14, p["accent"], 0.1)
            # Рабочий
            person = flat_person(120, 300, s=0.88, shirt_col="#FF6600", mood="happy")
            # Знак парковки
            sign_pole = f'<rect x="278" y="250" width="14" height="160" rx="4" fill="#888" stroke="{OUT}" stroke-width="2"/>'
            sign = flat_eink(228, 155, 120, 90, "EcoDisplays")
            # Солнечная панель наверху знака
            solar_top = (f'<rect x="228" y="135" width="120" height="18" rx="3" fill="#1E3A6E" stroke="{OUT}" stroke-width="2"/>'
                         f'<text x="288" y="148" font-family="Arial,sans-serif" font-size="10" fill="#6699FF" text-anchor="middle">☀️ SOLAR</text>')
            badge = pow_badge(420, 200, "ECO!", "#00C878", "white", 20)
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + dots + burst + sign_pole + sign + solar_top + person + badge + f'</svg>')

        elif panel_idx == 2:  # Чёткий знак на солнце
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            # Солнце (плоское)
            sun = starburst_flat(420, 120, 45, 100, 14, "#FFE600", 0.9)
            sun += f'<circle cx="420" cy="120" r="44" fill="#FFE600" stroke="{OUT}" stroke-width="3"/>'
            # Знак e-ink (крупный, чёткий)
            sign_pole = f'<rect x="193" y="300" width="14" height="140" rx="4" fill="#888" stroke="{OUT}" stroke-width="2"/>'
            # Экран знака с реальным контентом
            sign_frame = f'<rect x="90" y="155" width="240" height="140" rx="8" fill="#E8EDF2" stroke="{OUT}" stroke-width="4"/>'
            sign_screen = f'<rect x="100" y="165" width="220" height="108" rx="4" fill="white" stroke="#999" stroke-width="2"/>'
            sign_text = (f'<text x="210" y="200" font-family="Arial Black,sans-serif" font-size="17" font-weight="900" fill="{OUT}" text-anchor="middle">SLOBODNIH MESTA</text>'
                         f'<text x="210" y="235" font-family="Arial Black,sans-serif" font-size="40" font-weight="900" fill="#00C878" text-anchor="middle">14</text>'
                         f'<text x="210" y="262" font-family="Arial,sans-serif" font-size="13" fill="#666" text-anchor="middle">Nivo 2 · Sektor B</text>')
            # Водитель доволен
            person = flat_person(430, 320, s=0.8, shirt_col=p["accent"], mood="happy")
            badge = pow_badge(430, 230, "JASNO!", "#00C878", "white", 18)
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + dots + sun + sign_pole + sign_frame + sign_screen + sign_text + person + badge + f'</svg>')

        elif panel_idx == 3:  # Оператор управляет удалённо
            bg = f'<rect width="{W}" height="{H}" fill="{p["bg"]}"/>'
            dots = halftone(0, 0, W, H, OUT)
            burst = starburst_flat(W//2, H//2+20, 60, 250, 14, p["accent"], 0.1)
            # Монитор оператора
            monitor = (f'<rect x="55" y="190" width="180" height="135" rx="10" fill="#1A1A2E" stroke="{OUT}" stroke-width="3"/>'
                       f'<rect x="65" y="200" width="160" height="110" rx="5" fill="#0A2244"/>'
                       # Схема парковки на экране
                       f'<rect x="75" y="210" width="50" height="35" rx="3" fill="#00C87844"/>'
                       f'<rect x="135" y="210" width="50" height="35" rx="3" fill="#FF2D5544"/>'
                       f'<rect x="75" y="255" width="50" height="35" rx="3" fill="#00C87844"/>'
                       f'<rect x="135" y="255" width="50" height="35" rx="3" fill="#00C87844"/>'
                       f'<text x="100" y="233" font-family="Arial,sans-serif" font-size="11" fill="#00C878" text-anchor="middle">FREE</text>'
                       f'<text x="160" y="233" font-family="Arial,sans-serif" font-size="11" fill="#FF2D55" text-anchor="middle">FULL</text>'
                       f'<text x="100" y="278" font-family="Arial,sans-serif" font-size="11" fill="#00C878" text-anchor="middle">FREE</text>'
                       f'<text x="160" y="278" font-family="Arial,sans-serif" font-size="11" fill="#00C878" text-anchor="middle">FREE</text>'
                       # Подставка
                       f'<rect x="125" y="323" width="40" height="12" rx="3" fill="#444" stroke="{OUT}" stroke-width="2"/>'
                       f'<rect x="110" y="333" width="70" height="8" rx="3" fill="#333" stroke="{OUT}" stroke-width="2"/>')
            # Оператор
            person = flat_person(145, 300, s=0.78, shirt_col=p["accent"], mood="happy")
            # Wi-Fi лучи
            wifi = ""
            for ri in range(3):
                r2 = 20 + ri * 18
                wifi += f'<path d="M{240-r2*0.7:.0f},{295-r2*0.7:.0f} Q240,{295-r2:.0f} {240+r2*0.7:.0f},{295-r2*0.7:.0f}" stroke="{p["pop"]}" stroke-width="3" fill="none" stroke-linecap="round"/>'
            wifi += f'<circle cx="240" cy="300" r="5" fill="{p["pop"]}"/>'
            # Три знака парковки
            for si, sx in enumerate([300, 370, 440]):
                sp = f'<rect x="{sx-7}" y="280" width="14" height="100" rx="3" fill="#888" stroke="{OUT}" stroke-width="2"/>'
                sf = f'<rect x="{sx-35}" y="195" width="70" height="80" rx="4" fill="#E8EDF2" stroke="{OUT}" stroke-width="3"/>'
                ss = f'<rect x="{sx-29}" y="203" width="58" height="58" rx="2" fill="white"/>'
                num = ["14", "8", "22"][si]
                st = f'<text x="{sx}" y="242" font-family="Arial Black,sans-serif" font-size="22" font-weight="900" fill="#00C878" text-anchor="middle">{num}</text>'
                wifi += sp + sf + ss + st
            badge = pow_badge(270, 185, "LIVE!", p["pop"], "white", 18)
            return _render_svg(f'<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">'
                               + bg + dots + burst + monitor + person + wifi + badge + f'</svg>')

    return None


def _svg_isometric(scenario_id: int, panel_idx: int) -> bytes | None:
    """Стиль C: изометрическая иллюстрация. Геометрические 3D-блоки, чистая палитра."""

    W, H = 540, 540
    OUT = "#1A1A2A"

    # Изометрические константы
    ISO_X = 0.866   # cos(30°)
    ISO_Y = 0.5     # sin(30°)

    def iso(x, y, z=0):
        """Мировые координаты → экранные (изометрия)."""
        sx = W//2 + (x - y) * ISO_X * 28
        sy = H//2 - z * 22 + (x + y) * ISO_Y * 28
        return sx, sy

    def iso_box(draw, x, y, z, w, d, h, top, left, right, stroke=OUT, sw=2):
        """Изометрический параллелепипед."""
        # Верхняя грань
        tl = iso(x,   y,   z+h)
        tr = iso(x+w, y,   z+h)
        br = iso(x+w, y+d, z+h)
        bl = iso(x,   y+d, z+h)
        draw.polygon([tl, tr, br, bl], fill=top, outline=stroke, width=sw)
        # Левая грань
        ll_t = iso(x, y+d, z+h)
        ll_b = iso(x, y+d, z)
        lr_b = iso(x+w, y+d, z)
        lr_t = iso(x+w, y+d, z+h)
        draw.polygon([ll_t, ll_b, lr_b, lr_t], fill=left, outline=stroke, width=sw)
        # Правая грань
        rl_t = iso(x+w, y, z+h)
        rl_b = iso(x+w, y, z)
        rr_b = iso(x+w, y+d, z)
        rr_t = iso(x+w, y+d, z+h)
        draw.polygon([rl_t, rl_b, rr_b, rr_t], fill=right, outline=stroke, width=sw)

    def iso_person(draw, x, y, shirt="#2255CC", mood="neutral"):
        """Изометрический человечек из блоков."""
        # Тело
        iso_box(draw, x, y, 3, 1.2, 1.2, 2.5,
                shirt, _darken(shirt, 0.7), _darken(shirt, 0.55))
        # Голова
        skin = "#FFCB8A"
        iso_box(draw, x+0.1, y+0.1, 5.5, 1.0, 1.0, 1.2,
                skin, _darken(skin, 0.85), _darken(skin, 0.7))
        # Ноги
        leg = _darken(shirt, 0.5)
        iso_box(draw, x+0.1, y+0.1, 0, 0.45, 1.0, 3.2,
                leg, _darken(leg, 0.8), _darken(leg, 0.65))
        iso_box(draw, x+0.65, y+0.1, 0, 0.45, 1.0, 3.2,
                leg, _darken(leg, 0.8), _darken(leg, 0.65))

    def _darken(hex_col, factor=0.7):
        h = hex_col.lstrip("#")
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        return f"#{int(r*factor):02X}{int(g*factor):02X}{int(b*factor):02X}"

    def iso_display(draw, x, y, z, w=2.5, d=0.3, h=2.0, label="EcoDisplays"):
        """Изометрический e-ink дисплей."""
        iso_box(draw, x, y, z, w, d, h,
                "#D8E8F0", "#A8C0D0", "#88A8C0")
        # Экран (чуть меньше)
        iso_box(draw, x+0.15, y-0.01, z+0.15, w-0.3, d+0.02, h-0.3,
                "#F0F8FF", "#C0D8E8", "#A0C0D8")
        # Строки на экране
        from PIL import ImageFont, ImageDraw as ID
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
        except:
            font = ImageFont.load_default()
        lx, ly = iso(x + w/2, y, z + h/2 + 0.3)
        draw.text((lx, ly+14), label, font=font, fill="#00C878", anchor="mm")

    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO

    # Фоновые цвета по панелям
    bg_colors = ["#F0F4FF", "#F0FFF4", "#FFF8F0", "#F8F0FF"]
    floor_colors = ["#D8E0F0", "#C8E8D8", "#F0E0C8", "#E0D0F0"]
    accent_colors = ["#2255CC", "#00AA55", "#CC5500", "#7722CC"]

    bg = bg_colors[panel_idx % 4]
    floor_c = floor_colors[panel_idx % 4]
    acc = accent_colors[panel_idx % 4]

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # Сетка пола (изометрическая)
    for gx in range(-2, 8):
        for gy in range(-2, 8):
            p1 = iso(gx, gy, 0)
            p2 = iso(gx+1, gy, 0)
            p3 = iso(gx+1, gy+1, 0)
            p4 = iso(gx, gy+1, 0)
            draw.polygon([p1, p2, p3, p4], fill=floor_c, outline="#C0C8D8", width=1)

    try:
        font_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        font_med  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
        font_sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except:
        font_big = font_med = font_sm = ImageFont.load_default()

    # ── Сценарий 7: Музей ───────────────────────────────────────────────────
    if scenario_id == 7:

        if panel_idx == 0:  # Гора бумажных этикеток
            # Стол с принтером
            iso_box(draw, 1, 2, 0, 3, 2, 0.5, "#D4A870", "#A07840", "#B88850")
            iso_box(draw, 1.5, 2.3, 0.5, 2, 1.4, 1.2, "#E8E8E8", "#B0B0B0", "#C8C8C8")
            # Стопки бумаги
            for i in range(6):
                iso_box(draw, 1.6+i*0.25, 4.5, 0, 0.2, 0.5, 0.8+i*0.15,
                        "#FFFEF0", "#D0D0B8", "#E0E0C8")
            # Восклицательный знак (хаос)
            draw.text(iso(3, 1, 5), "!", font=font_big, fill="#FF3300", anchor="mm")
            iso_person(draw, 4.5, 2, shirt=acc)

        elif panel_idx == 1:  # Установка e-ink у экспоната
            # Постамент с экспонатом (ваза)
            iso_box(draw, 2, 3, 0, 2, 2, 2.5, "#E8E0D0", "#B0A890", "#C8C0A8")
            # Ваза (упрощённая)
            iso_box(draw, 2.4, 3.4, 2.5, 1.2, 1.2, 1.8, "#C08040", "#905820", "#A87030")
            iso_box(draw, 2.2, 3.2, 4.3, 1.6, 1.6, 0.4, "#C08040", "#905820", "#A87030")
            # E-ink дисплей рядом
            iso_display(draw, 4.5, 3, 0, w=2.0, h=1.6, label="EcoDisplays")
            iso_person(draw, 0.5, 3, shirt=acc)
            # Стрелка монтажа
            p1, p2 = iso(1.8, 3.5, 2), iso(4.5, 3.5, 1)
            draw.line([p1, p2], fill=acc, width=3)
            draw.text(((p1[0]+p2[0])//2, (p1[1]+p2[1])//2 - 12), "→", font=font_big, fill=acc, anchor="mm")

        elif panel_idx == 2:  # Куратор обновляет с ноутбука
            # Стол куратора
            iso_box(draw, 0.5, 3, 0, 2.5, 2, 0.4, "#C8A860", "#9A7A38", "#B08E48")
            # Ноутбук
            iso_box(draw, 0.7, 3.2, 0.4, 2.0, 1.6, 0.1, "#2A2A3A", "#1A1A2A", "#222232")
            iso_box(draw, 0.7, 3.2, 0.5, 2.0, 0.1, 1.2, "#1E3A8A", "#142A6A", "#182F7A")
            # Три дисплея в ряд обновляются
            for di in range(3):
                iso_display(draw, 4, 1.5+di*2, 0, w=1.8, h=1.4)
                # Wi-fi дуга к каждому
                px, py = iso(3, 2.5+di*2, 1.2)
                draw.arc([px-20, py-15, px+20, py+15], start=200, end=340,
                         fill="#00C878", width=3)
            iso_person(draw, 1, 4, shirt=acc, mood="happy")
            draw.text(iso(3.5, 3.5, 4), "Wi-Fi", font=font_sm, fill="#00C878", anchor="mm")

        elif panel_idx == 3:  # Счастливый директор, нет бумаги
            # Залы музея (изометрические стены)
            iso_box(draw, 0, 0, 0, 6, 0.3, 4, "#E8E4DC", "#C0BCB4", "#D4D0C8")
            iso_box(draw, 0, 0, 0, 0.3, 6, 4, "#E8E4DC", "#C0BCB4", "#D4D0C8")
            # Экспонаты с e-ink
            for ei in range(3):
                iso_box(draw, 1+ei*2, 0.8, 0, 1.2, 1.0, 2, "#EAE0D0", "#BAB090", "#CAC0A0")
                iso_display(draw, 1+ei*2, 2.2, 0, w=1.2, h=1.0)
            # Директор
            iso_person(draw, 2.5, 4, shirt=acc, mood="happy")
            # 0 PAPIRA
            draw.text(iso(5, 1, 5), "0", font=font_big, fill="#00C878", anchor="mm")
            draw.text(iso(5, 1, 3.5), "papira", font=font_sm, fill="#00C878", anchor="mm")

    # ── Дефолт для других сценариев ─────────────────────────────────────────
    else:
        iso_box(draw, 1, 1, 0, 4, 4, 3, "#D0E8FF", "#A0C0E0", "#B0D0F0")
        iso_display(draw, 2, 2, 3)
        iso_person(draw, 4, 4, shirt=acc)

    out = BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _svg_hero(scenario_id: int, panel_idx: int) -> bytes | None:
    """Стиль D: реалистичный супергеройский комикс. Силуэты, экшн-линии, драматика."""

    W, H = 540, 540
    import subprocess, tempfile

    palettes = [
        {"sky": "#0A0A1A", "sky2": "#1A1A3A", "acc": "#FFD700", "hero": "#1E90FF", "villain": "#CC2200"},
        {"sky": "#1A0A00", "sky2": "#2A1500", "acc": "#FF6600", "hero": "#00CC88", "villain": "#880088"},
        {"sky": "#00100A", "sky2": "#001A10", "acc": "#00FF88", "hero": "#FFD700", "villain": "#FF2200"},
        {"sky": "#100018", "sky2": "#1A0028", "acc": "#FF44FF", "hero": "#FFD700", "villain": "#FF2200"},
    ]
    p = palettes[panel_idx % 4]

    def speed_lines(cx, cy, n=24, r1=60, r2=320, color="#FFFFFF", opacity=0.12):
        lines = ""
        for i in range(n):
            a = _math.radians(i * 360 / n)
            x1 = cx + r1 * _math.cos(a)
            y1 = cy + r1 * _math.sin(a)
            x2 = cx + r2 * _math.cos(a)
            y2 = cy + r2 * _math.sin(a)
            lines += f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="1.5" opacity="{opacity}"/>'
        return lines

    def city_skyline(y_base, sky1, sky2):
        """Силуэт городского горизонта."""
        svg = (f'<defs>'
               f'<linearGradient id="skyG{panel_idx}" x1="0%" y1="0%" x2="0%" y2="100%">'
               f'<stop offset="0%" stop-color="{sky1}"/>'
               f'<stop offset="100%" stop-color="{sky2}"/>'
               f'</linearGradient></defs>'
               f'<rect width="{W}" height="{H}" fill="url(#skyG{panel_idx})"/>')
        # Здания
        buildings = [
            (10,  y_base-120, 60,  120),
            (55,  y_base-180, 45,  180),
            (90,  y_base-100, 55,  100),
            (130, y_base-220, 50,  220),
            (165, y_base-140, 40,  140),
            (240, y_base-260, 70,  260),
            (295, y_base-130, 55,  130),
            (335, y_base-200, 60,  200),
            (380, y_base-160, 50,  160),
            (415, y_base-240, 65,  240),
            (465, y_base-110, 75,  110),
        ]
        for bx, by, bw, bh in buildings:
            svg += f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="#111122"/>'
            # Окна
            for wx in range(bx+6, bx+bw-4, 10):
                for wy in range(by+8, by+bh-4, 14):
                    import random as _r
                    _r.seed(wx * 100 + wy)
                    if _r.random() > 0.5:
                        svg += f'<rect x="{wx}" y="{wy}" width="6" height="8" fill="#FFEE88" opacity="0.6"/>'
        svg += f'<rect x="0" y="{y_base}" width="{W}" height="{H-y_base}" fill="#0A0A15"/>'
        return svg

    def hero_figure(cx, cy, scale=1.0, color="#1E90FF", cape="#CC0000", pose="stand"):
        """Реалистичный силуэт супергероя с плащом."""
        s = scale
        OUT = "#000000"
        sw = int(3 * s)

        if pose == "fly":
            # Летящий силуэт
            body = (
                # Плащ развевается
                f'<path d="M{cx-int(60*s)},{cy+int(20*s)} '
                f'Q{cx-int(80*s)},{cy+int(80*s)} {cx-int(30*s)},{cy+int(100*s)} '
                f'L{cx+int(20*s)},{cy+int(60*s)} Z" fill="{cape}" stroke="{OUT}" stroke-width="{sw}"/>'
                # Тело
                f'<ellipse cx="{cx}" cy="{cy}" rx="{int(28*s)}" ry="{int(38*s)}" fill="{color}" stroke="{OUT}" stroke-width="{sw}"/>'
                # Голова
                f'<circle cx="{cx+int(15*s)}" cy="{cy-int(50*s)}" r="{int(22*s)}" fill="{color}" stroke="{OUT}" stroke-width="{sw}"/>'
                # Вытянутая рука вперёд
                f'<line x1="{cx+int(28*s)}" y1="{cy-int(10*s)}" x2="{cx+int(90*s)}" y2="{cy-int(30*s)}" stroke="{color}" stroke-width="{int(18*s)}" stroke-linecap="round"/>'
                # Луч энергии из руки
                f'<line x1="{cx+int(90*s)}" y1="{cy-int(30*s)}" x2="{cx+int(180*s)}" y2="{cy-int(50*s)}" stroke="{cape}" stroke-width="6" stroke-linecap="round" opacity="0.9"/>'
            )
        elif pose == "victory":
            acc = p["acc"]
            body = (
                f'<path d="M{cx-int(50*s)},{cy+int(10*s)} '
                f'Q{cx-int(70*s)},{cy+int(70*s)} {cx-int(20*s)},{cy+int(90*s)} '
                f'L{cx+int(10*s)},{cy+int(50*s)} Z" fill="{cape}" stroke="{OUT}" stroke-width="{sw}"/>'
                f'<ellipse cx="{cx}" cy="{cy}" rx="{int(25*s)}" ry="{int(35*s)}" fill="{color}" stroke="{OUT}" stroke-width="{sw}"/>'
                f'<circle cx="{cx}" cy="{cy-int(45*s)}" r="{int(20*s)}" fill="{color}" stroke="{OUT}" stroke-width="{sw}"/>'
                f'<line x1="{cx-int(25*s)}" y1="{cy-int(15*s)}" x2="{cx-int(70*s)}" y2="{cy-int(70*s)}" stroke="{color}" stroke-width="{int(16*s)}" stroke-linecap="round"/>'
                f'<line x1="{cx+int(25*s)}" y1="{cy-int(15*s)}" x2="{cx+int(70*s)}" y2="{cy-int(70*s)}" stroke="{color}" stroke-width="{int(16*s)}" stroke-linecap="round"/>'
                f'<rect x="{cx+int(65*s)}" y="{cy-int(100*s)}" width="{int(20*s)}" height="{int(30*s)}" rx="4" fill="{acc}" stroke="{OUT}" stroke-width="2"/>'
            )
        else:  # stand
            body = (
                f'<path d="M{cx-int(40*s)},{cy+int(20*s)} '
                f'Q{cx-int(60*s)},{cy+int(80*s)} {cx-int(15*s)},{cy+int(90*s)} '
                f'L{cx},{cy+int(50*s)} Z" fill="{cape}" stroke="{OUT}" stroke-width="{sw}"/>'
                f'<ellipse cx="{cx}" cy="{cy}" rx="{int(26*s)}" ry="{int(38*s)}" fill="{color}" stroke="{OUT}" stroke-width="{sw}"/>'
                f'<circle cx="{cx}" cy="{cy-int(48*s)}" r="{int(21*s)}" fill="{color}" stroke="{OUT}" stroke-width="{sw}"/>'
                f'<line x1="{cx-int(26*s)}" y1="{cy-int(5*s)}" x2="{cx-int(65*s)}" y2="{cy+int(45*s)}" stroke="{color}" stroke-width="{int(15*s)}" stroke-linecap="round"/>'
                f'<line x1="{cx+int(26*s)}" y1="{cy-int(5*s)}" x2="{cx+int(65*s)}" y2="{cy+int(45*s)}" stroke="{color}" stroke-width="{int(15*s)}" stroke-linecap="round"/>'
            )
        # Лого "E" на груди
        _acc = p["acc"]
        logo = f'<text x="{cx}" y="{cy+int(8*s)}" font-family="Arial Black" font-size="{int(22*s)}" font-weight="900" fill="{_acc}" text-anchor="middle" stroke="{OUT}" stroke-width="2" paint-order="stroke">E</text>'
        return body + logo

    def villain_led(cx, cy, scale=1.0):
        """LED-злодей — прямоугольный, агрессивный."""
        s = scale
        OUT = "#000"
        # Тело-billboard
        body = (f'<rect x="{cx-int(45*s)}" y="{cy-int(60*s)}" width="{int(90*s)}" height="{int(80*s)}" '
                f'fill="{p["villain"]}" stroke="{OUT}" stroke-width="3"/>'
                # Злобные "глаза" из светодиодов
                f'<rect x="{cx-int(35*s)}" y="{cy-int(50*s)}" width="{int(25*s)}" height="{int(18*s)}" fill="#FF6600" stroke="{OUT}" stroke-width="2"/>'
                f'<rect x="{cx+int(10*s)}" y="{cy-int(50*s)}" width="{int(25*s)}" height="{int(18*s)}" fill="#FF6600" stroke="{OUT}" stroke-width="2"/>'
                # Рот
                f'<rect x="{cx-int(25*s)}" y="{cy-int(22*s)}" width="{int(50*s)}" height="{int(8*s)}" fill="#FF0000"/>'
                # Текст "300W"
                f'<text x="{cx}" y="{cy+int(15*s)}" font-family="Arial Black" font-size="{int(18*s)}" '
                f'font-weight="900" fill="#FFD700" text-anchor="middle">300W</text>'
                # Руки-кабели
                f'<line x1="{cx-int(45*s)}" y1="{cy-int(30*s)}" x2="{cx-int(90*s)}" y2="{cy+int(20*s)}" '
                f'stroke="{OUT}" stroke-width="{int(12*s)}" stroke-linecap="round"/>'
                f'<line x1="{cx+int(45*s)}" y1="{cy-int(30*s)}" x2="{cx+int(90*s)}" y2="{cy+int(20*s)}" '
                f'stroke="{OUT}" stroke-width="{int(12*s)}" stroke-linecap="round"/>'
                # Ноги
                f'<rect x="{cx-int(35*s)}" y="{cy+int(20*s)}" width="{int(25*s)}" height="{int(50*s)}" fill="{p["villain"]}" stroke="{OUT}" stroke-width="2"/>'
                f'<rect x="{cx+int(10*s)}" y="{cy+int(20*s)}" width="{int(25*s)}" height="{int(50*s)}" fill="{p["villain"]}" stroke="{OUT}" stroke-width="2"/>'
                # Молнии вокруг
                )
        for a_deg in [30, 60, 120, 150, 210, 240, 300, 330]:
            a = _math.radians(a_deg)
            x1 = cx + int(50*s*_math.cos(a))
            y1 = cy + int(50*s*_math.sin(a))
            x2 = cx + int(80*s*_math.cos(a))
            y2 = cy + int(80*s*_math.sin(a))
            body += f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#FFD700" stroke-width="3"/>'
        return body

    def impact_text(x, y, text, size=36, color="#FFD700", outline="#000"):
        return (f'<text x="{x}" y="{y}" font-family="Arial Black,sans-serif" font-size="{size}" '
                f'font-weight="900" fill="{outline}" text-anchor="middle" '
                f'stroke="{outline}" stroke-width="6" paint-order="stroke">{text}</text>'
                f'<text x="{x}" y="{y}" font-family="Arial Black,sans-serif" font-size="{size}" '
                f'font-weight="900" fill="{color}" text-anchor="middle">{text}</text>')

    def halftone_circle(cx, cy, r, color, n_rows=8):
        dots = ""
        for row in range(-n_rows, n_rows+1):
            for col in range(-n_rows, n_rows+1):
                dx = col * (r / n_rows)
                dy = row * (r / n_rows)
                if dx*dx + dy*dy < r*r:
                    dots += f'<circle cx="{cx+dx:.0f}" cy="{cy+dy:.0f}" r="3" fill="{color}" opacity="0.25"/>'
        return dots

    # ── Построение панелей ───────────────────────────────────────────────────
    parts = []

    if panel_idx == 0:  # Злодей LED объявляет войну
        parts.append(city_skyline(380, p["sky"], p["sky2"]))
        parts.append(speed_lines(W//2, H//2, n=32, r1=40, r2=350, color=p["acc"], opacity=0.08))
        parts.append(halftone_circle(W//2, H//2, 200, p["acc"]))
        parts.append(villain_led(280, 270, scale=1.0))
        parts.append(impact_text(130, 200, "300W!", 40, p["villain"], "#000"))
        parts.append(impact_text(130, 250, "HA-HA!", 28, "#FF4444", "#000"))

    elif panel_idx == 1:  # Герой E-ink на солнце побеждает
        # Яркое солнце
        sun_svg = f'<defs><radialGradient id="sunH" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="#FFFFFF"/><stop offset="40%" stop-color="#FFFF00"/><stop offset="100%" stop-color="#FF8800" stop-opacity="0"/></radialGradient></defs>'
        sun_svg += f'<circle cx="400" cy="100" r="120" fill="url(#sunH)"/>'
        for a_deg in range(0, 360, 15):
            a = _math.radians(a_deg)
            sun_svg += f'<line x1="{400+80*_math.cos(a):.0f}" y1="{100+80*_math.sin(a):.0f}" x2="{400+140*_math.cos(a):.0f}" y2="{100+140*_math.sin(a):.0f}" stroke="#FFD700" stroke-width="4" stroke-linecap="round"/>'
        parts.append(city_skyline(400, "#000A1A", "#001A30"))
        parts.append(sun_svg)
        parts.append(speed_lines(200, 320, n=20, r1=30, r2=300, color=p["hero"], opacity=0.1))
        # Герой летит навстречу солнцу
        parts.append(hero_figure(200, 320, scale=1.0, color=p["hero"], cape="#CC0000", pose="fly"))
        # LCD горит и тает
        parts.append(f'<rect x="330" y="250" width="150" height="120" rx="6" fill="#AA2200" opacity="0.7" stroke="#FF4400" stroke-width="3"/>')
        parts.append(f'<line x1="330" y1="250" x2="480" y2="370" stroke="#FF0000" stroke-width="6"/>')
        parts.append(f'<line x1="480" y1="250" x2="330" y2="370" stroke="#FF0000" stroke-width="6"/>')
        parts.append(impact_text(405, 230, "ZASLEPLJEN!", 20, "#FF4444", "#000"))

    elif panel_idx == 2:  # Duel счётчики
        parts.append(f'<rect width="{W}" height="{H}" fill="{p["sky"]}"/>')
        parts.append(speed_lines(W//2, H//2, n=28, r1=10, r2=380, color="#FFFFFF", opacity=0.06))
        parts.append(halftone_circle(W//2, H//2, 240, p["acc"]))
        # Два персонажа сталкиваются
        parts.append(villain_led(390, 290, scale=0.85))
        parts.append(hero_figure(150, 290, scale=0.85, color=p["hero"], cape="#CC0000", pose="fly"))
        # Взрыв в центре
        parts.append(f'<polygon points="270,240 285,200 300,240 340,225 315,255 340,280 300,265 285,310 270,265 230,280 255,255 230,225" fill="{p["acc"]}" stroke="#000" stroke-width="2"/>')
        parts.append(impact_text(270, 270, "VS", 44, p["acc"], "#000"))
        parts.append(impact_text(150, 200, "3W", 32, p["hero"], "#000"))
        parts.append(impact_text(390, 200, "300W", 28, p["villain"], "#000"))

    elif panel_idx == 3:  # Победа героя
        parts.append(city_skyline(400, "#000A00", "#001A10"))
        parts.append(speed_lines(W//2, H//2, n=36, r1=20, r2=380, color=p["acc"], opacity=0.15))
        parts.append(halftone_circle(W//2, H//2 - 30, 180, p["acc"]))
        # Герой в позе победы
        parts.append(hero_figure(220, 310, scale=1.05, color=p["hero"], cape="#CC0000", pose="victory"))
        # Поверженный злодей
        parts.append(f'<g transform="rotate(30,420,360)">{villain_led(420, 380, scale=0.7)}</g>')
        parts.append(f'<text x="420" y="440" font-family="Arial Black" font-size="16" fill="#888" text-anchor="middle">💀 LED</text>')
        # Логотип победы
        parts.append(impact_text(220, 160, "EcoDisplays", 28, p["acc"], "#000"))
        parts.append(impact_text(220, 195, "POBEDNIK! 🏆", 22, "#00FF88", "#000"))

    svg = (f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
           + "".join(parts)
           + f'</svg>')

    return _render_svg(svg)


def _svg_hero3d(scenario_id: int, panel_idx: int) -> bytes | None:
    """Стиль E: реалистичный 3D супергерой. Градиенты, тени, объём — сценарий 4."""

    W, H = 540, 540

    def defs():
        return """<defs>
  <radialGradient id="h3skin" cx="38%" cy="32%" r="58%">
    <stop offset="0%" stop-color="#FFE8CC"/>
    <stop offset="60%" stop-color="#FFCB8A"/>
    <stop offset="100%" stop-color="#D4935A"/>
  </radialGradient>
  <linearGradient id="h3suit" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#4488FF"/>
    <stop offset="50%" stop-color="#1155CC"/>
    <stop offset="100%" stop-color="#003399"/>
  </linearGradient>
  <linearGradient id="h3cape" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#FF4444"/>
    <stop offset="100%" stop-color="#AA0000"/>
  </linearGradient>
  <linearGradient id="h3led" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#FF6622"/>
    <stop offset="50%" stop-color="#DD2200"/>
    <stop offset="100%" stop-color="#881100"/>
  </linearGradient>
  <radialGradient id="h3glow" cx="50%" cy="50%" r="50%">
    <stop offset="0%" stop-color="#FFD700" stop-opacity="0.9"/>
    <stop offset="60%" stop-color="#FF8800" stop-opacity="0.4"/>
    <stop offset="100%" stop-color="#FF4400" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="h3sun" cx="50%" cy="50%" r="50%">
    <stop offset="0%" stop-color="#FFFFFF"/>
    <stop offset="30%" stop-color="#FFFFA0"/>
    <stop offset="70%" stop-color="#FFD700"/>
    <stop offset="100%" stop-color="#FF8800"/>
  </radialGradient>
  <linearGradient id="h3sky0" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#08081A"/>
    <stop offset="100%" stop-color="#1A1A3A"/>
  </linearGradient>
  <linearGradient id="h3sky1" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#0A1A2E"/>
    <stop offset="100%" stop-color="#1A3A5E"/>
  </linearGradient>
  <linearGradient id="h3sky2" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#0A1A08"/>
    <stop offset="100%" stop-color="#1A3A18"/>
  </linearGradient>
  <linearGradient id="h3gold" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#FFE566"/>
    <stop offset="50%" stop-color="#FFD700"/>
    <stop offset="100%" stop-color="#CC9900"/>
  </linearGradient>
  <linearGradient id="h3eink" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#E8EDF5"/>
    <stop offset="50%" stop-color="#D0D8E8"/>
    <stop offset="100%" stop-color="#A8B8CC"/>
  </linearGradient>
  <filter id="h3shadow">
    <feDropShadow dx="4" dy="6" stdDeviation="6" flood-color="#000" flood-opacity="0.4"/>
  </filter>
  <filter id="h3glofw">
    <feGaussianBlur stdDeviation="10" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="h3fire">
    <feGaussianBlur stdDeviation="4" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
</defs>"""

    def city_bg(sky_id):
        s = f'<rect width="{W}" height="{H}" fill="url(#{sky_id})"/>'
        buildings = [
            (0,   400, 55,  140), (50,  340, 42,  200), (88,  380, 60,  160),
            (140, 320, 48,  220), (184, 360, 38,  180), (220, 290, 68,  250),
            (282, 350, 52,  190), (330, 310, 58,  230), (384, 345, 48,  195),
            (428, 280, 62,  260), (486, 370, 54,  170),
        ]
        for bx, by, bw, bh in buildings:
            s += f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="#0D0D22"/>'
            for wx in range(bx+5, bx+bw-3, 9):
                for wy in range(by+6, by+bh-4, 12):
                    import random as _r2; _r2.seed(wx*97+wy)
                    if _r2.random() > 0.45:
                        s += f'<rect x="{wx}" y="{wy}" width="5" height="7" fill="#FFEE99" opacity="0.55"/>'
        s += f'<rect x="0" y="480" width="{W}" height="60" fill="#0A0A18"/>'
        return s

    def hero3d(cx, cy, scale=1.0, pose="stand"):
        """Реалистичный 3D-персонаж E-ink героя с градиентами."""
        s = scale
        parts = []
        # Тень
        parts.append(f'<ellipse cx="{cx}" cy="{cy+int(200*s)}" rx="{int(55*s)}" ry="{int(14*s)}" fill="#000" opacity="0.3"/>')

        if pose == "fly":
            # Плащ развевается назад-вниз
            parts.append(f'<path d="M{cx},{cy+int(30*s)} Q{cx-int(90*s)},{cy+int(100*s)} {cx-int(50*s)},{cy+int(150*s)} L{cx+int(10*s)},{cy+int(80*s)} Z" fill="url(#h3cape)" filter="url(#h3shadow)"/>')
            # Тело (торс)
            parts.append(f'<ellipse cx="{cx}" cy="{cy+int(40*s)}" rx="{int(32*s)}" ry="{int(50*s)}" fill="url(#h3suit)" filter="url(#h3shadow)"/>')
            # Логотип "E" на груди
            parts.append(f'<text x="{cx}" y="{cy+int(52*s)}" font-family="Arial Black" font-size="{int(26*s)}" font-weight="900" fill="#FFD700" text-anchor="middle" stroke="#000" stroke-width="2" paint-order="stroke">E</text>')
            # Голова
            parts.append(f'<circle cx="{cx+int(20*s)}" cy="{cy-int(20*s)}" r="{int(36*s)}" fill="url(#h3skin)" filter="url(#h3shadow)"/>')
            # Шлем-маска
            parts.append(f'<path d="M{cx-int(10*s)},{cy-int(52*s)} Q{cx+int(50*s)},{cy-int(58*s)} {cx+int(56*s)},{cy-int(18*s)} Q{cx+int(55*s)},{cy+int(8*s)} {cx+int(20*s)},{cy+int(12*s)} Q{cx-int(15*s)},{cy-int(5*s)} {cx-int(10*s)},{cy-int(52*s)} Z" fill="url(#h3suit)" opacity="0.7"/>')
            # Рука вытянута вперёд
            parts.append(f'<ellipse cx="{cx+int(80*s)}" cy="{cy+int(10*s)}" rx="{int(50*s)}" ry="{int(18*s)}" fill="url(#h3suit)" filter="url(#h3shadow)" transform="rotate(-15,{cx+int(80*s)},{cy+int(10*s)})"/>')
            # Энергетический луч
            parts.append(f'<ellipse cx="{cx+int(155*s)}" cy="{cy-int(5*s)}" rx="{int(40*s)}" ry="{int(12*s)}" fill="url(#h3glow)" filter="url(#h3glofw)" opacity="0.85"/>')
            # Ноги
            parts.append(f'<ellipse cx="{cx-int(10*s)}" cy="{cy+int(120*s)}" rx="{int(18*s)}" ry="{int(45*s)}" fill="url(#h3suit)" transform="rotate(-20,{cx-int(10*s)},{cy+int(120*s)})"/>')
            parts.append(f'<ellipse cx="{cx+int(15*s)}" cy="{cy+int(115*s)}" rx="{int(18*s)}" ry="{int(45*s)}" fill="url(#h3suit)" transform="rotate(10,{cx+int(15*s)},{cy+int(115*s)})"/>')

        elif pose == "victory":
            # Плащ
            parts.append(f'<path d="M{cx},{cy+int(30*s)} Q{cx-int(80*s)},{cy+int(120*s)} {cx-int(40*s)},{cy+int(170*s)} L{cx+int(10*s)},{cy+int(90*s)} Z" fill="url(#h3cape)" filter="url(#h3shadow)"/>')
            # Торс
            parts.append(f'<ellipse cx="{cx}" cy="{cy+int(45*s)}" rx="{int(30*s)}" ry="{int(48*s)}" fill="url(#h3suit)" filter="url(#h3shadow)"/>')
            parts.append(f'<text x="{cx}" y="{cy+int(57*s)}" font-family="Arial Black" font-size="{int(26*s)}" font-weight="900" fill="#FFD700" text-anchor="middle" stroke="#000" stroke-width="2" paint-order="stroke">E</text>')
            # Голова
            parts.append(f'<circle cx="{cx}" cy="{cy-int(15*s)}" r="{int(35*s)}" fill="url(#h3skin)" filter="url(#h3shadow)"/>')
            parts.append(f'<path d="M{cx-int(30*s)},{cy-int(48*s)} Q{cx},{cy-int(55*s)} {cx+int(35*s)},{cy-int(45*s)} Q{cx+int(35*s)},{cy-int(10*s)} {cx},{cy-int(5*s)} Q{cx-int(30*s)},{cy-int(10*s)} {cx-int(30*s)},{cy-int(48*s)} Z" fill="url(#h3suit)" opacity="0.65"/>')
            # Руки вверх (V-победа)
            parts.append(f'<ellipse cx="{cx-int(75*s)}" cy="{cy-int(40*s)}" rx="{int(18*s)}" ry="{int(50*s)}" fill="url(#h3suit)" filter="url(#h3shadow)" transform="rotate(-30,{cx-int(75*s)},{cy-int(40*s)})"/>')
            parts.append(f'<ellipse cx="{cx+int(75*s)}" cy="{cy-int(40*s)}" rx="{int(18*s)}" ry="{int(50*s)}" fill="url(#h3suit)" filter="url(#h3shadow)" transform="rotate(30,{cx+int(75*s)},{cy-int(40*s)})"/>')
            # Трофей
            parts.append(f'<rect x="{cx+int(60*s)}" y="{cy-int(100*s)}" width="{int(28*s)}" height="{int(36*s)}" rx="4" fill="url(#h3gold)" filter="url(#h3shadow)"/>')
            parts.append(f'<text x="{cx+int(74*s)}" y="{cy-int(74*s)}" font-family="Arial Black" font-size="{int(14*s)}" fill="#000" text-anchor="middle">🏆</text>')
            # Ноги
            parts.append(f'<ellipse cx="{cx-int(12*s)}" cy="{cy+int(130*s)}" rx="{int(17*s)}" ry="{int(50*s)}" fill="url(#h3suit)"/>')
            parts.append(f'<ellipse cx="{cx+int(12*s)}" cy="{cy+int(130*s)}" rx="{int(17*s)}" ry="{int(50*s)}" fill="url(#h3suit)"/>')

        else:  # stand
            parts.append(f'<path d="M{cx},{cy+int(30*s)} Q{cx-int(70*s)},{cy+int(110*s)} {cx-int(35*s)},{cy+int(160*s)} L{cx+int(5*s)},{cy+int(80*s)} Z" fill="url(#h3cape)" filter="url(#h3shadow)"/>')
            parts.append(f'<ellipse cx="{cx}" cy="{cy+int(45*s)}" rx="{int(30*s)}" ry="{int(48*s)}" fill="url(#h3suit)" filter="url(#h3shadow)"/>')
            parts.append(f'<text x="{cx}" y="{cy+int(57*s)}" font-family="Arial Black" font-size="{int(26*s)}" font-weight="900" fill="#FFD700" text-anchor="middle" stroke="#000" stroke-width="2" paint-order="stroke">E</text>')
            parts.append(f'<circle cx="{cx}" cy="{cy-int(15*s)}" r="{int(35*s)}" fill="url(#h3skin)" filter="url(#h3shadow)"/>')
            parts.append(f'<path d="M{cx-int(30*s)},{cy-int(48*s)} Q{cx},{cy-int(55*s)} {cx+int(35*s)},{cy-int(45*s)} Q{cx+int(35*s)},{cy-int(10*s)} {cx},{cy-int(5*s)} Q{cx-int(30*s)},{cy-int(10*s)} {cx-int(30*s)},{cy-int(48*s)} Z" fill="url(#h3suit)" opacity="0.65"/>')
            parts.append(f'<ellipse cx="{cx-int(60*s)}" cy="{cy+int(40*s)}" rx="{int(16*s)}" ry="{int(44*s)}" fill="url(#h3suit)" filter="url(#h3shadow)" transform="rotate(-8,{cx-int(60*s)},{cy+int(40*s)})"/>')
            parts.append(f'<ellipse cx="{cx+int(60*s)}" cy="{cy+int(40*s)}" rx="{int(16*s)}" ry="{int(44*s)}" fill="url(#h3suit)" filter="url(#h3shadow)" transform="rotate(8,{cx+int(60*s)},{cy+int(40*s)})"/>')
            parts.append(f'<ellipse cx="{cx-int(12*s)}" cy="{cy+int(130*s)}" rx="{int(17*s)}" ry="{int(50*s)}" fill="url(#h3suit)"/>')
            parts.append(f'<ellipse cx="{cx+int(12*s)}" cy="{cy+int(130*s)}" rx="{int(17*s)}" ry="{int(50*s)}" fill="url(#h3suit)"/>')

        return "".join(parts)

    def villain3d(cx, cy, scale=1.0, defeated=False):
        """3D LED-злодей с объёмом и деталями."""
        s = scale
        parts = []
        parts.append(f'<ellipse cx="{cx}" cy="{cy+int(190*s)}" rx="{int(60*s)}" ry="{int(15*s)}" fill="#000" opacity="0.3"/>')
        # Корпус
        parts.append(f'<rect x="{cx-int(52*s)}" y="{cy-int(70*s)}" width="{int(104*s)}" height="{int(90*s)}" rx="8" fill="url(#h3led)" filter="url(#h3shadow)"/>')
        # Светящаяся рамка
        parts.append(f'<rect x="{cx-int(48*s)}" y="{cy-int(66*s)}" width="{int(96*s)}" height="{int(82*s)}" rx="6" fill="none" stroke="#FF6600" stroke-width="3" opacity="0.8"/>')
        # Экран "лицо"
        parts.append(f'<rect x="{cx-int(40*s)}" y="{cy-int(60*s)}" width="{int(80*s)}" height="{int(70*s)}" rx="4" fill="#1A0000"/>')
        # Злобные глаза-LED
        parts.append(f'<rect x="{cx-int(36*s)}" y="{cy-int(52*s)}" width="{int(28*s)}" height="{int(20*s)}" rx="3" fill="#FF6600" filter="url(#h3fire)"/>')
        parts.append(f'<rect x="{cx+int(8*s)}" y="{cy-int(52*s)}" width="{int(28*s)}" height="{int(20*s)}" rx="3" fill="#FF6600" filter="url(#h3fire)"/>')
        # Агрессивный рот
        parts.append(f'<rect x="{cx-int(28*s)}" y="{cy-int(24*s)}" width="{int(56*s)}" height="{int(10*s)}" rx="2" fill="#FF0000"/>')
        # Надпись "300W"
        parts.append(f'<text x="{cx}" y="{cy+int(15*s)}" font-family="Arial Black" font-size="{int(20*s)}" font-weight="900" fill="#FFD700" text-anchor="middle" stroke="#000" stroke-width="2" paint-order="stroke">300W</text>')
        if defeated:
            # X на экране
            parts.append(f'<line x1="{cx-int(35*s)}" y1="{cy-int(60*s)}" x2="{cx+int(35*s)}" y2="{cy+int(10*s)}" stroke="#888" stroke-width="{int(8*s)}" stroke-linecap="round"/>')
            parts.append(f'<line x1="{cx+int(35*s)}" y1="{cy-int(60*s)}" x2="{cx-int(35*s)}" y2="{cy+int(10*s)}" stroke="#888" stroke-width="{int(8*s)}" stroke-linecap="round"/>')
        else:
            # Молнии вокруг
            for a_deg in [20, 50, 130, 160, 200, 340]:
                a = _math.radians(a_deg)
                x1 = cx + int(55*s*_math.cos(a)); y1 = cy + int(55*s*_math.sin(a))
                x2 = cx + int(85*s*_math.cos(a)); y2 = cy + int(85*s*_math.sin(a))
                parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#FFD700" stroke-width="3" stroke-linecap="round"/>')
        # Руки-кабели
        parts.append(f'<line x1="{cx-int(52*s)}" y1="{cy-int(30*s)}" x2="{cx-int(100*s)}" y2="{cy+int(30*s)}" stroke="#881100" stroke-width="{int(14*s)}" stroke-linecap="round" filter="url(#h3shadow)"/>')
        parts.append(f'<line x1="{cx+int(52*s)}" y1="{cy-int(30*s)}" x2="{cx+int(100*s)}" y2="{cy+int(30*s)}" stroke="#881100" stroke-width="{int(14*s)}" stroke-linecap="round" filter="url(#h3shadow)"/>')
        # Ноги
        parts.append(f'<rect x="{cx-int(42*s)}" y="{cy+int(20*s)}" width="{int(28*s)}" height="{int(60*s)}" rx="4" fill="url(#h3led)" filter="url(#h3shadow)"/>')
        parts.append(f'<rect x="{cx+int(14*s)}" y="{cy+int(20*s)}" width="{int(28*s)}" height="{int(60*s)}" rx="4" fill="url(#h3led)" filter="url(#h3shadow)"/>')
        return "".join(parts)

    def eink_display3d(cx, cy, scale=1.0):
        """3D e-ink дисплей."""
        s = scale
        return (
            f'<rect x="{cx-int(70*s)}" y="{cy-int(90*s)}" width="{int(140*s)}" height="{int(100*s)}" rx="10" fill="url(#h3eink)" filter="url(#h3shadow)"/>'
            f'<rect x="{cx-int(62*s)}" y="{cy-int(82*s)}" width="{int(124*s)}" height="{int(84*s)}" rx="6" fill="#F0F5FF"/>'
            f'<text x="{cx}" y="{cy-int(50*s)}" font-family="Arial" font-size="{int(13*s)}" fill="#333" text-anchor="middle">E-ink Display</text>'
            f'<text x="{cx}" y="{cy-int(30*s)}" font-family="Arial Black" font-size="{int(18*s)}" font-weight="900" fill="#00AA44" text-anchor="middle">3W ✓</text>'
            f'<text x="{cx}" y="{cy-int(8*s)}" font-family="Arial" font-size="{int(12*s)}" fill="#555" text-anchor="middle">Čitljivo na suncu</text>'
            f'<rect x="{cx-int(8*s)}" y="{cy+int(10*s)}" width="{int(16*s)}" height="{int(20*s)}" rx="2" fill="#999"/>'
        )

    def label3d(text, x, y, color="#FFD700"):
        return (f'<text x="{x}" y="{y}" font-family="Arial Black,sans-serif" font-size="22" '
                f'font-weight="900" fill="#000" text-anchor="middle" '
                f'stroke="#000" stroke-width="7" paint-order="stroke">{text}</text>'
                f'<text x="{x}" y="{y}" font-family="Arial Black,sans-serif" font-size="22" '
                f'font-weight="900" fill="{color}" text-anchor="middle">{text}</text>')

    # ── Построение панелей ───────────────────────────────────────────────────
    body = ""

    if panel_idx == 0:
        # Панель 1: LED злодей объявляет войну городу
        body += city_bg("h3sky0")
        # Ореол зловещего свечения
        body += f'<circle cx="290" cy="240" r="180" fill="url(#h3glow)" opacity="0.5" filter="url(#h3glofw)"/>'
        body += villain3d(290, 230, scale=1.0)
        # Молния сверху
        body += f'<polygon points="310,60 295,140 315,130 295,210" fill="#FFD700" filter="url(#h3fire)" opacity="0.9"/>'
        body += label3d("NAPAD!", 290, 60, "#FF4444")
        body += label3d("300W HA-HA!", 165, 120, "#FF8800")

    elif panel_idx == 1:
        # Панель 2: E-ink герой летит навстречу солнцу, LCD горит
        body += city_bg("h3sky1")
        # Солнце
        body += f'<circle cx="420" cy="90" r="85" fill="url(#h3sun)" filter="url(#h3glofw)"/>'
        for a_deg in range(0, 360, 20):
            a = _math.radians(a_deg)
            body += f'<line x1="{420+65*_math.cos(a):.0f}" y1="{90+65*_math.sin(a):.0f}" x2="{420+115*_math.cos(a):.0f}" y2="{90+115*_math.sin(a):.0f}" stroke="#FFD700" stroke-width="5" stroke-linecap="round" opacity="0.7"/>'
        # Герой летит
        body += hero3d(180, 290, scale=0.95, pose="fly")
        # Горящий LCD (поверженный экран)
        body += f'<rect x="340" y="230" width="130" height="100" rx="8" fill="#881100" opacity="0.8" filter="url(#h3shadow)"/>'
        body += f'<line x1="340" y1="230" x2="470" y2="330" stroke="#FF2200" stroke-width="6"/>'
        body += f'<line x1="470" y1="230" x2="340" y2="330" stroke="#FF2200" stroke-width="6"/>'
        for i in range(5):
            fx = 340 + i*26; fy = 185 + (i%3)*15
            body += f'<polygon points="{fx},{fy+30} {fx+8},{fy} {fx+16},{fy+30}" fill="#FF6600" filter="url(#h3fire)" opacity="0.8"/>'
        body += label3d("ZASLEPLJEN!", 405, 215, "#FF4444")

    elif panel_idx == 2:
        # Панель 3: Дуэль — счётчики 3W vs 300W
        body += f'<rect width="{W}" height="{H}" fill="url(#h3sky0)"/>'
        # Взрыв в центре
        body += f'<circle cx="{W//2}" cy="{H//2}" r="140" fill="url(#h3glow)" filter="url(#h3glofw)" opacity="0.7"/>'
        body += f'<polygon points="270,200 285,155 300,200 345,180 318,215 345,245 300,228 285,275 270,228 225,245 252,215 225,180" fill="#FFD700" stroke="#000" stroke-width="2" filter="url(#h3fire)"/>'
        # Два персонажа
        body += villain3d(400, 270, scale=0.80)
        body += hero3d(140, 270, scale=0.80, pose="fly")
        body += label3d("3W", 140, 175, "#4488FF")
        body += label3d("VS", W//2, H//2+12, "#FFD700")
        body += label3d("300W", 400, 175, "#FF4444")

    elif panel_idx == 3:
        # Панель 4: Победа героя, поверженный злодей
        body += city_bg("h3sky2")
        # Ореол победы
        body += f'<circle cx="220" cy="280" r="170" fill="url(#h3glow)" opacity="0.35" filter="url(#h3glofw)"/>'
        body += hero3d(220, 270, scale=1.0, pose="victory")
        # Поверженный злодей на полу
        body += f'<g transform="rotate(35,410,380)">{villain3d(410, 380, scale=0.65, defeated=True)}</g>'
        body += f'<text x="410" y="448" font-family="Arial Black" font-size="15" fill="#888" text-anchor="middle">💀 LED: 0W</text>'
        # E-ink дисплей в фоне
        body += eink_display3d(375, 170, scale=0.9)
        body += label3d("POBEDNIK!", 220, 115, "#FFD700")
        body += label3d("EcoDisplays ✓", 220, 148, "#00FF88")

    svg = f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">{defs()}{body}</svg>'
    return _render_svg(svg)


def _svg_simpsons(panel_idx: int) -> bytes | None:
    """Симпсоны-стиль: жёлтые персонажи, жирные контуры, Спрингфилд."""
    W, H = 540, 540
    SW = 5  # stroke-width стандартный

    defs = """<defs>
  <radialGradient id="skyDay" cx="50%" cy="0%" r="100%">
    <stop offset="0%" stop-color="#87CEEB"/>
    <stop offset="100%" stop-color="#C8E8FF"/>
  </radialGradient>
  <radialGradient id="skyEvening" cx="50%" cy="0%" r="100%">
    <stop offset="0%" stop-color="#FF7043"/>
    <stop offset="60%" stop-color="#FFB74D"/>
    <stop offset="100%" stop-color="#FFF9C4"/>
  </radialGradient>
  <radialGradient id="sunGrad" cx="45%" cy="35%" r="55%">
    <stop offset="0%" stop-color="#FFFF99"/>
    <stop offset="100%" stop-color="#FFD600"/>
  </radialGradient>
  <linearGradient id="grassGrad" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#66BB6A"/>
    <stop offset="100%" stop-color="#388E3C"/>
  </linearGradient>
  <linearGradient id="houseWall" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#EF9A9A"/>
    <stop offset="100%" stop-color="#E57373"/>
  </linearGradient>
  <linearGradient id="floorGrad" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#D7CCC8"/>
    <stop offset="100%" stop-color="#BCAAA4"/>
  </linearGradient>
  <filter id="outline">
    <feMorphology operator="dilate" radius="2" result="thick"/>
    <feComposite in="SourceGraphic" in2="thick"/>
  </filter>
</defs>"""

    # ── Вспомогательные функции ──────────────────────────────────────────

    def sky(evening=False):
        grad = "skyEvening" if evening else "skyDay"
        return f'<rect width="{W}" height="{H}" fill="url(#{grad})"/>'

    def ground(y=380, color="url(#grassGrad)"):
        return f'<rect x="0" y="{y}" width="{W}" height="{H-y}" fill="{color}"/>'

    def sun(cx=450, cy=80, r=50):
        rays = ""
        import math
        for i in range(12):
            a = math.radians(i * 30)
            x1, y1 = cx + (r+8)*math.cos(a), cy + (r+8)*math.sin(a)
            x2, y2 = cx + (r+22)*math.cos(a), cy + (r+22)*math.sin(a)
            rays += f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#FFD600" stroke-width="4" stroke-linecap="round"/>'
        return (rays +
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#sunGrad)" stroke="#F9A825" stroke-width="{SW}"/>'
                f'<circle cx="{cx-12}" cy="{cy-10}" r="8" fill="white" opacity="0.4"/>')

    def cloud(cx, cy, s=1.0):
        return (f'<ellipse cx="{cx}" cy="{cy}" rx="{int(55*s)}" ry="{int(28*s)}" fill="white" stroke="#B0BEC5" stroke-width="2"/>'
                f'<ellipse cx="{cx-int(30*s)}" cy="{cy+int(8*s)}" rx="{int(35*s)}" ry="{int(22*s)}" fill="white" stroke="#B0BEC5" stroke-width="2"/>'
                f'<ellipse cx="{cx+int(30*s)}" cy="{cy+int(8*s)}" rx="{int(38*s)}" ry="{int(20*s)}" fill="white" stroke="#B0BEC5" stroke-width="2"/>')

    def springfield_house(x, y, w=160, h=120, roof_color="#EF5350", wall="url(#houseWall)"):
        # Стена
        out = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{wall}" stroke="#333" stroke-width="{SW}"/>'
        # Крыша (треугольник)
        out += f'<polygon points="{x-10},{y} {x+w//2},{y-60} {x+w+10},{y}" fill="{roof_color}" stroke="#333" stroke-width="{SW}"/>'
        # Окно
        out += f'<rect x="{x+20}" y="{y+20}" width="{w//4}" height="{w//4}" fill="#B3E5FC" stroke="#333" stroke-width="3"/>'
        out += f'<line x1="{x+20+w//8}" y1="{y+20}" x2="{x+20+w//8}" y2="{y+20+w//4}" stroke="#333" stroke-width="2"/>'
        out += f'<line x1="{x+20}" y1="{y+20+w//8}" x2="{x+20+w//4}" y2="{y+20+w//8}" stroke="#333" stroke-width="2"/>'
        # Дверь
        dx = x + w//2 - 18
        out += f'<rect x="{dx}" y="{y+h-50}" width="36" height="50" rx="4" fill="#8D6E63" stroke="#333" stroke-width="3"/>'
        out += f'<circle cx="{dx+28}" cy="{y+h-25}" r="4" fill="#FFD700" stroke="#333" stroke-width="2"/>'
        return out

    def homer(cx, cy, s=1.0, shocked=False, happy=False, arms="down"):
        """Гомер: лысый, круглый, жёлтый."""
        out = ""
        # Тень
        out += f'<ellipse cx="{cx}" cy="{cy+int(220*s)}" rx="{int(55*s)}" ry="{int(10*s)}" fill="#0003"/>'
        # Тело (белая рубашка)
        bw, bt = int(50*s), cy+int(38*s)
        bb = cy + int(160*s)
        out += f'<ellipse cx="{cx}" cy="{(bt+bb)//2}" rx="{bw}" ry="{int((bb-bt)//2)}" fill="white" stroke="#333" stroke-width="{SW}"/>'
        # Синие брюки
        lh = int(80*s); lb = bb - int(10*s)
        out += f'<rect x="{cx-bw+int(5*s)}" y="{lb}" width="{int(bw*0.9)}" height="{lh}" rx="{int(5*s)}" fill="#1565C0" stroke="#333" stroke-width="{SW}"/>'
        out += f'<rect x="{cx+int(5*s)}" y="{lb}" width="{int(bw*0.9)}" height="{lh}" rx="{int(5*s)}" fill="#1565C0" stroke="#333" stroke-width="{SW}"/>'
        # Коричневые ботинки
        out += f'<ellipse cx="{cx-int(20*s)}" cy="{lb+lh}" rx="{int(24*s)}" ry="{int(10*s)}" fill="#4E342E" stroke="#333" stroke-width="3"/>'
        out += f'<ellipse cx="{cx+int(20*s)}" cy="{lb+lh}" rx="{int(24*s)}" ry="{int(10*s)}" fill="#4E342E" stroke="#333" stroke-width="3"/>'
        # Руки
        arm_y = bt + int(30*s)
        if arms == "down":
            out += (f'<line x1="{cx-bw}" y1="{arm_y}" x2="{cx-bw-int(45*s)}" y2="{arm_y+int(70*s)}" stroke="#FFD90F" stroke-width="{int(18*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{arm_y}" x2="{cx+bw+int(45*s)}" y2="{arm_y+int(70*s)}" stroke="#FFD90F" stroke-width="{int(18*s)}" stroke-linecap="round"/>')
        elif arms == "up":
            out += (f'<line x1="{cx-bw}" y1="{arm_y}" x2="{cx-bw-int(40*s)}" y2="{arm_y-int(55*s)}" stroke="#FFD90F" stroke-width="{int(18*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{arm_y}" x2="{cx+bw+int(40*s)}" y2="{arm_y-int(55*s)}" stroke="#FFD90F" stroke-width="{int(18*s)}" stroke-linecap="round"/>')
        elif arms == "hold":
            out += (f'<line x1="{cx-bw}" y1="{arm_y}" x2="{cx-bw-int(20*s)}" y2="{arm_y+int(30*s)}" stroke="#FFD90F" stroke-width="{int(18*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{arm_y}" x2="{cx+bw+int(55*s)}" y2="{arm_y+int(10*s)}" stroke="#FFD90F" stroke-width="{int(18*s)}" stroke-linecap="round"/>')
        # Шея
        out += f'<rect x="{cx-int(14*s)}" y="{cy+int(30*s)}" width="{int(28*s)}" height="{int(20*s)}" fill="#FFD90F" stroke="#333" stroke-width="3"/>'
        # Голова (большая жёлтая)
        hr = int(42*s)
        out += f'<circle cx="{cx}" cy="{cy}" r="{hr}" fill="#FFD90F" stroke="#333" stroke-width="{SW}"/>'
        # Уши
        out += (f'<circle cx="{cx-hr}" cy="{cy+int(5*s)}" r="{int(14*s)}" fill="#FFD90F" stroke="#333" stroke-width="3"/>'
                f'<circle cx="{cx+hr}" cy="{cy+int(5*s)}" r="{int(14*s)}" fill="#FFD90F" stroke="#333" stroke-width="3"/>')
        # Глаза (большие белые)
        ew = int(13*s)
        out += (f'<circle cx="{cx-int(14*s)}" cy="{cy-int(8*s)}" r="{ew}" fill="white" stroke="#333" stroke-width="3"/>'
                f'<circle cx="{cx+int(14*s)}" cy="{cy-int(8*s)}" r="{ew}" fill="white" stroke="#333" stroke-width="3"/>')
        # Зрачки
        px_off = int(4*s)
        out += (f'<circle cx="{cx-int(14*s)+px_off}" cy="{cy-int(8*s)}" r="{int(6*s)}" fill="#1A1A1A"/>'
                f'<circle cx="{cx+int(14*s)+px_off}" cy="{cy-int(8*s)}" r="{int(6*s)}" fill="#1A1A1A"/>')
        # Блики на глазах
        out += (f'<circle cx="{cx-int(12*s)}" cy="{cy-int(12*s)}" r="3" fill="white"/>'
                f'<circle cx="{cx+int(16*s)}" cy="{cy-int(12*s)}" r="3" fill="white"/>')
        # Нос (шарик)
        out += f'<circle cx="{cx+int(12*s)}" cy="{cy+int(4*s)}" r="{int(9*s)}" fill="#FFB300" stroke="#333" stroke-width="2"/>'
        # Рот
        if shocked:
            out += f'<path d="M{cx-int(16*s)} {cy+int(18*s)} Q{cx} {cy+int(35*s)} {cx+int(16*s)} {cy+int(18*s)}" stroke="#333" stroke-width="3" fill="#CC2200"/>'
            # Молнии шока
            import math
            for a_deg in [40, 80, 130, 155]:
                a = math.radians(a_deg)
                out += (f'<line x1="{cx+int(hr*math.cos(a)):.0f}" y1="{cy+int(hr*math.sin(a)):.0f}" '
                        f'x2="{cx+int((hr+28)*math.cos(a)):.0f}" y2="{cy+int((hr+28)*math.sin(a)):.0f}" '
                        f'stroke="#FFD600" stroke-width="4"/>')
        elif happy:
            out += f'<path d="M{cx-int(16*s)} {cy+int(14*s)} Q{cx} {cy+int(30*s)} {cx+int(16*s)} {cy+int(14*s)}" stroke="#333" stroke-width="3" fill="#CC2200"/>'
        else:
            out += f'<line x1="{cx-int(14*s)}" y1="{cy+int(18*s)}" x2="{cx+int(14*s)}" y2="{cy+int(18*s)}" stroke="#333" stroke-width="3"/>'
        # 5 o'clock shadow (характерная щетина Гомера — полукруг)
        out += f'<path d="M{cx-int(28*s)} {cy+int(16*s)} Q{cx} {cy+int(42*s)} {cx+int(28*s)} {cy+int(16*s)}" stroke="#AAA" stroke-width="2" fill="none" opacity="0.5"/>'
        return out

    def marge(cx, cy, s=1.0, happy=False):
        """Мардж: синие волосы-башня, зелёное платье."""
        out = ""
        # Синие волосы (башня)
        hair_cx = cx
        out += f'<rect x="{hair_cx-int(22*s)}" y="{cy-int(130*s)}" width="{int(44*s)}" height="{int(130*s)}" rx="{int(20*s)}" fill="#1565C0" stroke="#333" stroke-width="{SW}"/>'
        out += f'<ellipse cx="{hair_cx}" cy="{cy-int(128*s)}" rx="{int(22*s)}" ry="{int(25*s)}" fill="#1565C0" stroke="#333" stroke-width="{SW}"/>'
        # Тело — зелёное платье
        bw = int(38*s); bt = cy+int(35*s); bb = cy+int(180*s)
        out += f'<ellipse cx="{cx}" cy="{(bt+bb)//2}" rx="{bw}" ry="{(bb-bt)//2}" fill="#66BB6A" stroke="#333" stroke-width="{SW}"/>'
        # Руки
        arm_y = bt + int(25*s)
        out += (f'<line x1="{cx-bw}" y1="{arm_y}" x2="{cx-bw-int(40*s)}" y2="{arm_y+int(60*s)}" stroke="#FFD90F" stroke-width="{int(15*s)}" stroke-linecap="round"/>'
                f'<line x1="{cx+bw}" y1="{arm_y}" x2="{cx+bw+int(40*s)}" y2="{arm_y+int(60*s)}" stroke="#FFD90F" stroke-width="{int(15*s)}" stroke-linecap="round"/>')
        # Голова
        hr = int(34*s)
        out += f'<circle cx="{cx}" cy="{cy}" r="{hr}" fill="#FFD90F" stroke="#333" stroke-width="{SW}"/>'
        # Уши
        out += (f'<circle cx="{cx-hr}" cy="{cy+int(4*s)}" r="{int(12*s)}" fill="#FFD90F" stroke="#333" stroke-width="3"/>'
                f'<circle cx="{cx+hr}" cy="{cy+int(4*s)}" r="{int(12*s)}" fill="#FFD90F" stroke="#333" stroke-width="3"/>')
        # Глаза
        ew = int(11*s)
        out += (f'<circle cx="{cx-int(12*s)}" cy="{cy-int(6*s)}" r="{ew}" fill="white" stroke="#333" stroke-width="3"/>'
                f'<circle cx="{cx+int(12*s)}" cy="{cy-int(6*s)}" r="{ew}" fill="white" stroke="#333" stroke-width="3"/>'
                f'<circle cx="{cx-int(9*s)}" cy="{cy-int(6*s)}" r="{int(5*s)}" fill="#1A1A1A"/>'
                f'<circle cx="{cx+int(15*s)}" cy="{cy-int(6*s)}" r="{int(5*s)}" fill="#1A1A1A"/>')
        # Нос маленький
        out += f'<circle cx="{cx+int(8*s)}" cy="{cy+int(4*s)}" r="{int(6*s)}" fill="#FFB300" stroke="#333" stroke-width="2"/>'
        # Рот
        if happy:
            out += f'<path d="M{cx-int(12*s)} {cy+int(14*s)} Q{cx} {cy+int(26*s)} {cx+int(12*s)} {cy+int(14*s)}" stroke="#333" stroke-width="3" fill="#CC2200"/>'
        else:
            out += f'<line x1="{cx-int(10*s)}" y1="{cy+int(16*s)}" x2="{cx+int(10*s)}" y2="{cy+int(16*s)}" stroke="#333" stroke-width="2"/>'
        # Ожерелье
        out += f'<circle cx="{cx}" cy="{cy+int(34*s)}" r="{int(5*s)}" fill="#E91E63" stroke="#333" stroke-width="2"/>'
        return out

    def eink_tv(x, y, w=160, h=120):
        """E-ink дисплей как TV-замена."""
        out = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#C8D4DC" stroke="#333" stroke-width="{SW}"/>'
        out += f'<rect x="{x+8}" y="{y+8}" width="{w-16}" height="{h-28}" rx="4" fill="#EEF4F8" stroke="#555" stroke-width="2"/>'
        # Контент на экране — строки
        for i, (lw2, lc) in enumerate([(w-40, "#222"), (w-55, "#444"), (w-65, "#666")]):
            ly = y + 18 + i * 18
            out += f'<rect x="{x+16}" y="{ly}" width="{lw2}" height="8" rx="3" fill="{lc}"/>'
        # Блик
        out += f'<rect x="{x+12}" y="{y+12}" width="{(w-24)//3}" height="{(h-36)//4}" rx="2" fill="white" opacity="0.5"/>'
        # Солнечная панель снизу
        out += f'<rect x="{x+4}" y="{y+h-18}" width="{w-8}" height="12" fill="#1A3A8A" rx="2" stroke="#333" stroke-width="2"/>'
        for j in range(6):
            xj = x + 4 + j * ((w-8)//6)
            out += f'<line x1="{xj}" y1="{y+h-18}" x2="{xj}" y2="{y+h-6}" stroke="#3A5ACC" stroke-width="1"/>'
        # Ножка
        out += f'<rect x="{x+w//2-8}" y="{y+h}" width="16" height="18" fill="#888" stroke="#333" stroke-width="2"/>'
        out += f'<rect x="{x+w//2-22}" y="{y+h+18}" width="44" height="8" rx="2" fill="#777" stroke="#333" stroke-width="2"/>'
        # Зелёный логотип
        out += f'<text x="{x+w//2}" y="{y+h+38}" font-family="Arial Black,sans-serif" font-size="11" fill="#00AA44" text-anchor="middle" font-weight="bold">EcoDisplays</text>'
        return out

    def bill(cx, cy, amount="€500!", color="#CC0000"):
        """Счёт за электричество."""
        out = f'<rect x="{cx-50}" y="{cy-70}" width="100" height="130" rx="4" fill="white" stroke="#333" stroke-width="3"/>'
        for i in range(4):
            out += f'<rect x="{cx-38}" y="{cy-55+i*20}" width="{55+i*3}" height="7" rx="2" fill="#CCC"/>'
        out += f'<rect x="{cx-38}" y="{cy+25}" width="76" height="16" rx="2" fill="{color}"/>'
        out += f'<text x="{cx}" y="{cy+37}" font-family="Arial Black,sans-serif" font-size="13" fill="white" text-anchor="middle">{amount}</text>'
        # Молнии
        out += f'<text x="{cx+55}" y="{cy-60}" font-family="sans-serif" font-size="28">⚡</text>'
        return out

    def action_burst(cx, cy, r=60, color="#FFD600", text="D\'oh!"):
        """Взрыв-надпись."""
        import math
        pts = []
        for i in range(16):
            rad = r if i % 2 == 0 else r * 0.65
            a = math.radians(i * 22.5)
            pts.append(f"{cx+rad*math.cos(a):.0f},{cy+rad*math.sin(a):.0f}")
        out = f'<polygon points="{" ".join(pts)}" fill="{color}" stroke="#333" stroke-width="3"/>'
        out += f'<text x="{cx}" y="{cy+8}" font-family="Arial Black,sans-serif" font-size="20" fill="#CC0000" text-anchor="middle" font-weight="bold">{text}</text>'
        return out

    # ── ПАНЕЛИ ──────────────────────────────────────────────────────────
    parts = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">', defs]

    floor_y = 360

    if panel_idx == 0:
        # Гомер получает счёт — шок
        parts.append(sky())
        parts.append(cloud(130, 70, 0.9))
        parts.append(cloud(360, 55, 0.75))
        parts.append(sun(450, 75, 45))
        parts.append(ground(floor_y))
        parts.append(springfield_house(290, floor_y - 180, w=200, h=130))
        # Большой LED-биллборд за домом
        parts.append(f'<rect x="80" y="140" width="150" height="90" fill="#FF5722" stroke="#333" stroke-width="{SW}"/>')
        parts.append(f'<rect x="88" y="148" width="134" height="74" fill="#FFCC02"/>')
        for r2 in range(4):
            for c2 in range(6):
                parts.append(f'<circle cx="{100+c2*22}" cy="{158+r2*18}" r="6" fill="#FF6F00" opacity="0.9"/>')
        parts.append(f'<rect x="148" y="230" width="10" height="80" fill="#555" stroke="#333" stroke-width="2"/>')
        # Гомер со счётом — шокирован
        parts.append(homer(165, floor_y - 135, s=1.05, shocked=True, arms="hold"))
        parts.append(bill(195, floor_y - 210, "€500!", "#CC0000"))
        # Выбросы дыма от LED
        parts.append(f'<circle cx="175" cy="130" r="18" fill="#888" opacity="0.4"/>')
        parts.append(f'<circle cx="195" cy="110" r="14" fill="#999" opacity="0.3"/>')

    elif panel_idx == 1:
        # Мардж объясняет про EcoDisplays
        parts.append(sky())
        parts.append(cloud(200, 65, 0.8))
        parts.append(sun(60, 70, 42))
        parts.append(ground(floor_y, "url(#floorGrad)"))
        # Интерьер — обои
        parts.append(f'<rect width="{W}" height="{floor_y}" fill="#FFF9C4" opacity="0.6"/>')
        parts.append(f'<rect x="0" y="{floor_y-8}" width="{W}" height="8" fill="#A1887F"/>')
        # Диван
        parts.append(f'<rect x="80" y="{floor_y-90}" width="300" height="80" rx="10" fill="#EF9A9A" stroke="#333" stroke-width="{SW}"/>')
        parts.append(f'<rect x="80" y="{floor_y-90}" width="300" height="30" rx="10" fill="#E57373" stroke="#333" stroke-width="{SW}"/>')
        # E-ink TV на стене
        parts.append(eink_tv(340, floor_y - 280, 170, 130))
        # Мардж указывает на TV
        parts.append(marge(200, floor_y - 155, s=1.0, happy=True))
        # Рука указывает
        parts.append(f'<line x1="238" y1="{floor_y-175}" x2="335" y2="{floor_y-215}" stroke="#FFD90F" stroke-width="14" stroke-linecap="round"/>')
        # Гомер сидит на диване
        parts.append(homer(390, floor_y - 170, s=0.85, arms="down"))
        # Мысль Гомера
        parts.append(f'<ellipse cx="440" cy="{floor_y-265}" rx="60" ry="30" fill="white" stroke="#333" stroke-width="3"/>')
        parts.append(f'<circle cx="415" cy="{floor_y-242}" r="6" fill="white" stroke="#333" stroke-width="2"/>')
        parts.append(f'<circle cx="406" cy="{floor_y-232}" r="4" fill="white" stroke="#333" stroke-width="2"/>')
        parts.append(f'<text x="440" y="{floor_y-270}" font-family="Arial Black,sans-serif" font-size="13" fill="#333" text-anchor="middle">3W?!</text>')
        parts.append(f'<text x="440" y="{floor_y-253}" font-family="Arial Black,sans-serif" font-size="11" fill="#666" text-anchor="middle">Mmm...</text>')

    elif panel_idx == 2:
        # Монтаж EcoDisplays на улице — Гомер с инструментами
        parts.append(sky())
        parts.append(cloud(100, 60, 0.85))
        parts.append(cloud(380, 75, 0.7))
        parts.append(sun(470, 65, 40))
        parts.append(ground(floor_y))
        parts.append(springfield_house(30, floor_y - 160, w=180, h=110, roof_color="#1976D2", wall="url(#houseWall)"))
        # Столб EcoDisplays на доме
        parts.append(f'<rect x="228" y="{floor_y-280}" width="10" height="200" fill="#555" stroke="#333" stroke-width="2"/>')
        parts.append(eink_tv(160, floor_y - 310, 150, 110))
        # Лучи от солнца к дисплею
        import math
        for i in range(5):
            a = math.radians(210 + i * 10)
            parts.append(f'<line x1="470" y1="65" x2="{235+40*math.cos(a):.0f}" y2="{floor_y-260+40*math.sin(a):.0f}" stroke="#FFD600" stroke-width="2" stroke-dasharray="8,6" opacity="0.6"/>')
        # Гомер с инструментами — довольный
        parts.append(homer(370, floor_y - 135, s=1.0, happy=True, arms="up"))
        # Инструменты в руках
        parts.append(f'<rect x="405" y="{floor_y-235}" width="35" height="8" rx="3" fill="#FF8F00" stroke="#333" stroke-width="2"/>')
        parts.append(f'<rect x="415" y="{floor_y-240}" width="10" height="18" rx="2" fill="#555" stroke="#333" stroke-width="2"/>')
        # Мардж смотрит с одобрением
        parts.append(marge(480, floor_y - 150, s=0.85, happy=True))
        # Значок солнечной энергии
        parts.append(action_burst(235, floor_y - 340, r=38, color="#FFF176", text="☀️"))

    elif panel_idx == 3:
        # Результат — вся семья довольна, счёт €12
        parts.append(sky(evening=True))
        parts.append(ground(floor_y, "url(#grassGrad)"))
        parts.append(springfield_house(30, floor_y - 170, w=180, h=120))
        # EcoDisplays на доме
        parts.append(f'<rect x="228" y="{floor_y-250}" width="8" height="170" fill="#555" stroke="#333" stroke-width="2"/>')
        parts.append(eink_tv(162, floor_y - 285, 140, 100))
        # Зелёный ореол вокруг дисплея
        parts.append(f'<ellipse cx="232" cy="{floor_y-235}" rx="90" ry="65" fill="#00AA44" opacity="0.12"/>')
        # Семья рядом — Гомер + Мардж
        parts.append(homer(360, floor_y - 140, s=1.0, happy=True, arms="up"))
        parts.append(marge(460, floor_y - 150, s=0.95, happy=True))
        # Маленький счёт €12
        parts.append(bill(390, floor_y - 270, "€12 ✓", "#00AA44"))
        # Восклицание Гомера
        parts.append(action_burst(305, floor_y - 295, r=50, color="#FFD600", text="Woo-hoo!"))
        # Звёзды на вечернем небе
        for sx2, sy2 in [(80,50),(140,30),(220,70),(300,40),(420,60),(500,35)]:
            parts.append(f'<circle cx="{sx2}" cy="{sy2}" r="3" fill="white" opacity="0.8"/>')

    parts.append('</svg>')
    return _render_svg("".join(parts))


def _svg_noir_detective(panel_idx: int) -> bytes | None:
    """Нуар-детектив: атмосферный SVG с дождём, прожекторами, тёмным городом."""
    W, H = 540, 540

    defs = """<defs>
  <radialGradient id="spotlight" cx="50%" cy="0%" r="80%">
    <stop offset="0%" stop-color="#FFFACC" stop-opacity="0.6"/>
    <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="greenspot" cx="50%" cy="50%" r="60%">
    <stop offset="0%" stop-color="#00FF88" stop-opacity="0.5"/>
    <stop offset="100%" stop-color="#003322" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="orangespot" cx="50%" cy="50%" r="60%">
    <stop offset="0%" stop-color="#FF6600" stop-opacity="0.7"/>
    <stop offset="100%" stop-color="#1A0800" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="sunriseGrad" cx="50%" cy="100%" r="80%">
    <stop offset="0%" stop-color="#FF8C00"/>
    <stop offset="40%" stop-color="#FFD700"/>
    <stop offset="100%" stop-color="#87CEEB"/>
  </radialGradient>
  <radialGradient id="skinGrad" cx="35%" cy="30%" r="65%">
    <stop offset="0%" stop-color="#FFE0B2"/>
    <stop offset="70%" stop-color="#FFCC80"/>
    <stop offset="100%" stop-color="#E6A060"/>
  </radialGradient>
  <linearGradient id="coatGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#3D3D3D"/>
    <stop offset="100%" stop-color="#1A1A1A"/>
  </linearGradient>
  <linearGradient id="einkFrame" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#C8D4DC"/>
    <stop offset="100%" stop-color="#8899AA"/>
  </linearGradient>
  <linearGradient id="einkScreen" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#F5F8FA"/>
    <stop offset="100%" stop-color="#DCE8F0"/>
  </linearGradient>
  <filter id="blur3">
    <feGaussianBlur stdDeviation="3"/>
  </filter>
  <filter id="blur6">
    <feGaussianBlur stdDeviation="6"/>
  </filter>
  <filter id="glow">
    <feGaussianBlur stdDeviation="4" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="shadow2">
    <feDropShadow dx="3" dy="4" stdDeviation="4" flood-color="#000" flood-opacity="0.5"/>
  </filter>
</defs>"""

    def buildings(sky_color="#0D0D1A", building_colors=None):
        if building_colors is None:
            building_colors = ["#1A1A2E", "#161622", "#111118", "#1D1D30"]
        parts = [f'<rect width="{W}" height="{H}" fill="{sky_color}"/>']
        import random as _r; _r.seed(panel_idx * 17 + 3)
        bw_list = [55, 70, 45, 80, 60, 50, 65, 75]
        bh_list = [220, 280, 190, 310, 250, 200, 270, 240]
        bx = 0
        for i, (bw, bh) in enumerate(zip(bw_list, bh_list)):
            bc = building_colors[i % len(building_colors)]
            parts.append(f'<rect x="{bx}" y="{H-bh}" width="{bw}" height="{bh}" fill="{bc}"/>')
            # Окна
            for wy in range(H - bh + 15, H - 40, 30):
                for wx in range(bx + 8, bx + bw - 8, 18):
                    lit = _r.random() > 0.45
                    wc = "#FFFAAA" if lit else "#333344"
                    parts.append(f'<rect x="{wx}" y="{wy}" width="8" height="12" fill="{wc}" opacity="0.85"/>')
            bx += bw + _r.randint(2, 8)
            if bx > W:
                break
        return "".join(parts)

    def rain(n=120, color="#6699AA", opacity=0.25):
        import random as _r; _r.seed(panel_idx * 31)
        parts = []
        for _ in range(n):
            x = _r.randint(0, W)
            y = _r.randint(0, H)
            l = _r.randint(12, 22)
            parts.append(f'<line x1="{x}" y1="{y}" x2="{x+3}" y2="{y+l}" stroke="{color}" '
                         f'stroke-width="1" opacity="{opacity}"/>')
        return "".join(parts)

    def puddle_reflect(x, y, w=90, color="#3344AA"):
        return (f'<ellipse cx="{x}" cy="{y}" rx="{w//2}" ry="10" fill="{color}" opacity="0.3"/>'
                f'<ellipse cx="{x}" cy="{y}" rx="{w//3}" ry="6" fill="#AABBCC" opacity="0.15"/>')

    def detective(cx, cy, scale=1.0, look_right=False, arms="down"):
        s = scale
        hr = int(32 * s)
        # Shadow
        out = f'<ellipse cx="{cx}" cy="{cy+int(215*s)}" rx="{int(55*s)}" ry="{int(12*s)}" fill="#000" opacity="0.4"/>'
        # Coat (trenchcoat) — body
        bw = int(42 * s); bt = cy + hr; bb = cy + int(155 * s)
        out += f'<rect x="{cx-bw}" y="{bt}" width="{bw*2}" height="{bb-bt+int(50*s)}" rx="{int(6*s)}" fill="url(#coatGrad)" filter="url(#shadow2)"/>'
        # Coat lapels
        out += (f'<polygon points="{cx},{bt+int(20*s)} {cx-bw},{bt} {cx-bw+int(12*s)},{bt+int(45*s)}" fill="#2A2A2A"/>'
                f'<polygon points="{cx},{bt+int(20*s)} {cx+bw},{bt} {cx+bw-int(12*s)},{bt+int(45*s)}" fill="#222222"/>')
        # Belt
        out += f'<rect x="{cx-bw}" y="{cy+int(110*s)}" width="{bw*2}" height="{int(10*s)}" fill="#111" rx="2"/>'
        # Arms
        if arms == "down":
            out += (f'<line x1="{cx-bw}" y1="{bt+int(20*s)}" x2="{cx-bw-int(40*s)}" y2="{bt+int(80*s)}" '
                    f'stroke="#2A2A2A" stroke-width="{int(22*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{bt+int(20*s)}" x2="{cx+bw+int(40*s)}" y2="{bt+int(80*s)}" '
                    f'stroke="#2A2A2A" stroke-width="{int(22*s)}" stroke-linecap="round"/>')
        elif arms == "point":
            # Right arm pointing
            out += (f'<line x1="{cx-bw}" y1="{bt+int(20*s)}" x2="{cx-bw-int(35*s)}" y2="{bt+int(75*s)}" '
                    f'stroke="#2A2A2A" stroke-width="{int(22*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{bt+int(20*s)}" x2="{cx+bw+int(65*s)}" y2="{bt+int(20*s)}" '
                    f'stroke="#2A2A2A" stroke-width="{int(22*s)}" stroke-linecap="round"/>')
        elif arms == "raise":
            out += (f'<line x1="{cx-bw}" y1="{bt+int(20*s)}" x2="{cx-bw-int(30*s)}" y2="{bt-int(30*s)}" '
                    f'stroke="#2A2A2A" stroke-width="{int(22*s)}" stroke-linecap="round"/>'
                    f'<line x1="{cx+bw}" y1="{bt+int(20*s)}" x2="{cx+bw+int(30*s)}" y2="{bt-int(30*s)}" '
                    f'stroke="#2A2A2A" stroke-width="{int(22*s)}" stroke-linecap="round"/>')
        # Legs / pants
        lw = int(20 * s); lb = bb + int(50 * s); lh = int(80 * s)
        out += (f'<rect x="{cx-lw*2}" y="{lb}" width="{lw+int(8*s)}" height="{lh}" rx="{int(5*s)}" fill="#111"/>'
                f'<rect x="{cx+int(4*s)}" y="{lb}" width="{lw+int(8*s)}" height="{lh}" rx="{int(5*s)}" fill="#111"/>')
        # Shoes
        sy = lb + lh
        out += (f'<ellipse cx="{cx-lw}" cy="{sy}" rx="{int(20*s)}" ry="{int(8*s)}" fill="#0A0A0A"/>'
                f'<ellipse cx="{cx+lw+int(8*s)}" cy="{sy}" rx="{int(20*s)}" ry="{int(8*s)}" fill="#0A0A0A"/>')
        # Neck
        out += f'<rect x="{cx-int(10*s)}" y="{cy+hr-int(5*s)}" width="{int(20*s)}" height="{int(20*s)}" fill="url(#skinGrad)"/>'
        # Head
        out += f'<ellipse cx="{cx}" cy="{cy}" rx="{hr}" ry="{int(34*s)}" fill="url(#skinGrad)" filter="url(#shadow2)"/>'
        # Fedora hat
        hbrim = int(55 * s); htop = int(28 * s)
        hat_y = cy - int(32 * s)
        out += (f'<ellipse cx="{cx}" cy="{hat_y}" rx="{hbrim}" ry="{int(9*s)}" fill="#1A1008"/>'
                f'<rect x="{cx-int(30*s)}" y="{hat_y-htop}" width="{int(60*s)}" height="{htop}" rx="{int(6*s)}" fill="#221208"/>'
                f'<rect x="{cx-int(28*s)}" y="{hat_y-int(12*s)}" width="{int(56*s)}" height="{int(5*s)}" fill="#3A2010"/>')
        # Eyes
        dir_x = int(10 * s) if look_right else int(-8 * s)
        out += (f'<circle cx="{cx-int(11*s)}" cy="{cy-int(6*s)}" r="{int(5*s)}" fill="#1A1010"/>'
                f'<circle cx="{cx+int(11*s)}" cy="{cy-int(6*s)}" r="{int(5*s)}" fill="#1A1010"/>'
                f'<circle cx="{cx-int(11*s)+dir_x//2}" cy="{cy-int(8*s)}" r="2" fill="white"/>'
                f'<circle cx="{cx+int(11*s)+dir_x//2}" cy="{cy-int(8*s)}" r="2" fill="white"/>')
        # Mouth — slight smirk
        out += f'<path d="M{cx-int(8*s)} {cy+int(10*s)} Q{cx+int(5*s)} {cy+int(16*s)} {cx+int(12*s)} {cy+int(9*s)}" stroke="#5A2A1A" stroke-width="2" fill="none"/>'
        return out

    def eink_display(x, y, w, h, glowing=True):
        parts = [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="url(#einkFrame)" filter="url(#shadow2)"/>',
            f'<rect x="{x+6}" y="{y+6}" width="{w-12}" height="{h-22}" rx="3" fill="url(#einkScreen)" stroke="#8899AA" stroke-width="1"/>',
        ]
        # Glare
        parts.append(f'<rect x="{x+10}" y="{y+10}" width="{(w-20)//3}" height="{(h-28)//4}" rx="2" fill="white" opacity="0.45"/>')
        # Content lines
        lx = x + 12; lw2 = w - 24
        for i, (lw3, lc) in enumerate([(int(lw2*0.85), "#222"), (int(lw2*0.65), "#444"), (int(lw2*0.5), "#666")]):
            ly = y + 20 + i * 18
            parts.append(f'<rect x="{lx}" y="{ly}" width="{lw3}" height="7" rx="3" fill="{lc}"/>')
        # Solar strip
        sy = y + h - 16
        parts.append(f'<rect x="{x+4}" y="{sy}" width="{w-8}" height="10" fill="#1A3A8A" rx="2"/>')
        for j in range(5):
            xj = x + 4 + j * ((w-8)//5)
            parts.append(f'<line x1="{xj}" y1="{sy}" x2="{xj}" y2="{sy+10}" stroke="#3A5ACC" stroke-width="1"/>')
        # Glow aura
        if glowing:
            parts.append(f'<rect x="{x-8}" y="{y-8}" width="{w+16}" height="{h+16}" rx="10" fill="#00FF88" opacity="0.15" filter="url(#blur6)"/>')
        return "".join(parts)

    def led_billboard(x, y, w, h):
        parts = [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="#FF4400" filter="url(#glow)" opacity="0.9"/>',
            f'<rect x="{x+5}" y="{y+5}" width="{w-10}" height="{h-10}" fill="#FF8800"/>',
        ]
        # Grid of LED dots
        for ry2 in range(y+10, y+h-10, 12):
            for rx2 in range(x+10, x+w-10, 12):
                parts.append(f'<circle cx="{rx2}" cy="{ry2}" r="3" fill="#FFCC00" opacity="0.9"/>')
        # Glow
        parts.append(f'<rect x="{x-15}" y="{y-15}" width="{w+30}" height="{h+30}" rx="10" fill="#FF4400" opacity="0.35" filter="url(#blur6)"/>')
        return "".join(parts)

    def city_person(cx, cy, shirt="#334455", happy=False, shocked=False, scale=0.7):
        s = scale; hr = int(22*s)
        out = f'<ellipse cx="{cx}" cy="{cy+int(200*s)}" rx="{int(30*s)}" ry="{int(8*s)}" fill="#000" opacity="0.3"/>'
        out += f'<circle cx="{cx}" cy="{cy}" r="{hr}" fill="url(#skinGrad)"/>'
        bw=int(24*s); bt=cy+hr; bb=cy+int(90*s)
        out += f'<rect x="{cx-bw}" y="{bt}" width="{bw*2}" height="{bb-bt}" rx="4" fill="{shirt}"/>'
        out += (f'<line x1="{cx-bw}" y1="{bt+int(10*s)}" x2="{cx-bw-int(28*s)}" y2="{bt+int(45*s)}" '
                f'stroke="{shirt}" stroke-width="{int(12*s)}" stroke-linecap="round"/>'
                f'<line x1="{cx+bw}" y1="{bt+int(10*s)}" x2="{cx+bw+int(28*s)}" y2="{bt+int(45*s)}" '
                f'stroke="{shirt}" stroke-width="{int(12*s)}" stroke-linecap="round"/>')
        out += (f'<rect x="{cx-bw+int(3*s)}" y="{bb}" width="{int(18*s)}" height="{int(45*s)}" rx="3" fill="#222"/>'
                f'<rect x="{cx+int(3*s)}" y="{bb}" width="{int(18*s)}" height="{int(45*s)}" rx="3" fill="#222"/>')
        if shocked:
            out += f'<ellipse cx="{cx}" cy="{cy+int(8*s)}" rx="{int(7*s)}" ry="{int(8*s)}" fill="#1A0A0A"/>'
        elif happy:
            out += f'<path d="M{cx-int(9*s)} {cy+int(5*s)} Q{cx} {cy+int(15*s)} {cx+int(9*s)} {cy+int(5*s)}" stroke="#5A2A1A" stroke-width="2" fill="none"/>'
        else:
            out += f'<line x1="{cx-int(7*s)}" y1="{cy+int(7*s)}" x2="{cx+int(7*s)}" y2="{cy+int(7*s)}" stroke="#5A2A1A" stroke-width="2"/>'
        return out

    # ── ПАНЕЛИ ──────────────────────────────────────────────────────────
    parts = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">', defs]

    floor_y = H - 130

    if panel_idx == 0:
        # Ночной дождливый город, детектив vs LED-баннер
        parts.append(buildings(sky_color="#08080F"))
        parts.append(rain(140, "#7799BB", 0.22))
        # Оранжевое свечение от LED
        parts.append(f'<ellipse cx="390" cy="200" rx="200" ry="160" fill="url(#orangespot)"/>')
        # LED billboard
        parts.append(led_billboard(300, 80, 200, 120))
        # Пол — мокрый асфальт
        parts.append(f'<rect x="0" y="{floor_y}" width="{W}" height="130" fill="#111118"/>')
        parts.append(f'<rect x="0" y="{floor_y}" width="{W}" height="4" fill="#2A2A3A"/>')
        parts.append(puddle_reflect(350, floor_y + 25, 130, "#FF4400"))
        parts.append(puddle_reflect(160, floor_y + 40, 90, "#3344AA"))
        # Детектив
        parts.append(detective(160, floor_y - 220, scale=1.0, look_right=True, arms="point"))
        # Измеритель в руке (символический)
        parts.append(f'<rect x="195" y="{floor_y-180}" width="45" height="28" rx="4" fill="#222" stroke="#FF6600" stroke-width="2"/>')
        parts.append(f'<text x="218" y="{floor_y-162}" font-family="Arial Black,sans-serif" font-size="12" fill="#FF4400" text-anchor="middle">300W</text>')
        # Spotlight сверху
        parts.append(f'<polygon points="250,0 80,{floor_y-100} 340,{floor_y-100}" fill="url(#spotlight)" opacity="0.5"/>')

    elif panel_idx == 1:
        # Тёмный переулок, детектив находит e-ink дисплей
        parts.append(buildings(sky_color="#060608", building_colors=["#0F0F14", "#0A0A10", "#111116", "#0D0D12"]))
        parts.append(rain(100, "#5577AA", 0.2))
        # Кирпичные стены переулка (SVG прямоугольники)
        for wy in range(0, H, 25):
            for wx2 in ([0, 30, 60] if wy % 50 == 0 else [15, 45]):
                parts.append(f'<rect x="{wx2*2}" y="{wy}" width="52" height="20" fill="#1A1010" stroke="#111" stroke-width="1" opacity="0.7"/>')
        parts.append(f'<rect x="380" y="0" width="160" height="{H}" fill="#111118" opacity="0.9"/>')
        # E-ink дисплей на стене — светится зеленью
        parts.append(f'<rect x="370" y="120" width="8" height="220" fill="#444" rx="3"/>')  # столб
        parts.append(eink_display(385, 100, 130, 100, glowing=True))
        parts.append(f'<ellipse cx="450" cy="200" rx="120" ry="100" fill="url(#greenspot)"/>')
        # Детектив с лупой
        parts.append(detective(210, floor_y - 220, scale=0.95, look_right=True, arms="point"))
        # Лупа
        parts.append(f'<circle cx="250" cy="{floor_y-180}" r="22" fill="none" stroke="#C8C8C8" stroke-width="4"/>')
        parts.append(f'<line x1="268" y1="{floor_y-163}" x2="290" y2="{floor_y-145}" stroke="#C8C8C8" stroke-width="4" stroke-linecap="round"/>')
        parts.append(f'<circle cx="250" cy="{floor_y-180}" r="18" fill="#CCDDEE" opacity="0.25"/>')
        # Пол
        parts.append(f'<rect x="0" y="{floor_y}" width="{W}" height="130" fill="#0D0D0F"/>')
        parts.append(puddle_reflect(240, floor_y + 30, 110, "#00AA44"))

    elif panel_idx == 2:
        # Городской совет — детектив раскрывает правду
        # Зал — тёмные стены
        parts.append(f'<rect width="{W}" height="{H}" fill="#0E0E16"/>')
        # Деревянные панели на стенах
        for wy in range(0, H, 40):
            parts.append(f'<rect x="0" y="{wy}" width="30" height="38" fill="#1A1008" stroke="#0A0806" stroke-width="1"/>')
            parts.append(f'<rect x="{W-30}" y="{wy}" width="30" height="38" fill="#1A1008" stroke="#0A0806" stroke-width="1"/>')
        # Два дисплея для сравнения
        # LCD (плохой — красный)
        parts.append(led_billboard(60, 100, 160, 120))
        parts.append(f'<line x1="60" y1="100" x2="220" y2="220" stroke="#FF2200" stroke-width="8" opacity="0.8"/>')
        parts.append(f'<line x1="220" y1="100" x2="60" y2="220" stroke="#FF2200" stroke-width="8" opacity="0.8"/>')
        # E-ink (хороший — зелёный)
        parts.append(eink_display(300, 100, 160, 120, glowing=True))
        parts.append(f'<text x="380" y="242" font-family="Arial Black,sans-serif" font-size="16" fill="#00FF88" text-anchor="middle">✓ 3W</text>')
        parts.append(f'<text x="140" y="242" font-family="Arial Black,sans-serif" font-size="13" fill="#FF4400" text-anchor="middle">✗ 300W</text>')
        # Стол совета
        parts.append(f'<rect x="40" y="{floor_y-30}" width="{W-80}" height="30" rx="4" fill="#1A1208" stroke="#3A2A18" stroke-width="2"/>')
        # Советники
        for ci, cx2 in enumerate([130, 230, 330, 420]):
            shirt = ["#222244", "#223322", "#332222", "#222233"][ci]
            parts.append(city_person(cx2, floor_y - 90, shirt=shirt, shocked=(ci % 2 == 0)))
        # Детектив указывает
        parts.append(detective(270, floor_y - 225, scale=0.9, look_right=False, arms="point"))
        # Прожектор на детектива
        parts.append(f'<polygon points="270,0 160,{floor_y-150} 380,{floor_y-150}" fill="url(#spotlight)" opacity="0.6"/>')

    elif panel_idx == 3:
        # Рассвет над городом — e-ink везде, детектив удовлетворён
        parts.append(f'<rect width="{W}" height="{H}" fill="url(#sunriseGrad)"/>')
        # Силуэты зданий
        buildings_data = [(0,200,60,340),(65,150,80,390),(150,180,55,360),(210,140,75,400),(290,160,65,370),(360,190,70,350),(435,150,60,390)]
        for bx2,by2,bw2,bh2 in buildings_data:
            parts.append(f'<rect x="{bx2}" y="{H-bh2//2}" width="{bw2}" height="{bh2//2}" fill="#1A1830" opacity="0.85"/>')
        # E-ink дисплеи везде (на столбах)
        for px2, py2, pw2, ph2 in [(50, H-320, 90, 70), (195, H-340, 90, 70), (370, H-310, 90, 70), (470, H-290, 70, 55)]:
            parts.append(f'<rect x="{px2+pw2//2-3}" y="{py2+ph2}" width="6" height="{H-py2-ph2-floor_y+100}" fill="#555" rx="2"/>')
            parts.append(eink_display(px2, py2, pw2, ph2, glowing=False))
        # Зелёные блики от дисплеев
        parts.append(f'<ellipse cx="95" cy="{H-280}" rx="70" ry="50" fill="#00CC66" opacity="0.12" filter="url(#blur6)"/>')
        parts.append(f'<ellipse cx="240" cy="{H-300}" rx="70" ry="50" fill="#00CC66" opacity="0.12" filter="url(#blur6)"/>')
        # Пол
        parts.append(f'<rect x="0" y="{floor_y}" width="{W}" height="130" fill="#1A1820"/>')
        # Прохожие
        for ci, cx2 in enumerate([80, 320, 440]):
            shirt = ["#335588", "#336644", "#553366"][ci]
            parts.append(city_person(cx2, floor_y - 80, shirt=shirt, happy=True, scale=0.65))
        # Детектив — доволен
        parts.append(detective(220, floor_y - 215, scale=1.0, look_right=True, arms="raise"))
        # Значок
        parts.append(f'<circle cx="290" cy="{floor_y-260}" r="28" fill="#00AA44" opacity="0.9" filter="url(#glow)"/>')
        parts.append(f'<text x="290" y="{floor_y-252}" font-family="Arial Black,sans-serif" font-size="22" fill="white" text-anchor="middle">✓</text>')

    parts.append('</svg>')
    svg_text = "".join(parts)
    return _render_svg(svg_text)


def _fetch_panel_image(prompt: str, panel_idx: int, scenario_id: int = 0,
                       style: str = "3d") -> bytes | None:
    """Генерирует панель. style: '3d' | 'popart' | 'iso'."""

    # Сценарий 10: Симпсоны
    if scenario_id == 10:
        r = _svg_simpsons(panel_idx)
        if r:
            return r
        return _draw_pil_fallback(panel_idx)

    # Сценарий 9: детектив нуар — фотореалистичный Pollinations Flux (приоритет)
    if scenario_id == 9:
        if panel_idx < len(_DETECTIVE_NOIR_PROMPTS):
            print(f"  Панель {panel_idx+1}: Pollinations Flux noir detective...")
            r = _fetch_pollinations_image(
                _DETECTIVE_NOIR_PROMPTS[panel_idx],
                width=540, height=540,
                seed=900 + panel_idx,
            )
            if r:
                print(f"  Панель {panel_idx+1}: OK {len(r)//1024}KB")
                return r
            print(f"  Панель {panel_idx+1}: Pollinations недоступен, SVG нуар-детектив...")
        r = _svg_noir_detective(panel_idx)
        if r:
            return r
        return _draw_pil_fallback(panel_idx)

    result = _generate_svg_panel(prompt, panel_idx)
    if result:
        return result

    if style == "popart" and scenario_id in (5, 6):
        print(f"  Панель {panel_idx+1}: поп-арт (сценарий {scenario_id})")
        r = _svg_popart(scenario_id, panel_idx)
        if r:
            return r

    if style == "iso" and scenario_id == 7:
        print(f"  Панель {panel_idx+1}: изометрия (сценарий {scenario_id})")
        r = _svg_isometric(scenario_id, panel_idx)
        if r:
            return r

    if scenario_id == 8:
        # Сценарий 8: реалистичный супергерой — всегда Pollinations Flux
        if panel_idx < len(_SUPERHERO_AI_PROMPTS):
            print(f"  Панель {panel_idx+1}: Pollinations Flux superhero...")
            r = _fetch_pollinations_image(
                _SUPERHERO_AI_PROMPTS[panel_idx],
                width=540, height=540,
                seed=800 + panel_idx,
            )
            if r:
                print(f"  Панель {panel_idx+1}: OK {len(r)//1024}KB")
                return r
            print(f"  Панель {panel_idx+1}: Pollinations недоступен, SVG fallback")
        r = _svg_hero(scenario_id, panel_idx)
        if r:
            return r
        return _draw_pil_fallback(panel_idx)

    if style == "real3d":
        # Реалистичные AI-изображения через Pollinations (Flux)
        prompts = _HERO3D_PROMPTS if scenario_id == 4 else None
        if prompts and panel_idx < len(prompts):
            print(f"  Панель {panel_idx+1}: Pollinations Flux (real3d)...")
            r = _fetch_pollinations_image(prompts[panel_idx], seed=scenario_id * 10 + panel_idx)
            if r:
                print(f"  Панель {panel_idx+1}: OK {len(r)//1024}KB")
                return r
            print(f"  Панель {panel_idx+1}: Pollinations недоступен, fallback SVG")
        r = _svg_hero3d(scenario_id, panel_idx)
        if r:
            return r

    if style == "hero3d":
        print(f"  Панель {panel_idx+1}: 3D-супергерой (сценарий {scenario_id})")
        r = _svg_hero3d(scenario_id, panel_idx)
        if r:
            return r

    if style == "hero":
        print(f"  Панель {panel_idx+1}: супергерой (сценарий {scenario_id})")
        r = _svg_hero(scenario_id, panel_idx)
        if r:
            return r

    if scenario_id == 4:
        print(f"  Панель {panel_idx+1}: 3D SVG (сценарий {scenario_id})")
        r = _svg_scenario4(panel_idx)
        if r:
            return r

    if scenario_id in (1, 2, 3, 4):
        return _draw_scenario_panel(scenario_id, panel_idx)
    return _draw_pil_fallback(panel_idx)


def generate_comic_styled(scenario: dict, style: str = "3d",
                          output_dir: Path = OUTPUT_DIR) -> Path | None:
    """Генерирует комикс с заданным стилем ('3d' или 'popart')."""
    print(f"\n=== Сценарий #{scenario['id']}: {scenario['title']} [{style.upper()}] ===")
    panels_data = []
    for i, panel in enumerate(scenario["panels"]):
        img_bytes = _fetch_panel_image(panel["scene"], i,
                                       scenario_id=scenario["id"], style=style)
        if i < 3 and OPENROUTER_API_KEY:
            time.sleep(15)
        panels_data.append({
            "image_bytes": img_bytes,
            "bubble": panel["bubble"],
            "label": panel["label"],
        })
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"comic_{scenario['id']}_{style}_{ts}.jpg"
    try:
        return assemble_comic(panels_data, scenario, out_path)
    except ImportError:
        return None


def _wrap_text(text: str, max_chars: int = 20) -> list[str]:
    return textwrap.wrap(text, width=max_chars)


# ── Зоны панели ─────────────────────────────────────────────────────────────
BUBBLE_ZONE_H = 150   # верхние 150px — только пузырь, без сцены
LABEL_ZONE_H  = 44    # нижние 44px — метка панели
# Сцена рисуется в [BUBBLE_ZONE_H .. PANEL_H - LABEL_ZONE_H]


def _draw_bubble_on_canvas(draw, px: int, py: int, text: str):
    """Рисует пузырь в выделенной белой зоне (верх панели на canvas)."""
    from PIL import ImageFont

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except Exception:
        font = ImageFont.load_default()

    BZ = BUBBLE_ZONE_H
    PAD = 12
    lines = _wrap_text(text, max_chars=20)
    line_h = 28
    bub_h = len(lines) * line_h + PAD * 2
    bub_w = PANEL_W - 32
    x0 = px + 16
    y0 = py + (BZ - bub_h - 20) // 2   # центрировано в зоне
    x1 = x0 + bub_w
    y1 = y0 + bub_h

    # Тень
    draw.rounded_rectangle([x0+4, y0+4, x1+4, y1+4], radius=14, fill=(80, 80, 80, 80))
    # Белый пузырь с зелёной рамкой
    draw.rounded_rectangle([x0, y0, x1, y1], radius=14,
                            fill=(255, 255, 255), outline=COLOR_BORDER, width=4)
    # Хвостик вниз (из центра нижней грани)
    tcx = (x0 + x1) // 2
    draw.polygon([(tcx - 12, y1), (tcx + 12, y1), (tcx, y1 + 18)],
                 fill=(255, 255, 255))
    draw.line([(tcx - 12, y1), (tcx, y1 + 18)], fill=COLOR_BORDER, width=4)
    draw.line([(tcx + 12, y1), (tcx, y1 + 18)], fill=COLOR_BORDER, width=4)

    # Текст — чёрный, крупный, по центру
    for idx, line in enumerate(lines):
        ty = y0 + PAD + idx * line_h
        draw.text(((x0 + x1) // 2, ty), line, font=font,
                  fill=(15, 15, 15), anchor="mt")


def _draw_label_on_canvas(draw, px: int, py: int, label: str):
    """Рисует метку панели в нижней полосе (гарантированно видна)."""
    from PIL import ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except Exception:
        font = ImageFont.load_default()

    y0 = py + PANEL_H - LABEL_ZONE_H
    y1 = py + PANEL_H
    # Сплошной тёмный фон на всю ширину
    draw.rectangle([px, y0, px + PANEL_W, y1], fill=(10, 10, 10))
    # Зелёная черта сверху
    draw.rectangle([px, y0, px + PANEL_W, y0 + 3], fill=COLOR_BORDER)
    # Текст по центру
    draw.text((px + PANEL_W // 2, y0 + LABEL_ZONE_H // 2), label,
              font=font, fill=COLOR_BORDER, anchor="mm")


def _draw_logo_bar(draw, comic_w: int, y0: int, y1: int):
    """Логотип и слоган в нижней полосе всего комикса."""
    from PIL import ImageFont

    draw.rectangle([0, y0, comic_w, y1], fill=(8, 8, 12))
    draw.rectangle([0, y0, comic_w, y0 + 4], fill=COLOR_BORDER)

    try:
        font_logo = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        font_tag  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
    except Exception:
        font_logo = font_tag = ImageFont.load_default()

    bar_mid = y0 + (y1 - y0) // 2
    draw.text((24, bar_mid), "EcoDisplays", font=font_logo, fill=COLOR_BORDER, anchor="lm")
    draw.text((190, bar_mid), "· e-ink outdoor displays · ecodisplays.com", font=font_tag,
              fill=(170, 170, 170), anchor="lm")


def assemble_comic(panels_data: list[dict], scenario: dict, out_path: Path) -> Path:
    """panels_data: список {'image_bytes': bytes|None, 'bubble': str, 'label': str}"""
    from PIL import Image, ImageDraw

    LOGO_BAR_H = 60
    GAP = 8           # зазор между панелями
    TOTAL_H = COMIC_H + LOGO_BAR_H

    canvas = Image.new("RGB", (COMIC_W, TOTAL_H), COLOR_BG)

    positions = [
        (0,       0),
        (PANEL_W + GAP, 0),
        (0,       PANEL_H + GAP),
        (PANEL_W + GAP, PANEL_H + GAP),
    ]
    # Реальная ширина: 2*PANEL_W + GAP = 1080+8 → обрежем до COMIC_W
    # Поэтому уберём GAP из позиций и используем BORDER как разделитель
    positions = [
        (0,      0),
        (PANEL_W, 0),
        (0,      PANEL_H),
        (PANEL_W, PANEL_H),
    ]

    for i, (pd, pos) in enumerate(zip(panels_data, positions)):
        px, py = pos
        img_bytes = pd.get("image_bytes")

        if img_bytes:
            try:
                panel_img = Image.open(BytesIO(img_bytes)).convert("RGB")
                panel_img = panel_img.resize((PANEL_W, PANEL_H), Image.LANCZOS)
            except Exception:
                panel_img = Image.new("RGB", (PANEL_W, PANEL_H), (40, 40, 50))
        else:
            panel_img = Image.new("RGB", (PANEL_W, PANEL_H), (40, 40, 50))

        canvas.paste(panel_img, (px, py))

        draw = ImageDraw.Draw(canvas, "RGBA")

        # ── 1. Белая зона пузыря (сверху) ──
        draw.rectangle([px, py, px + PANEL_W, py + BUBBLE_ZONE_H],
                       fill=(248, 248, 248))
        draw.rectangle([px, py + BUBBLE_ZONE_H - 3, px + PANEL_W, py + BUBBLE_ZONE_H],
                       fill=COLOR_BORDER)   # разделительная черта

        # ── 2. Пузырь ──
        _draw_bubble_on_canvas(draw, px, py, pd["bubble"])

        # ── 3. Метка внизу ──
        _draw_label_on_canvas(draw, px, py, pd["label"])

        # ── 4. Рамка панели ──
        draw.rectangle([px, py, px + PANEL_W - 1, py + PANEL_H - 1],
                       outline=COLOR_BORDER, width=BORDER)

    # Разделитель между панелями
    sep = ImageDraw.Draw(canvas)
    sep.rectangle([PANEL_W - BORDER, 0, PANEL_W + BORDER, COMIC_H], fill=COLOR_BG)
    sep.rectangle([0, PANEL_H - BORDER, COMIC_W, PANEL_H + BORDER], fill=COLOR_BG)

    # Логобар
    logo_draw = ImageDraw.Draw(canvas)
    _draw_logo_bar(logo_draw, COMIC_W, COMIC_H, TOTAL_H)

    canvas.save(str(out_path), "JPEG", quality=92)
    print(f"  Комикс сохранён: {out_path}")
    return out_path


def generate_comic(scenario: dict, output_dir: Path = OUTPUT_DIR) -> Path | None:
    """Генерирует один комикс-стрип по сценарию."""
    print(f"\n=== Сценарий #{scenario['id']}: {scenario['title']} ===")

    panels_data = []
    for i, panel in enumerate(scenario["panels"]):
        img_bytes = _fetch_panel_image(panel["scene"], i, scenario_id=scenario["id"])
        if i < 3 and OPENROUTER_API_KEY:
            time.sleep(15)  # пауза между запросами к LLM чтобы не попасть в rate limit
        panels_data.append({
            "image_bytes": img_bytes,
            "bubble": panel["bubble"],
            "label": panel["label"],
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"comic_{scenario['id']}_{ts}.jpg"

    try:
        result = assemble_comic(panels_data, scenario, out_path)
    except ImportError:
        print("  Pillow не установлен — установите: pip install Pillow")
        return None

    return result


def _tg(method: str, **kwargs):
    """Вызов Telegram Bot API."""
    import requests as req
    r = req.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        timeout=30, **kwargs
    )
    return r.json() if r.ok else {}


def send_to_telegram(image_path: Path, caption: str) -> int | None:
    """Отправляет комикс в Telegram с кнопками одобрения. Возвращает message_id."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  Telegram не настроен (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)")
        return None

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Опубликовать",      "callback_data": "approve"},
            {"text": "✏️ На переработку",    "callback_data": "revise"},
        ]]
    }

    with open(image_path, "rb") as f:
        result = _tg("sendPhoto",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "reply_markup": json.dumps(keyboard),
            },
            files={"photo": f},
        )

    msg_id = result.get("result", {}).get("message_id")
    if msg_id:
        print(f"  Отправлено в Telegram: {msg_id} (ожидание кнопки...)")
    else:
        print(f"  Telegram ошибка: {result}")
    return msg_id


def wait_for_approval(msg_id: int, scenario: dict, image_path: Path,
                      timeout: int = 600) -> tuple[str, str]:
    """
    Ждёт нажатия кнопки ✅ или ✏️ в течение timeout секунд.
    Возвращает ('approved', '') или ('revise', 'комментарий пользователя').
    """
    import requests as req

    print(f"  Ожидание решения (до {timeout//60} мин)...")
    offset = 0
    deadline = time.time() + timeout

    # Получаем актуальный offset чтобы не обрабатывать старые апдейты
    r = _tg("getUpdates", params={"timeout": 1, "limit": 1, "offset": -1})
    updates = r.get("result", [])
    if updates:
        offset = updates[-1]["update_id"] + 1

    waiting_comment = False   # флаг: ждём текстовый комментарий после "На переработку"

    while time.time() < deadline:
        remaining = int(deadline - time.time())
        poll_timeout = min(30, remaining)
        if poll_timeout <= 0:
            break

        r = _tg("getUpdates", params={
            "timeout": poll_timeout,
            "allowed_updates": json.dumps(["callback_query", "message"]),
            "offset": offset,
        })
        updates = r.get("result", [])

        for upd in updates:
            offset = upd["update_id"] + 1

            # ── Нажата inline-кнопка ──────────────────────────────────────
            if "callback_query" in upd:
                cq = upd["callback_query"]
                # Отвечаем боту чтобы убрать "часики" на кнопке
                _tg("answerCallbackQuery", json={"callback_query_id": cq["id"]})

                data = cq.get("data", "")
                chat_id = cq["message"]["chat"]["id"]

                if data == "approve":
                    # Убираем кнопки, добавляем статус
                    _tg("editMessageReplyMarkup", json={
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "reply_markup": json.dumps({"inline_keyboard": []}),
                    })
                    _tg("sendMessage", json={
                        "chat_id": chat_id,
                        "text": "✅ Одобрено! Публикую...",
                    })
                    print("  → Одобрено пользователем")
                    return ("approved", "")

                elif data == "revise":
                    # Убираем кнопки, просим комментарий
                    _tg("editMessageReplyMarkup", json={
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "reply_markup": json.dumps({"inline_keyboard": []}),
                    })
                    _tg("sendMessage", json={
                        "chat_id": chat_id,
                        "text": "✏️ Напишите комментарий для переработки:",
                    })
                    print("  → Запрошена переработка, жду комментарий...")
                    waiting_comment = True

            # ── Текстовый комментарий после "На переработку" ─────────────
            elif waiting_comment and "message" in upd:
                msg = upd["message"]
                if "text" in msg and str(msg["chat"]["id"]) == str(TELEGRAM_CHAT_ID):
                    comment = msg["text"]
                    _tg("sendMessage", json={
                        "chat_id": msg["chat"]["id"],
                        "text": f"📝 Принято. Комментарий: «{comment}»\nПересоздаю комикс...",
                    })
                    print(f"  → Комментарий: {comment}")
                    return ("revise", comment)

    print("  → Таймаут ожидания")
    return ("timeout", "")


def _upload_image_public(image_path: Path) -> str | None:
    """Загружает JPEG на публичный хостинг, возвращает прямой URL доступный Instagram API."""
    import requests as req

    # freeimage.host → iili.io CDN (Instagram API его принимает)
    try:
        with open(image_path, "rb") as f:
            r = req.post(
                "https://freeimage.host/api/1/upload",
                data={"key": "6d207e02198a847aa98d0a2a901485a5",
                      "action": "upload", "format": "json"},
                files={"source": (image_path.name, f, "image/jpeg")},
                timeout=60,
            )
        if r.ok:
            url = r.json().get("image", {}).get("url", "")
            if url:
                print(f"    Загружено: {url}")
                return url
    except Exception as e:
        print(f"    freeimage.host ошибка: {e}")

    # tmpfiles.org — запасной (Instagram может не принять)
    try:
        with open(image_path, "rb") as f:
            r = req.post("https://tmpfiles.org/api/v1/upload",
                         files={"file": (image_path.name, f, "image/jpeg")}, timeout=60)
        if r.ok:
            url = r.json().get("data", {}).get("url", "").replace(
                "tmpfiles.org/", "tmpfiles.org/dl/")
            if url:
                print(f"    Загружено (резерв): {url}")
                return url
    except Exception as e:
        print(f"    tmpfiles.org ошибка: {e}")

    return None


def _publish_instagram_photo(image_url: str, caption: str) -> str | None:
    """Публикует фото в Instagram через Graph API. Возвращает media_id или None."""
    import requests as req
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    uid   = os.getenv("INSTAGRAM_USER_ID")

    if not token or not uid or uid.endswith("..."):
        return None

    # Шаг 1: создаём контейнер
    r = req.post(f"https://graph.facebook.com/v21.0/{uid}/media",
                 data={"image_url": image_url, "caption": caption,
                       "access_token": token}, timeout=30)
    if not r.ok:
        print(f"    Instagram container error: {r.status_code} {r.text[:150]}")
        return None
    container_id = r.json().get("id")
    print(f"    Container: {container_id}")

    # Шаг 2: публикуем
    r2 = req.post(f"https://graph.facebook.com/v21.0/{uid}/media_publish",
                  data={"creation_id": container_id, "access_token": token}, timeout=30)
    if not r2.ok:
        print(f"    Instagram publish error: {r2.status_code} {r2.text[:150]}")
        return None

    media_id = r2.json().get("id")
    print(f"    Instagram media_id: {media_id}")
    return media_id


def publish_comic(image_path: Path, scenario: dict):
    """Публикует одобренный комикс через Make.com webhook."""
    import requests as req

    print(f"  📢 Публикация: {image_path.name}")

    hashtags = "#EcoDisplays #eink #smartcity #outdoor #digital #sustainability #ekologija #displej"
    caption_sr = scenario["caption_sr"]
    caption_en = scenario["caption_en"]
    caption_full = f"{caption_sr}\n\n{caption_en}\n\n{hashtags}"

    # 1. Загружаем изображение на публичный хостинг
    print("    Загружаю на хостинг...")
    image_url = _upload_image_public(image_path)
    if not image_url:
        _tg("sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "❌ Не удалось загрузить изображение на хостинг. Публикация отменена.",
        })
        return

    # 2. Отправляем в Make.com с полным набором полей для роутинга
    hook = os.getenv("MAKE_WEBHOOK_URL")
    if not hook:
        print("  ⚠️ MAKE_WEBHOOK_URL не задан в .env")
        return

    # Получаем реальные размеры файла и изображения
    file_size_bytes = image_path.stat().st_size
    img_w, img_h = COMIC_W, COMIC_H + 60   # 1080 × 1140
    aspect_ratio  = round(img_w / img_h, 4) # 0.9474 — в диапазоне 4:5..1.91:1 ✓

    payload = {
        # ── Роутинг ─────────────────────────────────────────────────────────
        "type":   "photo",          # "photo" | "reel" — Make Router смотрит сюда
        "source": "comic_generator",

        # ── ФОТО (Instagram Photo Requirements) ─────────────────────────────
        # Format: JPEG only
        # Max file size: 8 MiB  → наши ~350 KB, ✓
        # Aspect ratio: 4:5 (0.8) … 1.91:1  → наш 1080×1140 = 0.947, ✓
        # Width: 320–1440 px  → наш 1080, ✓
        "image_url":      image_url,        # публичный JPEG URL (прямая ссылка)
        "image_format":   "JPEG",
        "image_width":    img_w,            # 1080
        "image_height":   img_h,            # 1140
        "image_aspect":   aspect_ratio,     # 0.9474
        "image_size_kb":  round(file_size_bytes / 1024, 1),

        # ── ВИДЕО (поля присутствуют только если type=reel) ────────────────────
        # Format: MOV/MP4, H264/HEVC, AAC 48kHz, fast-start, 23-60 FPS
        # Aspect ratio: 9:16 рекомендуется (0.01:1…10:1 допустимо)
        # Duration: 3s…15min | File size: ≤1 GB | Bitrate: VBR ≤5 Mbps
        # video_url и остальные поля НЕ отправляются для type=photo

        # ── Подписи ──────────────────────────────────────────────────────────
        "caption_sr":  caption_sr,      # сербский текст
        "caption_en":  caption_en,      # английский текст
        "hashtags":    hashtags,        # хэштеги отдельно
        "caption":     caption_full,    # полный caption для прямой вставки в API

        # ── Мета-данные ──────────────────────────────────────────────────────
        "scenario_id":    scenario["id"],
        "scenario_title": scenario["title"],
        "filename":       image_path.name,
    }

    # Показываем payload в Telegram
    payload_preview = (
        f"📤 <b>Webhook → Make.com:</b>\n"
        f"<code>"
        f"type:          {payload['type']}\n"
        f"── ФОТО ──────────────────────\n"
        f"image_url:     {payload['image_url'][:55]}\n"
        f"image_format:  {payload['image_format']}\n"
        f"image_width:   {payload['image_width']} px\n"
        f"image_height:  {payload['image_height']} px\n"
        f"image_aspect:  {payload['image_aspect']} (норма: 0.8–1.91)\n"
        f"image_size_kb: {payload['image_size_kb']} KB\n"
        f"── ВИДЕО ─────────────────────\n"
        f"video_url:     (не отправляется для photo)\n"
        f"── ПОДПИСЬ ───────────────────\n"
        f"caption_sr:    {caption_sr[:45]}...\n"
        f"caption_en:    {caption_en[:45]}...\n"
        f"hashtags:      {hashtags[:40]}...\n"
        f"── МЕТА ──────────────────────\n"
        f"scenario_id:   {payload['scenario_id']}\n"
        f"filename:      {payload['filename']}"
        f"</code>"
    )
    _tg("sendMessage", json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": payload_preview,
        "parse_mode": "HTML",
    })

    r = req.post(hook, json=payload, timeout=15)
    print(f"    Make.com: {r.status_code} {r.text[:80]}")

    if r.ok:
        _tg("sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"✅ Make.com принял запрос ({r.status_code}): {r.text[:80]}",
        })
        print("  ✅ Make.com: принято")
    else:
        _tg("sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"❌ Make.com ошибка {r.status_code}:\n{r.text[:300]}",
        })
        print(f"  ❌ Make.com ошибка: {r.status_code}")


def send_ab_test(path_a: Path, scenario_a: dict, label_a: str,
                 path_b: Path, scenario_b: dict, label_b: str):
    """Отправляет два комикса A/B с отдельными кнопками и ждёт решения по каждому."""
    caption_a = (f"🅰️ {label_a}\n\n"
                 f"{scenario_a['caption_sr']}\n{scenario_a['caption_en']}\n\n"
                 f"#EcoDisplays #eink #ABtest")
    caption_b = (f"🅱️ {label_b}\n\n"
                 f"{scenario_b['caption_sr']}\n{scenario_b['caption_en']}\n\n"
                 f"#EcoDisplays #eink #ABtest")

    print("\n── A/B тест ──────────────────────────────")
    msg_a = send_to_telegram(path_a, caption_a)
    time.sleep(2)
    msg_b = send_to_telegram(path_b, caption_b)

    if not msg_a or not msg_b:
        return

    print(f"  Вариант A: msg {msg_a}  |  Вариант B: msg {msg_b}")
    print("  Жду решения по варианту A...")
    action_a, comment_a = wait_for_approval(msg_a, scenario_a, path_a, timeout=600)

    print("  Жду решения по варианту B...")
    action_b, comment_b = wait_for_approval(msg_b, scenario_b, path_b, timeout=600)

    _tg("sendMessage", json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": (f"📊 A/B результат:\n"
                 f"🅰️ {label_a}: {'✅ одобрен' if action_a == 'approved' else ('✏️ ' + comment_a) if action_a == 'revise' else '⏳ таймаут'}\n"
                 f"🅱️ {label_b}: {'✅ одобрен' if action_b == 'approved' else ('✏️ ' + comment_b) if action_b == 'revise' else '⏳ таймаут'}"),
    })

    if action_a == "approved":
        publish_comic(path_a, scenario_a)
    if action_b == "approved":
        publish_comic(path_b, scenario_b)


def main():
    parser = argparse.ArgumentParser(description="EcoDisplays Comic Strip Generator")
    parser.add_argument("--scenario", type=int, help="Номер сценария (1-N)")
    parser.add_argument("--list", action="store_true", help="Список всех сценариев")
    parser.add_argument("--all", action="store_true", help="Сгенерировать все сценарии")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Папка вывода")
    parser.add_argument("--style", choices=["3d", "popart", "iso", "hero", "hero3d", "real3d"], default="3d", help="Стиль панелей")
    parser.add_argument("--telegram", action="store_true", help="Отправить в Telegram с кнопками одобрения")
    parser.add_argument("--no-wait", action="store_true", help="Не ждать нажатия кнопки")
    parser.add_argument("--ab", action="store_true",
                        help="A/B тест: сценарий 4 (3D) vs сценарий 5 (поп-арт)")
    args = parser.parse_args()

    if args.ab:
        sc_a = next(s for s in SCENARIOS if s["id"] == 4)
        sc_b = next(s for s in SCENARIOS if s["id"] == 7)
        print("Генерирую A/B: сценарий 4 (3D) и сценарий 7 (изометрия)...")
        path_a = generate_comic_styled(sc_a, style="3d", output_dir=args.output)
        path_b = generate_comic_styled(sc_b, style="iso", output_dir=args.output)
        if path_a and path_b:
            send_ab_test(path_a, sc_a, "Стиль 3D · LED vs E-ink",
                         path_b, sc_b, "Изометрия · Muzej bez papira")
        return

    if args.list:
        print("\nДоступные сценарии:")
        for s in SCENARIOS:
            print(f"  {s['id']}. {s['title']}")
            print(f"     {s['caption_sr']}")
        return

    args.output.mkdir(exist_ok=True)

    if args.all:
        scenarios = SCENARIOS
    elif args.scenario:
        scenarios = [s for s in SCENARIOS if s["id"] == args.scenario]
        if not scenarios:
            print(f"Сценарий #{args.scenario} не найден. Доступны: {[s['id'] for s in SCENARIOS]}")
            sys.exit(1)
    else:
        scenarios = [random.choice(SCENARIOS)]
        print(f"Случайный сценарий: #{scenarios[0]['id']} — {scenarios[0]['title']}")

    for scenario in scenarios:
        revision_comment = ""
        attempt = 0

        while True:
            attempt += 1
            if attempt > 1:
                print(f"\n  🔄 Переработка #{attempt}: {revision_comment}")

            result = generate_comic_styled(scenario, style=args.style, output_dir=args.output)
            if not result:
                break

            if not args.telegram:
                break

            caption = (f"{scenario['caption_sr']}\n\n"
                       f"{scenario['caption_en']}\n\n"
                       f"#EcoDisplays #eink #smartcity")
            if revision_comment:
                caption = f"🔄 Переработка по комментарию: «{revision_comment}»\n\n" + caption

            msg_id = send_to_telegram(result, caption)
            if not msg_id or args.no_wait:
                break

            action, revision_comment = wait_for_approval(msg_id, scenario, result)

            if action == "approved":
                publish_comic(result, scenario)
                break
            elif action == "revise":
                # Продолжаем цикл с комментарием
                continue
            else:
                # Таймаут — выходим
                break

    print("\nГотово!")


if __name__ == "__main__":
    main()
