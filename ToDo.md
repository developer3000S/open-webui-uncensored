# ToDo — открытые задачи

> Обновляется после каждой завершённой задачи. Полный список переменных и
> инструкции — в README.md (раздел «Работа с Coder»).

## Coder-секция

- [ ] **Вписать реальные OAuth-креды** в `.env`: `CODER_GITHUB_CLIENT_ID` и
      `CODER_GITHUB_CLIENT_SECRET` от созданного OAuth-приложения GitHub
      (Settings → Developer settings → OAuth Apps). Callback URL:
      `http://<host>:8083/api/v1/coder/github/auth/callback`.
- [ ] **Перезапустить контейнер** после правки `.env`, чтобы приложение
      подхватило переменные и применило Alembic-миграцию (`coder_*` таблицы).
- [ ] **Проверить подключение GitHub** в разделе Coder (кнопка
      «Подключить GitHub» → редирект на OAuth → возврат с установленным
      соединением).

Сделано ранее:
- [x] `CODER_ENCRYPTION_KEY` сгенерирован и вписан в `.env`.
- [x] `.env` очищен от нечитаемых кодом Coder-переменных (см. Warning в README).
