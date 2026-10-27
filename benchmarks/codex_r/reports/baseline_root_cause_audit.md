# Root Cause Audit: полный baseline R-Knowledge-MCP

Дата аудита: 2026-10-25. Единственный исследуемый запуск: **20261025T135949Z-9ff06c47**.
Это офлайн-анализ сохранённых данных; B1/B2 не реализованы и не запускались.

## 1. Executive Summary

**Исходные числа подтверждены, но их содержательная трактовка требует пересмотра.**
В 19 парах A/B получено 113/136 (83.09%) и 116/136 (85.29%) checks,
то есть +3 checks, +2.21 процентного пункта. Полностью решено **13/19 в обоих
условиях**. MCP вызван в 2/19 задач B (10.53%); всего 57 вызовов. Изменения:
D01 +3, E04 +1, H10 −1, остальные 16 задач без изменения score.
E04 и H10 не обращались к MCP: это изменения между trials, не установленный
эффект MCP. Источники: [results.json](../results/20261025T135949Z-9ff06c47/results.json),
`$[*].score`, `$[*].mcp_usage`; [пересчёт](baseline_audit_data.json), `$.scores`, `$.pairs`.

Пять наиболее существенных проблем:

1. **Скрытый контракт JSON искажает E01/E05 (C7, high).** Оба E01 правильно предлагают
   R 4.5.2 при сохранении Bioconductor 3.22 и package pins, но получают 0/6 из-за
   строковых значений, форм объектов и дополнительных edges. Оба E05 правильно
   классифицируют три сценария, но получают 1/5: scorer ожидает словарь со скрытыми
   ключами, точное равенство `positive_package` и строки в `sources`.
   Основания: разделы 7–8; `knowledge_pilot.py::_compatibility_checks`;
   соответствующие `artifacts/answer.json`.
2. **Открытые D-задачи проверяются закрытым набором кандидатов (C7, high для механизма
   отказа; unknown для полной предметной корректности альтернатив).** D01 A выбирает
   `utils`, D02 B — `httptest`: оба отсутствуют в allowlist. Три проверки D02 B
   проваливаются через `expected={}`, поэтому 1/4 не доказывает плохой ответ MCP.
   Основания: разделы 5–6; `verifier/candidates.json`; `_score_recommendation`.
3. **57 вызовов нельзя связать с полным содержимым ответов (C9, high для пробела).**
   `redact_mcp_events` намеренно удаляет аргументы и результаты; сохранены идентичности
   вызовов и агрегированная серверная телеметрия. Причинная цепочка D01 подтверждается
   по порядку событий и итоговым изменениям лишь косвенно. Источник:
   `run_simple.py::redact_mcp_events`, `D01-B-1/events.json`, `$.item.payload_redacted`.
4. **Низкая adoption наблюдается; её психологическая/интерфейсная причина не установлена
   (C9).** Для каждого B зафиксирован один запрос `tools/list`, а не доказанное
   осознанное обнаружение инструмента. 12 задач без MCP уже решены B полностью.
   Локальные метаданные и инструкции «test locally with installed R» дают альтернативный
   путь; это объясняющая гипотеза, не установленный мотив. Основания: раздел 9.
5. **Поток docs-запросов неэффективен (наблюдение high, причина C9).**
   49/57 вызовов — `get_function_docs`; 26/49 возвращают `docs_not_found`;
   в D01 три точных повтора по серверному fingerprint. Нельзя восстановить,
   какие aliases угадывались, или доказать, что все остальные запросы лишние.
   Основания: раздел 10; [57 строк вызовов](baseline_tool_calls.csv).

Приоритет: сначала определить прозрачные измеряемые критерии и сохранить безопасную
наблюдаемость, затем проверять B1 (видимость существующих возможностей) и B2
(маршрут выбора/остановки запросов). Расширение toolset этим baseline не обосновано.

## 2. Источники данных и ограничения аудита

В дальнейшем **R/** означает относительный от корня репозитория путь
`benchmarks/codex_r/results/20261025T135949Z-9ff06c47/`, **K/** —
`benchmarks/codex_r/knowledge_pilot/`. Индексы `$[n]` в `events.json` — **с нуля**;
`calls[n]` — индекс серверной телеметрии, sequence в CSV — с единицы.
Так, `R/D01-B-1/events.json#$[123].item` однозначно задаёт первичный источник.

Изучены все 121 файла R/: `experiment.json`, `results.json`, `results.csv`,
38 `result.json`, 38 `events.json`, 38 файлов artifacts, `telemetry.jsonl`,
`mcp_calls.csv`, `mcp_metrics.csv`, `mcp_tool_aggregates.csv`.
Также прочитаны `AGENTS.md`, benchmark README, `run_simple.py`, описания
`runner/`, `hard/`, `configs/`, 19 prompts, fixtures, metadata, scorer и
соответствующие `server.py`, `service.py`, `providers/base.py`, `telemetry.py`,
release/compatibility contracts. [Инвентарь SHA-256](baseline_audit_data.json),
`$.source_run_inventory_sha256`, позволяет проверить каждый файл R/.

Основные источники проверки:

| Источник | Что подтверждает | Граница |
|---|---|---|
| [experiment.json](../results/20261025T135949Z-9ff06c47/experiment.json) | plan, модель, effort, toolset, allowlist, runtime, source digests, task hashes | snapshot деклараций; нет сохранённого полного ответа session creation и tool schemas |
| R/*/result.json | score, failed checks, artifact hashes, provenance, cleanup, server audit | не содержит полных MCP-ответов |
| R/*/events.json | доставленный user prompt, команды и их outputs, сообщения, MCP item IDs | MCP payload redacted; reasoning summaries пусты, внутреннее рассуждение не доступно |
| R/telemetry.jsonl | отдельные client/server observations, timestamps, status, bytes, latency | server/client correlation прямо помечена `ordinal_unconfirmed` |
| [knowledge_pilot.py](../knowledge_pilot.py) | действующие локальные JSON-предикаты D/E | исторический SHA Python-scorer отдельно не сохранён |
| K/verifier/candidates.json и official_resources.json | frozen D-кандидаты, версии, разрешённые URLs | закрытый набор; не архив полного текста документации |
| K/metadata/E-source-snapshot.json | frozen mapping и direct dependency facts | нормализованные факты, исходные HTML/PACKAGES payload hashes отсутствуют |

Фактам даны метки **Observed** (непосредственный артефакт), **Inferred**
(обоснованная интерпретация), **Unknown** (нельзя установить). Уровень confidence
относится к указанному механизму, а не к вероятности полезности будущего изменения.
Текст финального ответа агента не использован как единственное подтверждение факта.
Другие benchmark-runs не включались в численные сравнения и не заменяли отсутствующие
данные этого запуска. Внешние сайты не открывались, новые MCP-запросы не выполнялись.

## 3. Проверка целостности baseline

### 3.1. Plan, пары и условия

**Observed:** `experiment.json` содержит 19 задач × 2 modes × 1 repetition = 38 trials.
Идентификаторы summary, plan и индивидуальных `result.json` совпадают; дубликатов и
пропусков нет. Для всех 38 совпали `run_id`, task, mode, repetition, `gpt-6-luna`,
`medium`, `instructions=standard`, timeout 900 s и image IDs. Значения score и
MCP-учёта совпали между aggregate JSON и индивидуальными файлами. В `results.csv`
38 строк с теми же trial IDs и passed/total. Все 38 artifacts совпали с сохранёнными
SHA-256. Полный результат проверок — `baseline_audit_data.json#$.integrity_findings=[]`.

Доставленный текст user prompt во всех 38 events совпадает по SHA-256 с
`experiment.json#$.task_inputs_sha256[task].spec`: значит, A/B получили один prompt,
а не просто одинаковую метку задачи. Текущий `configs/renv.lock` совпадает с
manifest hash `3a6cfd804a979eb108ee9aa1308078f7a4a9e8a4ab722fd2223a2505631311e1`.
Task-specific inputs отдельно заданы в manifest: 13 input entries, включая
конфликтный E01 `renv.lock`; его нельзя подменять общим environment lock.

**Observed:** все 38 имеют trial/score status `scored`, `error=null`,
`session_deleted=true`, `cleanup_completed=true`, `cleanup_errors=[]`.
Нет trial/scorer timeout или environment mismatch, замаскированного под 0/6.
Внутри отдельных agent traces есть неуспешные команды, но это не ошибки запуска:
например, E01 A `$[191]` — отсутствует `python3`, затем JSON проверен R;
E05 B `$[118]` — `cat()` не принимает list от `BiocManager::valid()`, далее
проверка метаданных продолжена. Источник: соответствующие `events.json` и `result.json`.

### 3.2. Исторический toolset и дрейф исходников

**Observed:** историческая конфигурация — `consolidated-v1.1`, 15 зарегистрированных,
**12 разрешённых** инструментов. Разрешены:

`analyze_r_project`, `analyze_r_source`, `check_package_version`,
`check_r_compatibility`, `get_framework_docs`, `get_function_docs`, `get_package`,
`get_r_documentation_section`, `get_r_workflow_guidance`, `recommend_technology_stack`,
`search_packages`, `search_r_documentation`.

`build_r_prompt`, `get_r_prompt_context`, `validate_r_prompt` зарегистрированы, но
не разрешены этому baseline. Предлагать их как доступный агенту путь ошибочно.
Источник: `experiment.json#$.mcp_server.{registered_tools,allowed_tools}`.

Текущий source tree `src/**/*.py` совпал с историческим digest
`63a500a30ff2891719477d40adfe788301e34caca5e27c77595061200275e677`.
Поэтому прочитанные server descriptions и provider contracts относятся к тому же
снимку исходников, а не только к современной версии. Оба R verifier tree digests
тоже совпали: hard `0b316d2f9fdcf01366082b520f78e7f03067d1a4652278b4395f7da0eb148cf7`,
pilot `d8656c801e6c5f957d70ebb67780cbbf8b5869b96270d52abc7a1a3f1f79aa03`.
Для воспроизведения нужен регистрозависимый POSIX-порядок путей: Windows `sorted(Path)`
иначе сортирует `controls/` относительно `H01.R`. Экстрактор учитывает это явно.

**Unknown:** полный исторический Python runner/scorer не архивирован отдельным
SHA-256; manifest содержит dirty revision `f7e6e998c46e103620da1144888094e595a2d7e1`,
176 changed paths и общий dirty-tree fingerprint. Это не позволяет восстановить
их содержимое из одного commit. Версии D/E scorer сохранены (`d-recommendation-2`,
`e-compatibility-1`). После проверки чисто файловых веток существующего scorer
12 D/E JSON-artifacts повторно оценены **без изменения входов**, сети, Docker, R,
тестов или среды. Все status/passed/total/failed checks/artifact hashes совпали.
Это отдельная [контрольная переоценка](baseline_json_rescore.json), не исправленные
baseline scores и не доказательство побайтовой идентичности исторического Python-кода.

### 3.3. Метрики и корректные знаменатели

| Метрика | A | B / изменение |
|---|---|---|
| Tasks / trials | 19 / 19 | 19 / 19; всего 38 |
| Passed / total | 113/136 | 116/136; +3 |
| Доля passed checks | 83.0882% | 85.2941%; +2.2059 п.п. |
| Полностью решённые | 13/19, 68.4211% | 13/19, 68.4211% |
| Задачи с MCP calls | 0 (MCP не настроен) | 2/19, 10.5263% |
| Задачи B без calls | — | 17/19, 89.4737% |
| Calls на задачу B | — | 57/19 = 3; median 0 |
| Calls на использовавшую MCP задачу | — | 57/2 = 28.5 |
| Выше / ниже / равный score B | — | 2 / 1 / 16 |

«Выше score» не тождественно «MCP помог»: только один положительный сдвиг (D01)
сопровождается calls; E04 +1 и H10 −1 не имеют такого посредника. Один trial на
условие, фиксированный порядок A→B, разная длительность задач и свежие независимые
sessions не позволяют оценить воспроизводимый средний эффект или причинность.
Source: `R/experiment.json#$.trial_plan`, все `R/*/result.json`.

`usage` и `cost` во всех trials равны null, статусы unavailable. Их нельзя считать
нулевым расходом. В A `mcp_server_audit=null` означает отсутствие применимого сервера;
в B calls=0 подтверждены отдельно client count, audit и server telemetry. Неизвестные
bytes, relevance и использование конкретного ответа остаются null/unknown.

## 4. Сравнение всех 19 задач

`Да*` = сервер и allowlist настроены по manifest, audit содержит `list_tools_requests=1`;
это **не** сохранённый ответ `tools/list` и не событие осознанного выбора агентом.
Источники каждой строки: `R/<Task>-A-1/result.json#$.score`,
`R/<Task>-B-1/result.json#$.{score,mcp_usage,mcp_server_audit}`.

| Task | Score A | Score B | Delta | MCP available | MCP calls B | MCP tools | Result |
|---|---|---|---|---|---|---|---|
| H01 | 18/18 | 18/18 | 0 | Да* | 0 | — | Равно |
| H04 | 17/17 | 17/17 | 0 | Да* | 0 | — | Равно |
| H10 | 18/18 | 17/18 | −1 | Да* | 0 | — | B ниже, без MCP |
| B01 | 5/5 | 5/5 | 0 | Да* | 0 | — | Равно |
| B02 | 5/5 | 5/5 | 0 | Да* | 0 | — | Равно |
| B03 | 5/5 | 5/5 | 0 | Да* | 0 | — | Равно |
| C01 | 5/5 | 5/5 | 0 | Да* | 0 | — | Равно |
| C02 | 5/5 | 5/5 | 0 | Да* | 0 | — | Равно |
| C03 | 5/5 | 5/5 | 0 | Да* | 0 | — | Равно |
| C04 | 9/9 | 9/9 | 0 | Да* | 0 | — | Равно |
| C05 | 7/7 | 7/7 | 0 | Да* | 0 | — | Равно |
| D01 | 1/4 | 4/4 | +3 | Да* | 45 | get_function_docs 42; get_package 2; search_packages 1 | B выше, MCP использован |
| D02 | 1/4 | 1/4 | 0 | Да* | 12 | get_function_docs 7; get_package 5 | Равно при разных ответах |
| D03 | 2/4 | 2/4 | 0 | Да* | 0 | — | Равно |
| E01 | 0/6 | 0/6 | 0 | Да* | 0 | — | Равно, скрытая схема |
| E02 | 5/5 | 5/5 | 0 | Да* | 0 | — | Равно |
| E03 | 4/4 | 4/4 | 0 | Да* | 0 | — | Равно |
| E04 | 0/5 | 1/5 | +1 | Да* | 0 | — | B выше, без MCP |
| E05 | 1/5 | 1/5 | 0 | Да* | 0 | — | Равно, скрытая схема |

Машинно воспроизводимая версия: [baseline_comparison.md](baseline_comparison.md).
По каждой из 136 проверок есть строка с A/B в [baseline_failure_matrix.csv](baseline_failure_matrix.csv).
Пустое поле cause для успешного check не означает C9; причина там неприменима.

## 5. Подробный аудит D01

### 5.1. Что проверяли и что изменилось

Prompt `K/tasks/D01.md` требует терминальное keyboard single/multi-select,
стабильные возвращаемые значения отдельно от labels, fit/limits и official CRAN URLs.
`termr` прямо назван кандидатом, но не обязательным ответом. A выбирает `utils 4.5.2`,
B — `termr 1.0.1`. [A artifact](../results/20261025T135949Z-9ff06c47/D01-A-1/artifacts/answer.json),
[B artifact](../results/20261025T135949Z-9ff06c47/D01-B-1/artifacts/answer.json).

| Check | A → B | Наблюдаемый механизм |
|---|---|---|
| answer_shape | pass → pass | Оба следуют явной D JSON-схеме |
| accepted_package_and_version | fail → pass | utils отсутствует в candidates; termr 1.0.1 входит |
| official_source_and_docs | fail → pass | Для utils нет frozen entry; B даёт разрешённые termr archive/PDF URLs |
| documented_fit_and_limits | fail → pass | utils не имеет expected entry; B включает нужные feature/caveat IDs termr |

В A сообщения и локальные help outputs подтверждают реальную альтернативную
аргументацию, а не выдуманный пакет: `events.json $[97], $[100], $[103]` читают
installed `utils::menu`/`select.list`; `$[103]` содержит multi-select, возврат labels
и запрет non-interactive session. A оговаривает mapping labels→keys. **Unknown:**
эквивалентен ли этот вариант желаемому UX во всех деталях; scorer его не оценивает
по существу. В частности, `stable_return_values` потребует пользовательской обвязки.
Поэтому A 1/4 нельзя однозначно назвать knowledge failure. Основной наблюдаемый
механизм трёх отказов — C7 (high), предметная полнота A — отдельный вопрос.

### 5.2. Последовательность и предел причинного вывода

В `R/D01-B-1/events.json`:

| Event index | Наблюдение | Значение |
|---|---|---|
| 54, 65 | Список installed packages и exports локальных альтернатив | Предшествующий локальный поиск |
| 119 | Агент сообщает, что termr не установлен и проверит подключённый CRAN index | Наблюдаемый переход к MCP; самоотчёт о намерении |
| 123–125 | Завершены get_package, search_packages, get_package | Server telemetry calls 1–3: result package termr, unknown, cli; все ok |
| 138–147 | Первая серия из 10 docs calls | 9 docs_not_found, затем один ok |
| 168–185, 202–215 | Ещё 32 docs calls | Успехи, ошибки и три точных повтора |
| 314 | Сообщение про option_list(), checkbox(), test_app(), named choices и experimental APIs | Содержательное резюме агента после MCP |
| 321, 327 | Проверки answer.json через jsonlite; первая неудачна, вторая успешна | Проверка формы, не исполнение termr |
| artifacts/answer.json | termr 1.0.1, CRAN archive/PDF, headless/stable-value features и limits | Итоговое изменение относительно A |

**Inferred, medium:** MCP был информационным посредником выбора termr и его версии:
имя termr есть в prompt, пакет не установлен, metadata call сообщает verified result,
затем агент формулирует соответствующий fit и сохраняет его. Это сильнее простого
совпадения calls и score. **Unknown:** какой конкретный ответ содержал каждый факт,
не перепутал ли агент alias/семантику и был бы B успешен без этих ответов.
Payload у всех calls redacted, поэтому связывать `option_list` с определённым
call number как с доказанным исходным текстом нельзя. Никакого нового кода termr
агент не создавал: изменён JSON recommendation, а не реализовано приложение.

### 5.3. Аргументы, результаты и лишние обращения

В B: get_package 2, search_packages 1, get_function_docs 42; 20 server ok,
25 `docs_not_found`. Из docs успешны 17; три страницы имеют `page_truncated=true`.
`R/D01-B-1/result.json#$.mcp_telemetry.calls` содержит timestamps, fingerprints,
bytes и duration. Наибольшая metadata-идентичность: call 1 result package `termr`,
repository `cran`, verification `verified`. **Это поля результата, не восстановленные
аргументы запроса.** Query search, docs aliases, offsets, expected version и verbosity
не сохранены. Нельзя утверждать, что search был плохим или пустым.

Точные повторы по scoped HMAC fingerprints: **39↔17**, **42↔24**, **45↔15**.
Их response sizes соответственно 3890, 4148 и 8008 bytes совпадают; повторов после
ошибки нет. Остальные `similar` означают лишь тот же tool+package с другими аргументами,
а не семантически бессмысленный повтор. D01 тратит 45 вызовов на четыре score predicates;
минимально достаточное число из trace не выводится.

**Гипотеза B2:** достаточно начать с metadata названного кандидата, затем прочитать
несколько точных aliases по нужным feature/limits; после docs_not_found следовать
alias hints, не повторять уже успешный идентичный запрос. Проверяемая цель — уменьшить
ошибки/повторы при сохранении evidence coverage. Обещать «хватило бы ровно 4 вызовов»
эти данные не позволяют. `consolidated-v1.1` уже включает alias hints; рекомендовать
просто «добавить hints» как отсутствующую возможность было бы неверно.

## 6. Подробный аудит D02

Prompt `K/tasks/D02.md` допускает несколько подходящих пакетов для stub/fake responses,
request assertions и unit tests без public internet. Требует одну рекомендацию,
версию, official source/docs и точные feature/caveat IDs. Frozen candidates:
`httptest2 1.2.2`, `webmockr 2.2.0`, `webfakes 1.5.0`.

| Check | A (httptest2 1.1.0) | B (httptest 4.2.4) | Вывод |
|---|---|---|---|
| answer_shape | pass | pass | Явная JSON-схема соблюдена |
| accepted_package_and_version | fail: 1.1.0 ≠ 1.2.2 | fail: httptest отсутствует в candidates | A: неверный frozen pin; B: closed candidate gate |
| official_source_and_docs | fail: version gate | fail: expected/frozen отсутствуют | Само по себе не доказывает ложность URLs |
| documented_fit_and_limits | fail: нет httr2_specific | fail: expected отсутствует | A не соответствует rubric; B не проходит до независимой проверки fit |

Sources: [A artifact](../results/20261025T135949Z-9ff06c47/D02-A-1/artifacts/answer.json),
[B artifact](../results/20261025T135949Z-9ff06c47/D02-B-1/artifacts/answer.json),
`K/verifier/candidates.json#$.D02`, `knowledge_pilot.py::_score_recommendation`,
`R/D02-{A,B}-1/result.json#$.score.failed_checks`.

В B наблюдается содержательное сравнение подходов. `events.json $[126]`:
HTTP-testing packages не установлены; агент решает использовать подключённую документацию.
Calls 1–4 (`$[133]`–`$[136]`) — metadata webmockr, vcr, httptest2, httptest.
Calls 5–8 (`$[143]`–`$[146]`) — docs webmockr ok, docs_not_found, ещё metadata webmockr,
docs httptest ok. Сообщение `$[242]` выбирает httptest как широкий fit,
сравнивает webmockr и httr2-ориентированный httptest2. Calls 9–12 (`$[247]`–`$[250]`)
получают docs httptest. `$[344]` перечисляет `with_mock_api`, `without_internet`,
`expect_GET`; `$[347]` записывает итог и проверяет JSON.

**Observed:** 12 calls, 11 ok, 1 docs_not_found; get_package 5, get_function_docs 7,
search_packages 0; точных повторов 0. Повторный metadata webmockr (call 7)
имеет другой fingerprint и размер: нельзя считать его точной копией call 1.
Calls 8 и 9 docs httptest имеют равные bytes 8494, но разные fingerprints:
равный размер не доказывает повтор контента. Все MCP arguments и bodies отсутствуют.

**Inferred:** одинаковый score скрывает разные причины. A использует устаревший
относительно snapshot pin и не тот caveat. B меняет выбор после MCP, но получает
три отказа по отсутствию `httptest` в закрытом наборе. **Unknown:** точная версия
из ответа metadata, полнота/актуальность каждого документа и корректность полного
fit httptest; server `verification_status=verified` и `version_mismatch=false`
не заменяют исчезнувшее содержимое. Нельзя приписать B преимущественно C5 или C6.
Подтверждён C7 как механизм score; потенциальные tool-selection/application gaps
остаются гипотезами. Наличие calls `get_package(httptest2)` не доказывает, что агент
получил, увидел и проигнорировал именно необходимый rubric факт.

Новый инструмент не требуется: metadata/dependencies/vignettes и function docs уже
дают подходящий маршрут. `search_packages` мог расширить candidates, но B уже сравнил
четыре известных пакета; отсутствие поиска не является ошибкой само по себе.
До нового inference полезнее независимо оценить `httptest` по опубликованным task
requirements и определить, действительно ли frozen candidate list исчерпывающий.

## 7. Подробный аудит E01

Prompt `K/tasks/E01.md` требует распознать конфликт lock, предложить минимальную
правку и сохранить версии/источники. Fixture `K/fixtures/E01-renv.lock` содержит
R 4.4.3; BioCsoft URL для 3.22; DESeq2 1.50.2; SummarizedExperiment 1.40.0;
ggplot2 4.0.3. Frozen facts: 3.22 ↔ R 4.5; DESeq2 Depends SummarizedExperiment
≥1.1.6, Imports ggplot2 ≥3.4.0. Это метаданные, не проверенная установка.

Оба artifacts предлагают R 4.5.2 и сохраняют package pins и CRAN/BioCsoft identities.
A `classification=release_R_mismatch`, B `release/R mismatch` — семантически
описывают требуемый конфликт, но scorer требует ровно `incompatible`.

| Failed check (оба trials) | Что есть в артефакте | Почему scorer возвращает false | Оценка |
|---|---|---|---|
| release_and_R_conflict_identified | Верный release/R mismatch и пояснение | `classification != "incompatible"` | C7 high; enum не задан prompt |
| valid_minimal_release_alignment | `r_version.proposed="4.5.2"`, release 3.22 | r_version должен быть scalar string; A bioconductor тоже объект | C7 high; скрытая форма |
| package_sources_and_pins | Все три правильных pins; `BioCsoft` сохранён из lock | Строгое равенство объектам с repository="Bioconductor 3.22" | C7 high; repository alias не нормализуется |
| dependency_graph_constraints_satisfied | Две требуемые DESeq2 edges с правильными minima; ещё R edges | Все targets должны быть в packages; R-node отсутствует, `_node_version` даёт None | C7 high для механизма; не доказательство несовместимости самих minima |
| minimal_change_explained | Одна правка R.Version from/to и достаточный rationale | Список объектов не равен `["r_version"]` | C7 high; форма changed_fields не задана |
| official_evidence | sources — объекты с official URLs и provenance; среди них CRAN | Нужны строки, все только bioconductor.org, хотя задача смешанная | C7 high; наличие URL не доказывает его retrieval |

Источники: [A](../results/20261025T135949Z-9ff06c47/E01-A-1/artifacts/answer.json),
[B](../results/20261025T135949Z-9ff06c47/E01-B-1/artifacts/answer.json),
`knowledge_pilot.py::_compatibility_checks(E01)`, `R/E01-*/result.json#$.score`.
Повторная оценка неизменённых artifacts тем же локальным JSON-scorer снова даёт 0/6.
Это воспроизведение скрытого контракта, не подтверждение шести предметных ошибок.

### Действия и фактические границы ответа

В A `events.json $[63]` выводит R 4.5.2, DESeq2/SummarizedExperiment repositories;
`$[73]` — installed DESCRIPTION четырёх пакетов: BiocVersion Depends R≥4.5.0,
нужные DESeq2 minima, SummarizedExperiment Depends R≥4.0.0, ggplot2 Depends R≥4.1.
В B `$[70]` показывает исходный конфликтный lock; `$[156]` читает installed DESCRIPTION
и выводит BiocManager 3.22. Следовательно, package minima и локальные версии опираются
на наблюдаемые outputs, не только на финальный текст. Сам аудит эти команды не запускал.

Ни один основной package pin или две основные DESeq2 edges не опровергнуты frozen
данными. A утверждает нижнюю границу R≥4.5.0: локальный BiocVersion metadata её
поддерживает, но это не общий сертификат совместимости с произвольным более новым R.
Формулировку «requires R >=4.5.0» нужно читать вместе с release pairing R 4.5.
Оба ответа проверяют только перечисленные ограничения; полный dependency graph,
успешное восстановление renv, ABI/system libraries и воспроизводимость установки
**не установлены**. Дополнительные R edges создают неоднозначность формы graph,
но сохраняют проверяемые package facts. Официальные URL перечислены; их скачивание
в trials не показано. `BioCsoft` в lock — реальная repository identity, её сохранение
не является фактической ошибкой.

### MCP-потенциал

Доступны `check_r_compatibility(r_version="4.4.3", repository="bioconductor",
bioc_version="3.22")` для release mapping и `get_package(package="DESeq2",
repository="bioconductor", bioc_version="3.22", include=["metadata","dependencies"])`
для direct metadata; это **пример потенциального запроса, он не выполнялся**.
`get_package` ggplot2 сообщает текущую CRAN version, не гарантирует именно locked 4.0.3.
`check_package_version` сравнивает caller version с latest CRAN, не верифицирует
Bioconductor package version или установленный lock. `analyze_r_project` может
статически разобрать caller-provided manifest; не читает lock по произвольному пути.

Эти tools могли дополнить официальные источники, но не исправили бы скрытые
`classification`, `changed_fields`, sources types или R-node predicate. Нового
verification API для установленного root cause не требуется. Почему агент не
использовал MCP: **not_observable**; local inspection наблюдается, мотив неизвестен.

## 8. Подробный аудит E05

Prompt `K/tasks/E05.md` прямо задаёт три сценария и labels compatible/incompatible/
unverified, но не задаёт структуру `cases`, его ключи и форму `positive_package`
или `sources`. Оба artifacts дают массив cases a/b/c со **всеми тремя верными
классификациями** и правильным DESeq2 1.50.2; отличаются подробностью evidence.

| Check | A/B | Наблюдаемый механизм отказа / успеха |
|---|---|---|
| verified_positive | fail/fail | cases — list вместо dict с `release_322_r452`; positive_package содержит дополнительные поля, strict equality не проходит |
| verified_negative | fail/fail | Отсутствует скрытый ключ `release_322_r443`, хотя case b = incompatible |
| unknown_not_overclaimed | fail/fail | Отсутствует скрытый ключ `unlisted_package_version`, хотя case c = unverified |
| reasoning_distinguishes_evidence | pass/pass | Проверяется только rationale string длиной ≥30, не истинность аргументации |
| official_evidence | fail/fail | sources — объекты, не строки; есть также local/snapshot evidence |

Источники: [A artifact](../results/20261025T135949Z-9ff06c47/E05-A-1/artifacts/answer.json),
[B artifact](../results/20261025T135949Z-9ff06c47/E05-B-1/artifacts/answer.json),
`knowledge_pilot.py::_compatibility_checks(E05)`, `K/tasks/E05.md`.
Primary score mechanism C7, high. Существующие scores не исправлялись и нормализованные
ответы не создавались: «по смыслу верно» здесь не новый численный результат benchmark.

### Ledger утверждений: true, false, unverified, unknown

| Утверждение | Подтверждение в сохранённых данных | Статус и граница |
|---|---|---|
| R 4.5.2 / Bioconductor 3.22 соответствуют release mapping | E-source-snapshot `facts.bioconductor_3.22.r_major_minor="4.5"`; experiment runtime versions | Подтверждено как metadata pairing |
| DESeq2 1.50.2 — положительный package pin | snapshot facts и experiment runtime; B events `$[123]`: DESeq2 installed TRUE, version 1.50.2 | Подтверждено для snapshot и данного executor, не пользовательской машины |
| R 4.4.3 / Bioconductor 3.22 несовместимы по mapping | snapshot R 4.5 против R 4.4 | Подтверждено в указанном смысле |
| Unknown package 9.9.9 нельзя объявить совместимым/несовместимым по отсутствию | Имя и условие отсутствия прямо даны в task; B `$[123]`: installed FALSE | `unverified`; глобальное несуществование не доказано |
| «Официальная страница документирует версию» | URL есть в ответах и frozen facts, но retrieval HTML в trial не сохранён | Факт поддержан snapshot; непосредственное чтение страницы агентом unknown |
| «Совместимость доказана одним renv.lock / installed load» | Lock — запись и installed metadata, а не полный constraint/installation test | Такое сильное обобщение было бы unverified; артефакты нужно трактовать ограниченно |

Не обнаружено false-классификации трёх заданных cases. В A нет проверки installed
DESeq2 в command outputs; версия поддержана frozen benchmark facts, но получение
её из официальной страницы самим агентом unverified. B действительно проверил
локальную версию. Одновременно `$[118]` содержит warning `1 packages out-of-date;
19 packages too new` от `BiocManager::valid()` и ошибку печати list. Это **не**
подтверждение валидности полного environment; итоговый повтор `$[123]` проверяет
version/namespace, а не устраняет warning.

`check_r_compatibility` может проверить mapping и часть direct dependency constraints;
`get_package` — release-specific DESeq2 metadata. Но compatibility tool не принимает
произвольный package_version для воспроизведения любого frozen snapshot; отсутствие
пакета нужно оставить unverified. `check_package_version` — latest-CRAN comparison,
не нужный здесь universal verifier. Новый API не устранит hidden-schema failures;
description должен ясно ограничивать metadata claims, не обещать установочную проверку.
Нет calls и tool_search events; мотив обхода MCP **not_observable**.

## 9. Discovery/adoption: восемь этапов и все задачи

### 9.1. Что наблюдаемо на каждом этапе

| Этап | Наблюдаемый результат | Что нельзя заключить |
|---|---|---|
| 1. Регистрация / доступность | Manifest: 15 registered, 12 allowed; source hash совпал; 19 B server audit list requests | Нет raw tools/list response/schema snapshot для каждой session |
| 2. Возможность discovery | 19 запросов tools/list, rejected_requests=0; 0 tool_search_calls | tools/list не доказывает внимательное прочтение описаний |
| 3. Фактическое обнаружение / выбор | D01/D02 публикуют намерение пользоваться подключённой документацией, затем вызывают tools | Для 17 остальных выбор или отказ not_observable |
| 4. Реальный call | Client IDs дают 45+12=57; audit call requests=57; server log=57 | added+done не два вызова |
| 5. Результат | Server: 31 ok, 26 docs_not_found; transport items могут быть completed даже при application error | completed не означает успешный предметный ответ |
| 6. Релевантность | Package metadata fields и agent summaries косвенно согласуются со сценарием | Полная response relevance неизвестна после redaction |
| 7. Применение | D01 B сохраняет termr; D02 B — httptest после соответствующих metadata/docs серий | Какой ответ породил какой факт, не установлено |
| 8. Влияние на score | D01 +3, D02 0 | Воспроизводимый causal effect не оценён |

Источники: `R/experiment.json#$.mcp_server`, все `R/*-B-1/result.json#$.mcp_server_audit`,
`$.mcp_usage.tool_search_calls`; `R/telemetry.jsonl` source agent_stream/mcp_server;
D01 B `$[119], [314]`, D02 B `$[126], [242], [344]`.

### 9.2. Adoption matrix

Для каждого B сохранены configuration/list=1. В колонке «почему» **NO** означает
`not_observable`: есть путь выполнения, но нет надёжной записи причины отказа.
Для всех NO минимальное дополнительное наблюдение **N**: snapshot реально показанных
tool schemas/server instructions + видимые selection/discovery events либо короткое
публичное объяснение выбора источника до решения; скрытые рассуждения не требуются.
Эти данные нужно сохранить в будущем эксперименте, не пытаться реконструировать задним числом.

| Task | Relevance к MCP | Полезный разрешённый tool / возможные данные | Мог ли изменить score этого B? | Calls; наблюдаемый путь и evidence | Почему / что дополнительно |
|---|---|---|---|---|---|
| H01 | Средняя: R/dplyr semantics | get_function_docs: grouping/pick/summary; get_package: version | B уже 18/18; ceiling | 0; локальный dplyr version check, events `$[53]`; solution.R | NO; N + различать docs от локального теста |
| H04 | Средняя: dplyr rolling join | get_function_docs: join_by/closest; metadata pins | B уже 17/17 | 0; fixtures и R inspection `$[47]` | NO; N; не переносить отсутствующий data.table tool scenario |
| H10 | Низкая для package metadata; manuals частично | search_r_documentation/get_r_documentation_section: stats conventions | Потенциально пояснения, но FMI=0 corner case не гарантирован manuals | 0; 12 локальных command items; solution.R и score zero_total_variance | NO; N + точная проверка numerical branch |
| B01 | Средняя: dplyr / filtering | function docs и package metadata | B уже 5/5 | 0; starter+fixture, local versions `$[46]` | NO; N |
| B02 | Средняя: tidyr/dplyr | function docs: reshape/aggregation semantics | B уже 5/5 | 0; R check `$[172]`, solution.R | NO; N |
| B03 | Средняя: dplyr bug fix | function docs, dependencies | B уже 5/5 | 0; starter inspection `$[46]`, 9 command items | NO; N |
| C01 | Высокая: pinned dplyr behavior | get_function_docs + package_version guard | B уже 5/5 | 0; local versions `$[134]`, saved solution | NO; N; docs доступны также локально |
| C02 | Высокая: tidyr behavior | function docs о pivot semantics | B уже 5/5 | 0; installed version check `$[50]` | NO; N |
| C03 | Высокая: readr parsing | get_function_docs о locale/parse behavior | B уже 5/5 | 0; local starter/CSV/R `$[41]` | NO; N |
| C04 | Высокая: cranlogs API | get_package/get_function_docs: from/to vs when, scope statistic | B уже 9/9 | 0; 6 command items, artifact соответствует hidden verifier | NO; N; source-doc route не наблюдается |
| C05 | Высокая: cranlogs API | get_function_docs: date interval, mirror counts | B уже 7/7 | 0; проверки R/cranlogs availability `$[57], [65]` | NO; N; отсутствие installed cranlogs само по себе не вызывает MCP |
| D01 | Высокая: package selection | metadata, name/title search, Rd | B 4/4 против A 1/4; связь косвенная | 45; declared switch `$[119]`, termr summary `$[314]` | Выбор наблюдаем; missing payload мешает атрибуции |
| D02 | Высокая: package comparison | metadata/vignettes/Rd нескольких подходов | B 1/4; closed scorer gate | 12; switch `$[126]`, сравнение `$[242]` | Выбор наблюдаем; нужна независимая fit review |
| D03 | Высокая: package/version discovery | get_package: pointblank current pin; docs feature/caveats | Потенциально 0.12.2→frozen 0.12.4; не доказано counterfactual | 0; answer.json 0.12.2, 5 command items | NO; N + какой источник версии использован |
| E01 | Высокая: release/R/metadata | check_r_compatibility, get_package dependencies | Факты можно подтвердить; скрытую JSON-схему tools не исправят | 0; local DESCRIPTION `$[156]` | NO; N + доступный source evidence ledger |
| E02 | Высокая: DESeq2 workflow | get_function_docs, workflow guidance (границы static) | B уже 5/5 | 0; local version check `$[52]`, 7 command items | NO; N |
| E03 | Высокая: namespace relocation | get_function_docs в правильном package, metadata | B уже 4/4 | 0; namespace candidates `$[53]`, solution.R | NO; N; локальные exports решают задачу |
| E04 | Высокая: mixed repository dependencies | get_package include dependencies; compatibility mapping | Может исправить A факты, но B schema gates остаются | 0; packageDescription `$[276]`, version/edge в artifact | NO; N |
| E05 | Высокая: compatible/incompatible/unverified | mapping, release-specific package metadata | Подтверждает факты; hidden case keys не исправляет | 0; local metadata `$[123]` | NO; N; отличать local install от snapshot facts |

Для каждой строки источники — `R/<Task>-B-1/events.json` с указанными индексами,
`result.json#$.score` и task prompt в `hard/tasks/<Task>/prompt.md` либо K/tasks.
Перечисленные tools — потенциальный путь по историческому allowlist, не выполненные
аудитом запросы. Даже высокая relevance не означает необходимость обращения.

**Inferred:** среди 17 B без calls 12 уже полностью решены; сырая adoption не
является самостоятельным quality objective. Пять частично/неуспешных B без calls —
H10, D03, E01, E04, E05. D03 — наиболее чистый новый adoption probe; E01/E04/E05
требуют сначала прозрачного scorer contract. D01/D02 полезны как positive controls
уже наблюдавшегося выбора. **Unknown:** описания слишком общие, агент счёл tools
ненужными, инструкции про installed packages подавили выбор или tool UI плохо
показало сервер. Эти конкурирующие гипотезы требуют отдельных наблюдений.

## 10. Анализ всех 57 MCP-вызовов

### 10.1. Учёт без двойного подсчёта

| Tool (историческое имя) | D01 | D02 | Всего | ok | error |
|---|---|---|---|---|---|
| get_function_docs | 42 | 7 | 49 (85.96%) | 23 | 26 |
| get_package | 2 | 5 | 7 (12.28%) | 7 | 0 |
| search_packages | 1 | 0 | 1 (1.75%) | 1 | 0 |
| Всего | 45 | 12 | 57 | 31 (54.39%) | 26 (45.61%) |

Все ошибки — `docs_not_found`. По task docs error rate: D01 25/42 (59.52%),
D02 1/7 (14.29%). Во всех B rejected_requests=0: нет свидетельства отказа allowlist.
Источники: `R/D0{1,2}-B-1/result.json#$.mcp_telemetry.calls`,
`$.mcp_telemetry.reconciliation.status="matched"`, `R/mcp_calls.csv` (57 строк).

В `events.json` **114** snapshots MCP item (57 added + 57 done), но 57 уникальных IDs.
В `telemetry.jsonl` 57 agent_stream started, по 31 completed и 26 failed **для каждого
из двух источников** agent_stream/mcp_server. Суммирование обоих потоков completed/failed
дало бы ложные 114 calls. Серверные записи используют `server-call-0001`, клиентские —
`client-call-0001`; связь помечена `correlation="ordinal_unconfirmed"`.
Для примера: JSONL строка 722 — D01 server call 1 get_package termr,
`correlated_call_id=client-call-0001`. В новом CSV соединение по порядку completion
и совпадению tool name явно указано, а не объявлено доказанным distributed trace ID.
При отсутствии совпадения экстрактор сохраняет unknown и не назначает чужой результат.

### 10.2. Что содержит CSV

[baseline_tool_calls.csv](baseline_tool_calls.csv): ровно 57 строк, task/trial,
sequence, tool, server call number, client item ID, event indices, server record JSON path,
application status/error, request/result byte measurements, server duration,
UTC completion timestamp, repeat fingerprint/kind, flags и ограниченная package
идентичность результата. Аргументы **null**, `arguments_status=unavailable_not_reconstructed`;
полный retained response body size **null**, `response_payload_status=unavailable_redacted`.
Нулём отсутствие тела не обозначено: оно удалено, а не было пустым ответом.

`response_bytes_recorded` — измеренный сервером размер serialized JSON результата,
а **не** размер доступного аудитору полного payload. Сумма 277939 bytes:
D01 187993, D02 89946. Из них get_function_docs 220871, get_package 55225,
search_packages 1843. Несколько полей представляют одну информацию в text/structured
форме; складывать эти представления как уникальные факты нельзя. Page truncation
наблюдается 3 раза, output truncation 0; next_offset и действительное чтение следующих
страниц неизвестны. Server duration — не полная model/network wall latency.
Суммарные API tokens и стоимость **не оцениваются**, usage/cost unavailable.

### 10.3. Повторы, релевантность, использование

Категории в CSV взаимно исключающие для удобства импорта, но повтор/ошибка/релевантность
семантически независимы и также сохранены отдельными колонками:

| Категория | Количество | Что подтверждено |
|---|---|---|
| Полезный с доказанным использованием конкретного response | 0 подтверждённых | Это граница данных, не доказательство отсутствия полезности |
| Потенциально полезный, использование конкретного ответа не подтверждено | 28 | Server ok, без точного повтора; payload relevance unknown |
| Точный повтор | 3 | D01 calls 39/42/45, fingerprint repeats |
| Ошибочный | 26 | docs_not_found; причина отсутствия alias неизвестна |
| Доказанно нерелевантный | 0 подтверждённых | cli/vcr могут быть сравнительными кандидатами, нельзя автоматически исключать |
| Недостаточно данных для application status | 0 | Для всех есть server telemetry; данных для relevance недостаточно для всех 57 |

`RepeatTracker` (`src/cran_knowledge_mcp/telemetry.py`) считает `similar` по совпадению
tool+package и различию нормализованных аргументов. 44 similar, 3 identical, 10 first.
Similar **не** означает семантический повтор: это может быть другой alias, section
или pagination offset. Fingerprints солёные и не сравнимы между server processes.
Одинаковый byte size тоже не является доказательством одинакового содержания.

### 10.4. Почему документация доминирует, а поиск редок

**Observed:** D01 уже содержит `termr` в prompt; после metadata агент делает три
серии docs calls. D02 изначально перечисляет известные пакеты, делает metadata comparison,
затем подтверждает fit конкретного httptest. `search_packages` по контракту ищет
только package names/titles, причём все whitespace terms должны совпасть; это не
поиск full docs по пользовательской истории. `get_function_docs` требует literal Rd alias,
возвращает до 8000 chars/page; package metadata можно получить без известного alias.
Источники: `server.py::_register_tools`, `search_packages`, `get_function_docs`,
`providers/base.py::get_function_docs`, D01/D02 chronology выше.

**Inferred, medium:** при уже выбранном имени пакета агенту естественнее проверять
API features через function docs. **Гипотеза, low:** часть 25 ошибок D01 — угадывание
aliases. Ни aliases, ни query не сохранены, поэтому гипотеза не подтверждена.
Нельзя установить, что плохой `search_packages` query вызвал docs loop или что более
ранний поиск обязательно помог бы. `docs_not_found` hints уже присутствуют в source
snapshot; неизвестно, какие hints были возвращены и использованы.

## 11. Root Cause Matrix

Полная [CSV-матрица](baseline_failure_matrix.csv) содержит **162 строки**:
136 scorer checks с отдельными A/B outcomes и 26 MCP error observations.
Errors не добавляются в знаменатель 136. Каждая строка имеет primary/secondary,
confidence, evidence paths, failed trial IDs, требуемое наблюдение и MCP-remedy.
Для смешанных механизмов одной пары подробности ниже имеют преимущество над
одной общей categorical колонкой CSV.

| Task / trial | Проверка / событие | Primary; secondary | Evidence и confidence | Что ещё проверить | Исправляется MCP? |
|---|---|---|---|---|---|
| D01 A | accepted/version, sources, fit | C7; C9 | utils вне candidates; local utils help; high для score gate | Независимая оценка mapping labels и terminal UX | Docs помогают выбору, закрытую rubric не исправляют |
| D01 B | 25 docs_not_found | C9; C3/C4/C5 гипотезы | calls 4–12,19–23,25,29–36,43–44; high для error, low для причины | Exact aliases, bounded hints, offsets | Вероятно selection/stop guidance, эффект неизвестен |
| D01 B | calls 39,42,45 | C3 (inferred); C9 | Same-tool+args fingerprints после успешных вызовов; medium для избыточности | Менялся ли контекст и зачем повтор | Вероятно B2; новый tool не нужен |
| D02 A | accepted/version, fit | C1; C7 | httptest2 1.1.0 вместо 1.2.2; нет httr2_specific; high | Был ли pin проверен и происхождение версии | get_package/Rd потенциально помогают |
| D02 A | sources | C7; C1 | Версия гейтит URL predicate; high | Оценить URL отдельно от версии | Нет прямого решения metadata качества score |
| D02 B | три failed checks | C7; C9 | httptest не входит в candidates; high для gate | Frozen docs и независимая пригодность httptest | Нет оснований обвинять API |
| D02 B | docs_not_found call 6 | C9; C3/C4/C5 гипотезы | telemetry call 6; low для первопричины | Alias и error body | Unknown |
| D03 A/B | accepted/version, sources | C1; C7 | pointblank 0.12.2 против frozen 0.12.4; artifact; high | Свежесть фактов и source selection | get_package может дать pin; не доказан эффект |
| E01 A/B | все 6 | C7; C9 | Hidden scalar/enums/repository equality/R target/source types; high | Открытая схема + semantic adjudication | MCP не знает скрытой формы scorer |
| E05 A/B | 4 failed, rationale pass | C7; C9 | Case list против hidden dict; extra positive fields; source objects; high | Прозрачные types/keys; evidence ledger | Нет нужды в новом verification API |
| E04 A | version_constraints | C1; C7 | DESeq2 1.50.0 против snapshot 1.50.2; high | Независимая проверка версии | Metadata tool потенциально помогает |
| E04 A | dependency_edge_reported | C7; C1 | from/to вместо package/depends_on; дополнительно неверно Imports ≥1.11.12 | Отдельно schema и точность minima | Metadata помогает фактам, не hidden keys |
| E04 A/B | package_sources, install, evidence | C7; C9 | Repository objects; install_strategy object; mixed sources; B rationale list | Нормализовать контракт; BiocManager может обслужить CRAN без отдельного install.packages | API expansion не нужен |
| H10 B | zero_total_variance_collapses_the_interval | C6; C9 | result details: fmi actual .30 expected .00; solution.R branch; high | Требуемая task convention при нулевой дисперсии | Metadata не исправляет numerical branch |
| 17 B без calls | adoption | C9; C2 гипотеза | calls=0, list=1, summaries пусты; high для наблюдения | N из adoption matrix | B1 как эксперимент, не установленное лечение |

C4 не назначен основной причиной score-провала: в E01/E05 недостающий solver не
требуется для выявленных schema failures. C5 не назначен по одному docs_not_found:
это может быть корректный ответ на неизвестный alias. C8 наблюдается локально
(python/git missing, ошибки команд), но нет доказанного отдельного environment
failure, определившего score. Эти категории не нужно заполнять ради полноты таксономии.

Дополнение H10: артефакт B при W=B=0 задаёт riv=lambda=0, но для Barnard–Rubin df
оставляет конечным, затем считает `fmi=(riv+2/(df+3))/(riv+1)`, получая .30.
Oracle имеет явное `if (tt == 0) 0`. Это конкретная ошибка применения boundary
convention, а не регрессия от информации MCP. Источники: `R/H10-B-1/artifacts/solution.R`,
`K/../hard/verifier/H10.R`, check `zero_total_variance_collapses_the_interval` и score.details.

Дополнение E04: B независимо исправляет DESeq2 pin до 1.50.2 и edge до Depends ≥1.1.6,
откуда +1 `version_constraints`; JSON forms всё ещё расходятся с hidden predicates.
Установка через `BiocManager::install` для смешанного набора содержательно не
опровергнута отсутствием отдельного `install.packages` в тексте. Scorer требует
обе строки, хотя prompt просит дать BiocManager разрешить graph и CRAN-only dependencies.
Source: `R/E04-{A,B}-1/artifacts/answer.json`, `_compatibility_checks(E04)`.

## 12. Пробелы в возможностях сервера

Это границы существующего MCP, а не установленное объяснение всех неуспехов.

| Возможность / реальный сценарий | Почему существующего API недостаточно | Минимальный возможный API, только предложение | Нужен новый tool? Ценность / риск |
|---|---|---|---|
| Проверка точного набора locked package versions/repositories (E01/E05) | check_r_compatibility принимает R и package/release, но не произвольный полный versioned lock graph; latest CRAN metadata не исторический snapshot | Бounded `packages:[{name,version,repository,release}], r_version` в существующем compatibility маршруте; report checked_constraints/unresolved/provenance | Не приоритет этого baseline; можно расширить существующий tool после отдельного дизайна. Риск назвать metadata check solved transitive/install compatibility |
| Доступ к документации строго нужной старой версии (E01 pinned ggplot2; D versioned comparisons) | get_function_docs package_version — expected-version guard; при несовпадении отказывает, не загружает произвольную историческую документацию | Explicit version identity + unavailable, архивный путь только при проверенном source contract | Новое top-level имя не обосновано; прежде важнее не подменять version. Риск тихой latest substitution |
| Статическая проверка пригодности альтернативного D-пакета | Нет универсального evidence-based semantic adjudicator пользовательской истории | Новый API не предлагается: metadata + vignettes + Rd и независимая rubric уже применимы | Закрытая scorer allowlist — benchmark gap, не server gap |
| Полное исполнение установки/численного кода (H10, claims E05) | Сервер read-only, не исполняет R и не тестирует install | API исполнения не предлагается | Намеренная граница; эту задачу не надо решать добавлением runtime control |
| Подбор правильного Rd alias (D01 25 errors) | Literal alias lookup уже имеет alias hints; raw hints не сохранены | Сначала переиспользовать существующие hints и остановку; catalogue API лишь если доказана непригодность hints | Пока новый tool не нужен; иначе повышается tool-selection complexity без доказанного выигрыша |

Sources: verified source `server.py::_register_tools`, `service.py::get_versioned_function_docs`,
`service.py::check_r_compatibility`, `providers/base.py`, `releases.py`;
`experiment.json` allowlist.
`get_package` с dependencies даёт прямые DESCRIPTION fields; это не решённый транзитивный
граф. Lock не доказывает installed environment. Ни один предлагаемый future API не должен
принимать произвольный URL/path, исполнять R или заявлять успешное восстановление среды.

## 13. Рекомендации B1: server-level discovery

**Не реализовано.** Цель — проверить причинную гипотезу о видимости уже существующих
возможностей. В исходном source server instructions уже есть «Check R/Bioconductor
compatibility before recommending Bioconductor packages». Следовательно, нельзя
объяснять E-no-calls простым отсутствием этой рекомендации.
В `run_simple.py::STANDARD_INSTRUCTIONS` документационные инструменты optional,
первая фраза направляет к installed R; D-agents переключаются на MCP, когда нужных
пакетов нет локально. Последнее — наблюдение в D01/D02, а общий эффект wording — гипотеза.

| Гипотеза | Малый будущий эксперимент | Проверяемые метрики / опровержение |
|---|---|---|
| B1-H1: конкретное перечисление задач/facts делает tools заметнее | Сравнить только server-level wording при том же allowlist/API/tool descriptions/model/effort; D03 и E01/E05 с заранее явной схемой; D01 как positive control, C01 как ceiling control | Первый релевантный call, task adoption, mapping/source coverage, correct version identity, time-to-first-call; если calls растут без evidence/quality, цель не достигнута |
| B1-H2: фраза про installed packages воспринимается как ограничение recommendation universe | Отдельное исследование benchmark instruction wording, одинаковое в A/B; не смешивать с H1 | Доли installed-only recommendations и unverified version claims; публичное пояснение источника до решения. Это эксперимент протокола, не чистый B1 server effect |
| B1-H3: tools не представлены пользователю модели так, как ожидает конфиг | Сначала сохранить effective tool schemas/server instructions и discovery events в небольшом контроле | Сопоставление configured/advertised/selected; при отсутствии advertising исправлять harness, а не descriptions |

Предложение server-level текста для будущей review, без изменения файлов:

> Для выбора R-пакета можно проверить CRAN/Bioconductor metadata и версии; для
> Bioconductor указать release и R version и проверить их mapping. Для известного
> пакета доступна документация Rd; при неизвестном кандидате — поиск names/titles.
> Ответы содержат источники и check time. Проверяется metadata, установка и полный
> dependency graph не тестируются; latest repository version не равна locked/installed.

Эти claims поддержаны историческим allowlist и проверенным source tree. Нельзя
обещать project file access, execution, историческую документацию любой версии,
полную совместимость или GUI/live-session control.

Рекомендуется несколько свежих repetitions с заранее зафиксированным планом,
уравновесить порядок условий, не переиспользовать baseline artifacts как новые trials.
E-scoring/schema исправления должны получить отдельную версию и новый protocol;
historical 113/116 сохраняются. Увеличение calls не является основной целью:
нужны верные проверяемые факты и меньшая доля неподтверждённых утверждений.

## 14. Рекомендации B2: tool selection

**Не реализовано.** Минимальный будущий A/B: тот же server-level wording и API,
меняются только descriptions выбора tools; D01/D02 — основные probes,
D03 — контроль package metadata, E01 — контроль repository-aware constraints.
Прозрачность scorer и telemetry должна быть одинаковой во всех ветках.

| Tool | Точечная будущая формулировка / правило выбора | Основание / проверка |
|---|---|---|
| search_packages | «Если пакет неизвестен, ищите короткие terms в names/titles; все terms должны совпасть. Поиск не покрывает весь текст документации» | Контракт узкий; query D01 неизвестен. Проверять accepted candidate recall, не требовать поиск при известном имени |
| get_package | «Для известного пакета сначала metadata; dependencies для direct DESCRIPTION fields, vignettes для обзорных URL. Это не install/transitive solver» | В D01/D02 metadata уже вызывается перед docs; улучшение должно проверять полезность секций, а не навязывать лишний call |
| get_function_docs | «Используйте точный literal Rd alias, не описание задачи. При docs_not_found используйте available/closest aliases. Не повторяйте успешный идентичный запрос; page continuation только по next_offset» | 26 errors и 3 exact repeats; hints уже реализованы, недоказан их actual use |
| get_function_docs package_version | «Версия — guard против подмены, не выбор любой архивной версии; несоответствие требует unavailable» | Предотвращает ошибочную верификацию historical environment |
| check_package_version | «Только сравнение caller-supplied installed version с latest CRAN; не inspection и не Bioconductor/frozen-lock verifier» | Особенно важно для E05 |
| check_r_compatibility | «Для Bioconductor явно укажите release и client R; ограниченные metadata/direct constraints. Для доказательства точного package pin дополнительно нужна package metadata identity» | Нужды E01/E05, ограничения current signature |

B2-H1: alias-hints/stop guidance уменьшает docs_not_found и identical repeats, сохраняя
feature/evidence coverage. B2-H2: обзорные metadata/vignettes до точных Rd уменьшают
calls при package selection. Оба эффекта неизвестны; lower call count без полноты
источников не успех. Метрики: calls/task, unique tool+args, error/repeat rates,
relevant fact coverage, page continuation, outcome по независимой rubric, latency.
Бюджет/API tokens измерять только если поставщик вернул usage; bytes отдельно.

## 15. Приоритетный backlog

Все изменения ниже — **предложения**, не внесённые правки. Приоритет учитывает
количество затронутых задач, прямоту evidence, стоимость и риск регрессии.

| Priority | Problem | Evidence | Proposed change | Expected benefit | Verification experiment |
|---|---|---|---|---|---|
| P0 | Hidden E JSON contract, особенно E01/E05 | E01 0/6 при верном R fix; E05 labels верны; E04 object/list gates | Для будущей версии опубликовать schema/enums; отдельно score shape/facts/evidence; reviewer adjudication исходных ответов отдельно от baseline | Устраняет ложную трактовку C7 как knowledge gap; 3 задачи | Offline references + equivalent object/string forms + adversarial false facts; historical scores не переписывать |
| P0 | Невозможна response-level attribution | Все 57 payloads redacted; ordinal_unconfirmed links | Сохранять безопасный bounded projection aliases/offsets/queried identity и facts/provenance; серверный correlation ID; secrets исключать до записи | Объяснимые ошибки/дубли и проверяемая цепочка facts→artifact | Локальный mock protocol test без model/API; доказать redaction и completeness |
| P1 | D open scenario vs closed candidates | D01 utils, D02 httptest, три gated checks | В будущем явно определить candidate universe или независимую evidence-based rubric; версии/URLs оценивать отдельно | Позволяет различить плохой tool selection и rubric exclusion | Offline экспертная оценка сохранённых альтернатив; затем новый scorer version |
| P1 | Adoption cause not_observable | 17 no-calls, 19 automatic list, 12 full-score ceiling | B1-H1 с effective schemas snapshot; D03 основной probe | Проверить видимость без требования calls ради calls | Несколько balanced repetitions и ceiling controls; evidence quality рядом с adoption |
| P1 | Excess docs calls | D01 25 errors, 3 identical; D02 1 error | B2 alias/stop/overview guidance в descriptions | Меньше ошибок/повторов при том же evidence coverage | D01/D02 paired selection experiment, API неизменен |
| P2 | Устаревшие pins и неверные direct edges | D02 A 1.1.0; D03 0.12.2; E04 A wrong DESeq2/minimum | Поощрить version/repository facts ledger через существующий get_package | Меньше неподтверждённых exact-version claims | Metadata-only vs metadata+Rd на version probes; source times сохранять |
| P2 | H10 zero-variance FMI | B fmi=.30 vs required .00, no MCP calls | Отдельное исследование numerical conventions/локальных проверок, не server expansion | Более точное разделение reasoning и metadata benefits | Trusted offline boundary test сохранённого кода при разрешённом R runtime, отдельный отчёт |
| P3 | Произвольный exact-version lock verification | E01/E05 limited metadata vs arbitrary historical graph | Сперва дизайн versioned constraints extension существующего tool | Возможная будущая ценность, baseline gain не доказан | Mocked unknown/history/mixed-repo cases; запрет claims full install compatibility |

P0 telemetry projection не должен сохранять caller source/schema text, секреты,
credentials или произвольные docs instructions. Для новых описаний не нужен новый
инструмент; расширение поверхности не поставлено выше наблюдаемых C7/C9 причин.

## 16. Воспроизводимость, проверки и открытые вопросы

Генерация табличных артефактов из существующих файлов, без API и R:

```powershell
.venv/Scripts/python.exe -m benchmarks.codex_r.audit_baseline --rescore-json
.venv/Scripts/python.exe -m pytest tests/test_baseline_root_cause_audit.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check benchmarks/codex_r/audit_baseline.py tests/test_baseline_root_cause_audit.py
.venv/Scripts/python.exe -m ruff format --check benchmarks/codex_r/audit_baseline.py tests/test_baseline_root_cause_audit.py
```

Экстрактор использует stdlib, импортирует существующий scorer только с явным
`--rescore-json`, разрешает лишь шесть JSON task IDs и запрещает executor fallback.
Без флага не выполняет scorer. Источники читаются без правок; output внутри source
run запрещён. Input inventory проверяется до/после. Генерация детерминирована;
ручной содержательный отчёт отделён от автоматически создаваемых таблиц.

Проверены pairing и доставленные task prompt hashes (38/38), текущие public prompt/fixture
hashes (32/32: 19 prompts и 13 inputs), artifact hashes (38/38), CSV/JSON
согласованность (38/38), client/server totals, statuses, отдельная JSON re-evaluation
(12/12 совпадений), source/verifier tree digests и неизменность всех 121 source files.
Синтетические offline tests проверяют dedup added/done, незавершённые события,
несовпадение tool order/name, server-only observations, null/scoring_error,
одиночный failed_check string, безопасный UTF-8 CSV, POSIX digest order,
запрет output overlap и детерминизм. В CSV null записывается пустым полем;
статусы unknown/unavailable/not_applicable сохранены отдельно. Числа не маскируются
строками; текстовые formula prefixes защищены для spreadsheet import.

Фактический результат финальной проверки: **15 tests passed**; scoped `ruff check`
и `ruff format --check` для двух добавленных Python-файлов проходят. Pytest с отключённым
cacheprovider выдаёт warning о `cache_dir` в существующем pyproject; failures нет.
Первоначальные попытки использовать стандартный tmp_path столкнулись с Windows
PermissionError для mode=0o700; новые tests используют собственный temporary fixture
с обычными наследуемыми permissions, не меняя существующие tests или среду scorer.
Полный pytest проекта и Docker build не запускались: production code не менялся,
PR не создавался, runtime/scoring execution не требовалось для этого офлайн-аудита.

Созданы: этот Markdown; `baseline_failure_matrix.csv`; `baseline_tool_calls.csv`;
`baseline_comparison.md`; `baseline_audit_data.json`; `baseline_json_rescore.json`;
`benchmarks/codex_r/audit_baseline.py`; `tests/test_baseline_root_cause_audit.py`.

Ограничения доказательств:

- Нет MCP arguments, raw response content или полных tools/list schemas. Нельзя
  восстановить docs aliases/query/offset и подтвердить применение каждого ответа.
- Нет записанного historical Python scorer hash; отдельная переоценка совпала,
  но не заменяет исторический исходник. Source MCP и R verifier hashes совпали.
- Official resources — frozen URLs/status/version list; E snapshot — normalized facts.
  Это не побайтовые архивы страниц. UTC times snapshots сохранены, не обновлены:
  D official_resources `2026-10-25T08:56:01Z`; E captured `2026-10-25T10:47:27Z`;
  D01/D02 metadata checked_at `2026-10-25T07:27:05Z`. Per-call timestamps в CSV —
  completion time сервера, не автоматически время первичного upstream retrieval/cache check.
- Нет API usage/cost. Нельзя рассчитать оплаченные tokens из bytes или назвать
  стоимость нулевой. Server duration и model wall time — разные метрики.
- Не проведено независимое документальное подтверждение альтернатив utils/httptest
  по всем требованиям; они не объявляются полностью корректными только из-за C7.
- Нет repeated inference trials. Две положительные и одна отрицательная score delta
  не доказывают стабильную пользу/вред, latency effect или статистическую значимость.
- Общие инструкции/SDK runtime не полностью представлены session snapshot; `standard`
  подтверждён metadata, его полные фактически показанные bytes отдельно не сохранены.

Рабочее дерево **было изменено до аудита**. Существующие изменения пользователя,
сервер, scorer, task prompts, benchmark settings, artifacts и events не редактировались.
Добавлены только этот отчёт, вспомогательный offline script, его tests и производные
таблицы/JSON. Никаких платных сессий, inference, внешних API, R/package scripts,
benchmark A/B, публикаций или deployment в ходе аудита не запускалось.

## 17. Итоговые выводы

Численный baseline воспроизводится точно. Содержательно D01 показывает наблюдаемый
переход от локальных альтернатив к подключённой документации и принятому termr;
это правдоподобная, но не полностью атрибутированная польза MCP. D02 показывает
сравнение пакетов и смену рекомендации, которую закрытый scorer не умеет принять;
«MCP не помог» здесь означает отсутствие score gain, а не установленную бесполезность
или неправильность полученной информации.

E01/E05 нельзя использовать как доказательство критического незнания compatibility:
основные ответы соответствуют frozen facts, а score в значительной мере определён
скрытыми типами/ключами JSON. Реальные version/edge ошибки видны в D02 A, D03 и E04 A;
отдельная numerical ошибка — H10 B. Подмена всех этих механизмов одним «плохое discovery»
сделала бы следующий эксперимент неинтерпретируемым.

Для отсутствия calls в 17 задачах корректный итог — **not_observable как причина**,
при доказанном no-call и настроенном MCP. Сначала нужны прозрачный измерительный
контракт и bounded evidence capture. Затем B1 и B2 можно проверить отдельно,
не превращая adoption в требование пользоваться инструментами без полезной цели.
