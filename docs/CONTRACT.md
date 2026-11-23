# Контракт проекта lab-chat

Этот файл — источник правды. Если код расходится с ним, прав контракт.
Меняет его только интегратор (главный агент), остальные агенты только читают.

## 1. Зоны ответственности

| Папка | Владелец | Что внутри |
|---|---|---|
| `content/modules/` | контент-агенты | шаблоны шагов `m01_samba.json` … `m09_browser.json` |
| `app/` | backend-агент | FastAPI, БД, auth, LLM, SSE |
| `web/` | frontend-агент | HTML, CSS, JS, vendor |
| `shared/` | интегратор | модель варианта, компилятор, рендер шага |
| `tools/`, `deploy/`, `docs/` | интегратор | скрипты, деплой, документация |

Никто не пишет за пределы своей папки. Общие схемы не правятся без интегратора.

## 2. Модель варианта (задание)

База — методичка. Задание переопределяет только то, что в нём явно написано.
Реализация: `shared/params.py` (`DEFAULTS`, `normalize`, `flatten`, `render`).

Значения по умолчанию: домен `au-team.irpo`, `P@ssw0rd`, HQ-SRV `192.168.0.1`,
HQ-CLI `192.168.0.65`, HQ-RTR `192.168.0.62`, BR-SRV `192.168.1.30`,
ISP `172.16.1.14`, RAID 0 из 2 дисков, монтирование `/raid0`, порт 8080.

Производные поля считает `normalize()`, их нельзя задавать в шаблонах вручную:
`storage.disks`, `storage.devices`, `storage.devices_str`, `storage.md`,
`storage.mount`, `storage.raid_name`, `nfs.export`, `nfs.server`, `nfs.client_host`.

Минимум дисков: RAID 0/1 — 2, RAID 5 — 3, RAID 6/10 — 4.

## 3. Шаблон модуля

```json
{
  "module": 2,
  "title": "Файловое хранилище: RAID",
  "goal": "Собрать программный RAID и смонтировать его",
  "steps": [
    {
      "id": "2.1",
      "title": "Список дисков",
      "action": "Покажи список дисков и найди свободные.",
      "command": "lsblk",
      "gui": null,
      "check": "видны свободные диски",
      "pitfalls": ["имена дисков могут отличаться"],
      "image": "assets/img/image23.png",
      "requires": {"storage.raid_level": [0, 1, 5, 10]},
      "exclude": null
    }
  ]
}
```

Правила:

- `id` = `"<модуль>.<порядок>"`, уникален, префикс совпадает с `module`.
- `action` — 1–2 предложения, без «теперь», «итак», «пожалуйста».
- `command` — дословно из методички, параметры через `{{...}}`. Для GUI-шага `null`.
- `gui` — путь кликов («Система → Администрирование → …»). Для командного шага `null`.
- `check` — одна строка, по чему понять, что шаг выполнен.
- `pitfalls` — 0–2 короткие строки, только если в методичке есть предупреждение.
- `requires` — условие включения шага, `exclude` — условие исключения.
  Если `requires` нет, шаг есть у всех.
- `image` — путь относительно `content/`, либо `null`.
- Один шаг = одна команда или одно действие в интерфейсе.

## 4. Компиляция

`shared/compiler.compile_plan(variant, modules)`:

1. `normalize(variant)` → плоская карта параметров.
2. Модули идут в порядке `variant.modules`.
3. Шаги фильтруются по `requires` / `exclude`.
4. Все строки рендерятся: `{{key}}` → значение. Неизвестный ключ = ошибка.
5. Нумерация сквозная с 1 до N, поля `num` и `total`.

Проверка: `python tools/validate_modules.py` — собирает план для RAID 0/1/5/10.

## 5. Текст шага

Единственный формат, отдаётся фронту как готовый markdown (`shared/render.py`):

```
**Шаг 12/58 · Модуль 2: Файловое хранилище: RAID**

**Что делать:** Собери массив из 4 дисков.

```bash
mdadm --create --verbose /dev/md0 -l 10 -n 4 /dev/sdb /dev/sdc /dev/sdd /dev/sde
```

**Готово, если:** lsblk показывает md0
```

Модель этот текст не переписывает. Кнопка «Дальше» просто берёт следующий
шаг из плана, без вызова API.

## 6. HTTP API

Все ответы JSON, ошибки `{"error": {"code": "...", "message": "..."}}`.
Cookie-сессия `sid` (HttpOnly, SameSite=Lax, 12 часов).

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| POST | `/api/login` | `{username, password}` | `{user}` + cookie |
| POST | `/api/logout` | — | 204 |
| GET | `/api/state` | — | `{user, phase, variant, sources, unknown, progress, step}` |
| POST | `/api/intake` | `{text}` | `{variant, sources, unknown, warnings}` |
| POST | `/api/intake/confirm` | `{variant}` | `{step, progress}` |
| POST | `/api/chat` | `{text, client_msg_id}` | SSE |
| POST | `/api/next` | `{client_msg_id}` | `{step, progress}` |
| POST | `/api/jump` | `{to}` | `{step, progress}` |
| POST | `/api/restart` | — | `{step, progress}` |
| POST | `/api/variant` | `{variant}` | `{step, progress}` |

`phase`: `intake` (задание не принято) → `confirm` (карточка показана) → `chat`.

`variant` для `/api/intake/confirm` и `/api/variant` — вложенный объект. Поля
считаются заданными пользователем, если отличаются от сохранённых; в `sources`
они получают `source="user"`. Значения, взятые из базы методички, идут с
`source="method"`, найденные в тексте задания — `exam`, дозаполненные моделью — `model`.

`step` в ответах:

```json
{"num": 12, "total": 58, "id": "2.2", "module": 2,
 "module_title": "...", "markdown": "**Шаг 12/58 ...**", "image": null}
```

`progress`: `{idx, total, can_advance}`.

`/api/next` и `/api/jump` продвигают шаг только если `can_advance` истинно;
иначе 409 `{"error":{"code":"not_ready"}}`.

## 7. SSE-протокол `/api/chat`

```
event: meta
data: {"intent": "question", "step_num": 12, "model": "deepseek-chat"}

event: delta
data: {"text": "Ошибка в имени диска. "}

event: done
data: {"can_advance": true, "progress": {"idx": 12, "total": 58}}
```

`intent`: `question`, `error`, `off_topic`, `advance`, `jump`, `restart`,
`edit_variant`. Для `advance` сервер сам шлёт `event: step` и `event: done`,
без обращения к модели.

`client_msg_id` — uuid от фронта, защита от двойной отправки: повторный
запрос с тем же id возвращает 409 и не двигает шаг.

## 8. БД (SQLite, `data/app.db`)

```sql
users(id TEXT PK, username TEXT UNIQUE, pass_hash TEXT, display_name TEXT);
auth_sessions(id TEXT PK, user_id TEXT, expires_at INTEGER);
chats(user_id TEXT PK, variant TEXT, sources TEXT, unknown TEXT, plan TEXT,
      current_idx INTEGER DEFAULT 0, can_advance INTEGER DEFAULT 0,
      phase TEXT DEFAULT 'intake', updated_at INTEGER);
messages(id TEXT PK, user_id TEXT, role TEXT, kind TEXT, content TEXT,
         step_num INTEGER, created_at INTEGER);
seen(user_id TEXT, client_msg_id TEXT, PRIMARY KEY(user_id, client_msg_id));
```

`plan` — JSON-массив шагов после компиляции. `current_idx` — номер шага с 1,
`0` значит «ещё не начали».

Пароль: `hashlib.scrypt`, формат `scrypt$n$r$p$salt_b64$hash_b64`.

## 9. LLM-слой

Модели из `.env`: `MODEL_MAIN` (DeepSeek V4.1 Flash, id уточнить через
`GET /models`), `MODEL_REASONER` (опционально, только для `error`).

Первый шаг — дешёвый классификатор (non-stream, `temperature=0`,
`max_tokens=30`, `response_format={"type":"json_object"}`):

```json
{"intent": "question|error|jump|restart|advance|off_topic|edit_variant",
 "target": "12" | "2.3" | null}
```

Детерминированный роутер срабатывает раньше модели: `дальше/next/готово/ок/да`
→ `advance`; `шаг N` / `N.N` → `jump`; `заново/с начала` → `restart`.

Ответ на `question` / `error` / `off_topic` — стрим, `temperature=0.3`,
`max_tokens=400`, системный промпт `app/prompt_system.md`.

Правила промпта: русский, максимум 4 строки, без приветствий и извинений,
без забегания вперёд, команды строго из текущего шага, при ошибке —
причина (1 строка) → исправление → «Дальше?».

Таймаут 60 с, один ретрай на 429/5xx. `reasoning_content` в браузер не отдаётся.

## 10. UI

Тема и разметка — `docs/THEME.md`. Кратко: чёрный фон, белый текст,
моноширинный шрифт, тонкие границы, без теней и градиентов.

Обязательные элементы: логин, карточка задания с редактируемыми полями и двумя
группами «ИЗ ЗАДАНИЯ» / «ИЗ МЕТОДИЧКИ», лента сообщений, поле ввода с кнопкой
«Дальше», шапка `Шаг 12/58 · Модуль 2`, кнопка копирования у каждого блока
команды, переход к шагу по номеру.

## 11. Чего не делаем

- Регистрации и восстановления пароля.
- Рейт-лимитов.
- Админки (пользователи создаются скриптом).
- Мобильного приложения (только адаптивная вёрстка).
- Загрузки файлов в чат.

## 12. Готовность

- `python tools/validate_modules.py` — без ошибок.
- `uvicorn app.main:app` поднимается, логин работает.
- Intake → карточка → подтверждение → шаг 1.
- «Дальше» двигает шаг, откат по номеру работает.
- Вопрос и ошибка дают короткий ответ, шаг не двигается.
- `python tools/smoke.py` проходит на заглушке модели (без реального ключа).
