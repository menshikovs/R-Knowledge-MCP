# P0 — Benchmark Runner Regression Repair

Дата проверки: 2026-10-25. Работа выполнена офлайн; платные и внешние API-запросы не запускались.

## Executive Summary

Подтверждены четыре группы причин: две устаревшие группы тестовых fixtures, nullable-ошибка в Dashboard v2 и ошибочное ожидание теста выбора default run. Они объясняют основные семейства из исходного отчёта: 30 ошибок в interrupt/telemetry tests, 46 ошибок executor/lifecycle tests и 2 ошибки analytics. В текущей Windows-среде эти группы нельзя полностью перепроверить, поэтому число фактически устранённых исходных failures не заявляется.

Изменены fixtures, чтобы они соответствовали действующим контрактам `prepare()` и spend control. В `queries.py` исправлен выбор первого непустого номера вызова. Production lifecycle, MCP server, scorer и сохранённые результаты не изменялись. В текущем CSV exporter уже есть колонка и mapping `tool_search_calls`; отдельный код для неё не потребовался.

## Root Cause Matrix

| Root cause | Исходные test families | Evidence | Fix | Regression coverage |
|---|---|---|---|---|
| `prepare()` fixture отставал от API | 21 `test_codex_simple_interrupts`, 6 `test_telemetry_integration` и 3 telemetry interruption tests | Runner вызывает `prepare(task, destination, scorer_choice)`; реальная `knowledge_pilot.prepare` принимает третий аргумент. Два monkeypatch callback принимали только два и останавливали trial до сценария теста. | Обновлены обе тестовые обёртки, production API не менялся. | Исправленные fixtures в соответствующих модулях. Interrupt модуль на Windows пропускается как Linux-only; интеграционные тесты заблокированы pytest temp ACL.
| Synthetic lifecycle fixtures не задавали обязательный spend-control limit | 11 executor contract и 35 durability failures из предоставленной сводки | `build_agent_config()` требует положительный целочисленный limit. Контроллер строит config до фиксации попытки создания сессии; без approval исключение остаётся на `create_session`, поэтому startup, CLI diagnostics и crash hooks не достигаются. | Добавлен привязанный к attempt synthetic approval и общий fixture helper. В контроллерных synthetic тестах временно подменяется только запрет на закрытый исторический attempt ID: helper проверяет fixture shape, identity и confirmation, а настоящий клиент по-прежнему проверяет положительный limit. | Новый тест fixture approval прошёл. Полные executor/durability suites не исполнились из-за недоступного pytest temp root.
| `pandas.NA` попадал в логическое выражение | Analytics nullable projection | Выражение `client_call_number or server_call_number` пытается преобразовать `pandas.NA` в `bool` и падает. | Добавлен `_first_non_null`: пропускает `None` и pandas missing values, но сохраняет корректный номер `0`. | 7 параметров проверки `None`, `pd.NA`, нуля, обоих fallback-вариантов прошли.
| Тест default run ожидал отсутствие выбора при наличии другого полного запуска | Analytics run selector | `default_run_id()` выбирает только `full_comparable`. Ошибочный scoring run частичный, поэтому независимый полный baseline остаётся допустимым default. Scorer-mismatch без другого полного run по-прежнему не выбирается. | Исправлено ожидание: выбирается `full-baseline`; добавлено отдельное ожидание `None` для одного scorer-mismatch run. | Интеграционный тест изменён, но не был выполнен из-за pytest temp ACL.
| В CSV могло отсутствовать наблюдение model-driven discovery | MCP diagnostics | В текущем `save_results()` уже объявлена колонка `tool_search_calls` и переносится `mcp_usage.tool_search_calls`. Существующий regression test ожидает значение `1`. В данном checkout код mapping присутствует. | Дополнительное изменение не вносилось; round-trip тест заблокирован pytest temp ACL. | Тест `test_results_csv_reports_discovery_and_server_columns` сохранён без изменения.

Ошибки `start_executor`, отсутствующий `cli_nonzero`, `not_attempted` и `UNCLASSIFIED_ERROR` рассматриваются как каскады неподходящих fixtures: без валидного synthetic spend-control setup соответствующие executor и stream сценарии не запускались. Имена lifecycle stages и классификатор не менялись.

## Code Changes

- `tests/test_codex_simple_interrupts.py`: monkeypatch `prepare` принимает аргумент выбора scorer.
- `tests/test_telemetry_integration.py`: wrapper передаёт scorer choice в настоящий `prepare`.
- `tests/test_codex_executor_contract_integration.py`: добавлены явная synthetic spend-control фикстура и contract test; executor сценарий получает тот же attempt ID.
- `tests/test_codex_lifecycle_durability.py`: durability fixture использует общий approval и attempt ID, чтобы crash hooks достигали реальных lifecycle переходов.
- `benchmarks/codex_r/analytics/queries.py`: безопасное разрешение nullable call sequence.
- `tests/test_benchmark_analytics.py`: regression cases nullable projection и корректное ожидание default run.

В lifecycle synthetic tests действует узкая подмена проверки только для закрытого исторического attempt ID, потому что тестовый journal обязан использовать этот фиксированный ID. Подмена ограничена контекстом одного synthetic вызова; проверка привязки approval и тип/значение лимита остаются. Production код не менялся.

## Safety Verification

- Не отправлялись OpenAI, CRAN, Bioconductor или иные внешние запросы; платные сессии не запускались.
- Запущенные unit tests используют локальные данные; executor integration fixtures используют `httpx.MockTransport`. Полные controller tests в этой среде не дошли до выполнения.
- Не менялись production retry, uncertain outcome, session confirmation, cleanup, первичная ошибка, telemetry redaction или scorer logic. Для устранения fixture mismatch изменены только тестовые fixtures.
- Чувствительные значения в telemetry не добавлялись. Два существующих offline F10 теста на протокольную обработку и закрытое sanitization поведение прошли; остальные telemetry privacy tests не подтверждены запуском.
- Benchmark baseline не пересчитывался и не записывался. В каталоге baseline 121 файл; сводный SHA-256 до и после работы: `8e96f1a7c168d1da29116d0624d9cd49056c21d4ea864f4e93d7c102b13ffab3`.
- Read-only повторная проверка baseline: 113/136 без MCP; 116/136 с MCP; fully correct 13/19 в обоих режимах; adoption 2/19; 57 MCP calls; 26 `docs_not_found`.

## Test Results

| Check | Result |
|---|---|
| Offline targeted pytest без `tmp_path` | 22 passed; один pytest warning о `cache_dir`, так как cache plugin отключён на время запуска. В выборку вошли nullable cases, error taxonomy, spend-control contract, MCP usage/audit parsing и два F10 теста. |
| `tests/test_codex_simple_interrupts.py` | 26 skipped на Windows: модуль предназначен для Linux. |
| `tests/test_benchmark_analytics.py` | 13 passed, 16 errors. Ошибки происходят при создании `tmp_path`: `PermissionError [WinError 5]` на basetemp, до выполнения соответствующих тестов. |
| WSL/Linux pytest | Не запустился: WSL вернул `E_ACCESSDENIED` для `/mnt/c/programming_pj/cran-mcp`; `.venv-wsl/bin/python` недоступен в этой среде. |
| Полный pytest после исправлений | Результат не получен. Windows temp ACL блокирует pytest fixtures; Linux runtime недоступен. Предоставленные ранее 1 278 passed / 79 failed / 31 skipped относятся к исходному запуску, не к этому исправленному checkout. |
| `ruff check .` | Exit 0, `All checks passed!`; Ruff вывел предупреждения `Access is denied` при обходе защищённых scratch directories. Проверка шести затронутых Python файлов также прошла. |
| `ruff format --check` для шести затронутых файлов | Passed: все файлы уже отформатированы. |
| `ruff format --check .` | Не прошёл: Ruff завершился panic `Expected a ruff source file` при полном обходе рабочей области с недоступными scratch directories. |
| `py_compile` шести затронутых Python файлов | Passed. |

## Remaining Risks

- Нельзя утверждать, что исходные 79 failures устранены: требуемые Linux-only и `tmp_path` suites не прошли фактическое повторное выполнение.
- Требуется повторить семь целевых test modules и полный pytest в WSL/Linux с доступным `/tmp`, затем повторить полный Ruff format check в рабочей области без защищённых scratch directories.
- CSV export round-trip, полный lifecycle crash matrix, interruption cleanup и telemetry privacy regressions остаются непроверенными запуском в текущей среде. Результаты baseline при этом подтверждены read-only и не изменены.
- Проверка temp ACL показала, что Python-created temporary folders остаются недоступными даже при размещении под workspace; система также запретила их очистку. Защищённые scratch-каталоги, включая `benchmarks/codex_r/reports/.p0-temp-root-probe-20261025`, оставлены нетронутыми; ACL не изменялись.
- B1 не начинался.
