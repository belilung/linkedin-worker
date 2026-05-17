# LinkedIn Worker — установка и запуск

Инструмент для автоматизированной работы с LinkedIn: парсит результаты поиска, генерирует персональные сообщения и комментарии через Claude AI, отправляет DM и комменты через браузер.

Работает на **Windows**, **macOS** и **Ubuntu/Linux**.

---

## Что тебе понадобится

- **Python 3.11 или новее** — [скачать](https://www.python.org/downloads/)
  На Windows при установке поставь галку **"Add Python to PATH"**.
- **Anthropic API ключ** — [получить](https://console.anthropic.com/settings/keys)
  Нужно пополнить баланс минимум на $5. На 200 сообщений уйдёт ≈ $0.60.

---

## Быстрый старт

### 1. Распакуй архив

Распакуй `linkedin-worker-student.zip` в любую папку. Открой терминал внутри неё.

- **macOS:** в Finder ПКМ по папке → "Новый терминал в папке"
- **Windows:** в Проводнике в адресную строку напиши `cmd` и нажми Enter
- **Linux:** ПКМ → "Open Terminal Here"

### 2. Запусти установку

**macOS / Linux:**
```bash
./setup.sh
```

Если ругается на права — сначала: `chmod +x setup.sh`

**Windows:**
```cmd
setup.bat
```

Скрипт сам создаст виртуальное окружение, установит зависимости, скачает Chromium и создаст файлы `.env` и `config.yaml` из шаблонов.

### 3. Впиши свой API ключ

Открой файл `.env` в любом текстовом редакторе и вставь свой ключ:

```
ANTHROPIC_API_KEY=sk-ant-api03-твой-ключ-сюда
```

### 4. Настрой кампанию

Открой `config.yaml` — внутри есть комментарии к каждому полю.

Минимум что нужно поменять:
- `campaign.context` — кто ты и что предлагаешь (Claude использует это для оценки релевантности лидов)
- `campaign.search_url` — URL поиска людей на LinkedIn (см. ниже)
- `voice.sample_message` — пример сообщения в твоём стиле
- `connect_campaign.keywords` — ключевые слова для поиска постов

**Как получить search_url:**
1. Зайди на linkedin.com
2. Поиск → People → настрой фильтры (страна, отрасль, должность)
3. Скопируй URL из адресной строки

### 5. Логин в LinkedIn

Активируй виртуальное окружение и выполни логин:

**macOS / Linux:**
```bash
source venv/bin/activate
linkedin-worker login
```

**Windows:**
```cmd
venv\Scripts\activate.bat
linkedin-worker login
```

Откроется окно браузера. Войди в свой LinkedIn вручную, потом нажми Enter в терминале. Cookies сохранятся в `data/cookies/`.

**Важно:** перед каждой работой с воркером сначала активируй venv (как в шаге выше).

---

## Запуск

Есть 3 рабочих сценария — выбери под свою цель.

### `run` — отправить DM существующим связям (1st-degree)

Ищет людей по `search_url`, фильтрует **только 1st-degree связи**, парсит профили, генерирует персональное сообщение и отправляет.

```bash
linkedin-worker run --dry-run        # Превью — генерит сообщения, но не отправляет
linkedin-worker run                  # Полный запуск — отправляет DM
linkedin-worker run --no-headless    # Показать окно браузера (для дебага)
```

### `connect` — комментировать чужие посты + отправлять Connect

Ищет **посты** по ключевикам, генерирует комментарий через Claude, постит его, опционально отправляет Connect-запрос автору.

Подходит для **холодного аутрича** к людям, с которыми ты ещё не связан.

```bash
linkedin-worker connect --dry-run    # Превью
linkedin-worker connect              # Постит комменты + шлёт Connect
linkedin-worker connect --no-connect # Только комменты, без Connect
```

### `dm-recent` — DM тем, кто принял твой Connect

Находит людей, которые приняли твой Connect за последние N дней, парсит их профили, генерит сообщение и отправляет.

```bash
linkedin-worker dm-recent --dry-run  # Превью
linkedin-worker dm-recent            # Полный запуск
linkedin-worker dm-recent --days 7   # За последние 7 дней (по умолчанию 14)
```

### Типичный 3-шаговый флоу

1. `linkedin-worker connect` — комменты + Connect-запросы холодным
2. Подожди несколько дней, пока принимают
3. `linkedin-worker dm-recent` — DM тем, кто принял

### Утилиты

```bash
linkedin-worker status               # Статистика по отправкам
linkedin-worker export               # Экспорт всей активности в CSV
```

---

## Опции

| Флаг | Что делает | Где работает |
|---|---|---|
| `--dry-run` | Сгенерить, но не отправлять | run, connect, dm-recent |
| `--no-headless` | Показать окно браузера | run, connect, dm-recent |
| `--batch-size N` | Сколько лидов за раз | run, connect |
| `--config path.yaml` | Использовать другой конфиг | все |
| `--max-pages N` | Сколько страниц поиска | run |
| `--no-connect` | Только коммент, без Connect | connect |
| `--keywords "text"` | Переопределить ключевики | connect |
| `--days N` | Свежесть Connect (по умолчанию 14) | dm-recent |

---

## Headless vs видимый браузер

По умолчанию браузер **видимый** (`headless: false`). Это безопаснее — LinkedIn умеет детектить headless-браузеры и может забанить.

- `headless: false` — окно видно, безопаснее, **рекомендую**
- `headless: true` — окно скрыто, быстрее, выше риск детекта

Меняется в `config.yaml` (`session.headless`) или флагом `--no-headless` / `--headless`.

**Правила безопасности:**
- Задержки между действиями не меньше 3-8 секунд (`session.min_delay_seconds`)
- Не больше 20-40 Connect-запросов в день
- Не больше 50-100 комментариев в день
- Сначала всегда `--dry-run`

---

## Если что-то сломалось

### `ANTHROPIC_API_KEY not set`
Проверь что файл `.env` лежит в корне проекта и в нём вписан ключ.

### `Playwright browser not found`
```bash
playwright install chromium
```

### Linux: отсутствуют системные библиотеки
```bash
sudo playwright install-deps chromium
```

### `Not logged in`
Cookies протухли. Перелогинься:
```bash
linkedin-worker login
```

### LinkedIn просит подтверждение по почте / телефону при логине
Подтверди вручную в браузере, потом нажми Enter в терминале — `linkedin-worker login` дождётся.

### Аккаунт заблокировали / "временно ограничили"
Снизь активность:
- Подними задержки: `min_delay_seconds: 8`, `max_delay_seconds: 15`
- Уменьши `batch_size` до 5
- Гоняй с `headless: false`
- Не больше 20 Connect / 50 комментов в день

---

## Стоимость

- **200 сообщений ≈ $0.60** через Anthropic API
- Claude Sonnet: input ~$3 / 1M токенов, output ~$15 / 1M токенов

---

## Где что лежит

```
.
├── src/linkedin_worker/    # код воркера
├── tests/                  # тесты (необязательно для запуска)
├── config.example.yaml     # шаблон конфига
├── .env.example            # шаблон .env
├── setup.sh / setup.bat    # установщики
├── import_cookies.py       # импорт cookies из расширения браузера (опционально)
└── data/                   # cookies, БД, скриншоты (создаётся при первом запуске)
```

`data/` в gitignore — туда складываются твои cookies и БД с историей. Не делись этой папкой ни с кем.
