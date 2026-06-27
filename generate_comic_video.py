"""
EcoDisplays Comic Video Generator
===================================
Берёт 4 панели комикса и собирает анимированный MP4 для Instagram:
  - Каждая панель появляется по очереди с wipe-эффектом
  - Финальный кадр — весь комикс целиком
  - Форматы: 1080×1080 (Feed) или 1080×1920 (Reels/Stories)
  - Опционально: фоновая музыка из /content/music.mp3 или без звука

Запуск:
  python3 generate_comic_video.py                             # случайный сценарий, reels
  python3 generate_comic_video.py --scenario 3               # конкретный сценарий
  python3 generate_comic_video.py --from-file output/comic_10_3d_*.jpg  # из готового комикса
  python3 generate_comic_video.py --format feed              # квадратный формат
  python3 generate_comic_video.py --style popart             # стиль комикса
  python3 generate_comic_video.py --no-music                 # без музыки
  python3 generate_comic_video.py --send                     # отправить в Telegram
"""

import argparse
import os
import random
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
OUTPUT_DIR.mkdir(exist_ok=True)

CONTENT_DIR = Path("/root/Ecodisplays/content")

# Импортируем всё нужное из generate_comic.py
sys.path.insert(0, str(Path(__file__).parent))
from generate_comic import (
    SCENARIOS,
    _fetch_panel_image,
    assemble_comic,
    OUTPUT_DIR as COMIC_OUTPUT_DIR,
    COMIC_W, COMIC_H, PANEL_W, PANEL_H,
    BUBBLE_ZONE_H, LABEL_ZONE_H, BORDER,
    COLOR_BG, COLOR_BORDER,
    _draw_bubble_on_canvas, _draw_label_on_canvas, _draw_logo_bar,
)

# ── Параметры анимации ────────────────────────────────────────────────────
FPS = 30
PANEL_DURATION = 3.5    # секунд на каждую панель
FINAL_DURATION = 4.0    # финальный кадр — весь комикс
INTRO_DURATION = 1.5    # вступительный кадр
FADE_DURATION = 0.4     # длительность fade-in панели


def render_single_panel(panel_data: dict, panel_idx: int) -> Path:
    """Рендерит одну панель комикса как отдельный JPG 1080×1080."""
    from PIL import Image, ImageDraw, ImageFont

    LOGO_BAR_H = 60
    W, H = 1080, 1080
    CONTENT_H = H - LOGO_BAR_H

    # Изображение сцены
    img_bytes = panel_data.get("image_bytes")
    if img_bytes:
        try:
            scene_img = Image.open(BytesIO(img_bytes)).convert("RGB")
            scene_img = scene_img.resize((W, CONTENT_H), Image.LANCZOS)
        except Exception:
            scene_img = Image.new("RGB", (W, CONTENT_H), (30, 30, 40))
    else:
        scene_img = Image.new("RGB", (W, CONTENT_H), (30, 30, 40))

    canvas = Image.new("RGB", (W, H), COLOR_BG)
    canvas.paste(scene_img, (0, 0))

    draw = ImageDraw.Draw(canvas, "RGBA")

    # Белая зона пузыря
    draw.rectangle([0, 0, W, BUBBLE_ZONE_H], fill=(248, 248, 248))
    draw.rectangle([0, BUBBLE_ZONE_H - 3, W, BUBBLE_ZONE_H], fill=COLOR_BORDER)

    # Пузырь (используем временный canvas под PANEL_W×PANEL_H координаты)
    # Масштабируем: панель теперь 1080px широкая, а не 540
    _draw_bubble_wide(draw, 0, 0, W, BUBBLE_ZONE_H, panel_data["bubble"])

    # Метка внизу контента
    _draw_label_wide(draw, 0, CONTENT_H - LABEL_ZONE_H, W, panel_data["label"])

    # Рамка
    draw.rectangle([0, 0, W - 1, CONTENT_H - 1], outline=COLOR_BORDER, width=BORDER * 2)

    # Номер панели (большой)
    try:
        font_num = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    except Exception:
        font_num = ImageFont.load_default()
    num_text = str(panel_idx + 1)
    draw.text((W - 30, CONTENT_H - LABEL_ZONE_H - 10), num_text,
              font=font_num, fill=(0, 200, 120, 60), anchor="rb")

    # Логобар
    logo_draw = ImageDraw.Draw(canvas)
    _draw_logo_bar(logo_draw, W, CONTENT_H, H)

    out = OUTPUT_DIR / f"_panel_{panel_idx}_{int(time.time())}.jpg"
    canvas.save(str(out), "JPEG", quality=92)
    return out


def _draw_bubble_wide(draw, px, py, width, height, text):
    """Пузырь для широкого (1080px) холста."""
    import textwrap
    from PIL import ImageFont
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
    except Exception:
        font = ImageFont.load_default()

    lines = textwrap.wrap(text, width=36)
    line_h = 38
    PAD = 16
    bub_h = len(lines) * line_h + PAD * 2
    bub_w = width - 80
    x0 = px + 40
    y0 = py + max(8, (height - bub_h - 24) // 2)
    x1 = x0 + bub_w
    y1 = y0 + bub_h

    draw.rounded_rectangle([x0 + 4, y0 + 4, x1 + 4, y1 + 4], radius=18,
                            fill=(60, 60, 60, 80))
    draw.rounded_rectangle([x0, y0, x1, y1], radius=18,
                            fill=(255, 255, 255), outline=COLOR_BORDER, width=5)
    # Хвостик
    tcx = (x0 + x1) // 2
    draw.polygon([(tcx - 14, y1), (tcx + 14, y1), (tcx, y1 + 22)],
                 fill=(255, 255, 255))
    draw.line([(tcx - 14, y1), (tcx, y1 + 22)], fill=COLOR_BORDER, width=5)
    draw.line([(tcx + 14, y1), (tcx, y1 + 22)], fill=COLOR_BORDER, width=5)

    for idx, line in enumerate(lines):
        ty = y0 + PAD + idx * line_h
        draw.text(((x0 + x1) // 2, ty), line, font=font,
                  fill=(15, 15, 15), anchor="mt")


def _draw_label_wide(draw, px, py, width, label):
    """Метка для широкого холста."""
    from PIL import ImageFont
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    draw.rectangle([px, py, px + width, py + LABEL_ZONE_H], fill=(10, 10, 10))
    draw.rectangle([px, py, px + width, py + 3], fill=COLOR_BORDER)
    draw.text((px + width // 2, py + LABEL_ZONE_H // 2), label,
              font=font, fill=COLOR_BORDER, anchor="mm")


def render_intro_frame(scenario: dict) -> Path:
    """Создаёт вступительный кадр с названием сценария."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1080, 1080
    canvas = Image.new("RGB", (W, H), COLOR_BG)
    draw = ImageDraw.Draw(canvas)

    # Фоновая сетка
    for x in range(0, W, 60):
        draw.line([(x, 0), (x, H)], fill=(20, 30, 20), width=1)
    for y in range(0, H, 60):
        draw.line([(0, y), (W, y)], fill=(20, 30, 20), width=1)

    # Логотип
    try:
        font_logo = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        font_title = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        font_ep = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        font_logo = font_title = font_ep = ImageFont.load_default()

    draw.text((W // 2, 320), "EcoDisplays", font=font_logo,
              fill=COLOR_BORDER, anchor="mm")
    draw.text((W // 2, 400), "· e-ink outdoor displays ·", font=font_ep,
              fill=(120, 180, 120), anchor="mm")

    # Разделитель
    draw.rectangle([W // 2 - 220, 440, W // 2 + 220, 444], fill=COLOR_BORDER)

    # Название сценария
    import textwrap
    title_lines = textwrap.wrap(scenario["title"], width=24)
    for i, line in enumerate(title_lines):
        draw.text((W // 2, 490 + i * 48), line, font=font_title,
                  fill=(220, 240, 220), anchor="mm")

    # "Комикс"
    draw.text((W // 2, 640), "комикс", font=font_ep,
              fill=(100, 150, 100), anchor="mm")

    out = OUTPUT_DIR / f"_intro_{int(time.time())}.jpg"
    canvas.save(str(out), "JPEG", quality=90)
    return out


def find_music() -> Path | None:
    """Ищет музыкальный файл."""
    candidates = [
        CONTENT_DIR / "music.mp3",
        CONTENT_DIR / "music.mp4",
        CONTENT_DIR / "bg_music.mp3",
        Path("/root/Ecodisplays/content/music.mp3"),
    ]
    for p in candidates:
        if p.exists():
            return p
    # Пробуем найти любой аудиофайл
    for ext in ("*.mp3", "*.m4a", "*.aac", "*.ogg"):
        found = list(CONTENT_DIR.glob(ext))
        if found:
            return found[0]
    return None


def build_comic_video(
    scenario_id: int | None = None,
    style: str = "3d",
    fmt: str = "reels",     # "reels" (1080x1920) или "feed" (1080x1080)
    use_music: bool = True,
    output_dir: Path = OUTPUT_DIR,
) -> Path | None:
    """
    Основная функция: рендерит панели, собирает видео через ffmpeg.
    Возвращает путь к готовому MP4.
    """

    # 1. Выбираем сценарий
    if scenario_id is not None:
        scenario = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
        if not scenario:
            print(f"Сценарий #{scenario_id} не найден")
            return None
    else:
        scenario = random.choice(SCENARIOS)

    print(f"\n🎬 Генерирую видео-комикс: #{scenario['id']} «{scenario['title']}»")
    print(f"   Стиль: {style} | Формат: {fmt}")

    # 2. Рендерим 4 панели
    print("\n▶ Фаза 1: рендер панелей...")
    panels_data = []
    for i, panel in enumerate(scenario["panels"]):
        print(f"  Панель {i+1}/4: {panel['label']}")
        img_bytes = _fetch_panel_image(panel["scene"], i, scenario_id=scenario["id"], style=style)
        panels_data.append({
            "image_bytes": img_bytes,
            "bubble": panel["bubble"],
            "label": panel["label"],
        })
        if i < 3:
            time.sleep(3)  # небольшая пауза между панелями

    # 3. Сохраняем каждую панель как отдельный кадр 1080×1080
    print("\n▶ Фаза 2: сохраняем панели...")
    panel_frames = []
    for i, pd in enumerate(panels_data):
        p = render_single_panel(pd, i)
        panel_frames.append(p)
        print(f"  → {p.name}")

    # 4. Финальный кадр — весь комикс
    print("\n▶ Фаза 3: сборка финального кадра...")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = output_dir / f"_comic_final_{ts}.jpg"
    assemble_comic(panels_data, scenario, final_path)

    # 5. Intro frame
    intro_path = render_intro_frame(scenario)

    # 6. Собираем видео через ffmpeg
    print("\n▶ Фаза 4: сборка видео через ffmpeg...")
    out_video = output_dir / f"comic_video_{scenario['id']}_{ts}.mp4"

    # Определяем итоговые размеры
    if fmt == "reels":
        OUT_W, OUT_H = 1080, 1920
        # Панели центрируем: 1080×1080 вписываем в 1080×1920 (добавляем 420px сверху и снизу)
        vf_pad = "pad=1080:1920:0:420:black"
    else:
        OUT_W, OUT_H = 1080, 1080
        vf_pad = None

    def img_to_clip(img_path: Path, duration: float, vf_extra: str = "") -> list[str]:
        """Возвращает ffmpeg-фрагмент для одного изображения."""
        frames = int(duration * FPS)
        vf = f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black"
        if vf_extra:
            vf += f",{vf_extra}"
        return [
            "-loop", "1",
            "-t", str(duration),
            "-i", str(img_path),
        ]

    # Строим список входов и filter_complex
    all_frames = [intro_path] + panel_frames + [final_path]
    durations = [INTRO_DURATION] + [PANEL_DURATION] * 4 + [FINAL_DURATION]
    n = len(all_frames)

    inputs = []
    for f in all_frames:
        inputs += ["-loop", "1", "-t", str(durations[all_frames.index(f)]), "-i", str(f)]

    # Для каждого клипа: scale + pad + fps + зум для панелей
    fc_parts = []
    for i in range(n):
        d = int(durations[i] * FPS)
        zoom_vf = ""
        if 1 <= i <= 4:  # панели с лёгким zoom-in
            zoom_vf = f",zoompan=z='min(1+on/{d}*0.08,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={OUT_W}x{OUT_H}:fps={FPS}"
            fc_parts.append(
                f"[{i}:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
                f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black{zoom_vf}[v{i}];"
            )
        else:
            fc_parts.append(
                f"[{i}:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
                f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,"
                f"fps={FPS}[v{i}];"
            )

    # Склеиваем через xfade
    TRANSITIONS = ["fade", "wipeleft", "wiperight", "slideleft", "slideright", "dissolve"]
    xfade_parts = []
    offset = INTRO_DURATION - FADE_DURATION
    prev = "[v0]"
    for i in range(1, n):
        tag = f"[xv{i}]"
        tr = TRANSITIONS[(i - 1) % len(TRANSITIONS)]
        xfade_parts.append(
            f"{prev}[v{i}]xfade=transition={tr}:duration={FADE_DURATION:.2f}:offset={offset:.2f}{tag}"
        )
        prev = tag
        offset += durations[i] - FADE_DURATION

    filter_complex = "".join(fc_parts) + ";".join(xfade_parts)
    final_video_tag = f"[xv{n-1}]"

    # Проверяем музыку
    music_path = find_music() if use_music else None

    total_duration = sum(durations) - FADE_DURATION * (n - 1)

    if music_path:
        print(f"  Музыка: {music_path.name}")
        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-i", str(music_path)]
            + [
                "-filter_complex",
                filter_complex + f";[{n}:a]aloop=loop=-1:size=999999,atrim=duration={total_duration:.2f},volume=0.4,afade=t=out:st={total_duration-2:.2f}:d=2[aout]",
                "-map", final_video_tag,
                "-map", "[aout]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p",
                "-t", str(total_duration),
                "-r", str(FPS),
                str(out_video),
            ]
        )
    else:
        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + [
                "-filter_complex", filter_complex,
                "-map", final_video_tag,
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-t", str(total_duration),
                "-r", str(FPS),
                "-an",
                str(out_video),
            ]
        )

    print(f"  Запуск ffmpeg... ({total_duration:.1f}с видео)")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0 or not out_video.exists():
        print(f"  ❌ ffmpeg ошибка:\n{result.stderr[-2000:]}")
        # Fallback: простой вариант без xfade (concat)
        print("  ⚡ Пробую fallback (простой concat)...")
        out_video = _fallback_concat(all_frames, durations, OUT_W, OUT_H, music_path, out_video)

    if out_video and out_video.exists():
        size_mb = out_video.stat().st_size / 1024 / 1024
        print(f"\n✅ Готово: {out_video.name} ({size_mb:.1f} MB, {total_duration:.1f}с)")
    else:
        print("\n❌ Не удалось создать видео")
        out_video = None

    # Удаляем временные файлы
    for p in [intro_path] + panel_frames:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass

    return out_video


def _fallback_concat(frames: list[Path], durations: list[float],
                     W: int, H: int,
                     music_path: Path | None,
                     out_path: Path) -> Path | None:
    """Простой concat без xfade — надёжный fallback."""
    # Создаём список файлов для concat
    concat_list = out_path.parent / f"_concat_{int(time.time())}.txt"
    scaled_clips = []

    for i, (frame, dur) in enumerate(zip(frames, durations)):
        clip = out_path.parent / f"_clip_{i}_{int(time.time())}.mp4"
        r = subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(frame),
            "-t", str(dur),
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,fps={FPS}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an", str(clip),
        ], capture_output=True)
        if clip.exists():
            scaled_clips.append(clip)

    if not scaled_clips:
        return None

    with open(concat_list, "w") as f:
        for c in scaled_clips:
            f.write(f"file '{c}'\n")

    total_dur = sum(durations)
    if music_path:
        r = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(music_path),
            "-filter_complex", f"[1:a]aloop=loop=-1:size=999999,atrim=duration={total_dur:.2f},volume=0.4[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p", "-t", str(total_dur),
            str(out_path),
        ], capture_output=True)
    else:
        r = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-an", str(out_path),
        ], capture_output=True)

    for c in scaled_clips:
        c.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)

    return out_path if out_path.exists() else None


def send_to_telegram(video_path: Path, scenario: dict) -> bool:
    """
    Создаёт стандартный пакет (как у approval_bot) и отправляет видео в Telegram
    с кнопками approve:<pkg_name> / skip:<pkg_name> — совместимо с approval_bot.py.
    """
    import json as _json
    import requests as req
    from datetime import datetime as _dt

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram не настроен (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)")
        return False

    # Создаём пакет в OUTPUT_DIR
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    title = scenario.get("title", "Comic_Video")[:30].replace(" ", "_")
    pkg_name = f"{ts}_comic_{title}"
    pkg_dir = OUTPUT_DIR / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # Копируем видео как reel.mp4
    import shutil
    reel_path = pkg_dir / "reel.mp4"
    shutil.copy2(video_path, reel_path)

    # Создаём post_meta.json
    caption_sr = (
        f"🎬 EcoDisplays комикс: «{scenario.get('title', '')}»\n"
        "e-ink дисплеи за паметне градове. "
        "Информације у реалном времену, без одблеска, ниска потрошња. 🌿"
    )
    meta = {
        "generated_at": _dt.now().isoformat(),
        "source": str(video_path),
        "status": "pending_approval",
        "caption_sr": caption_sr,
        "caption_en": f"EcoDisplays comic: \"{scenario.get('title', '')}\". Smart city e-ink displays.",
        "hashtags": [
            "#EcoDisplays", "#eink", "#epaper", "#smartcity",
            "#comics", "#urbantech", "#digitaldisplay", "#Serbia",
        ],
        "content_type": "comic_video",
        "post_title": title,
        "is_trending": False,
    }
    (pkg_dir / "post_meta.json").write_text(_json.dumps(meta, ensure_ascii=False, indent=2))
    (pkg_dir / "caption.txt").write_text(caption_sr)

    caption_tg = (
        f"🎬 *Видео-комикс:* «{scenario.get('title', '')}»\n"
        f"📂 `{pkg_name}`\n\n"
        f"Одобрить → отправится в Instagram через Make.com"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Опубликовать", "callback_data": f"approve:{pkg_name}"},
            {"text": "❌ Пропустить",   "callback_data": f"skip:{pkg_name}"},
        ]]
    }

    print(f"  📤 Отправка в Telegram ({video_path.stat().st_size / 1024 / 1024:.1f} MB)...")
    with open(reel_path, "rb") as f:
        resp = req.post(
            f"https://api.telegram.org/bot{token}/sendVideo",
            data={
                "chat_id": chat_id,
                "caption": caption_tg,
                "parse_mode": "Markdown",
                "reply_markup": _json.dumps(keyboard),
                "supports_streaming": "true",
            },
            files={"video": f},
            timeout=120,
        )

    if resp.ok and resp.json().get("ok"):
        # Сохраняем file_id для Make.com
        result = resp.json().get("result", {})
        video_obj = result.get("video", {})
        file_id = video_obj.get("file_id", "")
        sent_path = OUTPUT_DIR / "sent_log.json"
        try:
            sent = _json.loads(sent_path.read_text()) if sent_path.exists() else {}
        except Exception:
            sent = {}
        sent[pkg_name] = {"file_id": file_id, "status": "pending_approval", "msg_id": result.get("message_id")}
        sent_path.write_text(_json.dumps(sent, indent=2))
        print(f"  ✅ Отправлено в Telegram · пакет: {pkg_name}")
        return True
    else:
        print(f"  ❌ Ошибка: {resp.text[:300]}")
        return False


def video_from_existing_comic(
    comic_path: Path,
    fmt: str = "reels",
    use_music: bool = True,
    output_dir: Path = OUTPUT_DIR,
) -> Path | None:
    """
    Собирает видео из уже готового JPG-комикса (1080×1080 или 1080×1140).
    Нарезает на 4 панели, анимирует, добавляет музыку.
    """
    from PIL import Image, ImageDraw, ImageFont

    print(f"\n🎬 Видео из готового комикса: {comic_path.name}")

    img = Image.open(comic_path)
    W, H = img.size
    LOGO_H = 60 if H > 1080 else 0
    COMIC_H = H - LOGO_H
    PW, PH = W // 2, COMIC_H // 2

    # 4 панели
    crops = [
        img.crop((0,  0,   PW, PH)),
        img.crop((PW, 0,   W,  PH)),
        img.crop((0,  PH,  PW, COMIC_H)),
        img.crop((PW, PH,  W,  COMIC_H)),
    ]

    OW = 1080
    OH = 1920 if fmt == "reels" else 1080
    PAD_Y = (OH - OW) // 2 if fmt == "reels" else 0

    ts = int(time.time())
    panel_files = []
    for i, crop in enumerate(crops):
        p = crop.resize((OW, OW), Image.LANCZOS)
        path = output_dir / f"_ep{i}_{ts}.jpg"
        p.save(str(path), "JPEG", quality=93)
        panel_files.append(path)

    # Финальный кадр — весь комикс
    final_img = img.crop((0, 0, W, COMIC_H)).resize((OW, OW), Image.LANCZOS)
    final_path = output_dir / f"_efinal_{ts}.jpg"
    final_img.save(str(final_path), "JPEG", quality=93)

    # Intro
    intro = Image.new("RGB", (OW, OW), (10, 15, 12))
    d = ImageDraw.Draw(intro)
    for x in range(0, OW, 60):
        d.line([(x, 0), (x, OW)], fill=(20, 35, 22), width=1)
    for y in range(0, OW, 60):
        d.line([(0, y), (OW, y)], fill=(20, 35, 22), width=1)
    try:
        fL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 70)
        fS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        fL = fS = ImageFont.load_default()
    d.text((540, 420), "EcoDisplays", font=fL, fill=(0, 200, 120), anchor="mm")
    d.text((540, 510), "· e-ink outdoor displays ·", font=fS, fill=(100, 180, 100), anchor="mm")
    d.rectangle([320, 545, 760, 549], fill=(0, 200, 120))
    d.text((540, 600), comic_path.stem[:30], font=fS, fill=(160, 220, 160), anchor="mm")
    intro_path = output_dir / f"_eintro_{ts}.jpg"
    intro.save(str(intro_path), "JPEG", quality=90)

    all_frames = [intro_path] + panel_files + [final_path]
    durations = [1.5, 3.5, 3.5, 3.5, 3.5, 4.5]
    FADE = 0.4
    n = len(all_frames)

    inputs = []
    for f in all_frames:
        inputs += ["-loop", "1", "-t", str(durations[all_frames.index(f)]), "-i", str(f)]

    fc = []
    for i in range(n):
        dd = int(durations[i] * FPS)
        base = f"[{i}:v]scale={OW}:{OW}:force_original_aspect_ratio=decrease,pad={OW}:{OW}:(ow-iw)/2:(oh-ih)/2:black"
        pad_h = f",pad={OW}:{OH}:0:{PAD_Y}:black" if fmt == "reels" else ""
        if 1 <= i <= 4:
            zp = f",zoompan=z='min(1+on/{dd}*0.06,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={dd}:s={OW}x{OW}:fps={FPS}"
            fc.append(f"{base}{zp}{pad_h}[v{i}];")
        else:
            fc.append(f"{base}{pad_h},fps={FPS}[v{i}];")

    TRANSITIONS = ["fade", "wipeleft", "wiperight", "slideleft", "slideright", "dissolve"]
    xf = []
    offset = durations[0] - FADE
    prev = "[v0]"
    for i in range(1, n):
        tag = f"[xv{i}]"
        tr = TRANSITIONS[(i - 1) % len(TRANSITIONS)]
        xf.append(f"{prev}[v{i}]xfade=transition={tr}:duration={FADE:.2f}:offset={offset:.2f}{tag}")
        prev = tag
        offset += durations[i] - FADE

    filter_str = "".join(fc) + ";".join(xf)
    total = sum(durations) - FADE * (n - 1)
    out_video = output_dir / f"comic_video_{comic_path.stem}_{ts}.mp4"

    music_path = find_music() if use_music else None

    if music_path:
        extra = ["-i", str(music_path),
                 "-filter_complex",
                 filter_str + f";[{n}:a]aloop=loop=-1:size=999999,atrim=duration={total:.2f},volume=0.4,afade=t=out:st={total-2:.2f}:d=2[aout]",
                 "-map", prev, "-map", "[aout]",
                 "-c:a", "aac", "-b:a", "128k"]
    else:
        extra = ["-filter_complex", filter_str, "-map", prev, "-an"]

    cmd = (["ffmpeg", "-y"] + inputs + extra +
           ["-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-t", str(total), "-r", str(FPS), str(out_video)])

    print(f"  ffmpeg: {total:.1f}с, {OW}×{OH}...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ❌ ffmpeg:\n{r.stderr[-1000:]}")
        out_video = None
    else:
        sz = out_video.stat().st_size / 1024 / 1024
        print(f"  ✅ {out_video.name} ({sz:.1f} MB, {total:.1f}с)")

    for p in all_frames:
        p.unlink(missing_ok=True)

    return out_video


def main():
    parser = argparse.ArgumentParser(description="EcoDisplays Comic Video Generator")
    parser.add_argument("--scenario", type=int, default=None,
                        help="ID сценария (по умолчанию — случайный)")
    parser.add_argument("--from-file", type=str, default=None,
                        help="Путь к готовому JPG-комиксу (не генерировать, а собрать из файла)")
    parser.add_argument("--style", choices=["3d", "popart", "isometric", "hero"],
                        default="3d", help="Стиль комикса")
    parser.add_argument("--format", dest="fmt",
                        choices=["reels", "feed"], default="reels",
                        help="Формат видео: reels=1080x1920, feed=1080x1080")
    parser.add_argument("--no-music", action="store_true",
                        help="Без фоновой музыки")
    parser.add_argument("--send", action="store_true",
                        help="Отправить результат в Telegram")
    parser.add_argument("--list", action="store_true",
                        help="Показать список сценариев")
    args = parser.parse_args()

    if args.list:
        print("\nДоступные сценарии:")
        for s in SCENARIOS:
            print(f"  #{s['id']:2d}  {s['title']}")
        return

    # Режим: из готового файла
    if args.from_file:
        comic_path = Path(args.from_file)
        if not comic_path.exists():
            # Пробуем glob
            matches = sorted(Path(".").glob(args.from_file))
            if not matches:
                print(f"Файл не найден: {args.from_file}")
                sys.exit(1)
            comic_path = matches[-1]

        video_path = video_from_existing_comic(
            comic_path=comic_path,
            fmt=args.fmt,
            use_music=not args.no_music,
        )
        if video_path and args.send:
            scenario_stub = {"id": 0, "title": comic_path.stem}
            send_to_telegram(video_path, scenario_stub)
        return

    # Режим: генерация новых панелей
    if args.scenario is not None:
        scenario = next((s for s in SCENARIOS if s["id"] == args.scenario), None)
        if not scenario:
            print(f"Сценарий #{args.scenario} не найден")
            sys.exit(1)
    else:
        scenario = random.choice(SCENARIOS)

    video_path = build_comic_video(
        scenario_id=scenario["id"],
        style=args.style,
        fmt=args.fmt,
        use_music=not args.no_music,
    )

    if video_path and args.send:
        send_to_telegram(video_path, scenario)


if __name__ == "__main__":
    main()
