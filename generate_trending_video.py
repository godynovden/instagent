"""
Генератор ежедневного трендового видео для Ecodisplays.

Формат: hook (3с) + ESG-факт (20с) + CTA (3с) = max 30 сек, 9:16
Озвучка: OpenAI TTS
Видео: AI-генерация через generate_reel.py pipeline (HF → Luma → Runway → Pollinations)
Субтитры: ffmpeg drawtext поверх видео

Запуск:
  python3 generate_trending_video.py              # генерирует и отправляет в Telegram
  python3 generate_trending_video.py --dry-run    # только генерирует, не отправляет
  python3 generate_trending_video.py --topic 3    # выбрать тему по индексу
  python3 generate_trending_video.py --list       # показать все темы

Cron (ежедневно в 8:00):
  0 8 * * * cd /root/Ecodisplays && python3 generate_trending_video.py >> /var/log/trending.log 2>&1
"""

import os
import sys
import json
import time
import shutil
import argparse
import subprocess
import tempfile
import textwrap
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/root/Ecodisplays/output"))
OUTPUT_DIR.mkdir(exist_ok=True)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
PUBLIC_BASE_URL = "http://146.103.111.13/ecodisplays/reels"
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")

USED_TOPICS_FILE = OUTPUT_DIR / "trending_used_topics.json"

# ─── Пул тем ──────────────────────────────────────────────────────────────────
# Каждая тема: hook (цепляющее начало) + fact (ESG-факт) + cta + scene_prompt
TRENDING_HOOKS = [
    {
        "id": "energy_111x",
        "hook": "Da li znate da LED displej troši 111 puta više struje od e-ink?",
        "fact": "EcoDisplays e-ink displej radi na samo 3 vata — manje od jedne sijalice. LED bilbord troši 333 vata. Na godišnjem nivou razlika je 2.800 kilovat-sati i hiljade evra. E-ink ekran prikazuje sadržaj bez struje — energija se troši samo pri promeni slike.",
        "cta": "Pratite @ecodisplays.rs za više ESG saveta.",
        "caption_sr": "💡 Da li znate da LED displej troši 111x više struje od e-ink?\n\nEcoDisplays radi na 3W — manje od jedne sijalice. Na godišnjem nivou to znači 2.800 kWh razlike po jednom ekranu.\n\nPametni gradovi biraju pametna rešenja. 🌱",
        "caption_en": "E-ink uses 111x less power than LED. Smart cities choose smarter screens.",
        "hashtags": ["#ecodisplays", "#einksignage", "#smartcity", "#sustainability", "#energyefficiency", "#outdoorsignage", "#greentechnology", "#urbantechnology", "#serbia", "#beograd", "#smartgradovi", "#eink", "#digitalsignage", "#ESG", "#cleanenergy"],
        "scene_prompt": "cinematic 9:16 vertical, modern Belgrade street at dusk, slim e-ink digital display on pole showing simple bold icons, warm city lights, energy-efficient green ambient glow, photorealistic movie still, no glowing screen, matte display surface",
        "voice": "nova",
        "music_hint": "calm ambient electronic, eco smart city, subtle positive energy",
    },
    {
        "id": "solar_autonomous",
        "hook": "Zamislite ekran koji radi besplatno — na sunčevu energiju.",
        "fact": "EcoDisplays outdoor displej može biti potpuno autonoman zahvaljujući solarnom panelu od 20 do 250 vati. Nema troškova struje, nema kabliranja, nema odobrenja komunalnog preduzeća. Postavljanje traje manje od jednog sata.",
        "cta": "Saznajte više na ecodisplays.rs",
        "caption_sr": "☀️ Displej koji se sam napaja sunčevom energijom.\n\nEcoDisplays outdoor ekran sa solarnim panelom 20-250W — nema strujnih troškova, nema kablova, montaža za manje od sat vremena.\n\nIdealano za parkove, turistička mesta, autobuska stajališta. 🌿",
        "caption_en": "Solar-powered e-ink display. Zero energy costs, zero cables, installed in under an hour.",
        "hashtags": ["#ecodisplays", "#solarpowered", "#smartcity", "#sustainability", "#outdoorsignage", "#greenenergy", "#eink", "#urbansolutions", "#serbia", "#pametnigrad", "#solarsignage", "#ESG", "#zerowaste", "#cleantech", "#innovation"],
        "scene_prompt": "cinematic 9:16 vertical, sunny city park, e-ink outdoor display on pole with small solar panel on top, people relaxing on benches nearby, bright daylight, matte screen clearly readable in sunlight, photorealistic, warm natural light",
        "voice": "alloy",
        "music_hint": "uplifting nature ambient, solar clean energy vibe",
    },
    {
        "id": "sunlight_readable",
        "hook": "Ovaj ekran je čitljiviji na direktnom suncu — to nije greška, to je funkcija.",
        "fact": "Dok LED i LCD ekrani postaju gotovo nevidljivi na jakom suncu, e-ink displej koristit sunčevu svetlost da bi bio jasniji. Kao novinska strana — što je svetlije, to bolje se čita. IP65 zaštita, temperaturni opseg od minus 20 do plus 60 stepeni.",
        "cta": "EcoDisplays — tehnologija koja radi kada je to najvažnije.",
        "caption_sr": "☀️ Direktno sunce? Ekran postaje jasniji!\n\nE-ink tehnologija koristi sunčevu svetlost kao prednost — ne kao problem. IP65 zaštita, -20°C do +60°C, čitljiv 24/7 sa 180° ugla gledanja.\n\nIdealano za outdoor instalacije u Srbiji. 🇷🇸",
        "caption_en": "Sunlight makes e-ink clearer, not washed out. 180° viewing angle, readable 24/7.",
        "hashtags": ["#ecodisplays", "#eink", "#outdoordisplay", "#sunlightreadable", "#smartcity", "#digitalsignage", "#IP65", "#weatherproof", "#serbia", "#urbantechnology", "#outdoorsignage", "#innovation", "#sustainability", "#pametnigrad"],
        "scene_prompt": "cinematic 9:16, harsh direct midday sunlight, e-ink outdoor display on street pole showing bold clear map/icons, person looking at screen and nodding satisfied, LCD billboard in background completely washed out, photorealistic, high contrast",
        "voice": "nova",
        "music_hint": "bright upbeat electronic, city morning energy",
    },
    {
        "id": "bus_stop_realtime",
        "hook": "Autobusko stajalište koje zna kada stiže sledeći autobus — bez struje iz mreže.",
        "fact": "EcoDisplays e-ink displej na autobuskom stajalištu prikazuje red vožnje u realnom vremenu, napaja se solarno i ažurira sadržaj na daljinu putem CMS sistema. Bez kabliranja, bez redovnog održavanja, bez potrošnih delova. Garancija deset godina.",
        "cta": "Modernizujte javni prevoz sa EcoDisplays.",
        "caption_sr": "🚌 Autobusko stajalište budućnosti — već danas.\n\nEcoDisplays e-ink displej prikazuje red vožnje u realnom vremenu, napaja se solarno i ažurira se daljinski. Bez kablova, bez održavanja.\n\nSubotica, Beograd, Đerdap — implementujemo već sada. 📍",
        "caption_en": "Real-time bus schedule display, solar powered, zero maintenance. 10-year warranty.",
        "hashtags": ["#ecodisplays", "#publictransport", "#smartcity", "#busstop", "#realtimeinformation", "#serbia", "#subotica", "#beograd", "#urbantransport", "#sustainability", "#eink", "#solarpowered", "#smartinfrastructure", "#pametnigrad"],
        "scene_prompt": "cinematic 9:16 vertical, modern bus stop in Serbian city morning light, slim e-ink display showing clean schedule board, commuters waiting, warm sunrise light, matte screen perfectly readable, photorealistic street photography style",
        "voice": "shimmer",
        "music_hint": "calm morning city ambient, light jazz electronic",
    },
    {
        "id": "zero_burn_10years",
        "hook": "Šta bi se desilo kada bi vaš ekran radio deset godina — bez ijednog kvara?",
        "fact": "EcoDisplays e-ink displej nema pozadinskog osvjetljenja, nema motora, nema delova koji se troše. Nema efekta sagorevanja ekrana. Garancija deset godina znači da instalirate jednom i zaboravite na servis. Ukupan trošak vlasništva je tri do pet puta niži od LCD ili LED alternative.",
        "cta": "Izračunajte uštedine za vaš projekat na ecodisplays.rs",
        "caption_sr": "🔧 10 godina garancije. Nula sagorevanja ekrana. Nula zamene delova.\n\nEcoDisplays e-ink nema pozadinsko osvjetljenje — nema čega da se pokvari. TCO je 3-5x niži od LCD/LED.\n\nUloži jednom, koristi deceniju. 💚",
        "caption_en": "10-year warranty, no screen burn-in, no moving parts. 3-5x lower total cost of ownership vs LED.",
        "hashtags": ["#ecodisplays", "#eink", "#10yearwarranty", "#digitalsignage", "#sustainability", "#TCO", "#smartcity", "#noburn", "#outdoorsignage", "#serbia", "#investment", "#greentechnology", "#urbansolutions", "#longterm"],
        "scene_prompt": "cinematic 9:16, time-lapse feel single frame, e-ink display on park pole with seasonal background (autumn leaves), old cracked LCD billboard next to it looking deteriorated, e-ink screen pristine and clear, photorealistic, narrative contrast",
        "voice": "onyx",
        "music_hint": "steady calm ambient, reliability and trust vibe",
    },
    {
        "id": "installation_1min",
        "hook": "Koliko vam treba vremena da instalirate digitalni ekran? Ovaj se postavlja za manje od jednog sata.",
        "fact": "EcoDisplays outdoor displej debeo je svega 32 milimetra — tanak kao ramić slike. Montira se magnetno na standardni stub bez bušenja ili betoniranja. Tim od dva čoveka može da postavi ekran za manje od sat vremena. Bez zatvaranja saobraćaja, bez dizalica.",
        "cta": "Brza instalacija, dugotrajna vrednost — EcoDisplays.",
        "caption_sr": "⚡ Digitalni ekran koji se montira za manje od sat vremena.\n\nSamo 32mm debljine, magnetna montaža na standardni stub. Tim od 2 osobe, nema betona, nema dizalica.\n\nBrza instalacija = manje troškova = više projekata. 🏗️",
        "caption_en": "32mm thin, magnetic mounting, installed in under 1 hour by a 2-person team. No drilling, no cranes.",
        "hashtags": ["#ecodisplays", "#easyinstall", "#digitalsignage", "#smartcity", "#outdoorsignage", "#serbia", "#urbantechnology", "#fastinstallation", "#eink", "#sustainability", "#innovation", "#beograd", "#infrastructure"],
        "scene_prompt": "cinematic 9:16, two technicians in hi-vis vests quickly and easily mounting slim e-ink display on street pole, slim aluminum frame 32mm, one person holding display, other securing magnets, sunny day, city street, photorealistic documentary style",
        "voice": "alloy",
        "music_hint": "energetic upbeat ambient, efficiency and speed",
    },
    {
        "id": "cms_remote_update",
        "hook": "Promenite sadržaj na sto ekrana — odjednom, sa laptopa, za trideset sekundi.",
        "fact": "EcoDisplays Cloud CMS sistem omogućava centralno upravljanje svim ekranima u mreži. Ažurirajte raspored, objave ili reklame u realnom vremenu. Puna API integracija sa vašim postojećim sistemima. WiFi, mobilna mreža ili Ethernet — ekran se bira sam.",
        "cta": "Demonstracija CMS sistema — kontaktirajte nas.",
        "caption_sr": "💻 100 ekrana, jedan klik.\n\nEcoDisplays Cloud CMS — ažurirajte sadržaj na svim ekranima u realnom vremenu. Puna API integracija, WiFi/4G/Ethernet.\n\nIdealano za gradove, transportne mreže, korporativne kampuse. 🌐",
        "caption_en": "Update 100 screens simultaneously via Cloud CMS. Full API integration, WiFi/4G/Ethernet.",
        "hashtags": ["#ecodisplays", "#CMS", "#remotecontent", "#smartcity", "#digitalsignage", "#API", "#cloudplatform", "#serbia", "#urbantechnology", "#eink", "#connectivity", "#infrastructure", "#pametnigrad", "#innovation"],
        "scene_prompt": "cinematic 9:16, person at laptop in modern office updating content on e-ink displays visible through window on street poles, map dashboard on laptop screen, city skyline in background, photorealistic corporate tech style",
        "voice": "nova",
        "music_hint": "modern tech ambient, efficiency and connectivity",
    },
    {
        "id": "tourist_trail",
        "hook": "Turistički put koji vodi — bez papirnih mapa, bez baterija, bez interneta.",
        "fact": "EcoDisplays e-ink kiosci za turistički i kulturni turizam prikazuju mape, opise i smernice trajno, bez napajanja iz mreže. Solarna autonomnost, čitljivi po suncu i u mraku uz reflektor, vandalizmu otporni aluminijumski kućišti. Idealni za nacionalne parkove i historijske centre.",
        "cta": "Turistička infrastruktura budućnosti — već danas u Srbiji.",
        "caption_sr": "🗺️ Turistički put koji ne zahteva papir, baterije ni internet.\n\nEcoDisplays e-ink kiosci za nacionalne parkove i kulturna mesta — solarni, vandalizmu otporni, čitljivi 24/7.\n\nĐerdapska klisura već koristi ovu tehnologiju. 🏔️",
        "caption_en": "Solar-powered wayfinding e-ink kiosks for national parks and heritage sites. No power lines needed.",
        "hashtags": ["#ecodisplays", "#wayfinding", "#tourism", "#nationalpark", "#djerdap", "#serbia", "#smarttourism", "#eink", "#sustainability", "#outdoorsignage", "#solarpowered", "#heritage", "#visitserbia", "#kulturniturizam"],
        "scene_prompt": "cinematic 9:16 vertical, hiking trail in Serbian national park, e-ink wayfinding kiosk showing trail map in bold clear graphics, hiker consulting the display, mountains and river in background, golden hour light, photorealistic",
        "voice": "shimmer",
        "music_hint": "nature adventure ambient, inspiring landscape vibe",
    },
    {
        "id": "comparison_lcd_cost",
        "hook": "Koliko vas košta LCD ekran koji gorite posle tri godine? Izračunajmo zajedno.",
        "fact": "Tipični LCD outdoor displej: 300 vati, trošak struje 1.500 evra godišnje, zamena panela posle tri do pet godina još 2.000 evra. EcoDisplays e-ink: 3 vata, solarna opcija bez troškova struje, garancija deset godina. Razlika za deset godina? Više od 15.000 evra po ekranu.",
        "cta": "Tražite ponudu za vaš projekat — ecodisplays.rs",
        "caption_sr": "💰 10 godina, jedna razlika: 15.000€ po ekranu.\n\nLCD outdoor: 300W, zamena svakih 3-5g, trošak struje 1.500€/god.\nEcoDisplays e-ink: 3W, solarna opcija, garancija 10 godina.\n\nMatematika je jasna. 📊",
        "caption_en": "Over 10 years: e-ink saves €15,000+ per screen vs LCD. Lower power, no replacement, longer warranty.",
        "hashtags": ["#ecodisplays", "#costcomparison", "#einkvsled", "#ROI", "#digitalsignage", "#sustainability", "#smartcity", "#outdoorsignage", "#serbia", "#investment", "#TCO", "#energysaving", "#greentechnology", "#businesscase"],
        "scene_prompt": "cinematic 9:16 vertical, split scene: left side old glowing bright LCD screen on street with visible burn marks and washed out in sun, right side slim e-ink display same location looking crisp and perfect, dramatic comparison lighting, photorealistic",
        "voice": "onyx",
        "music_hint": "confident business ambient, clear decision making",
    },
    {
        "id": "ip65_weatherproof",
        "hook": "Kiša, sneg, minus dvadeset — ovaj ekran ne može ni da primetiti.",
        "fact": "EcoDisplays outdoor displej ima IP65 sertifikat koji garantuje potpunu zaštitu od prašine i vode. Temperaturni opseg minus 20 do plus 60 stepeni Celzijusa. Kaljeno staklo na ekranu, aluminijumsko kućište debljine 32 milimetra. Vandalizmu otporni. Ne zahteva klimatizaciju ili grejanje unutar kućišta.",
        "cta": "Radite po svim vremenskim uslovima — EcoDisplays.",
        "caption_sr": "🌧️ Kiša? Sneg? Vrućina? EcoDisplays nije ni primetio.\n\nIP65 sertifikat, -20°C do +60°C, kaljeno staklo, aluminijumski oklop.\nBez klimatizacije, bez grejanja unutra.\n\nPravi outdoor displej za balkanske uslove. 🇷🇸",
        "caption_en": "IP65 rated, -20°C to +60°C, tempered glass. Built for every climate, every season.",
        "hashtags": ["#ecodisplays", "#IP65", "#weatherproof", "#outdoordisplay", "#durability", "#serbia", "#allweather", "#eink", "#smartcity", "#digitalsignage", "#robust", "#outdoor", "#balkan", "#engineering"],
        "scene_prompt": "cinematic 9:16 vertical, heavy rain in Belgrade street, e-ink display on pole perfectly readable showing clear information, raindrops sliding off tempered glass screen, dramatic rain light, person in rain coat reading display without problems, photorealistic",
        "voice": "alloy",
        "music_hint": "dramatic weather ambient, resilience and strength",
    },
]


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def load_used_topics() -> list:
    if USED_TOPICS_FILE.exists():
        try:
            return json.loads(USED_TOPICS_FILE.read_text())
        except Exception:
            pass
    return []


def save_used_topic(topic_id: str):
    used = load_used_topics()
    used.append({"id": topic_id, "date": datetime.now().isoformat()})
    # Держим только последние 30 записей (ротация)
    USED_TOPICS_FILE.write_text(json.dumps(used[-30:], ensure_ascii=False, indent=2))


def pick_topic(force_index: int | None = None) -> dict:
    """Выбирает наименее использованную тему."""
    if force_index is not None:
        return TRENDING_HOOKS[force_index % len(TRENDING_HOOKS)]

    used_ids = [u["id"] for u in load_used_topics()]
    # Фильтруем темы которые не использовались
    unused = [t for t in TRENDING_HOOKS if t["id"] not in used_ids]
    if unused:
        return unused[0]
    # Все использованы — начинаем заново с первой
    return TRENDING_HOOKS[len(used_ids) % len(TRENDING_HOOKS)]


# ─── TTS через OpenAI ─────────────────────────────────────────────────────────

def generate_voiceover(script: str, voice: str = "nova") -> Path | None:
    """
    Генерирует MP3 озвучку.
    Приоритет: OpenAI TTS → gTTS (Google, бесплатно)
    """
    import requests as req

    out_path = OUTPUT_DIR / f"voiceover_{int(time.time())}.mp3"

    # --- OpenAI TTS (качество лучше) ---
    if OPENAI_API_KEY:
        print(f"  🎙️  OpenAI TTS ({voice}): {script[:60]}...")
        resp = req.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "tts-1", "voice": voice, "input": script, "response_format": "mp3", "speed": 0.92},
            timeout=30,
        )
        if resp.ok:
            out_path.write_bytes(resp.content)
            size_kb = out_path.stat().st_size // 1024
            print(f"  ✅ TTS готово: {out_path.name} ({size_kb}KB)")
            return out_path
        else:
            print(f"  ⚠️  OpenAI TTS ошибка {resp.status_code}: {resp.text[:80]} — пробую gTTS...")

    # --- gTTS fallback (бесплатный Google TTS) ---
    # gTTS не поддерживает 'sr' — сербский читаем через hr (хорватский, похоже) или bs
    try:
        from gtts import gTTS
        has_latin_serbian = any(c in script for c in "čćđšžČĆĐŠŽ")
        # Пробуем языки по очереди: hr близок к sr фонетически
        for lang in (["hr", "bs"] if has_latin_serbian else ["en"]):
            try:
                print(f"  🎙️  gTTS ({lang}): {script[:60]}...")
                tts = gTTS(text=script, lang=lang, slow=False)
                tts.save(str(out_path))
                if out_path.exists() and out_path.stat().st_size > 5000:
                    # Нормализуем скорость через ffmpeg atempo если > 30с
                    probe = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(out_path)],
                        capture_output=True, text=True
                    )
                    import json as _json
                    dur = float(_json.loads(probe.stdout).get("format", {}).get("duration", 28))
                    if dur > 28.5:
                        tempo = min(dur / 27.0, 1.4)  # ускоряем до 140% макс
                        sped = out_path.with_suffix(".sped.mp3")
                        subprocess.run([
                            "ffmpeg", "-i", str(out_path),
                            "-filter:a", f"atempo={tempo:.3f}",
                            "-y", str(sped)
                        ], capture_output=True)
                        if sped.exists() and sped.stat().st_size > 5000:
                            out_path.unlink(missing_ok=True)
                            sped.rename(out_path)
                            print(f"  ⚡ atempo x{tempo:.2f} → вписывается в 27с")
                    size_kb = out_path.stat().st_size // 1024
                    print(f"  ✅ gTTS готово ({lang}): {out_path.name} ({size_kb}KB)")
                    return out_path
            except Exception:
                continue
    except Exception as e:
        print(f"  ❌ gTTS ошибка: {e}")

    print("  ⚠️  Озвучка недоступна — видео без звука")
    return None


# ─── ffmpeg: видео + аудио + субтитры ────────────────────────────────────────

def _wrap_subtitle(text: str, max_chars: int = 38) -> str:
    """Переносит длинные строки для субтитров."""
    lines = textwrap.wrap(text, max_chars)
    return "\\n".join(lines)


def compose_reel_with_voice(
    video_path: Path,
    audio_path: Path | None,
    topic: dict,
    output_path: Path,
) -> bool:
    """
    Финальная сборка через ffmpeg (трёхфазная, чтобы избежать filter_complex):
    1. Scale 9:16 + обрезка до 30с → tmp1
    2. Заменить/добавить аудио → tmp2
    3. Наложить субтитры через SRT файл + логотип → final
    """
    logo_path = Path("/root/Ecodisplays/image006.png")
    tmp1 = OUTPUT_DIR / f"_tmp1_{int(time.time())}.mp4"
    tmp2 = OUTPUT_DIR / f"_tmp2_{int(time.time())}.mp4"

    def cleanup(*paths):
        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

    # ── Фаза 1: scale 9:16, обрезка 30с ──────────────────────────────────────
    # Детектируем размер — если уже 1080x1920 h264, пропускаем ре-энкод
    _vprobe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams",
         "-select_streams", "v:0", str(video_path)],
        capture_output=True, text=True
    )
    import json as _json2
    _vstreams = _json2.loads(_vprobe.stdout).get("streams", [{}])
    _vs = _vstreams[0] if _vstreams else {}
    _already_ok = (
        _vs.get("width") == 1080 and _vs.get("height") == 1920
        and _vs.get("codec_name") == "h264"
        and _vs.get("pix_fmt") == "yuv420p"
    )

    if _already_ok:
        import shutil as _sh
        _sh.copy(str(video_path), str(tmp1))
        r1_ok = tmp1.exists()
    else:
        cmd1 = [
            "ffmpeg", "-i", str(video_path), "-t", "30",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "128k",
            "-y", str(tmp1),
        ]
        r1 = subprocess.run(cmd1, capture_output=True, text=True)
        r1_ok = r1.returncode == 0
        if not r1_ok:
            print(f"  ❌ Фаза 1 ошибка: {r1.stderr[-300:]}")
            cleanup(tmp1)
            return False

    # ── Фаза 2: voiceover + ducking фоновой музыки ───────────────────────────
    if audio_path and audio_path.exists():
        # Если в видео уже есть ambient музыка (track 0:a) — делаем ducking:
        # музыка -18dB под голос, голос 0dB. Иначе просто заменяем аудио.
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_streams", "-select_streams", "a",
             str(tmp1)], capture_output=True, text=True
        )
        has_bg_audio = "codec_type=audio" in probe.stdout

        # Voiceover: нормализация + fade in 0.3с / fade out 0.5с
        vo_filter = "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.3,afade=t=out:st=26:d=0.8"
        if has_bg_audio:
            # Ducking: bg музыка -85% под голос + fade
            cmd2 = [
                "ffmpeg",
                "-i", str(tmp1),
                "-i", str(audio_path),
                "-filter_complex",
                f"[0:a]volume=0.12,afade=t=in:d=1.0,afade=t=out:st=26:d=1.5[bg];"
                f"[1:a]{vo_filter}[vo];"
                "[bg][vo]amix=inputs=2:duration=shortest:weights=1 3[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-y", str(tmp2),
            ]
        else:
            cmd2 = [
                "ffmpeg",
                "-i", str(tmp1),
                "-i", str(audio_path),
                "-filter_complex", f"[1:a]{vo_filter}[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-y", str(tmp2),
            ]

        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        if r2.returncode != 0:
            print(f"  ⚠️  Фаза 2 ошибка (аудио): {r2.stderr[-200:]} — продолжаю без voiceover")
            shutil.copy(tmp1, tmp2)
        cleanup(tmp1)
    else:
        tmp1.rename(tmp2)

    # ── Фаза 3: SRT субтитры + логотип → финал ───────────────────────────────
    hook_text = topic["hook"][:70]
    # Факт разбиваем на чанки по ~60 символов для субтитров
    fact_text = topic.get("fact", "")
    fact_chunks = textwrap.wrap(fact_text, 65)
    cta_text = topic["cta"][:70]

    srt_path = OUTPUT_DIR / f"_subs_{int(time.time())}.srt"
    srt_lines = []
    idx = 1

    # Hook: 0-5с
    srt_lines.append(f"{idx}\n00:00:00,000 --> 00:00:05,000\n{hook_text}\n")
    idx += 1

    # Факт: 5-25с — делим поровну между чанками
    if fact_chunks:
        n = len(fact_chunks)
        chunk_duration = 20.0 / n
        for i, chunk in enumerate(fact_chunks):
            start = 5.0 + i * chunk_duration
            end = start + chunk_duration - 0.2
            def _ts(s):
                m = int(s) // 60; sec = s - m*60
                return f"00:{m:02d}:{sec:06.3f}".replace(".", ",")
            srt_lines.append(f"{idx}\n{_ts(start)} --> {_ts(end)}\n{chunk}\n")
            idx += 1

    # CTA: 25-30с
    srt_lines.append(f"{idx}\n00:00:25,000 --> 00:00:30,000\n{cta_text}\n")

    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

    # subtitles filter с принудительным шрифтом
    srt_filter = f"subtitles={srt_path}:force_style='FontSize=16,PrimaryColour=&H99ffffff,OutlineColour=&H66000000,Outline=1,Shadow=0,Bold=0,Alignment=2,MarginV=25'"

    if logo_path.exists():
        cmd3 = [
            "ffmpeg",
            "-i", str(tmp2),
            "-i", str(logo_path),
            "-filter_complex",
            f"[0:v]{srt_filter}[vsub];[1:v]scale=iw*0.18:-1[logo];[vsub][logo]overlay=W-w-30:H-h-30[vout]",
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "128k",
            "-y", str(output_path),
        ]
    else:
        cmd3 = [
            "ffmpeg", "-i", str(tmp2),
            "-vf", srt_filter,
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "copy",
            "-y", str(output_path),
        ]

    print(f"  🎬 Собираю финальный Reel (субтитры + лого)...")
    r3 = subprocess.run(cmd3, capture_output=True, text=True)
    cleanup(tmp2, srt_path)

    if r3.returncode != 0:
        print(f"  ❌ Фаза 3 ошибка:\n{r3.stderr[-400:]}")
        return False

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  ✅ Reel готов: {output_path.name} ({size_mb:.1f}MB)")
    return True


# ─── Генерация видео ──────────────────────────────────────────────────────────

def generate_ai_video(topic: dict) -> Path | None:
    """Генерирует AI-видео через существующий пайплайн generate_reel.py."""
    sys.path.insert(0, "/root/Ecodisplays")
    try:
        from generate_reel import generate_media_with_fallback
    except ImportError as e:
        print(f"  ❌ Не могу импортировать generate_reel: {e}")
        return None

    caption_data = {
        "content_type": "comparison",
        "post_title": topic["id"],
        "caption_sr": topic["caption_sr"],
        "caption_en": topic["caption_en"],
        "hashtags": topic["hashtags"],
        "video_prompt": topic["scene_prompt"],
        "music_hint": topic.get("music_hint", "ambient electronic eco city"),
    }

    print(f"  🎥 Генерирую AI-видео: {topic['scene_prompt'][:80]}...")
    video_path, media_type = generate_media_with_fallback(
        video_prompt=topic["scene_prompt"],
        source_image=None,
        preferred_mode="auto",
        caption_data=caption_data,
    )

    if video_path and video_path.exists():
        print(f"  ✅ AI-видео готово: {video_path.name} ({media_type})")
        return video_path
    else:
        print(f"  ❌ AI-видео не сгенерировалось")
        return None


# ─── Пакет и отправка ─────────────────────────────────────────────────────────

def save_trending_package(reel_path: Path, topic: dict) -> Path:
    """Сохраняет пакет трендового видео в OUTPUT_DIR."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"trending_{topic['id']}"[:40]
    package_dir = OUTPUT_DIR / f"{ts}_{slug}"
    package_dir.mkdir(exist_ok=True)

    shutil.copy(reel_path, package_dir / "reel.mp4")

    meta = {
        "generated_at": datetime.now().isoformat(),
        "source": "trending_agent",
        "status": "pending_approval",
        "is_trending": True,
        "topic_id": topic["id"],
        "hook": topic["hook"],
        "cta": topic["cta"],
        "post_title": topic["id"],
        "caption_sr": topic["caption_sr"],
        "caption_en": topic["caption_en"],
        "hashtags": topic["hashtags"],
        "content_type": "trending_video",
    }
    (package_dir / "post_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    caption_text = (
        f"{topic['caption_sr']}\n\n"
        f"{topic['caption_en']}\n\n"
        f"{' '.join(topic['hashtags'])}"
    )
    (package_dir / "caption.txt").write_text(caption_text, encoding="utf-8")

    print(f"\n✅ Пакет сохранён: {package_dir.name}")
    return package_dir


def send_for_approval(package_dir: Path, topic: dict):
    """Отправляет видео в Telegram для одобрения."""
    import requests

    video_path = package_dir / "reel.mp4"
    if not video_path.exists():
        print(f"  ❌ Нет видео: {video_path}")
        return

    caption = (
        f"🎬 *Трендовое видео* — `{topic['id']}`\n\n"
        f"*Hook:* {topic['hook'][:100]}\n\n"
        f"*Caption SR:* {topic['caption_sr'][:150]}..."
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Опубликовать в Instagram", "callback_data": f"approve:{package_dir.name}"},
            {"text": "❌ Пропустить", "callback_data": f"skip:{package_dir.name}"},
        ]]
    }

    print(f"  📤 Отправляю в Telegram: {package_dir.name}")
    with open(video_path, "rb") as f:
        resp = requests.post(
            f"{TG_API}/sendVideo",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "Markdown",
                "reply_markup": json.dumps(keyboard),
                "supports_streaming": "true",
            },
            files={"video": f},
            timeout=120,
        )

    if resp.ok:
        file_id = resp.json().get("result", {}).get("video", {}).get("file_id", "")
        print(f"  ✅ Отправлено в Telegram (file_id: {file_id[:20]}...)")

        # Сохраняем file_id в sent_to_telegram.json (как другие пакеты)
        sent_log = OUTPUT_DIR / "sent_to_telegram.json"
        sent = {}
        if sent_log.exists():
            try:
                sent = json.loads(sent_log.read_text())
            except Exception:
                pass
        sent[package_dir.name] = {
            "file_id": file_id,
            "status": "pending",
            "sent_at": datetime.now().isoformat(),
            "is_trending": True,
        }
        sent_log.write_text(json.dumps(sent, ensure_ascii=False, indent=2))
    else:
        print(f"  ❌ Ошибка Telegram: {resp.status_code} {resp.text[:200]}")


# ─── Главный пайплайн ─────────────────────────────────────────────────────────

def run(force_topic_index: int | None = None, dry_run: bool = False, force_source: str | None = None):
    print(f"\n{'='*60}")
    print(f"  EcoDisplays — Трендовое видео [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print(f"{'='*60}\n")

    topic = pick_topic(force_topic_index)
    print(f"📌 Тема: {topic['id']}")
    print(f"   Hook: {topic['hook'][:80]}...\n")

    # Шаг 1: Озвучка
    full_script = f"{topic['hook']} {topic['fact']} {topic['cta']}"
    audio_path = generate_voiceover(full_script, voice=topic.get("voice", "nova"))

    # Шаг 2: видео — force_source → AI → реальное видео → multi-photo slideshow
    raw_video = None
    if force_source:
        src = Path(force_source)
        if src.exists():
            print(f"  📹 Источник задан вручную: {src.name}")
            raw_video = src
        else:
            print(f"  ❌ Файл не найден: {force_source}")
            return None

    if not raw_video:
        raw_video = generate_ai_video(topic)

    if not raw_video:
        # Fallback 1: реальные видео из /content/
        content_dir = Path("/root/Ecodisplays/content")
        real_videos = sorted(content_dir.glob("*.mp4")) + sorted(content_dir.glob("*.MP4"))
        if real_videos:
            import random
            chosen = random.choice(real_videos)
            print(f"  📹 Fallback: реальное видео {chosen.name}")
            raw_video = chosen

    if not raw_video:
        # Fallback 2: multi-photo slideshow из реальных фото
        sys.path.insert(0, "/root/Ecodisplays")
        try:
            from generate_reel import create_multi_photo_reel, create_lavfi_motion_reel
            content_dir = Path("/root/Ecodisplays/content")
            photos = list(content_dir.glob("*.jpg")) + list(content_dir.glob("*.JPG")) + list(content_dir.glob("*.jpeg"))
            if photos:
                import random
                chosen_photos = random.sample(photos, min(3, len(photos)))
                print(f"  🖼  Fallback: multi-photo из {len(chosen_photos)} реальных фото")
                raw_video = create_multi_photo_reel(chosen_photos, duration=28)
            if not raw_video:
                print("  🌊 Fallback: lavfi animated gradient")
                raw_video = create_lavfi_motion_reel(duration=28)
        except Exception as e:
            print(f"  ⚠️  Fallback ошибка: {e}")

    if not raw_video:
        print("  ❌ Видео не сгенерировалось — прерываю")
        return None

    # Получаем длительность видео
    _probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(raw_video)],
        capture_output=True, text=True
    )
    import json as _json
    _dur = float(_json.loads(_probe.stdout).get("format", {}).get("duration", 28))

    if _dur < 27.0:
        # Растягиваем до 28с — всегда ре-энкодим (совместимость с HEVC/любым кодеком)
        looped = OUTPUT_DIR / f"_looped_{int(time.time())}.mp4"
        subprocess.run([
            "ffmpeg", "-stream_loop", "-1", "-i", str(raw_video),
            "-t", "28",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-an", "-y", str(looped),
        ], capture_output=True)
        if looped.exists() and looped.stat().st_size > 10_000:
            if not str(raw_video).startswith("/root/Ecodisplays/content"):
                raw_video.unlink(missing_ok=True)
            raw_video = looped

    # Шаг 3: Финальная сборка
    final_path = OUTPUT_DIR / f"trending_final_{int(time.time())}.mp4"
    ok = compose_reel_with_voice(raw_video, audio_path, topic, final_path)

    # Cleanup временных файлов (не удаляем оригинальный force_source)
    _is_original_source = force_source and str(raw_video) == str(Path(force_source))
    if not _is_original_source and raw_video.exists():
        raw_video.unlink(missing_ok=True)
    if audio_path and audio_path.exists():
        audio_path.unlink(missing_ok=True)

    if not ok or not final_path.exists():
        print("  ❌ Финальная сборка не удалась")
        return None

    # Шаг 4: Сохраняем пакет
    package_dir = save_trending_package(final_path, topic)
    final_path.unlink(missing_ok=True)

    # Отмечаем тему как использованную
    save_used_topic(topic["id"])

    if dry_run:
        print(f"\n🧪 Dry-run: пакет сохранён но НЕ отправлен в Telegram")
        print(f"   Путь: {package_dir}")
        return package_dir

    # Шаг 5: Отправляем в Telegram
    send_for_approval(package_dir, topic)
    print(f"\n🎉 Готово! Жди одобрения в Telegram.")
    return package_dir


def main():
    parser = argparse.ArgumentParser(description="Генератор трендового видео Ecodisplays")
    parser.add_argument("--dry-run", action="store_true", help="Не отправлять в Telegram")
    parser.add_argument("--topic", type=int, default=None, help="Индекс темы (0-N)")
    parser.add_argument("--list", action="store_true", help="Показать все темы")
    parser.add_argument("--source", type=str, default=None, help="Путь к готовому видео (пропустить AI-генерацию)")
    args = parser.parse_args()

    if args.list:
        print(f"\n📋 Темы ({len(TRENDING_HOOKS)} шт):\n")
        used = [u["id"] for u in load_used_topics()]
        for i, t in enumerate(TRENDING_HOOKS):
            status = "✅" if t["id"] in used else "⭕"
            print(f"  {i:2d}. {status} [{t['id']}]")
            print(f"       {t['hook'][:70]}...")
        return

    run(force_topic_index=args.topic, dry_run=args.dry_run, force_source=args.source)


if __name__ == "__main__":
    main()
