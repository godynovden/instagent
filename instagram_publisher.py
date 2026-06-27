"""
Instagram Publisher — публикация Reels через Meta Graph API.

Требования:
  - Instagram Business или Creator аккаунт
  - Привязанная Facebook страница
  - Долгосрочный Page Access Token (60 дней)

Получить токен: https://developers.facebook.com/tools/explorer
Нужные разрешения: instagram_basic, instagram_content_publish, pages_read_engagement

Запуск (тест):
  python3 instagram_publisher.py --package output/20260527_112418_Ecodisplays_Eink_Totem
"""

import os
import sys
import json
import time
import tempfile
import subprocess
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

IG_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
IG_USER_ID = os.getenv("INSTAGRAM_USER_ID")
GRAPH_API = "https://graph.facebook.com/v21.0"


def upload_video_to_hosting(video_path: Path) -> str | None:
    """
    Загружает видео на временный хостинг (0x0.st) и возвращает публичный URL.
    Instagram требует публично доступный URL для загрузки видео.
    """
    print(f"  Загружаю видео на временный хостинг...")
    try:
        with open(video_path, "rb") as f:
            resp = requests.post(
                "https://0x0.st",
                files={"file": (video_path.name, f, "video/mp4")},
                timeout=120
            )
        if resp.ok and resp.text.startswith("https://"):
            url = resp.text.strip()
            print(f"  Видео загружено: {url}")
            return url
        else:
            print(f"  Ошибка хостинга: {resp.text[:100]}")
    except Exception as e:
        print(f"  Ошибка загрузки: {e}")

    # Fallback: catbox.moe
    try:
        print("  Пробую catbox.moe...")
        with open(video_path, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (video_path.name, f, "video/mp4")},
                timeout=120
            )
        if resp.ok and "https://" in resp.text:
            url = resp.text.strip()
            print(f"  Видео загружено: {url}")
            return url
    except Exception as e:
        print(f"  catbox.moe ошибка: {e}")

    return None


def create_reels_container(video_url: str, caption: str) -> str | None:
    """Создаёт медиа-контейнер для Reel."""
    print(f"  Создаю контейнер Instagram Reel...")
    resp = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=60
    )
    if not resp.ok:
        print(f"  Ошибка создания контейнера: {resp.status_code} {resp.text[:200]}")
        return None

    container_id = resp.json().get("id")
    print(f"  Контейнер создан: {container_id}")
    return container_id


def wait_for_container(container_id: str, max_wait: int = 300) -> bool:
    """Ждёт пока Instagram обработает видео."""
    print(f"  Жду обработки видео Instagram...")
    for i in range(max_wait // 10):
        time.sleep(10)
        resp = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_ACCESS_TOKEN},
            timeout=15
        )
        if not resp.ok:
            continue
        data = resp.json()
        status = data.get("status_code", data.get("status", ""))
        print(f"  Статус: {status} ({i+1}/{max_wait//10})")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            print(f"  Ошибка обработки: {data}")
            return False
    print("  Таймаут ожидания обработки")
    return False


def publish_container(container_id: str) -> str | None:
    """Публикует готовый контейнер."""
    print(f"  Публикую Reel...")
    resp = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=30
    )
    if not resp.ok:
        print(f"  Ошибка публикации: {resp.status_code} {resp.text[:200]}")
        return None

    media_id = resp.json().get("id")
    print(f"  ✅ Reel опубликован! Media ID: {media_id}")
    return media_id


def publish_package(package_dir: Path) -> str | None:
    """Полный цикл публикации пакета поста в Instagram."""
    if not IG_ACCESS_TOKEN or not IG_USER_ID:
        print("  INSTAGRAM_ACCESS_TOKEN или INSTAGRAM_USER_ID не заданы в .env")
        return None

    meta_file = package_dir / "post_meta.json"
    video_file = package_dir / "reel.mp4"

    if not meta_file.exists() or not video_file.exists():
        print(f"  Пакет неполный: {package_dir}")
        return None

    meta = json.loads(meta_file.read_text())

    # Формируем caption (Serbian + English + hashtags)
    caption = (
        f"{meta['caption_sr']}\n\n"
        f"{meta['caption_en']}\n\n"
        f"{' '.join(meta['hashtags'])}"
    )
    # Instagram лимит — 2200 символов
    if len(caption) > 2200:
        caption = caption[:2197] + "..."

    # 1. Загружаем видео на хостинг
    video_url = upload_video_to_hosting(video_file)
    if not video_url:
        print("  Не удалось загрузить видео на хостинг")
        return None

    # 2. Создаём контейнер
    container_id = create_reels_container(video_url, caption)
    if not container_id:
        return None

    # 3. Ждём обработки
    if not wait_for_container(container_id):
        return None

    # 4. Публикуем
    media_id = publish_container(container_id)
    if media_id:
        # Сохраняем ID публикации в meta
        meta["instagram_media_id"] = media_id
        meta["published_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    return media_id


def check_token() -> dict | None:
    """Проверяет валидность токена и возвращает информацию об аккаунте."""
    resp = requests.get(
        f"{GRAPH_API}/{IG_USER_ID}",
        params={"fields": "username,name,followers_count", "access_token": IG_ACCESS_TOKEN},
        timeout=10
    )
    if resp.ok:
        return resp.json()
    print(f"Ошибка токена: {resp.status_code} {resp.text[:200]}")
    return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Instagram Publisher")
    parser.add_argument("--check", action="store_true", help="Проверить токен")
    parser.add_argument("--package", type=str, help="Путь к пакету поста")
    args = parser.parse_args()

    if args.check:
        info = check_token()
        if info:
            print(f"✅ Токен валиден! Аккаунт: @{info.get('username')} ({info.get('followers_count', '?')} подписчиков)")
        else:
            print("❌ Токен невалиден — нужно обновить INSTAGRAM_ACCESS_TOKEN в .env")

    elif args.package:
        pkg = Path(args.package)
        media_id = publish_package(pkg)
        if media_id:
            print(f"\n✅ Опубликовано в Instagram! ID: {media_id}")
        else:
            print("\n❌ Публикация не удалась")
    else:
        parser.print_help()
