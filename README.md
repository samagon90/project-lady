# project-lady — Telegram-бот «Лилит» 🌸

**Виртуальная девушка-компаньон для совершеннолетних пользователей (18+).**
Полностью локальный и бесплатный стек: никаких платных API.

- **Текст** — локальная LLM через [Ollama](https://ollama.com) (любая модель, задаётся через `LLM_MODEL`);
- **Изображения** — локальный [ComfyUI](https://github.com/comfyanonymous/ComfyUI) через HTTP API;
- **Голос** — локальный [Piper](https://github.com/rhasspy/piper) TTS, конвертация в OGG/Opus через ffmpeg;
- **Память** — SQLite/PostgreSQL + локальные embeddings (Ollama) + векторный индекс (numpy, опционально FAISS);
- **Бот** — Python 3.12+, aiogram 3, SQLAlchemy 2 async, Alembic.

> ⚠️ Персонаж — вымышленный ИИ (женщина, 24 года). Бот всегда честно сообщает,
> что он ИИ, а не человек. NSFW-функции доступны только после подтверждения
> 18+ и **отдельного** добровольного согласия. Запрещённый контент
> (несовершеннолетние, насилие, инцест, животные, реальные люди, дипфейки и т.д.)
> блокируется модерацией.

---

## Содержание

1. [Возможности](#возможности)
2. [Команды](#команды)
3. [Архитектура](#архитектура)
4. [Установка](#установка)
5. [Запуск через Docker Compose](#запуск-через-docker-compose)
6. [Бесплатное облако](#бесплатное-облако)
7. [Память и приватность](#память-и-приватность)
8. [Безопасность](#безопасность)
9. [Тесты](#тесты)
10. [Устранение неполадок](#устранение-неполадок)

> 📘 **Пошаговая инструкция запуска — в файле [RUNBOOK.md](RUNBOOK.md)**:
> с нуля до работающего бота (Python, BotFather, Ollama, Piper, ffmpeg,
> ComfyUI, первое знакомство, бесплатное облако Oracle, Docker, FAQ).
> Перед запуском выполните `make doctor` — он проверит готовность окружения.
>
> 🐣 **Вы никогда не программировали?** Откройте
> **[GUIDE_FOR_BEGINNERS.md](GUIDE_FOR_BEGINNERS.md)** — инструкция простыми
> словами. На Windows запуск — двойной клик по **`start_windows.bat`**,
> на Mac — перетащить **`start.sh`** в Терминал.
   - [Шаг 1. Python и зависимости](#шаг-1-python-и-зависимости)
   - [Шаг 2. Telegram-бот через BotFather](#шаг-2-telegram-бот-через-botfather)
   - [Шаг 3. Ollama и LLM](#шаг-3-ollama-и-llm)
   - [Шаг 4. Piper и ffmpeg (голос)](#шаг-4-piper-и-ffmpeg-голос)
   - [Шаг 5. ComfyUI (изображения)](#шаг-5-comfyui-изображения)
   - [Шаг 6. Конфигурация .env](#шаг-6-конфигурация-env)
   - [Шаг 7. База данных и запуск](#шаг-7-база-данных-и-запуск)
5. [Запуск через Docker Compose](#запуск-через-docker-compose)
6. [Бесплатное облако](#бесплатное-облако)
7. [Память и приватность](#память-и-приватность)
8. [Безопасность](#безопасность)
9. [Тесты](#тесты)
10. [Устранение неполадок](#устранение-неполадок)

---

## Возможности

- Общение на русском языке с персонажем «Лилит» — величавая игривая госпожа
  24 лет с вампирическим шармом (в духе леди Диметреску): аристократичная,
  соблазнительная, без табу на взрослые темы в NSFW-режиме
  (характер, стиль и правила — в `prompts/persona_lilith.md`);
- Уровни общения: `0 — дружеский`, `1 — лёгкий флирт`, `2 — романтический`, `3 — NSFW`;
- NSFW включается **только** после 18+ и отдельного согласия (версия и дата сохраняются), никогда — автоматически;
- Генерация изображений персонажа через ComfyUI с очередью задач и сообщением «Изображение создаётся…»;
- Голосовые ответы (Piper → OGG/Opus), включаются/выключаются командой `/voice`;
- Долговременная память по категориям: `profile, preferences, boundaries, relationship, events, conversation_style`;
- Извлечение фактов LLM (confidence / sensitivity / expires_at), семантический поиск с жёсткой изоляцией по `telegram_user_id`;
- Суммаризация старых диалогов, чтобы контекст не раздувался;
- Полное разделение данных пользователей + каскадное удаление `/forget_me`;
- Rate limiting, лимит параллельных генераций, graceful shutdown, санитизация логов;
- Все модели — за абстрактными провайдерами (меняются через `.env` без изменения кода);
- **Лилит переодевается по запросу**: «переоденься в костюм горничной» / «надень
  красное платье» — наряд запоминается и применяется к картинкам;
- **Меняет манеру речи**: «говори нежнее» / «разговаривай грубо» — стиль
  запоминается и строго соблюдается;
- **Два стиля аватара и картинок**: `/style` — реалистичный 📸 или рисованный
  (аниме) 🖌, переключение на лету с показом аватара;
- Лилит сама пишет первой, если пользователь молчит (проактивные сообщения).

## 🌐 Провайдеры LLM: OpenRouter / Venice / Ollama

Бот может работать на любом провайдере через единый интерфейс
(`src/providers/openrouter.py`):

| Провайдер | NSFW | Карта? | Лимиты | Настройка |
|---|---|---|---|---|
| **OpenRouter** (`openrouter`) | ✅ частично (выбор модели) | ❌ не нужна | 50 запросов/день (20/мин); $10 → 1000/день | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` |
| **Venice** (`venice`) | ✅✅ самые либеральные | ❌ не нужна | свои | `VENICE_API_KEY`, `VENICE_MODEL` |
| **Ollama** (`ollama`) | ✅ (локально, без цензуры) | — | без лимитов | `LLM_BASE_URL`, `LLM_MODEL` |

NSFW-дружественные модели OpenRouter (провайдеры DeepInfra / Novita / Together):
- `openrouter/free` — авто-выбор из бесплатных (может быть цензура);
- модели с пометкой abliterated/uncensored на этих провайдерах;
- ограничить провайдеров: `OPENROUTER_PROVIDERS=DeepInfra,Novita,Together`.

> ⚠️ Бесплатные модели OpenRouter имеют лимит 50 запросов/день — для
> постоянного бота лучше Venice или локальная Ollama.



| Команда | Описание |
|---|---|
| `/start` | Запуск и возрастная проверка (18+) |
| `/help` | Справка |
| `/profile` | Профиль и известные боту предпочтения |
| `/settings` | Настройки: имя, обращение, местоимения, интересы, границы |
| `/mode` | Режим: дружеский / флирт / романтический / NSFW |
| `/voice` | Включить/выключить голосовые ответы |
| `/photo` | Создать изображение персонажа (`/photo описание` или отдельным сообщением) |
| `/memory` | Категории сохранённых воспоминаний |
| `/reset` | Сбросить историю диалога (память сохраняется) |
| `/forget_me` | Безвозвратно удалить профиль, сообщения, память и файлы |
| `/privacy` | Политика обработки данных |
| `/cancel` | Отменить текущую операцию |

## Архитектура

```
src/
  bot/
    handlers/       # Telegram-хендлеры (common, consent, commands, chat)
    keyboards.py    # Inline-клавиатуры
    middlewares.py  # группы, rate limit, DI-контекст, регистрация
    states.py       # FSM
    di.py           # DI-контейнер (AppContext)
  config.py         # Pydantic Settings (.env)
  database/
    models.py       # 10 моделей (User, Consent, Preferences, Message, MemoryItem, ...)
    repositories.py # доступ к данным, везде WHERE telegram_user_id
    base.py         # движок/сессии
  services/
    chat.py         # диалог: контекст -> LLM -> ответ
    memory.py       # память: факты, семантика, суммаризация
    image.py        # изображения: модерация -> промпт -> очередь -> ComfyUI
    tts.py          # голос: очистка -> Piper -> OGG/Opus
    moderation.py   # блоклисты + LLM-судья
    consent.py      # age gate и согласия
    audit.py        # журнал событий без текста переписки
    storage.py      # временные файлы (UUID), очистка
  providers/
    base.py         # абстрактные интерфейсы (LLM/Image/TTS/Embeddings)
    ollama.py       # Ollama: /api/chat, /api/embed
    comfyui.py      # ComfyUI: workflow из JSON, поллинг /history
    piper.py        # Piper TTS
    embeddings.py   # векторный индекс (numpy / FAISS)
  workers.py        # очередь генерации + воркер очистки
  prompts.py        # загрузка системных промптов
  main.py           # запуск, миграции, graceful shutdown
prompts/            # персонаж, правила, промпты для памяти/модерации/изображений
workflows/          # ComfyUI workflow (JSON)
migrations/         # Alembic
tests/              # unit + integration тесты
```

## Установка

### Шаг 1. Python и зависимости

Нужен **Python 3.12+**. Проверьте: `python3 --version`.

```bash
git clone <ваш-репозиторий> && cd project-lady
cp .env.example .env

make install        # создаёт .venv и ставит зависимости (или: python3 -m venv .venv && .venv/bin/pip install -e ".[dev]")
```

### Шаг 2. Telegram-бот через BotFather

1. Откройте в Telegram [@BotFather](https://t.me/BotFather);
2. `/newbot` → имя бота (например, «Лилит») → username (например, `lilith_companion_bot`);
3. Скопируйте **токен** вида `123456789:AA...` и вставьте в `.env`:

```dotenv
TELEGRAM_TOKEN=123456789:AA...
```

4. (Опционально) `/setprivacy` → Disable, чтобы бот видел все сообщения в группах (он всё равно откажется в них работать).

### Шаг 3. Ollama и LLM

```bash
# Установка Ollama (Linux):
curl -fsSL https://ollama.com/install.sh | sh

# Модель для общения (рекомендуется Qwen 3 без цензуры):
ollama pull huihui_ai/qwen3-abliterated:14b
# Для слабых ПК — 8b:
#   ollama pull huihui_ai/qwen3-abliterated:8b
# Классика: dolphin3:8b

# Модель для embeddings (семантическая память):
ollama pull nomic-embed-text

# Проверка: сервер слушает http://127.0.0.1:11434
ollama serve
```

В `.env`:

```dotenv
LLM_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=qwen2.5:7b
EMBEDDING_MODEL=nomic-embed-text
```

Можно подключить любой OpenAI-совместимый локальный сервер — проект использует нативный HTTP API Ollama (`/api/chat`, `/api/embed`), к одной модели не привязан.

### Шаг 4. Piper и ffmpeg (голос)

```bash
# ffmpeg:
sudo apt install ffmpeg          # Debian/Ubuntu
sudo dnf install ffmpeg          # Fedora
brew install ffmpeg              # macOS

# Piper (официальные релизы, бесплатно):
#   https://github.com/rhasspy/piper/releases — скачайте piper_amd64.tar.gz
#   (или piper_arm64.tar.gz / piper_i686.tar.gz), распакуйте и добавьте в PATH.

# Русский голос (бесплатно, лицензия MIT/CC; голос Ирины — с согласия автора):
make voice
# = скачивает models/piper/ru_RU-irina-medium.onnx и .onnx.json с HuggingFace
```

Проверка: `echo "Привет" | piper --model models/piper/ru_RU-irina-medium.onnx -f /tmp/test.wav && ls -la /tmp/test.wav`

В `.env`: `PIPER_VOICE_MODEL=models/piper/ru_RU-irina-medium.onnx`. Если Piper/голос не установлены — бот работает без голоса (текстовые ответы остаются).

### Шаг 5. ComfyUI (изображения)

```bash
# Установка (Linux, нужен Python 3.10-3.12 + git):
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Checkpoint (SD 1.5, бесплатный; пример — dreamshaper_8):
#   https://civitai.com/api/download/models/128713
#   (или huggingface.co/Lykon/dreamshaper-8) — положите в ComfyUI/models/checkpoints/

# Запуск с доступом для бота:
python main.py --listen 0.0.0.0 --port 8188 --cpu
```

Бот шлёт workflow из `workflows/comfyui_lilith_sd15.json`, подставляя значения в узлы
по **названию узла** (title): `Load Checkpoint`, `Positive Prompt`, `Negative Prompt`,
`Empty Latent Image`, `KSampler`, `Save Image`. Если добавите узел `LoraLoader`
с title `Load LoRA` — бот подставит имя LoRA из `COMFYUI_LORA`.

В `.env`:

```dotenv
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_CHECKPOINT=dreamshaper_8.safetensors
```

Если ComfyUI недоступен — бот отвечает понятным сообщением об ошибке (без путей и stack trace).

### Шаг 6. Конфигурация .env

Скопируйте `.env.example` в `.env` и заполните как минимум `TELEGRAM_TOKEN`.
Все параметры описаны в файле с комментариями. Основные группы: LLM, ComfyUI,
Piper, лимиты, хранение, логирование.

### Шаг 7. База данных и запуск

```bash
make doctor         # проверить готовность: Python, .env, БД, Ollama, Piper, ffmpeg, ComfyUI
make migrate        # Alembic: создаёт таблицы (SQLite по умолчанию)
make run            # запуск бота
```

> При каждом старте миграции применяются автоматически — `make migrate` нужен для явного запуска.
> `make doctor` покажет, чего не хватает, и подскажет, что выполнить.

**PostgreSQL (опционально):** создайте БД и укажите в `.env`:
`DATABASE_URL=postgresql+asyncpg://user:password@host:5432/project_lady`, затем
установите драйвер: `.venv/bin/pip install -e ".[postgres]"`.

## Запуск через Docker Compose

```bash
cp .env.example .env        # заполните TELEGRAM_TOKEN
# голос:
mkdir -p models/piper && make voice

# бот + Ollama:
docker compose up -d --build

# + ComfyUI (тяжёлый сервис, нужен GPU или мощный CPU):
docker compose --profile comfyui up -d
```

- Бот и Ollama запускаются сразу; ComfyUI — по профилю (модели кладите в `./comfyui/models`);
- Данные сохраняются в `./data` (volume), голосовые модели — в `./models`.

## Бесплатное облако

Весь стек локальный, поэтому «облако» — это ваша собственная машина, где можно бесплатно держать сервисы 24/7:

| Вариант | Что даёт | Что учесть |
|---|---|---|
| **Oracle Cloud Free Tier** (VM.Standard.A1.Flex, 4 OCPU ARM / 24 GB RAM) | Самый щедрый бесплатный VPS без ограничения по времени | ARM: нужен Piрer arm64; ComfyUI на CPU — медленно, но работает; поставьте Ubuntu 22.04+ и Docker |
| **Домашний ПК / ноутбук** + проброс порта (или WireGuard/Tailscale) | Бесплатно и просто, есть GPU — картинки быстрые | Машина должна быть включена; Telegram бот сам подключается к серверу (исходящее соединение), открывать порты не обязательно при использовании Tailscale |
| **GitHub Codespaces** (бесплатные часы) | Быстрый старт для теста | Таймаут простоя; подходит для демо, не для 24/7 |
| **Google Cloud / AWS / Azure free tiers** | 1–2 vCPU, 1 GB RAM | Мало для 7B LLM + ComfyUI; подойдёт только с моделью ~3-4B и отключёнными картинками |

Рекомендация для бесплатного 24/7: **Oracle Cloud ARM Free Tier + Docker Compose**.
На ARM-инстансе: `ollama pull qwen2.5:7b` (есть ARM-сборка), Piper `piper_arm64`, ComfyUI на CPU — генерация одной картинки 512×768 занимает 2–10 минут; увеличьте `IMAGE_PHOTO_RATE_LIMIT_MINUTES`.

Если ресурсов мало, отключите тяжёлое: `TTS_ENABLED=false` и не запускайте ComfyUI — бот останется полноценным текстовым.

### Автозапуск 24/7 через systemd

Для постоянной работы без Docker:

```bash
sudo mkdir -p /opt/project-lady && sudo chown $USER /opt/project-lady
cp -r . /opt/project-lady            # код проекта
cd /opt/project-lady && make install && cp .env.example .env  # настроить токен
sudo useradd -r -s /usr/sbin/nologin projectlady || true
sudo chown -R projectlady:projectlady /opt/project-lady
sudo cp deploy/project-lady.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now project-lady
journalctl -u project-lady -f        # логи
```

Юнит использует `EnvironmentFile=/opt/project-lady/.env`, перезапускает бота при
падении и корректно останавливает его по SIGTERM (graceful shutdown).

## NSFW-контент: картинки и голос (18+)

Всё это уже реализовано в боте. Что нужно от вас — только установка моделей.

### 🔞 NSFW-картинки (`/photo`)

1. **Поставьте checkpoint с поддержкой взрослого контента** (SD1.5 или SDXL):
   на civitai.com ищите по тегу «explicit» (например, majicMIX realistic,
   Pony-семейство, или любой SD1.5 + NSFW-LoRA). Файл `.safetensors` положите
   в `ComfyUI/models/checkpoints/`, LoRA — в `ComfyUI/models/loras/`.
2. В `.env` укажите. **Важно:** эротические запросы автоматически рисуются
   ОТДЕЛЬНОЙ моделью, если её задать:
   ```dotenv
   COMFYUI_CHECKPOINT=ваш_обычный_checkpoint.safetensors   # для обычных фото
   COMFYUI_NSFW_CHECKPOINT=ваш_nsfw_checkpoint.safetensors # для NSWF (18+)
   COMFYUI_NSFW_LORA=ваша_nsfw_lora.safetensors            # опционально
   ```
3. Для качества лучше SDXL: в `.env` поменяйте
   `COMFYUI_WORKFLOW_PATH=workflows/comfyui_lilith_sdxl.json` и
   `IMAGE_DEFAULT_SIZE=832x1216` (нужен SDXL-checkpoint ~6–7 ГБ).
4. В Telegram: `/photo <описание>` — бот сам определит эротический запрос,
   проверит NSFW-согласие (18+ + отдельный opt-in) и поставит в очередь.

Внешность Леи стабильна благодаря character sheet; для идеально
узнаваемого лица добавьте обученный на персонаже LoRA.

> Модерация изображений отключаться не будет: запросы с несовершеннолетними,
> реальными людьми, дипфейками и т.п. блокируются всегда — это защита от
> незаконного контента, а не «цензура характера».

### 🎙 Голосовые ответы (`/voice`)

1. Установите Piper (см. раздел «Установка», шаг 6) и `make voice` — русский голос.
2. В Telegram: `/voice` → включить.
3. Параметры в `.env`: `PIPER_VOICE_MODEL`, `PIPER_LENGTH_SCALE` (скорость),
   `TTS_MAX_CHARS` (длина части).
4. Если Piper недоступен — бот отвечает текстом, без падения.

---

## 🎨 Качество картинок

Если изображения «аморфные/уродливые»:

1. **hi-res fix** (встроен в workflow): генерация идёт в 2 прохода — сначала
   576×864, потом upscale до 864×1296 с повторной обработкой (denoise 0.5).
   Это убирает «плывущие» лица;
2. **Усилен negative prompt** — «melted face, deformed, amorf, blurry…»;
3. **Модель**: Unstable Diffusion хороша для откровенных сцен, но лица у неё
   «сырые». Для красивых лиц поставьте в `COMFYUI_CHECKPOINT` более
   качественную модель (majicMIX realistic, Juggernaut XL, RealVisXL) —
   NSFW останется через `COMFYUI_NSFW_CHECKPOINT`;
4. **Разрешение**: `IMAGE_DEFAULT_SIZE=576x864` (не меньше), шаги 32.



**Что хранится** (локально, в вашей БД):
- профиль и предпочтения (имя, обращение, интересы, границы);
- история переписки и извлечённые факты (категория, confidence, sensitivity, срок действия);
- сгенерированные файлы (временные, удаляются автоматически);
- обезличенный журнал аудита (без текста сообщений).

**Что делает бот:**
- перед ответом: профиль → последние N сообщений → до K релевантных воспоминаний (только этого пользователя) → компактный контекст → LLM;
- каждый объект памяти привязан к `telegram_user_id`, любой поиск фильтруется по нему **до** передачи в LLM;
- случайные факты не сохраняются: работает отдельный этап извлечения с порогом уверенности;
- NSFW-диалоги не попадают в обычные логи;
- `/forget_me` — полное каскадное удаление (БД, векторный индекс, файлы).

## Безопасность

- токен — только из `.env` (в Git не попадает, см. `.gitignore`);
- модерация: блоклисты (RU/EN) + LLM-судья для изображений; запрещены несовершеннолетние/неопределённый возраст в сексуальном контексте, насилие, инцест, животные, реальные люди/дипфейки, эксплуатация, шантаж;
- «18+» нельзя просто дописать к несовершеннолетнему образу — такие запросы блокируются;
- rate limiting на пользователя; лимит параллельных генераций (`IMAGE_MAX_WORKERS`);
- безопасные имена файлов (UUID), запрет удаления вне `data_dir`, таймауты/retry для Ollama/ComfyUI/Piper;
- graceful shutdown (SIGINT/SIGTERM): остановка воркеров, закрытие БД и HTTP-клиентов;
- при недоступности Ollama/ComfyUI/Piper бот отвечает понятным текстом и продолжает работать;
- в группах бот вежливо предлагает перейти в личный чат.

## Тесты

```bash
make test       # pytest (31 тест)
make lint       # ruff + mypy
```

Покрытие включает: регистрацию, age gate, NSFW opt-in/opt-out, запрет NSFW до согласия,
**изоляцию памяти двух пользователей (SQL + семантический поиск + контекст LLM)**,
`/forget_me`, смену режимов, отказ на запрещённые запросы, недоступность Ollama/ComfyUI,
fallback TTS, rate limiting, очистку временных файлов.

## Устранение неполадок

| Проблема | Решение |
|---|---|
| «TELEGRAM_TOKEN не задан» | Заполните `.env` (скопируйте из `.env.example`) |
| «Моя языковая модель сейчас недоступна» / бот не отвечает | В `.env` нет `LLM_MODEL` или указана несуществующая модель. Проверьте: `ollama list` → имя модели (например `huihui_ai/qwen3-abliterated:14b`) → в `.env` строка `LLM_MODEL=<то же имя>`, перезапустите бота. В Colab просто загрузите свежий ноутбук v1.8.7+ — он пишет `LLM_MODEL` сам, а в конце самопроверкой показывает ✅/❌ |
| «Модель ... не найдена в Ollama» | `ollama pull huihui_ai/qwen3-abliterated:14b` (при RAM < 10 ГБ — `:8b`); после установки перезапустите бота. С v1.8.7 бот сам подхватывает установленную модель |
| Голос не отправляется | `piper` в PATH (`which piper`), `make voice`, ffmpeg установлен |
| Картинки не генерируются | ComfyUI запущен (`curl http://127.0.0.1:8188/system_stats`), checkpoint скачан (~2 ГБ), имя совпадает с `COMFYUI_CHECKPOINT`. С v1.8.7 бот сам найдёт установленный checkpoint |
| Бот не отвечает в группе | Это by design: личные сообщения только |
| Бот отвечает слишком скромно / «замкнуто», отказывает в NSFW | Встроенная цензура модели (qwen2.5 и др. «причёсаны») | Поставьте модель без цензуры: `ollama pull dolphin-llama3:8b`, затем в `.env`: `LLM_MODEL=dolphin-llama3:8b`, перезапустите бота. Также помогает `/reset` — старые «скромные» сообщения уходят из контекста |
| Ошибка миграций | `rm -f data/bot.db && make migrate` (или проверьте права на `data/`) |

---

*Все компоненты — бесплатные и open-source: Ollama, ComfyUI, Piper, SQLite/PostgreSQL,
aiogram, SQLAlchemy. Никаких платных API. Голоса Piper используются только публичные,
с согласия авторов; голоса реальных людей не клонируются.*

## 📱 Telegram Mini App

У бота есть веб-интерфейс внутри Telegram (Mini App): профиль, настройки
(имя, режим, стиль картинок, голос, наряд, манера речи), галерея
сгенерированных фото и память.

- Команда **`/app`** — кнопка «Открыть приложение Лилит»;
- Безопасность: каждый запрос проверяется через initData Telegram
  (HMAC-SHA256 от токена бота) — посторонние не получат доступ;
- Настройка: `MINIAPP_HOST/PORT` и `WEBAPP_URL` (публичный HTTPS-адрес,
  например через localtunnel: `npx localtunnel --port 8001`);
- Запускается автоматически вместе с ботом (aiohttp, порт 8001).

## Сравнение с похожими open-source проектами

| Проект | Стек | Наш бот |
|---|---|---|
| telegram-novita (AI-girlfriend) | платные API (Novita), python-telegram-bot | ✅ полностью бесплатный локальный стек |
| ai-girlfriend-with-voice (AlexTs10) | OpenAI + ElevenLabs + Stripe ($1/мин) | ✅ бесплатный голос (Piper), без оплат |
| talk-to-girlfriend-ai | Claude + Nia API (платные) | ✅ локальная LLM + семантическая память |

Что мы взяли из лучших практик конкурентов: автоопределение запросов фото
(«нарисуй/пришли фото»), живой характер, голосовые ответы, проактивные
сообщения, Mini App. Чего у нас нет и почему: платные API и оплаты
(противоречит требованию «бесплатно»), транскрибация голоса (тяжёлая,
можно добавить позже через локальный Whisper).



Нет карты? Запустите **весь бот целиком** в Google Colab — бесплатно, нужен
только Google-аккаунт:
- **`colab/run_everything.ipynb`** — ноутбук «всё-в-одном»: бот + LLM (Ollama)
  + голос (Piper) + картинки (ComfyUI на GPU T4). Запустили → вставили токен →
  бот работает.
- Ограничение: сессия Colab живёт несколько часов и прерывается при
  бездействии; перезапуск — 2 минуты (Выполнить всё → токен).
- Это лучший бесплатный вариант без карты; для 24/7 потребуется платный VPS
  или Oracle (с картой).
