# EcoDisplays Content Agent

Автоматизация Instagram-контента для **EcoDisplays** — e-ink наружных дисплеев
(32"/42", IP65, на солнечных батареях, 10–20× меньше энергии, чем LCD).

Агент генерирует посты (изображения/Reels + подписи), отправляет их на одобрение
в Telegram и публикует в Instagram. Целевые рынки: Залив (Дубай/ОАЭ) и юг Европы /
Средиземноморье; сербская локальная база — вторична.

## Состав

| Файл | Назначение |
|---|---|
| `media_bot.py` | Ежедневный бот тем дня (`--daily-prompt`), ротация `DAILY_TOPICS`, генерация видео/подписи |
| `generate_reel.py` | Генерация Reels + двуязычных подписей (EN основной / SR короткий), image/video промпты |
| `approval_bot.py` | Telegram-бот одобрения: предпросмотр, регенерация, правка текста, публикация в Make/Instagram |
| `view_tracker.py` | Трекинг просмотров постов, обратная связь по качеству |
| `instagram_publisher.py` | Публикация в Instagram через Graph API |
| `content_calendar.py` | Контент-календарь / планирование |
| `content_farm.py` | Пакетная обработка медиа из `content/` |
| `generate_comic.py`, `generate_comic_video.py` | Генерация комикс-контента |
| `generate_trending_video.py` | Видео по трендовым форматам |

## Установка

```bash
pip install -r requirements.txt
cp .env.example .env   # заполнить своими ключами
```

## Переменные окружения

См. `.env.example`. Минимум для работы: `OPENAI_API_KEY` (или `OPENROUTER_API_KEY`),
`GOOGLE_API_KEY` (Veo для видео), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`,
`INSTAGRAM_ACCESS_TOKEN` + `INSTAGRAM_USER_ID`.

Секреты хранятся **только** в `.env` (в git не попадают).

## Запуск

```bash
# Тема дня (обычно по cron 2× в сутки)
python3 media_bot.py --daily-prompt

# Telegram-бот одобрения (демон)
python3 approval_bot.py
```

Пример cron:

```cron
0 9  * * * cd /path/to/repo && python3 media_bot.py --daily-prompt >> media_bot.log 2>&1
0 15 * * * cd /path/to/repo && python3 media_bot.py --daily-prompt >> media_bot.log 2>&1
```

## Примечания

- Генерёнка (`output/`, `content/`), логи и runtime-состояние (`*.json`-стейты)
  в репозиторий не входят — см. `.gitignore`.
- `DAILY_TOPICS` в `media_bot.py` несут «ДНК поста-победителя»: живые люди + реальный
  монтаж, трансформация, документальность, медленный zoom-out. Локации — Дубай/Залив
  и Средиземноморье; 2 сербские сцены оставлены в ротации.
