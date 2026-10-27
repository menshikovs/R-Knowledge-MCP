# P1-C — исправление экспозиции MCP-инструментов

## Итог

Причина нулевого числа вызовов `list_package_functions` в стандартном прогоне
`20261026T155642Z-05edb0df` — инструмент входил в зарегистрированный сервер, но
отсутствовал в benchmark allowlist. Runner строил из этого списка конфигурацию
инструментов агента. Поэтому он не был доступен агенту в том прогоне. Само по себе
старое поле metadata показывало несовпадение списков; фактический механизм ограничения
подтверждён трассировкой запроса создания сессии и тестом с `httpx.MockTransport`.

`suite_for()` в `benchmarks/codex_r/run_simple.py` выбирает задачу, toolset и allowlist.
`SimpleClient.create_simple_session()` передаёт результат `agent_mcp_tools()` в
`POST /v1/agents/sessions`, в `agent.tools[].allowed_tools`. Это конфигурация для
Agents API, а не только описание в metadata. `without-mcp` передаёт `tools: []`.

## Политика toolset

Стандартный consolidated allowlist теперь содержит 13 инструментов:

```text
search_packages, get_package, get_function_docs, list_package_functions,
check_package_version, check_r_compatibility, search_r_documentation,
get_r_documentation_section, get_framework_docs, get_r_workflow_guidance,
analyze_r_source, analyze_r_project, recommend_technology_stack
```

`build_r_prompt`, `get_r_prompt_context` и `validate_r_prompt` остаются исключёнными.
Allowlist не заменён списком всех зарегистрированных инструментов. Проверка требует
наличия четырёх ключевых инструментов discovery/docs/package и разрешает серверу
регистрировать дополнительные инструменты, которых нет в allowlist.

Стандартный runner по умолчанию включает discovery. Флаг
`--function-discovery disabled` создаёт отдельную контрольную политику без
`list_package_functions`; явная политика сохраняется в metadata и переносится при
resume. Legacy задачи продолжают получать legacy allowlist.

Для B1 в `hard/manifest.json` зафиксирован исходный 12-инструментный список. B1 всегда
использует его и запрещает включать новый discovery tool. Существующие B1 результаты
не редактировались. SHA-256 проверены:

* `results/20261026T104750Z-f78eabf1/results.json`:
  `8dab038ca58f683c377e5684546a864cd01748c3e35c60f775af644b1b4e02e0`
* `scorer_evidence/knowledge_pilot_claims_v2_1.json`:
  `af2ce8d3a9ed944fa9179bcd4ae03138ffb26e1175f08471ed5ada17dadb864f`

Файлы исторического стандартного прогона, B1, frozen evidence и scorer output не
перезаписывались. В новых запусках metadata сохраняет allowlist по задаче, фактический
список `agent.tools` по режимам, зарегистрированные server tools и политику discovery.
Отдельный hash для allowlist схема metadata не задаёт; provenance новых запусков
содержит значения списков и обычное состояние Git-репозитория. Старые записи не
пересчитывались.

## Preflight и метаданные

`tool_exposure_preflight()` получает source server registry через локальный вызов
`create_server(...).list_tools()`, проверяет, что каждый разрешённый инструмент
зарегистрирован, строит фактическую структуру `agent.tools` и сверяет её с выбранным
режимом. Несвязанные зарегистрированные инструменты не являются ошибкой. Для
`without-mcp` ожидается пустой список.

`write_experiment_manifest()` записывает для каждой задачи `allowed_tools_by_task`,
`registered_tools_by_task`, `agent_tools_by_task_mode` и состояние проверки.
Дополнительно каждый trial сохраняет точный allowlist для своей MCP-конфигурации.
Regression tests сравнивают output metadata с ожидаемыми режимами и проверяют, что
удаление обязательного discovery tool ломает контракт.

Offline preflight подтверждает созданную конфигурацию, но не подтверждает живое
обнаружение инструментов удалённой сессией. В metadata это явно отмечено как
`generated_configuration: verified` и `live_mcp_discovery: unverified`.

## TUI

TUI не содержит отдельного списка разрешённых tools: источник списка остаётся в Python
runner/manifest. Стандартный `launcher_core.R::build_args()` явно передаёт
`--function-discovery enabled`; runner разрешает отдельно задать disabled. B1 ветка
не передаёт этот флаг и использует фиксированный список. Добавлены Python-проверка
паритета с runner и testthat regression для построения команд. Сам testthat здесь не
запускался: он требует Rscript, `termr` и `testthat`; вместо этого прошла offline
проверка исходного TUI command builder.

## Dashboard

Локальный `dashboard.py` уже содержал исправления пользователя; файл не переписывался.
Проверено, что `markdown_export()` используется как `str` в `_markdown_report()` и
сравнительном Markdown download, а ошибочных вызовов
`markdown_export(...).decode("utf-8")` в dashboard больше нет. Добавлен regression
test для обоих путей.

## Изменённые файлы P1-C

* `benchmarks/codex_r/hard/manifest.json`
* `benchmarks/codex_r/run_simple.py`
* `benchmarks/codex_r/launcher/launcher_core.R`
* `benchmarks/codex_r/launcher/README.md`
* `benchmarks/codex_r/launcher/tests/testthat/test-core.R`
* `tests/test_codex_hard.py`
* `tests/test_codex_simple.py`
* `tests/test_mcp_discovery.py`
* `tests/test_benchmark_analytics.py`
* `tests/test_bioc_benchmark.py`
* `tests/test_knowledge_pilot_v2.py`
* `tests/test_telemetry_integration.py`

## Проверки и ограничения

Offline targeted suite из runner, mocked Agents API, diagnostics, scorers, Bioconductor,
discovery и analytics завершился с **148 passed, 7 deselected, 1 failed**. Единственный
сбой оказался в новой B1-проверке: тест сравнивал per-task конфигурацию с устаревшим
общим полем `mcp_server.allowed_tools`. Проверка исправлена и привязана к frozen
12-tool контракту; затем B1 manifest regression и dashboard regression прошли отдельно:
**2 passed**.

Команда broad suite:

```text
.venv-wsl/bin/python -m pytest tests/test_codex_hard.py tests/test_codex_simple.py tests/test_codex_mcp_diagnostics.py tests/test_knowledge_pilot_v2.py tests/test_bioc_benchmark.py tests/test_mcp_discovery.py tests/test_benchmark_analytics.py -q --tb=short -m 'not docker' -o usefixtures=r01a_offline_guard
```

После broad suite повторный запуск через WSL был отклонён средой с `Wsl/Service/E_ACCESSDENIED`.
Windows fallback для двух исправленных regression tests завершился успешно. Попытка
повторить pytest через Windows virtualenv не дала надёжного результата: sandbox запретил
доступ к pytest temp root и локальному basetemp. Поэтому полный набор после исправления
того assertion не запускался целиком.

Успешный fallback для двух конкретных regression tests:

```text
.venv/Scripts/python.exe -m pytest tests/test_mcp_discovery.py::test_b1_single_run_manifest_captures_both_conditions_and_task_scoring tests/test_benchmark_analytics.py::test_dashboard_markdown_report_and_comparison_export_are_text -q --tb=short --basetemp=.pytest-tmp-p1c
```

* `ruff check .`: **All checks passed** (Windows virtualenv; Ruff показал предупреждения
  доступа к нескольким уже существующим временным каталогам).
* Полный `ruff format --check .` проходил в WSL до последней правки тестового assertion;
  изменённый `tests/test_mcp_discovery.py` отдельно проходит `ruff format --check`.
  Повторный полный Windows обход завершился внутренней ошибкой Ruff при сканировании
  запрещённых временных каталогов.
* Не запускались Docker, модели, Agents API, benchmark trials, Rscript/testthat, загрузки
  R packages или запросы CRAN/Bioconductor.

## Следующий эксперимент

Стандартный consolidated runner готов к новому контролируемому запуску. Для измерения
ценности discovery следует отдельно задать контроль с
`--function-discovery disabled` и treatment с `--function-discovery enabled`, при
одинаковых задачах, scorer, модели, prompt, effort, repetitions и остальных настройках.
Проверить их manifests и per-trial `allowed_tools` до запуска. Этот патч доказывает
доступность инструмента в конфигурации; он не доказывает, что модель выберет инструмент
или улучшит результат. Эксперимент в рамках P1-C не запускался.
