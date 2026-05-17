# LinkedIn Worker

Автоматизация холодного аутрича в LinkedIn: парсит поиск, комментирует посты, шлёт Connect и DM. Сообщения и комменты генерит Claude AI под твой стиль и контекст.

## Быстрый старт

1. Распакуй архив, открой терминал в папке
2. **macOS/Linux:** `./setup.sh` &nbsp;&nbsp; **Windows:** `setup.bat`
3. Открой `.env`, впиши `ANTHROPIC_API_KEY` ([получить](https://console.anthropic.com/settings/keys))
4. Открой `config.yaml`, настрой под себя (комментарии внутри)
5. Логин: `linkedin-worker login`
6. Запуск: `linkedin-worker connect --dry-run` (превью) → `linkedin-worker connect`

Полная инструкция: **[INSTALL.ru.md](INSTALL.ru.md)**

## Три команды

- **`run`** — DM существующим связям (1st-degree)
- **`connect`** — комменты на чужие посты + Connect-запросы
- **`dm-recent`** — DM тем, кто принял Connect

## Что нужно

- Python 3.11+
- Anthropic API ключ (баланс от $5; 200 сообщений ≈ $0.60)
- 5 минут на настройку

## Безопасность

- Не превышай 20-40 Connect и 50-100 комментов в день
- Задержки в `config.yaml` не опускай ниже 3 секунд
- Сначала всегда `--dry-run`
- Cookies и БД в `data/` — не делись этой папкой
