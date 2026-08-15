# ☁️ Гайд: бот «Лея» 24/7 на Oracle Cloud Free Tier (бесплатно)

*Этот гайд — для новичка. Если что-то непонятно — просто идите по шагам,
команды копируйте целиком. Всё бесплатно (нужна карта только для
подтверждения, деньги не списываются).*

---

## Что вы получите

- **Сервер в интернете, который работает 24/7** — бот отвечает, даже когда ваш компьютер выключен;
- **4 ядра ARM + 24 ГБ памяти — навсегда бесплатно** (Oracle Free Tier);
- Бот целиком: разговор (NSFW-госпожа), голос, память;
- Картинки — медленные (2–10 минут на CPU), но работают. Быстрые картинки — через Colab (отдельный гайд).

---

## Шаг 0. Что понадобится

1. **E-mail** (для регистрации);
2. **Банковская карта** (Visa/MC/Мир — для верификации. Деньги НЕ списываются, только блокировка ~1$ на проверку, потом разблокируется);
3. **Телефон** (подтверждение по SMS);
4. **Пароль** — придумайте надёжный (минимум 12 символов, буквы+цифры+символы).

---

## Шаг 1. Регистрация (15–20 минут, может быть с капризами)

1. Откройте: **https://signup.cloud.oracle.com**
2. Заполните: страна, имя, e-mail, пароль → **Continue**.
3. Подтвердите e-mail (придёт письмо → нажмите ссылку).
4. Введите данные карты (страна должна совпадать с той, что указали в шаге 2) → **Continue**.
   > Если пишет ошибку — попробуйте: другой браузер / режим инкогнито / карту с другим банком. Это самое капризное место.
5. Подтвердите телефон (SMS-код) → **Continue**.
6. Придумайте имя пользователя для входа (например, `admin` — это логин в консоль) → **Continue**.
7. Дождитесь загрузки консоли (иногда 1–2 минуты). Если пишет «Your account is provisioning» — подождите 5–15 минут и обновите страницу.

---

## Шаг 2. Создайте виртуальную машину (сервер)

1. В консоли Oracle слева выберите меню ☰ → **Compute** → **Instances**.
2. Нажмите **Create instance**.
3. **Name** — любое, например `leya-bot`.
4. **Placement** — оставьте как есть (Availability domain — любой).
5. **Image and shape** → нажмите **Edit**:
   - **Image**: выберите **Ubuntu 24.04** (важно! не Oracle Linux);
   - **Shape**: нажмите **Change shape** → слева выберите **Specialty and legacy** → **Ampere** → выберите **VM.Standard.A1.Flex** → **OCPU count: 4**, **Memory: 24 GB** (или максимум доступного — у всех по-разному, часто 4/24) → **Select shape**.
   > ⚠️ Если Ampere недоступен («Out of capacity») — попробуйте: другой Availability domain, или подождите 15–30 минут, или уменьшите до 2 OCPU / 12 ГБ. Это бесплатный лимит, он есть у всех.
6. **Networking** — оставьте как есть (создастся сеть и публичный IP).
7. **Add SSH keys** — выберите **Generate a key pair for me**:
   - Нажмите **Save Private Key** → скачается файл `ssh-key-...key` (сохраните, он нужен для входа!);
   - Нажмите **Save Public Key** (не обязательно, но можно).
8. Нажмите **Create**.

Подождите 1–2 минуты — появится строка с состоянием **Running** и **Public IP address** (запишите его, например `168.138.12.34`).

---

## Шаг 3. Установите всё на сервер (копируйте команды целиком)

Откройте **Терминал** на вашем компьютере:
- **Windows:** Пуск → наберите `cmd` → Enter (или PowerShell);
- **Mac:** Cmd+Пробел → `Терминал`.

### 3.1 Подключитесь к серверу

Скопируйте команду, вставив вместо `168.138.12.34` ваш IP и вместо `путь_к_ключу` — путь к скачанному ключу (обычно `Downloads\ssh-key-2026-08-15.key`):

```
ssh -i путь_к_ключу ubuntu@168.138.12.34
```

- Если спросит про «fingerprint» — введите `yes` → Enter;
- Введёт в систему (приглашение `ubuntu@...:~$`).

> На Windows может потребоваться установить OpenSSH: **Параметры → Приложения → Дополнительные компоненты → Добавить → «Клиент OpenSSH» → Установить**. Или используйте **PuTTY** (гугл «putty download»).

### 3.2 Установите базовое

```
sudo apt update && sudo apt install -y git python3.12-venv ffmpeg curl
```

### 3.3 Установите Ollama (мозг бота) и модели

```
curl -fsSL https://ollama.com/install.sh | sh
ollama pull dolphin-llama3:8b
ollama pull nomic-embed-text
```

> Это скачает ~5 ГБ. Подождите, не выключайте. (Если ARM-версия недоступна для dolphin — выполните `ollama pull qwen2.5:7b` как запасную.)

### 3.4 Установите Piper (голос) — опционально

```
sudo mkdir -p /opt/piper && cd /opt/piper
sudo curl -L -o piper.tar.gz https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz
sudo tar -xzf piper.tar.gz && sudo rm piper.tar.gz
sudo ln -s /opt/piper/piper /usr/local/bin/piper
cd ~ && mkdir -p models/piper
curl -L -o models/piper/ru_RU-irina-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx
curl -L -o models/piper/ru_RU-irina-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json
```

### 3.5 Скопируйте проект на сервер

**Способ А (проще всего):** на вашем ПК откройте второй терминал, в папке со скачанным проектом (`project-lady-0.2.9`) выполните:

```
scp -i путь_к_ключу -r . ubuntu@168.138.12.34:/home/ubuntu/project-lady
```

**Способ Б:** на сервере (в ssh) выполните:
```
git clone https://github.com/samagon90/project-lady.git /home/ubuntu/project-lady
cd /home/ubuntu/project-lady
git checkout v0.2.9
```

### 3.6 Настройте и установите бота

```
cd /home/ubuntu/project-lady
cp .env.example .env
nano .env
```

Откроется редактор. Вставьте токен: найдите строку `TELEGRAM_TOKEN=` и впишите после `=` ваш токен от BotFather. **Сохранение в nano:** Ctrl+O → Enter → Ctrl+X.

Затем:
```
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m alembic upgrade head
```

---

## Шаг 4. Автозапуск 24/7 (бот переживёт перезагрузку)

```
sudo useradd -r -s /usr/sbin/nologin projectlady || true
sudo chown -R projectlady:projectlady /home/ubuntu/project-lady
sudo cp /home/ubuntu/project-lady/deploy/project-lady.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now project-lady
```

Проверьте, что бот запустился:
```
sudo systemctl status project-lady
```
Должно быть **active (running)**. Логи:
```
journalctl -u project-lady -f
```

---

## Шаг 5. Проверка в Telegram

Откройте Telegram → ваш бот → `/start` → 18+ → согласия → `/mode` → NSFW → общайтесь. Бот работает 24/7, даже когда ваш компьютер выключен!

---

## Шаг 6. Безопасность (важно!)

- **Не открывайте порты наружу**: в консоли Oracle → Networking → **Security Lists** → оставьте открытым только порт **22 (SSH)**. Порты 11434 (Ollama) и 8188 (ComfyUI) нужны только внутри сервера, наружу их открывать НЕ надо.
- Публичный IP лучше сделать **зарезервированным** (Reserved public IP), иначе при перезапуске он меняется: в консоли Networking → IP Management → Reserved Public IPs → Reserve → привязать к инстансу.

---

## Частые проблемы

| Проблема | Решение |
|---|---|
| «Out of capacity» при создании VM | Смените Availability domain / подождите / уменьшите до 2 OCPU |
| Не пускает ssh (Permission denied) | Проверьте путь к ключу; на Windows может нужен `-i` с полным путём; попробуйте PuTTY |
| Бот не отвечает | `sudo systemctl status project-lady` — смотрите ошибку; проверьте токен в `.env` |
| Картинки очень медленные | Это CPU — нормально 2–10 мин. Для быстрых — Colab (отдельный гайд) |
| Хочу удалить всё | `sudo systemctl stop project-lady && sudo rm -rf /home/ubuntu/project-lady` + удалить VM в консоли |

---

*Oracle Cloud Free Tier: 4 OCPU ARM / 24 ГБ RAM — навсегда бесплатно. Карта нужна только для верификации.*
