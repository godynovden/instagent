"""
Ecodisplays Content Farm — ежедневный запуск.

Обходит все необработанные медиафайлы в /content,
генерирует Reels пакеты, отправляет в Telegram на одобрение.

Запуск:
  python3 content_farm.py              # обработать все новые файлы
  python3 content_farm.py --limit 3    # обработать до 3 файлов
  python3 content_farm.py --mode veo   # использовать Veo для видео

Расписание (cron):
  0 9 * * * cd /root/Ecodisplays && python3 content_farm.py --limit 1
"""

import os
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

CONTENT_DIR = Path(os.getenv("CONTENT_DIR", "/root/Ecodisplays/content"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
STATE_FILE = OUTPUT_DIR / "processed_files.json"

OUTPUT_DIR.mkdir(exist_ok=True)

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".heic"}
SUPPORTED_VIDEOS = {".mp4", ".mov", ".avi"}  # берём только для caption, не для публикации

# Темы для генерации без исходников — ротируются при запуске --topics
# Распределение по типам с высоким approval rate:
#   comparison (75%), eco_fact (30%), urban_case (50%)
# product_shot и installation убраны — их нужно генерировать только с реальными фото
TOPIC_POOL = [
    # --- eco_fact (30% approval) ---
    "e-ink vs LED energy comparison: 111x less consumption, solar-powered outdoor display",
    "e-ink display IP65 weatherproof: works in rain, -20°C to +60°C, no maintenance",
    "e-ink 10 year warranty no screen burn outdoor signage: total cost of ownership",
    "e-ink zero power static image: energy only when content changes, smart city",
    "e-ink sunlight enhancement: direct sun makes image clearer, unlike LCD glare",
    "e-ink solar panel 20-250W autonomous outdoor display no grid connection needed",
    # --- comparison (75% approval) ---
    "e-ink vs LCD outdoor screen direct sunlight readability comparison side by side",
    "e-ink vs LED billboard power consumption comparison 300W vs 3W outdoor signage",
    "e-ink vs static printed sign: real-time remote update vs physical replacement cost",
    "e-ink 111x energy saving vs conventional display outdoor digital signage cost",
    "e-ink vs LED outdoor display lifespan: 10 years no burn vs 3-5 year replacement",
    # --- urban_case (50% approval) ---
    "smart bus stop e-ink real time schedule display public transport Serbia",
    "e-ink tourist trail wayfinding display national park autonomous solar powered",
    "e-ink municipal information kiosk city park urban outdoor smart display",
    "CMS remote content update outdoor e-ink display network city infrastructure",
    "smart city e-ink outdoor display API integration real time urban information",
]


def load_state() -> set:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return set(json.load(f).get("processed", []))
    return set()


def save_state(processed: set):
    with open(STATE_FILE, "w") as f:
        json.dump({"processed": list(processed), "updated": datetime.now().isoformat()}, f)


def get_unprocessed_files(processed: set) -> list[Path]:
    files = []
    for f in sorted(CONTENT_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in (SUPPORTED_IMAGES | SUPPORTED_VIDEOS):
            if f.name not in processed:
                files.append(f)
    return files


def convert_heic(heic_path: Path) -> Path | None:
    """Конвертирует HEIC в JPEG через ImageMagick."""
    converted = OUTPUT_DIR / (heic_path.stem + "_converted.jpg")
    if converted.exists():
        return converted
    result = subprocess.run(
        ["convert", str(heic_path), str(converted)],
        capture_output=True
    )
    return converted if result.returncode == 0 and converted.exists() else None


def send_telegram_notification(package_dir: Path, caption_data: dict, media_type: str = "video"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  Telegram не настроен — пропускаю уведомление")
        return False

    try:
        import requests

        caption = (
            f"{'📹 Новый Reel' if media_type == 'video' else '📷 Новое фото'} для одобрения\n\n"
            f"SR: {caption_data['caption_sr'][:200]}\n\n"
            f"EN: {caption_data['caption_en'][:200]}\n\n"
            f"Теги: {' '.join(caption_data['hashtags'][:10])}\n\n"
            f"Папка: {package_dir.name}"
        )

        if media_type == "photo":
            photo_path = next(package_dir.glob("post.*"), None)
            if not photo_path:
                print("  Файл фото не найден в пакете")
                return False
            with open(photo_path, "rb") as pf:
                resp = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                    files={"photo": pf},
                    timeout=60,
                )
        else:
            video_path = next(package_dir.glob("reel*"), None)
            if not video_path:
                print("  Файл reel.mp4 не найден в пакете")
                return False
            with open(video_path, "rb") as vf:
                resp = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "supports_streaming": True},
                    files={"video": vf},
                    timeout=180,
                )

        if resp.ok:
            print("  Отправлено в Telegram ✓")
            return True
        else:
            print(f"  Telegram ошибка: {resp.text[:200]}")
            return False

    except Exception as e:
        print(f"  Telegram ошибка: {e}")
        return False


def process_file(file_path: Path, mode: str, content_type: str | None = None,
                  project: str | None = None, ai_illustration: bool = False) -> dict | None:
    from generate_reel import (
        generate_caption, generate_media_with_fallback,
        save_post_package, save_image_package,
        pick_esg_scene_prompt,
    )

    print(f"\n📸 Обрабатываю: {file_path.name}")

    ext = file_path.suffix.lower()

    # Конвертация HEIC → JPEG для передачи в caption LLM
    if ext == ".heic":
        try:
            converted = convert_heic(file_path)
        except FileNotFoundError:
            print(f"  Пропускаю HEIC (нет imagemagick): {file_path.name}")
            return None
        if not converted:
            print(f"  Пропускаю HEIC (ошибка конвертации): {file_path.name}")
            return None
        file_path = converted
        ext = ".jpg"

    image_for_gpt = file_path if ext in SUPPORTED_IMAGES else None

    try:
        caption_data = generate_caption(
            image_path=image_for_gpt,
            content_type_hint=content_type,
            project_hint=project,
        )
    except RuntimeError as e:
        print(f"  Не удалось сгенерировать caption: {e}, пропускаю")
        return None

    video_prompt = pick_esg_scene_prompt(caption_data)

    media_path, media_type = generate_media_with_fallback(
        video_prompt=video_prompt,
        source_image=image_for_gpt,
        preferred_mode=mode,
        caption_data=caption_data,
    )

    if not media_path or not media_path.exists():
        print(f"  ❌ Все генераторы недоступны — отправляю comic-запрос в Telegram")
        from generate_reel import send_comic_prompt_to_telegram
        send_comic_prompt_to_telegram(caption_data, video_prompt)
        return None

    if media_type == "photo":
        package_dir = save_image_package(media_path, caption_data, str(file_path))
    else:
        package_dir = save_post_package(media_path, caption_data, str(file_path))

    meta_path = package_dir / "post_meta.json"
    with open(meta_path) as f:
        meta = json.load(f)
    meta["source_file"] = file_path.name
    meta["media_type"] = media_type
    if content_type:
        meta["content_type"] = content_type
    if ai_illustration:
        meta["ai_illustration"] = True
        meta["caption_en"] = meta.get("caption_en", "") + "\n\n📸 Illustration — real installation photos coming soon."
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {"package_dir": package_dir, "caption_data": caption_data, "media_type": media_type}


def process_topic(topic: str, mode: str, content_type: str | None = None,
                   project: str | None = None, ai_illustration: bool = False) -> dict | None:
    """Генерирует контент по теме.

    Для comparison/eco_fact/urban_case — идёт напрямую в AI-генерацию (без реального фото).
    Эти типы имеют высокий approval rate именно в AI-режиме (comparison 75%, urban_case 50%).
    Реальное фото для них только мешает — агент пытается сделать Ken Burns из случайного
    снимка который может не показывать продукт.
    """
    from generate_reel import (
        generate_caption, generate_media_with_fallback,
        save_post_package, save_image_package,
        _pick_real_photo, pick_esg_scene_prompt,
    )

    # Типы с высоким AI approval rate — не используем случайные фото из /content/
    AI_PREFERRED_TYPES = {"comparison", "eco_fact", "urban_case"}

    if content_type in AI_PREFERRED_TYPES:
        print(f"\n💡 AI-тема [{content_type}]: {topic[:60]}")
        source_for_caption = None
        source_for_media = None
    else:
        # Для остальных типов — реальное фото как основа
        real_photo = _pick_real_photo()
        if real_photo:
            print(f"\n📸 Реальное фото [{content_type}]: {real_photo.name}")
            source_for_caption = real_photo
            source_for_media = real_photo
        else:
            print(f"\n💡 Тема: {topic[:60]}")
            source_for_caption = None
            source_for_media = None

    try:
        caption_data = generate_caption(
            image_path=source_for_caption,
            topic=topic if not source_for_caption else None,
            content_type_hint=content_type,
            project_hint=project,
        )
    except RuntimeError as e:
        print(f"  Не удалось сгенерировать caption: {e}")
        return None

    video_prompt = pick_esg_scene_prompt(caption_data)

    media_path, media_type = generate_media_with_fallback(
        video_prompt=video_prompt,
        source_image=source_for_media,
        preferred_mode=mode,
        caption_data=caption_data,
    )

    if not media_path or not media_path.exists():
        print("  ❌ Все генераторы недоступны — отправляю comic-запрос в Telegram")
        from generate_reel import send_comic_prompt_to_telegram
        send_comic_prompt_to_telegram(caption_data, video_prompt)
        return None

    if media_type in ("photo", "comic"):
        package_dir = save_image_package(media_path, caption_data, f"topic:{topic[:50]}")
    else:
        package_dir = save_post_package(media_path, caption_data, f"topic:{topic[:50]}")

    meta_path = package_dir / "post_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        if content_type:
            meta["content_type"] = content_type
        if ai_illustration:
            meta["ai_illustration"] = True
            meta["caption_en"] = meta.get("caption_en", "") + "\n\n📸 Illustration — real installation photos coming soon."
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    return {"package_dir": package_dir, "caption_data": caption_data, "media_type": media_type}


def process_eink_search(mode: str, limit: int, content_type: str | None = None) -> dict:
    """
    Ищет реальные фото e-ink реализаций (32" и 42"), генерирует контент на их основе.
    """
    from generate_reel import (
        search_eink_reference_photos, pick_eink_reference_photo,
        generate_caption, generate_media_with_fallback,
        save_post_package, save_image_package,
        pick_esg_scene_prompt,
    )

    print("\n🔍 Поиск реальных фото e-ink технологий...")
    photos = search_eink_reference_photos(max_per_query=3, max_total=20)
    if not photos:
        print("  ❌ Фото не найдены — проверь подключение к интернету")
        return {"generated": 0, "sent": 0, "failed": 0}

    # Темы привязанные к реальным фото e-ink с указанием размеров
    EINK_REAL_TOPICS = [
        "32 inch outdoor e-ink display real installation — EcoDisplays similar technology",
        "42 inch e-paper display outdoor urban deployment — EcoDisplays comparison",
        "e-ink outdoor display implementation smart city — EcoDisplays 32/42 inch solution",
        "electronic paper outdoor signage real photo — EcoDisplays e-ink technology",
        "e-paper display bus stop public transport — EcoDisplays 32/42 inch install",
    ]

    import random
    stats = {"generated": 0, "sent": 0, "failed": 0}
    used_photos: set[str] = set()

    for i in range(limit):
        # Берём фото которое ещё не использовали
        available = [p for p in photos if p.name not in used_photos]
        if not available:
            available = photos  # начинаем сначала

        photo = random.choice(available)
        used_photos.add(photo.name)
        topic = EINK_REAL_TOPICS[i % len(EINK_REAL_TOPICS)]
        ct = content_type or "comparison"

        print(f"\n📸 E-ink реальное фото [{i+1}/{limit}]: {photo.name}")
        print(f"   Тема: {topic[:60]}")

        try:
            caption_data = generate_caption(
                image_path=photo,
                topic=topic,
                content_type_hint=ct,
                project_hint=None,
            )
        except RuntimeError as e:
            print(f"  ❌ Caption ошибка: {e}")
            stats["failed"] += 1
            continue

        # Помечаем что это реальное фото e-ink технологий
        caption_data["eink_reference_photo"] = True
        caption_data["display_sizes"] = "32\" и 42\""

        video_prompt = pick_esg_scene_prompt(caption_data)

        media_path, media_type = generate_media_with_fallback(
            video_prompt=video_prompt,
            source_image=photo,
            preferred_mode=mode,
            caption_data=caption_data,
        )

        if not media_path or not media_path.exists():
            # Используем само найденное фото как медиа
            print("  ⚠️  Видео недоступно — используем найденное e-ink фото напрямую")
            from generate_reel import save_image_package
            package_dir = save_image_package(photo, caption_data, f"eink_search:{photo.name}")
            media_type = "photo"
        else:
            if media_type in ("photo", "comic"):
                package_dir = save_image_package(media_path, caption_data, f"eink_search:{photo.name}")
            else:
                package_dir = save_post_package(media_path, caption_data, f"eink_search:{photo.name}")

        meta_path = package_dir / "post_meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            meta["content_type"] = ct
            meta["eink_reference_photo"] = str(photo)
            meta["source_type"] = "eink_web_search"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

        stats["generated"] += 1
        sent = send_telegram_notification(package_dir, caption_data, media_type)
        if sent:
            stats["sent"] += 1
        else:
            stats["failed"] += 1

        time.sleep(2)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Ecodisplays Content Farm")
    parser.add_argument("--limit", type=int, default=3, help="Максимум файлов/тем за запуск")
    parser.add_argument("--mode", choices=["auto", "runway", "luma", "kling", "veo", "hf", "video", "photo"], default="auto",
                        help="Режим генерации (по умолчанию: auto — бесплатные сначала, затем платные, fallback на фото)")
    parser.add_argument("--reset", action="store_true", help="Сбросить список обработанных файлов")
    parser.add_argument("--topics", action="store_true", help="Генерировать без исходников — по пулу тем")
    parser.add_argument("--no-notify", action="store_true", help="Не отправлять в Telegram (approval_bot сделает это сам с кнопками)")
    parser.add_argument("--content-type", default=None,
                        help="Тип контента для слота (installation, eco_fact, behind_scenes, ...)")
    parser.add_argument("--project", default=None,
                        help="Проект для слота (djerdap, subotica, ...)")
    parser.add_argument("--source-image", default=None,
                        help="Путь к реальному фото для генерации")
    parser.add_argument("--ai-illustration", action="store_true",
                        help="Пометить пост как AI-иллюстрацию (суффикс в caption)")
    parser.add_argument("--eink-search", action="store_true",
                        help="Найти реальные фото e-ink технологий (32/42 дюйма) и генерировать контент на их основе")
    args = parser.parse_args()

    # Режим поиска реальных e-ink фото
    if args.eink_search:
        stats = process_eink_search(
            mode=args.mode,
            limit=args.limit,
            content_type=getattr(args, "content_type", None),
        )
        print(f"\n✅ E-ink поиск завершён: сгенерировано={stats['generated']}, "
              f"отправлено={stats['sent']}, ошибок={stats['failed']}")
        return

    if args.reset:
        STATE_FILE.unlink(missing_ok=True)
        print("Список обработанных файлов сброшен")
        return

    # Режим генерации по темам — не нужны исходники
    if args.topics:
        topics_state_file = OUTPUT_DIR / "processed_topics.json"
        used = set()
        if topics_state_file.exists():
            with open(topics_state_file) as f:
                used = set(json.load(f).get("used", []))
        available = [t for t in TOPIC_POOL if t not in used]
        if not available:
            # Все темы использованы — начинаем сначала
            used = set()
            available = list(TOPIC_POOL)
            print("Все темы использованы — начинаю новый цикл")

        stats = {"generated": 0, "sent": 0, "failed_video": 0, "failed_telegram": 0}
        for topic in available[:args.limit]:
            result = process_topic(topic, args.mode,
                                   content_type=getattr(args, "content_type", None),
                                   project=getattr(args, "project", None),
                                   ai_illustration=getattr(args, "ai_illustration", False))
            if not result:
                stats["failed_video"] += 1
                continue
            stats["generated"] += 1
            # Всегда помечаем тему как использованную — Telegram-уведомление опционально
            used.add(topic)
            with open(topics_state_file, "w") as f:
                json.dump({"used": list(used), "updated": datetime.now().isoformat()}, f)
            if not args.no_notify:
                mtype = result.get("media_type", "video")
                sent = send_telegram_notification(result["package_dir"], result["caption_data"], mtype)
                if sent:
                    stats["sent"] += 1
                else:
                    stats["failed_telegram"] += 1
                    print(f"  ⚠️  Telegram не принял {'видео' if mtype == 'video' else 'фото'}")
            time.sleep(2)

        print(f"\n✅ Готово. Статистика: сгенерировано={stats['generated']}, отправлено={stats['sent']}, "
              f"ошибок медиа={stats['failed_video']}, ошибок Telegram={stats['failed_telegram']}")
        return

    processed = load_state()
    files = get_unprocessed_files(processed)

    if not files:
        print("⚠️  Новые пакеты не найдены — возможно все файлы уже обработаны")
        print("    Запусти с флагом --topics для генерации по темам без исходников:")
        print("    python3 content_farm.py --topics --limit 3")
        return

    print(f"Найдено {len(files)} необработанных файлов. Обрабатываю до {args.limit}...")

    stats = {"generated": 0, "sent": 0, "failed_media": 0, "failed_telegram": 0}

    source_image = Path(args.source_image) if getattr(args, "source_image", None) else None
    if source_image and source_image.exists():
        files = [source_image] + [f for f in files if f != source_image]

    for file_path in files[:args.limit]:
        result = process_file(file_path, args.mode,
                              content_type=getattr(args, "content_type", None),
                              project=getattr(args, "project", None),
                              ai_illustration=getattr(args, "ai_illustration", False))
        if not result:
            stats["failed_media"] += 1
            print(f"  Файл {file_path.name} пропущен (все генераторы недоступны)")
            continue

        stats["generated"] += 1
        processed.add(file_path.name)
        save_state(processed)
        if not args.no_notify:
            mtype = result.get("media_type", "video")
            sent = send_telegram_notification(result["package_dir"], result["caption_data"], mtype)
            if sent:
                stats["sent"] += 1
            else:
                stats["failed_telegram"] += 1
                print(f"  ⚠️  Telegram не принял {'видео' if mtype == 'video' else 'фото'} для {file_path.name}")

        time.sleep(2)

    print(f"\n✅ Готово. Пакеты постов в: {OUTPUT_DIR}")
    print(f"   Статистика: сгенерировано={stats['generated']}, отправлено={stats['sent']}, "
          f"ошибок медиа={stats['failed_media']}, ошибок Telegram={stats['failed_telegram']}")
    if stats["failed_telegram"] > 0:
        print("   Для повтора отправки запусти скрипт снова — файлы с ошибкой Telegram будут обработаны заново")
    print("Проверь output/ папки и опубликуй одобренные посты")


if __name__ == "__main__":
    main()
