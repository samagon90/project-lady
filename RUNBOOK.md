# RUNBOOK — пошаговая инструкция запуска бота «Лея»

Подробное руководство «с нуля до работающего бота». Время прохождения:
**~30–60 минут** (большая часть — скачивание моделей). Всё бесплатно.

---

## 0. Что вам понадобится

| Компонент | Для чего | Минимальные требования |
|---|---|---|
| Машина (ПК / VPS) | работает 24/7 или когда вы онлайн | 8+ ГБ RAM (для LLM 7B), 10+ ГБ диска |
| Python 3.12+ | сам бот | — |
| Telegram-аккаунт | создать бота через @BotFather | бесплатно |
| Ollama + модель | генерация текста | ~6 ГБ RAM (qwen2.5:7b), можно 3b на слабых машинах |
| Ollama + nomic-embed-text | семантическая память | ~0.3 ГБ |
| Piper + русский голос | голосовые сообщения | ~0.1 ГБ |
| ffmpeg | конвертация аудио | — |
| ComfyUI + checkpoint | изображения | CPU/GPU, 4+ ГБ RAM (опционально, без него бот работает) |

**Три варианта размещения:**

1. **Свой ПК/ноутбук (Linux)** — самый простой для первого запуска. Рекомендую начать здесь.
2. **Windows** — используйте WSL2 (Ubuntu 24.04) и выполняйте те же команды Linux.
3. **Бесплатное облако 24/7** — Oracle Cloud Free Tier (24 ГБ RAM, 4 ARM CPU), подробно в разделе 11.

---

## 1. Получить код проекта

```bash
git clone <адрес-вашего-репозитория> project-lady
cd project-lady
```

> Если репозиторий недоступен — скачайте архив проекта и распакуйте в папку `project-lady`.

---

## 2. Создать Telegram-бота (BotFather) — 2 минуты

1. Откройте в Telegram: [@BotFather](https://t.me/BotFather)
2. Нажмите **Start** → команда `/newbot`
3. Название: например `Лея` (любое)
4. Username: обязательно заканчивается на `bot`, например `leya_companion_bot`
5. BotFather пришлёт **токен** — строку вида:
   ```
   123456789:AAHfK3x8y...-токен
   ```
6. Сохраните токен — он нужен в шаге 4.
7. (Рекомендация) `/setprivacy` → **Disable** — чтобы бот видел сообщения (он всё равно отвечает только в личке).

---

## 3. Установить Python 3.12+

**Ubuntu 24.04+ / Debian 13+** — уже в системе:
```bash
python3 --version   # должно показать 3.12.x
```

**Ubuntu 22.04 / Debian 12** — через deadsnakes:
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv
# проверка:
python3.12 --version
```

> Дальше везде, где встречается `make install`, на старых дистрибутивах используйте:
> `make install PYTHON_BIN=python3.12`

**Windows** — поставьте Python 3.12 с python.org (галочка «Add to PATH») и запускайте
команды из WSL2 (рекомендую) или из PowerShell с заменой `.venv/bin/python` на `.venv\Scripts\python`.

---

## 4. Установить зависимости бота

```bash
cd project-lady
cp .env.example .env        # создаём файл конфигурации
make install                # ~2-3 минуты: создаёт .venv и ставит пакеты
```

Откройте `.env` любым редактором и вставьте токен:

```dotenv
TELEGRAM_TOKEN=123456789:AAHfK3x8y...-токен
```

Пока больше ничего менять не нужно — остальные параметры уже имеют
рабочие значения по умолчанию (см. `.env.example` с комментариями).

---

## 5. Установить Ollama + модели (текст и память)

```bash
# 1) Установка Ollama (Linux / macOS):
curl -fsSL https://ollama.com/install.sh | sh

# 2) Модель для общения (~4.7 ГБ). Для слабых машин (8 ГБ RAM) берите qwen2.5:3b
ollama pull qwen2.5:7b

# 3) Модель для embeddings (семантическая память, ~0.3 ГБ)
ollama pull nomic-embed-text

# 4) Проверка, что сервер отвечает:
curl http://127.0.0.1:11434/api/tags
# ожидаем JSON со списком моделей
```

Если сервер не запущен — `ollama serve` (или перезапустите `ollama`).

> На Windows установите Ollama с сайта ollama.com — дальше всё то же самое.

---

## 6. Установить голос (Piper + ffmpeg)

```bash
# ffmpeg (Linux):
sudo apt install -y ffmpeg
# Windows: winget install ffmpeg   |   macOS: brew install ffmpeg

# Piper — скачайте бинарник под вашу архитектуру:
#   x86_64: https://github.com/rhasspy/piper/releases  →  piper_amd64.tar.gz
#   ARM64 : https://github.com/rhasspy/piper/releases  →  piper_arm64.tar.gz
# Распакуйте и добавьте в PATH, например:
tar -xzf piper_amd64.tar.gz -C ~/piper
echo 'export PATH="$HOME/piper:$PATH"' >> ~/.bashrc && source ~/.bashrc

# Русский голос (бесплатный, ~100 МБ) — качает make voice:
make voice
# → скачает models/piper/ru_RU-irina-medium.onnx и .onnx.json

# Проверка синтеза:
echo "Привет, я Лея" | piper --model models/piper/ru_RU-irina-medium.onnx -f /tmp/test.wav
ls -la /tmp/test.wav    # файл должен появиться
```

> Если Piper не установлен — бот всё равно работает: просто не будет голосовых
> ответов (текст отправляется всегда). Это допустимо на этапе теста.

---

## 7. Установить ComfyUI + checkpoint (изображения, опционально)

Понадобится, только если хотите команду `/photo`.

```bash
# 1) Клонируем ComfyUI (не в папку бота, а рядом):
cd ~
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
python3 -m venv venv && source venv/bin/activate

# 2) На машине БЕЗ видеокарты (CPU) сначала ставим CPU-версию torch:
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
# На машине С видеокартой NVIDIA этот шаг пропускаем.

pip install -r requirements.txt

# 3) Checkpoint (SD 1.5, ~2 ГБ, бесплатный):
#    DreamShaper 8: https://civitai.com/api/download/models/128713
#    (или найдите "DreamShaper 8" на civitai.com / зеркалах huggingface.co)
#    Положите файл в:
mkdir -p models/checkpoints
mv ~/Downloads/dreamshaper_8.safetensors models/checkpoints/

# 4) Запуск (порт 8188):
python main.py --listen 0.0.0.0 --port 8188
```

В `.env` бота убедитесь, что имя совпадает:

```dotenv
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_CHECKPOINT=dreamshaper_8.safetensors
```

> На CPU генерация одной картинки 512×768 занимает 2–10 минут — это нормально.
> В `.env` можно увеличить `IMAGE_PHOTO_RATE_LIMIT_MINUTES=10`.

---

## 8. Проверка готовности: `make doctor`

Всё должно быть запущено (Ollama и ComfyUI — в фоне) и установлено. Проверяем:

```bash
make doctor
```

Ожидаемый вывод (на полностью настроенной машине):

```
1. Python
  ✅ Python 3.12.x (нужен 3.12+)
2. Конфигурация (.env)
  ✅ .env найден
  ✅ TELEGRAM_TOKEN задан
3. База данных и миграции
  ✅ Миграции применены (sqlite+aiosqlite:///./data/bot.db)
  ✅ Подключение к БД работает
4. LLM и embeddings (Ollama)
  ✅ Ollama доступен ...
  ✅ LLM-модель qwen2.5:7b установлена
  ✅ Embedding-модель nomic-embed-text установлена
5. Голос (Piper + ffmpeg)
  ✅ piper найден ...
  ✅ Голосовой модель: .../ru_RU-irina-medium.onnx
  ✅ ffmpeg найден
6. Изображения (ComfyUI)
  ✅ ComfyUI доступен ...
  ✅ Workflow: comfyui_leya_sd15.json
  ✅ Checkpoint dreamshaper_8.safetensors найден
7. Каталоги данных
  ✅ Данные: .../data
  ✅ Временные файлы: .../data/tmp
```

`⚠️` (предупреждение) — бот запустится, но соответствующая функция будет
недоступна (например, ComfyUI не запущен → `/photo` будет писать ошибку).
`❌` — нужно исправить, иначе бот не запустится или не будет отвечать.

---

## 9. Запуск бота

```bash
make migrate    # применить миграции (можно пропустить — бот делает это сам при старте)
make run        # запуск
```

В логах должны появиться строки:

```
INFO  [alembic.runtime.migration] Running upgrade -> 8572ccfcce63, initial schema
INFO  ... Доступен: LLM (Ollama)
INFO  ... Доступен: Изображения (ComfyUI)      # если запущен
INFO  ... Доступен: TTS (Piper)                # если установлен
INFO  ... Бот запущен. Нажмите Ctrl+C для остановки.
```

**Остановка:** `Ctrl+C` (плавная: воркеры завершаются, БД закрывается).

---

## 10. Первое знакомство с ботом

1. Откройте Telegram → найдите username вашего бота (например, `@leya_companion_bot`).
2. Нажмите **Start** (или отправьте `/start`).
3. Бот покажет приветствие и кнопку **«✅ Мне есть 18 лет»** → нажмите.
4. Прочитайте политику → **«✅ Согласен(на)»**.
5. Вопрос про NSFW → «🔞 Принимаю условия NSFW» (или «Нет, спасибо» — режим включите позже).
6. Готово! Напишите что-нибудь — Лея ответит.
7. Проверьте команды по очереди:
   - `/mode` → выберите режим (например, Романтический);
   - `/photo Лея в осеннем парке` → через 30 секунд – несколько минут придёт картинка
     (первый раз дольше: ComfyUI загружает модель);
   - `/voice` → включить голосовые, затем следующее сообщение придёт и текстом, и голосом;
   - `/memory` → посмотреть, что бот запомнил;
   - `/profile` → профиль и согласия.

Первый ответ после запуска может занять 10–30 секунд — Ollama загружает модель в память.

---

## 11. Бесплатное облако 24/7 (Oracle Cloud Free Tier)

Самый щедрый бесплатный вариант: **4 ARM CPU / 24 ГБ RAM навсегда бесплатно**.

### 11.1 Регистрация и создание сервера

1. Зайдите на https://www.oracle.com/cloud/free/ → **Start for free**.
   - Потребуется банковская карта для верификации (списаний нет; с баланса ничего не уходит).
2. После входа: **Create a VM instance**:
   - Image: **Ubuntu 24.04** (ARM-архитектура);
   - Shape: **VM.Standard.A1.Flex**, OCPU = **4**, Memory = **24 GB**;
   - Добавьте свой SSH-ключ (или сгенерируйте и скачайте);
   - Assign public IPv4: **Yes**.
3. Подождите 1–2 минуты — сервер готов. Запишите IP-адрес.

### 11.2 Подключение и установка

```bash
ssh ubuntu@<IP-адрес>

# Устанавливаем всё нужное (~10 минут, скачивание моделей дольше):
sudo apt update && sudo apt install -y git python3.12-venv ffmpeg
curl -fsSL https://ollama.com/install.sh | sh          # ARM-сборка ставится автоматически
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

# Piper (ARM-версия) — как в разделе 6, файл piper_arm64.tar.gz

# Код бота:
sudo mkdir -p /opt/project-lady && sudo chown ubuntu /opt/project-lady
cd /opt/project-lady
# скопируйте проект: git clone ... или scp с вашего ПК:  scp -r ./project-lady/* ubuntu@IP:/opt/project-lady/

cp .env.example .env && nano .env   # вставить TELEGRAM_TOKEN
make install
make voice                          # голос (можно пропустить — без него бот работает)
```

### 11.3 Автозапуск через systemd (бот переживёт перезагрузку)

```bash
sudo useradd -r -s /usr/sbin/nologin projectlady || true
sudo chown -R projectlady:projectlady /opt/project-lady
sudo cp /opt/project-lady/deploy/project-lady.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now project-lady
journalctl -u project-lady -f       # смотреть логи
```

### 11.4 Безопасность (важно!)

- **Не открывайте порты 11434 и 8188 наружу** — Ollama и ComfyUI нужны только боту,
  они работают на `127.0.0.1`. Бот сам ходит в Telegram (исходящее соединение),
  поэтому наружу достаточно **только SSH (22)**.
- В консоли Oracle: Networking → Security Lists → оставить открытым только порт 22.
- ComfyUI на этом сервере можно не ставить (CPU ARM — медленно) или поставить:
  картинка будет генерироваться 5–15 минут. Для начала хватит текста и голоса.

---

## 12. Альтернатива: Docker Compose (только x86_64)

Если на машине Linux x86_64 с Docker — можно поднять всё одной командой
(кроме картинок: ComfyUI запускается отдельным профилем).

```bash
cd project-lady
cp .env.example .env        # вставить TELEGRAM_TOKEN

mkdir -p models/piper && make voice        # голос (или пропустить)

# Бот + Ollama:
docker compose up -d --build

# Плюс ComfyUI (тяжёлый, нужен GPU/мощный CPU):
mkdir -p comfyui/models
# положите checkpoint: cp dreamshaper_8.safetensors comfyui/models/checkpoints/
docker compose --profile comfyui up -d

# Логи:
docker compose logs -f bot
```

> На ARM (Oracle Cloud) Dockerfile не подойдёт — внутри он скачивает piper_amd64.
> Используйте на ARM путь из раздела 11 (без Docker).

---

## 13. Частые проблемы и решения

| Симптом | Причина | Решение |
|---|---|---|
| `TELEGRAM_TOKEN не задан` | пустой .env | `cp .env.example .env`, вставить токен |
| Бот не отвечает / «модель недоступна» | Ollama не запущен | `ollama serve`; `make doctor` |
| `Модель ... не найдена в Ollama` | модель не скачана | `ollama pull qwen2.5:7b` |
| Голосовых нет, но текст есть | Piper/ffmpeg/голос не установлены | раздел 6; `make doctor` |
| `/photo` пишет «недоступен» | ComfyUI не запущен | `python main.py --listen 0.0.0.0 --port 8188` |
| `/photo` пишет «ошибка генерации» | checkpoint не совпадает | `make doctor` — раздел про checkpoint |
| Картинка 5–15 минут | CPU-генерация | норма; увеличьте `IMAGE_PHOTO_RATE_LIMIT_MINUTES` |
| Первый ответ 10–30 сек | Ollama грузит модель | норма |
| Бот отвечает в группе? | запрещено намеренно | пишите боту в личные сообщения |
| Хочу сбросить всё | — | `rm -rf data bot.db` — но осторожно: это удалит все данные |
| Бот упал в облаке | — | systemd сам перезапустит: `systemctl status project-lady` |

---

## 14. Обновление и бэкап

```bash
# Бэкап (SQLite):
cp data/bot.db backup-$(date +%F).db

# Обновление кода:
git pull
make install        # если добавились зависимости
make run            # миграции применятся автоматически
```

---

*Все компоненты бесплатные: Ollama (MIT), ComfyUI (GPL-3.0), Piper (MIT),
голос ru_RU-irina (CC-BY-NC 4.0 — бесплатно для личного использования),
SQLite, aiogram, SQLAlchemy. Никаких платных API.*
