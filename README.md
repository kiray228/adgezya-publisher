# Публикатор «Адгезия»

Публикует посты в Instagram и Threads по расписанию через официальные API — без браузера.

- `queue.json` — очередь: `id`, `when` (время по Алматы, `ГГГГ-ММ-ДД ЧЧ:ММ`), `type` (`image` / `carousel` / `reel` / `text`), `platforms`, `media` (пути в `media/`), `caption`, `threads_text` (необязательно — отдельный текст для Threads).
- `media/` — картинки и видео; платформы скачивают их по публичной ссылке GitHub Pages.
- `state/published.json` — журнал: что опубликовано, ссылки, ошибки. Повторно пост не публикуется.
- `.github/workflows/publish.yml` — запуск каждый час; вручную: Actions → «Публикация по расписанию» → Run workflow (можно указать `only` = id поста).
- `.github/workflows/refresh.yml` — продление ключей по понедельникам.

## Секреты (Settings → Secrets and variables → Actions)

| Имя | Что это |
|---|---|
| `IG_TOKEN` | ключ Instagram API (developers.facebook.com → приложение → Instagram → Generate token) |
| `THREADS_TOKEN` | ключ Threads API (приложение → Threads → токен пользователя) |
| `GH_PAT` | личный токен GitHub с правом «Secrets: Read and write» на этот репозиторий — для автопродления ключей |

Ключи никому не пересылать и не вставлять в файлы репозитория.
