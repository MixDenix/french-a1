# Français A1+ — тренажёр французского

Один файл на стандартной библиотеке Python. Чат: бот говорит по-французски
короткими фразами (уровень A1), переводит на русский, мягко исправляет ошибки.

## Деплой на Northflank

1. New Service → Deploy from repository → этот репозиторий, ветка `main`.
2. Build type: **Dockerfile**.
3. Networking → Add port: **8080**, HTTP, Public.
4. Environment variables:
   - `OPENAI_API_KEY` — ключ DeepSeek
   - `OPENAI_BASE_URL` = `https://api.deepseek.com/v1`
   - `MODEL` = `deepseek-chat`
   - `PORT` = `8080`
5. Advanced → Health check: HTTP, путь `/`.

Память: ~40 МБ, влезает в бесплатный план (256 МБ).
