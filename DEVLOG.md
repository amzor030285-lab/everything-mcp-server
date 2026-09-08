# Журнал разработки (devlog)

## 2026-09-09 — Миграция на MCP SDK 2.x (v3)

**Автор:** Времес (агент main) по запросу владельца.
**Причина:** пакет `mcp` обновился до 2.1.1 (глобальный Python 3.14, user-site), сервер падал при старте: `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` → gateway ловил «MCP error -32000: Connection closed».

### Что изменено (everything_mcp_server.py)
- `from mcp.server.fastmcp import FastMCP` → `from mcp.server.mcpserver import MCPServer`.
- `FastMCP("EverythingSearch")` → `MCPServer("EverythingSearch")`.
- Больше ничего: по migration guide v1→v2 декоратор `@mcp.tool()`, сигнатуры обработчиков и `run(transport="stdio")` не изменились; внутренние переименования (snake_case поля, McpError→MCPError, AnyUrl→str, httpx→httpx2) этот сервер не затрагивают (он ходит в Everything по HTTP через `requests`, а не через клиентский транспорт SDK).

### Как проверялось
- E2E-тест по stdio (сабпроцесс + JSON-RPC): `initialize` → OK; `tools/list` → `[search_files, get_search_tips]`; `tools/call get_search_tips` → OK; `tools/call search_files` («ext:md dm:today», 3 результата) → реальные данные от Everything HTTP (`[showing 3 of 2500 total]`, пути+размеры+даты, подсказка offset).
- Версии: `mcp==2.1.1`, Python 3.14.0. Даунгрейд SDK не используется.

### Заметки
- Владелец просил НЕ пинать `mcp<2`, а обновить код — так и сделано.
- `mcp.exe` ставится в `…\Python314\Scripts`, который вне PATH (warning pip) — на работу сервера не влияет.
- Если SDK снова сломает API (3.x) — первым делом смотреть traceback импорта, затем migration guide: py.sdk.modelcontextprotocol.io/v2/migration/

---

## 2026-08-25 — Исправление багов поиска (v2)

**Автор:** ox-alpha (агент) по запросу владельца.
**Бэкап:** `everything_mcp_server.py.bak` — оригинальная версия до всех правок (6147 байт). Для отката просто скопировать обратно.

---

### 1. Что было найдено (анализ + живые тесты)

Все пункты подтверждены экспериментально GET-запросами к `http://127.0.0.1:8888/` (Everything был запущен):

| # | Баг | Доказательство |
|---|-----|----------------|
| 1 | Размер файла всегда «unknown size» | В запросе не было `size_column=1`, Everything отдаёт поле `size` только при явном запросе колонки. `_format_size()` всегда получала `None` |
| 2 | Даты изменения не возвращались, хотя docstring обещал | Не запрашивалась `date_modified_column=1`. Формат — Windows FILETIME (строка тиков по 100 нс с 1601 г.), требует конвертации |
| 3 | Защита от широких запросов фиктивна | Регэксп `^[\*\s]+$` блокировал только `***`. Запрос `e` проходил и давал `totalResults=5 401 231`; агент получал 50 строк из 5.4 млн без предупреждения |
| 4 | Мёртвый код | Ветка `[WARNING] Server returned N items...` не могла сработать: сервер уважает `count` (проверено: count=150 → ровно 150 элементов) |
| 5 | `get_search_tips()` учил неверному синтаксису | `folder:x` в Everything = «папки С ИМЕНЕМ x», а не «искать внутри папки» (подтверждено: `folder:windows` вернул только type=folder). `size:huge` = 16 МБ–1 ГБ, а не «>100mb» |
| 6 | Нет пагинации | `offset` сервером поддерживается (проверено), но инструментом не выставлялся; потолок 100 результатов нельзя было обойти |
| 7 | Мелкие проблемы | Проверка длины query шла до `strip()`; избыточный `isinstance(max_results, int)`; голый `except Exception` глотал собственные баги; URL/порт/таймаут захардкожены |

Пустой запрос `search=` Everything принимает и отдаёт всю базу — своя валидация пустоты обязательна (была и осталась).

---

### 2. Что изменено

#### everything_mcp_server.py
- **Запрос:** добавлены `size_column=1&date_modified_column=1&count=&offset=` в URL.
- **Новое:** `_format_filetime()` — конвертация FILETIME → `%Y-%m-%d %H:%M` (учтены None/мусор/переполнение).
- **Новое:** `_get_total_results()` — безопасное извлечение `totalResults`.
- **Новое:** `_validate_query()` — strip → длина → защита от широких запросов (минимум ~2 значимых символа после удаления `*` и пробелов).
- **Изменено:** формат строки результата: `имя -> путь (размер, дата)`.
- **Изменено:** заголовок выдачи `[showing N of M total]` + подсказка следующего offset вместо мёртвого WARNING.
- **Новое:** параметр `search_files(..., offset=0)` для пагинации.
- **Исправлено:** tips — пороги size:, честное описание `folder:`, скоуп через `parent:` или имя папки в запросе.
- **Конфиг:** env-переменные `EVERYTHING_URL` (по умолчанию `http://127.0.0.1:8888/`) и `EVERYTHING_TIMEOUT` (5 с).
- **Обработка ошибок:** конкретные исключения (`ConnectionError`, `Timeout`, `RequestException`, не-JSON) вместо голого `except Exception`.
- **Docstring-подсказки инструментов** (видны LLM как description): в `search_files` добавлено правило «минимум ~2 значимых символа» и отсылка к `get_search_tips()`; у `get_search_tips` описано, когда его вызывать. Проверено через `mcp.list_tools()`.

#### README.md
- Сигнатура `search_files(query, max_results=50, offset=0)`, описание выдачи (размер + дата + счётчик).
- Новая секция Configuration с env-переменными.
- Обновлена секция Security.

---

### 3. Как проверялось (осторожно, реальная машина)

Только read-only GET к Everything, никаких изменений системы:

- `python -m py_compile` — OK; `python -m ruff check` — All checks passed.
- 10 живых тестов через импорт модуля: размеры/даты видны (`15.22 KB, 2026-08-24 17:09`); offset сдвигает выдачу; `e`, `***`, пустой — заблокированы; `max_results=0` и `offset=-5` отклонены; кириллица ОК («отчет» найден); hint при нуле результатов работает.
- Юнит-проверки хелперов: `_format_size(None/8997/0/"abc"/1.5GB)`, `_format_filetime(валидный/None/junk)` — все случаи покрыты.
- Регистрация инструментов MCP: `mcp.list_tools()` → `search_files(query, max_results, offset)`, `get_search_tips()`.
- Временный тестовый скрипт удалён после проверки.

---

### 4. Известные компромиссы / заметки на будущее

- Односимвольные запросы (`a`, `1`) теперь отклоняются защитой от широких поисков — осознанный компромисс.
- Выдача ограничена 100 строками за вызов; для большего — offset-пагинация.
- Файл `nul` в корне репо — старый артефакт Windows (`> nul`), не трогали (удаляется только через `\\?\`-путь).
- Если порт 8888 занят другим приложением — переопределить `EVERYTHING_URL`.
