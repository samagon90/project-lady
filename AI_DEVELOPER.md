# 🤖 AI-разработчику: как доработать бота «Лилит»

*Этот файл — инструкция для ИИ-ассистента (JanatorLLM, Claude, GPT и т.п.),
которому передают проект на доработку. Прочитай его ПЕРВЫМ, затем
ознакомься с кодом по ссылкам ниже.*

---

## 1. Что это за проект

Telegram-бот «Лилит» — виртуальная девушка-компаньон (18+):
- **Текст**: локальная LLM через Ollama (модель задаётся в `.env`, `LLM_MODEL`);
- **Изображения**: локальный ComfyUI (workflow в `workflows/`, checkpoint в `.env`);
- **Голос**: локальный Piper TTS (конвертация ffmpeg);
- **Память**: SQLite/PostgreSQL + семантический поиск (векторный индекс);
- **Telegram Mini App**: визуальная новелла (аватар Лилит с эмоциями).

**Стек:** Python 3.12+, aiogram 3, SQLAlchemy 2 async, Alembic, aiohttp,
Pydantic Settings, httpx. Всё бесплатное и локальное.

**Версия:** `APP_VERSION` в `src/config.py`.

---

## 2. Структура (карта для быстрого входа)

```
src/
  main.py                  # точка входа: миграции, бот, Mini App, воркеры
  config.py                # ВСЕ настройки (.env) — Pydantic Settings
  prompts.py               # загрузка промптов + инструкции режимов
  utils.py                 # утилиты (JSON, safe_filename, CJK-детект)
  miniapp_server.py        # Telegram Mini App: aiohttp, initData-валидация,
                           #   /api/me, /api/settings, /api/gallery, /api/memory,
                           #   /api/avatar (эмоции), /api/chat (прокси)
  bot/
    di.py                  # DI-контейнер AppContext (все сервисы)
    middlewares.py         # защита групп, rate limit, регистрация
    keyboards.py           # inline-клавиатуры
    states.py              # FSM
    handlers/
      common.py            # /start, /help, /app, /cancel, /version
      consent.py           # онбординг: age gate 18+, согласия
      commands.py          # /profile, /settings, /mode, /voice, /photo,
                           #   /style, /avatar, /memory, /reset, /forget_me
      chat.py              # ГЛАВНЫЙ диалог: эмоции-аватары, переодевание,
                           #   манера речи, распознавание «нарисуй/покажи»
  services/
    chat.py                # диалог: контекст -> LLM -> ответ (+ авто-фиксы)
    memory.py              # долговременная память (факты, семантика, суммаризация)
    image.py               # генерация: модерация -> промпт -> очередь -> ComfyUI
    tts.py                 # голос: Piper -> OGG/Opus
    moderation.py          # блоклисты RU/EN + LLM-судья + is_adult_request
    consent.py             # age gate, согласия (базовое + NSFW)
    audit.py               # журнал безопасности (без текста переписки)
    storage.py             # временные файлы (UUID), очистка
  providers/
    base.py                # абстрактные интерфейсы (LLM/Image/TTS/Embeddings)
    ollama.py              # Ollama: /api/chat, /api/embed
    comfyui.py             # ComfyUI: workflow из JSON, инжекция значений
    piper.py               # Piper TTS
    embeddings.py          # векторный индекс (numpy/FAISS)
  workers.py               # очередь генерации, очистка, проактивные сообщения
  database/
    models.py              # 10 моделей (User, Consent, Preferences, Message...)
    repositories.py        # доступ к данным (всегда WHERE telegram_user_id)
    base.py                # движок/сессии
prompts/
  persona_lilith.md        # ХАРАКТЕР Лилит (главный файл личности)
  character_sheet.md       # внешность/наряд для генерации картинок
  system.md                # системный промпт (пол, живость, свобода)
  image_prompt.md          # модуль превращения запроса в промпт ComfyUI
  moderation.md            # промпт LLM-судьи
  safety_rules.md          # правила безопасности
  extract_facts.md         # извлечение фактов для памяти
  summarize.md             # суммаризация диалогов
workflows/                 # ComfyUI JSON (sd15 с hi-res fix, sdxl, ipadapter)
miniapp/                   # фронтенд Mini App (HTML/JS/CSS новеллы)
assets/emotions/           # аватары Лилит: 23 эмоции + lingerie/ + stage/
colab/                     # ноутбуки автозапуска (Colab/Kaggle)
tests/                     # pytest (93 теста)
migrations/                # Alembic
```

---

## 3. Ключевые механики (что где менять)

### Личность Лилит
- **`prompts/persona_lilith.md`** — характер: игривая госпожа, хвостики,
  свобода общения, живость, женский род (СТРОГО).
- **`prompts/system.md`** — системный промпт: «ты — женщина» (жёсткий блок),
  возможности, режимы.
- **`src/prompts.py`** — инструкции режимов (0-3) и загрузка файлов.
- **`src/bot/handlers/chat.py`** — распознавание намерений («покажи себя»,
  «переоденься», «говори ...»), эмоции-аватары к ответам.

### Эмоции и аватары
- Файлы: `assets/emotions/lilith_{emotion}.png` (+ `_anime`, `lingerie/`, `stage/`).
- Список эмоций: `src/miniapp_server.py` (allowed), `miniapp/app.js` (labels).
- Детектор эмоций по тексту: `src/bot/handlers/chat.py` (`_detect_reply_emotion`),
  `src/miniapp_server.py` (`_detect_emotion_and_stage`).

### Генерация картинок
- `src/services/image.py` — модерация → `_build_image_prompt` (LLM + fallback
  с переводом RU→EN) → очередь → ComfyUI.
- `src/providers/comfyui.py` — инжекция в workflow по title узлов;
  авто-подстановка checkpoint; референс IPAdapter.
- `workflows/comfyui_lilith_sd15.json` — двухпроходный hi-res fix.

### Mini App (визуальная новелла)
- `src/miniapp_server.py` — бэкенд (валидация initData через HMAC от токена!).
- `miniapp/index.html`, `app.js`, `style.css` — фронтенд: аватар по центру,
  меняется по диалогу, кнопки «В белье», вкладки (настройки/галерея/память).

### Память
- `src/services/memory.py` — извлечение фактов (LLM), семантический поиск
  (обязательно фильтр по `telegram_user_id`!), суммаризация.
- `src/database/repositories.py` — ВСЕ запросы с WHERE telegram_user_id.

---

## 4. Правила и ограничения (НЕ нарушать)

1. **Изоляция данных**: каждый пользователь видит только свои данные.
   Любой поиск памяти — с фильтром `telegram_user_id` ДО передачи в LLM.
   Тест: `tests/test_memory_isolation.py`.
2. **Модерация обязательна**: блокируются несовершеннолетние (в любом виде),
   насилие/принуждение, инцест, животные, реальные люди/дипфейки,
   шантаж/эксплуатация. Взрослый (18+) контент с вымышленным персонажем
   разрешён. См. `src/services/moderation.py`.
3. **Age gate 18+ и согласия**: NSFW только после отдельного opt-in
   (`src/services/consent.py`). Никогда не включать NSFW автоматически.
4. **Бесплатно и локально**: не добавлять платные API (OpenAI и т.п.),
   всё через абстрактные провайдеры (`src/providers/base.py`).
5. **Женский род**: Лилит всегда говорит о себе в женском роде
   (см. system.md и авто-фикс в `src/services/chat.py`).
6. **Не раскрывать технические детали пользователю**: она не говорит
   «я ИИ/модель/промпт» (кроме прямого вопроса «ты настоящая?»).
7. **Кодировка Windows**: `.bat`-файлы — ТОЛЬКО ASCII (иначе кракозябры).
8. **Тесты**: после изменений — `make test`, `make lint`. Стиль — ruff, mypy.

---

## 5. Типичные задачи (куда смотреть)

| Задача | Файлы |
|---|---|
| Сменить характер/стиль Лилит | `prompts/persona_lilith.md`, `src/prompts.py` |
| Добавить эмоцию | сгенерировать PNG в `assets/emotions/`, добавить в allowed + labels + детекторы |
| Улучшить качество картинок | `workflows/*.json`, `src/providers/comfyui.py`, negative prompt в `src/prompts.py` |
| Добавить команду | `src/bot/handlers/commands.py` (и в меню `src/main.py`) |
| Улучшить память | `src/services/memory.py`, `src/database/repositories.py` |
| Изменить Mini App | `miniapp/` (фронт), `src/miniapp_server.py` (бэк) |
| Настройки | `src/config.py` + `.env.example` |

---

## 6. Запуск и тесты

```bash
cp .env.example .env        # заполнить TELEGRAM_TOKEN
make install                # venv + зависимости
make migrate                # Alembic
make test                   # pytest (93 теста)
make lint                   # ruff + mypy
make run                    # запуск бота
```

Для Colab/Kaggle — `colab/run_everything.ipynb` (автозапуск, ключи в секретах).

---

## 7. Текущее состояние (v1.5.1)

- 93 теста зелёные, ruff/mypy чисты;
- 23 эмоции Лилит (реалистичные) + 5 аниме + 9 в белье + 4 стадии «раздевания»;
- Mini App: визуальная новелла, эмоции по диалогу, кнопка «В белье»;
- Модель по умолчанию: `huihui_ai/qwen3-abliterated:14b` (без цензуры);
- Проактивные сообщения, переодевание, манера речи, авто-фикс пола,
  лимит картинок отключён (`IMAGE_PHOTO_RATE_LIMIT_MINUTES=0`);
- Известные TODO: догенерировать аниме-версии всех эмоций и остальные
  14 эмоций в белье (лимит генерации изображений).
