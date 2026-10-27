# P1-A — аудит поиска функций и документации R-пакетов

Дата: 2026-10-26. Run B1: 20261026T104750Z-f78eabf1. Аудит выполнен offline по локальным исходникам и сохранённым результатам.

## 1. Краткий вывод

Ошибка docs_not_found означает: после выбора версии, загрузки архива и построения Rd alias index буквальный alias, равный запрошенной строке, не найден. Это не доказывает отсутствия функции, неверного package или отказа upstream. Код provider-а задаёт именно этот результат при пустом literal lookup (providers/base.py:288–310).

B1 сохранил 59 таких ответов на 132 вызова get_function_docs: Control 33, Treatment 26; все fingerprints различны. Package/name projection есть у 42 событий: termr 28, climenu 12, validate 2; для 17 аргументы не сохранены. D01 дал 56 (Control 32, Treatment 24), D03 — 3 (Control 1, Treatment 2); C01 — 0. Корневая причина не установлена ни для одного события.

Уже существует частичный discovery: после miss get_function_docs возвращает alias из проверенного архива — весь список при количестве до 30, иначе 10 ближайших (parsers.py:142–176). Большой индекс целиком не выдаётся; список не сообщает export/callability. search_r_documentation ищет в шести общих R manuals, а не по package APIs.

**Рекомендация P1-B — вариант C: отдельный ограниченный list_package_functions.** Он покажет version-scoped имена до docs lookup и раздельно представит export declarations, Rd aliases/topics и методы. Такой tool проще выбрать агенту при задаче «найди функцию». Дополнительно следует усилить get_function_docs error envelope, сохранив совместимость. Вариант B не подходит по смыслу; вариант A возможен, но прячет discovery в универсальном get_package и всё равно требует query/pagination.

Созданы только audit artifacts. Публичные API/schemas, scorer, frozen evidence и historical results не менялись. Не запускались тесты, модели, Agents API, Docker, R, сеть или B1/B2 trials.

## 2. MCP-инструменты

Точка регистрации — src/cran_knowledge_mcp/server.py. По умолчанию используется консолидированный набор из 15 tools; сохранён legacy-набор из 35 (server.py:993, create_server). Legacy также имеет resource cran://{package}/man/{alias}, который требует уже известный alias (server.py:1627). Аргументы описываются через Annotated/Literal/Field и публикуются в MCP schema. bounded() нормализует ошибки; tests/test_function_docs_hints.py проверяет isError=true и structuredContent.

Server-level instructions задаёт mcp_discovery.py. Без experimental environment override выбирается control: он описывает источники/provenance, но не даёт workflow поиска package functions. B1 treatment явно предлагает искать package, repository/release и official function docs/existing functions/Rd aliases; поясняет, что docs_not_found сам по себе не означает, что пакет не подходит, и просит не повторять идентичные запросы без причины. В B1 Treatment было 26 misses против 33 Control, но это описательная разница 12 trials, не причинное доказательство.

| Tool | Вход/валидация | Результат/границы |
|---|---|---|
| search_packages | Query 1–200 chars, limit 1–20, offset 0–100000, repository cran/bioconductor/all, Bioc release (server.py:997). | Package names/titles, version/category, provenance. CRAN: PACKAGES + каталог; Bioc: release-specific indexes. Функций нет. |
| get_package | Exact Package name; include — непустое подмножество пяти sections; verify_archive boolean. agent_guidance требует revision, context7 требует question ≤500 chars; revision/question разрешены только вместе с соответствующим section; repository=all запрещает эти внешние sections (service.py:1558–1598). | DESCRIPTION/index, прямые dependency-поля, ссылки или opt-in docs. Default — metadata. Function index отсутствует. |
| get_function_docs | Package, alias 1–160 chars, offset ≥0, repository/Bioc release; expected version в consolidated schema (server.py:1077, service.py:1648). | Raw Rd одного alias, 8000 chars/page, topic file, version, offset/next_offset и sources (providers/base.py:288–326). |
| search_r_documentation | Query 1–500 chars, один/несколько шести ManualId, limit 1–10, optional R version (server.py:1155). | Локальный поиск по шести общим R manuals; package/repository/version аргументов нет (providers/r_documentation.py:557–675). |

### Providers, версии, storage и errors

- PackageRepository — provider contract (providers/protocol.py:9–19). CranProvider и BioconductorProvider независимы; общий SourceRepository обрабатывает archive/Rd (providers/base.py:105–326).
- CRAN выбирает версию из текущего PACKAGES. Bioc разрешает release/devel/history и R mapping по официальному config.yaml (releases.py:23–78), далее выбирает package/version/category в release-specific indexes (providers/bioconductor.py:14–75). Исторические CRAN docs не подставляются; repository=all сохраняет identities отдельно.
- Archive читается в памяти: фиксированные маршруты, byte limits, доступная MD5 проверка, сверка Package/Version по DESCRIPTION; на диск не извлекается (http.py:139–285, providers/base.py:181–219). Код не выполняет R, package scripts или Rd expressions.
- HTTP cache process-local, TTL 300s default, LRU ≤32 objects/configured bytes; redirects off, trust_env=False, ограниченные retry (http.py:96–280). Parsed source cache ≤8 archives/48 MiB (providers/base.py:23–24, 141–160); это не постоянный function index.
- Внутри parsed-source cache хранятся валидированные DESCRIPTION и archive members, а alias index сопоставляет literal aliases с Rd archive members (providers/base.py:141–231). Это внутренние данные; отдельного MCP метода списка нет. Успешный docs result возвращает одну страницу/topic; miss details возвращают ограниченные имена, но не полный alias→topic map и не namespace export map.
- R manual provider читает локальный JSON cache и обновляется отдельной командой; лимиты source 8 MiB/index 64 MiB/section 256 KiB (providers/r_documentation.py:24–28, 98–106, 455–520, 810–884). Это index общих R manuals, не package archives.
- Общий failure() ставит top-level package_version=null, sources=[], помещая error URL/details внутрь error (service.py:164–181). Output capped at 60 000 bytes, outer deadline 60s (service.py:51, 2174–2229).

| Источник | Текущее назначение | Ограничение |
|---|---|---|
| CRAN PACKAGES/DESCRIPTION | Package/version/dependencies | Не список функций |
| CRAN/Bioc archive | Rd и aliases для docs retrieval | Нет namespace export index; доступна только выбранная версия/release |
| Bioc config/PACKAGES | Release/channel/R mapping/category | Не функции и не install test |
| Reference manuals | Не текущий package search backend | Topic не доказывает export/callability |
| Шесть R manuals | Offline R documentation search | Не package APIs |
| Context7/agent guidance | Opt-in complementary docs | Не полный/verifiable export index |
| Локальные installed packages/help() | Не вызваны/не подключены | Runtime потребовал бы выполнения R |

## 3. B1: что подтверждает docs_not_found

get_function_docs() выбирает package из repository index, загружает source archive, проверяет доступные checksum/version поля и строит индекс из .Rd. _alias_index() извлекает только буквальные \alias после удаления комментариев; макросы и условные Rd не разворачиваются (parsers.py:135–140, providers/base.py:220–231). Запрос сравнивается буквально и case-sensitive. Ноль совпадений даёт docs_not_found; несколько файлов с одним alias дают ambiguous_docs.

Это не доказывает отсутствие R-объекта, неправильный package, отсутствие re-export/method, отсутствие функции в другой версии или отказ upstream. Это lookup miss по alias index выбранного source archive.

Во всех 59 telemetry rows source_count=0 — свойство общего failure envelope, не признак отсутствия архива. 56 вызовов получили суммарно 213 HTTP cache hits; ещё 3 сделали upstream fetch и всё равно завершились docs_not_found. Сетевые/архивные ошибки имеют другие коды. Медиана длительности — около 2.2 ms, максимум 8.7 s при первичной загрузке источника.

Сохранённые call records дают 59 уникальных fingerprints. mcp_observations_v2.jsonl проецирует package/function/repository для 42 событий: termr 28, climenu 12, validate 2. Requested version доступна для 33 из 42: termr 1.0.1 — 22, climenu 0.2.0 — 10, validate 1.1.7 — 1. Остальные версии/идентификаторы неизвестны. events.json помечает call payload redacted; per-event error details, alias hints и source URL в безопасную проекцию не вошли. В CSV соседи показаны номером, tool и нормализованным статусом, без сообщений.

| Запрошенная категория | Подтверждённые причины | Вывод |
|---|---:|---|
| Буквальный Rd-alias miss | 59 | Высокая уверенность по error и коду provider-а. Это этап отказа, не первопричина. |
| Вероятно несуществующая функция | 0 установленных | Для всех 59 существование символа неизвестно. Гипотетические названия не доказательство. |
| Возможно неверный package | 0 установленных | Для 42 package известен, но намеренный API не восстановлен; у 17 скрыты даже аргументы. |
| Alias/topic mismatch | 42 с известными именами; 17 неидентифицируемы | Запрошенная строка не была literal alias; почему — не установлено. |
| Namespace/re-export mismatch | 0 подтверждено | NAMESPACE отсутствует в call telemetry; остаётся возможным, но непроверенным. |
| Version mismatch | 0 errors с таким кодом; 59 причин не разрешены | В 33 запросах есть requested version, но resolved archive version не сохранена. |
| Upstream/document retrieval failure | 0 source errors | 59 получили provider-level docs_not_found. Export discovery gap — ограничение, не доказанная причина misses. |
| Insufficient evidence | 59 | Корректная итоговая классификация root cause. |

44 ошибки непосредственно предшествуются другим get_function_docs:docs_not_found; после 15 следует успешный docs lookup. Это показывает последовательность попыток с альтернативными именами и успешные lookup-и в той же серии, но не связывает успешное имя с неудачным. Все 59 запросов различны; точных повторов miss нет. Call-by-call контекст есть в CSV.

Код уже генерирует alias hints только из alias index: полный список до 30 имён, иначе 10 ближайших по SequenceMatcher. pkg::name и name() учитываются только при ранжировании; точный lookup остаётся literal (parsers.py:142–176). Предложенные имена присутствуют как Rd aliases в загруженном archive, но это не подтверждает exported/callable function. Из-за redaction нельзя проверить, какие подсказки модель получила/прочитала/использовала.

## 4. Exports, help topics, aliases и callable API

Это разные множества и разные утверждения:

| Понятие | Источник | Что подтверждает / чего не подтверждает |
|---|---|---|
| Package/version/repository | CRAN/Bioc PACKAGES, DESCRIPTION, release config | Идентичность публикации; не наличие функции. |
| Namespace export declaration | NAMESPACE: export, exportPattern, exportClasses, exportMethods, importFrom, S3method | Статическое объявление имени/метода/re-export; не runtime binding и не документацию. Вычисляемые директивы могут остаться partial/unknown. |
| Rd alias | \alias в man/*.Rd; иногда help/AnIndex | Rd заявляет alias в данном archive; не доказывает export/callability и даже то, что сущность — обычная функция. |
| Help topic | \name, man/*.Rd, AnIndex, reference manual | Есть документированный topic; topic может иметь несколько aliases. Не тождествен символу. |
| S3 method | Alias generic.class и S3method в NAMESPACE | Подтверждает статическую method связь, если источники связаны; не отдельный экспортируемый symbol. |
| S4 generic/method | exportMethods/exportClasses, Rd, method metadata | Статические объявления; не регистрацию метода после загрузки package. |
| Callable runtime function | Успешное разрешение в установленном namespace/R session | Runtime-факт для конкретной среды; provider его не проверяет. |

Символ может экспортироваться под одним именем, а документация быть в общем Rd topic с другими aliases. Re-export может быть объявлен без собственной Rd страницы; topic может описывать internal объект; метод не всегда самостоятельная экспортируемая функция. Discovery response должен возвращать эти свидетельства раздельно и не называть каждую запись «существующей и вызываемой функцией».

## 5. Доступные offline sources

В checked-in src/tests/benchmarks не обнаружены .tar.gz, .pdf, NAMESPACE, help/AnIndex, Meta/nsInfo.rds или package .Rd files для целевых пакетов. B1 official_resources.json хранит версии, URLs и HTTP statuses источников, не архивы и не тела страниц. D01/D03 metadata фиксируют package/version/doc URL, но не документационное содержимое. tests/test_function_docs_hints.py использует синтетические архивы и fake Rd; это тест поведения, не source snapshot.

Поэтому offline можно подтвердить поведение реализации и telemetry, но нельзя решить, встречались ли запрошенные имена в NAMESPACE, другом topic или иной версии. Live CRAN/Bioc запросов не делалось.

Для будущей верификации CRAN нужен точный PACKAGES record + source archive версии: DESCRIPTION, NAMESPACE, Rd aliases, help/AnIndex, INDEX, при наличии Meta/nsInfo.rds. Для Bioc сначала фиксируются config.yaml release/R mapping, затем package category/version и архив именно этого релиза. Reference manual может служить отдельным fallback, с собственной version provenance. Installed-package helpers help(), help.search(), getNamespaceExports() здесь не вызываются: это потребовало бы выполнения R. utils:::.getHelpFile — private API и не рекомендованная зависимость. RDS не разбирался.

Точная проверка для спорного имени: «в package@version и repository/release есть ли имя в exports, Rd aliases или help topics, и какой topic его описывает?» Если понадобится upstream, сначала получить зафиксированные версии/хэши из официального индекса, ограниченно прочитать архив в памяти, не распаковывая на диск; сохранить URL, checksum, UTC check time. Для нынешнего аудита такой запрос не выполнялся.

## 6. Варианты API и рекомендация

| Вариант | Польза | Издержки/оценка |
|---|---|---|
| A — get_package(include=function_discovery) | Не добавляет отдельный tool; section можно запрашивать опционально. | get_package уже агрегирует разные metadata/docs. Полный список раздувает payload; нужны query/limit/offset и новые schema params. Discovery скрыт в include, вероятность выбора агентом неочевидна. Возможен, но не самый удобный. |
| B — расширить search_r_documentation | Есть локальный FTS по R manuals. | Текущий scope — шесть общих manuals, нет package/repository/version identity. Package search смешает две разные задачи и источники. Не рекомендую. |
| C — отдельный list_package_functions | Прямой tool name/description; package/repository/release/query/pagination явны. Возможен version-scoped индекс exports, aliases, topics, methods. | Один новый tool/schema; нужно удержать byte/row limits, provenance, version pin и тесты. Tool selection надо измерить. |

**Выбор: C.** Это не выбор по числу tools. В B1 агент уже вызывал get_package и затем делал длинные серии docs lookups; общее metadata не дало ему index. Явное имя инструмента лучше соответствует пользовательскому намерению, чем ещё один get_package include или изменение инструмента поиска R manuals. Текущие alias hints оставить recovery path, не выдавая за полный index.

## 7. Предлагаемый data contract

Поля результата должны отдельно нести: package, repository, bioc_version/channel, exact package_version, query, exports, documentation_topics (topic, aliases, archive_member), methods, matches, next_offset, verification_status, per-source provenance и limitations.

Для export-элемента указывать name, declaration_kind (explicit/pattern/method/reexport) и status (declared/partial/unknown). Для docs — topic и literal aliases. Для match — match_type (exact/alias/fuzzy), alias_verified, export_status и documentation_topic. Все имена-кандидаты копируются только из version-scoped источника; fuzzy показывает ранжирование, не наличие функции. Не включать placeholder/fabricated suggestions.

### Backward compatibility и payload budget

Новый tool не меняет существующие schemas/results. Error envelope get_function_docs может получить additive поля, сохраняя error.code/message. Держать query ≤200 chars, limit 1–50, bounded offset/cursor, target response ≤20 KiB (общий hard limit сейчас 60 KB); выдавать компактные имена и paging, не тела Rd. Successful docs остаются в отдельном tool с paging по 8 000 chars.

Ключ parsed index/cache: repository + resolved Bioc release/channel + package + exact version + artifact content identity. Версия страницы должна оставаться стабильной; при обновлении источника возвращать stale/version error вместо смешивания. Первая загрузка архива может увеличить latency; последующие операции используют process-local cache. Источник/freshness должны показываться в ответе.

## 8. Доработки get_function_docs

1. Сохранить literal exact lookup; не возвращать fuzzy candidate как точный docs result.
2. В docs_not_found добавить requested_function, resolved_package_version, version_scope, lookup_stage=rd_alias, provenance и structured suggestions; оставить существующие error fields.
3. Подсказка должна нести match_type, подтверждение присутствия alias в архиве, topic/archive member, отдельный export_status и callability=not_checked. Fuzzy rank не подтверждает экспорт.
4. Разделить requested_package_version и available_package_version. При несовпадении вернуть requested_version_unavailable без подстановки current; при неизвестной версии обозначить фактический current/release scope.
5. При package_not_found/source_unavailable/checksum errors не строить hints из другого источника/version. Для repository=all сохранять partial и identity каждого результата.
6. Тестировать exact alias/topic, общий topic с несколькими aliases, namespace-qualified input, alias typo, отсутствующее имя, ambiguous topics, unknown version, partial source, package missing, empty suggestions и неподтверждённый fuzzy.
7. Для fuzzy показывать только names из проверенного alias/export index. Если подтверждённых вариантов нет — пустой список и явное объяснение; не придумывать имя.

Общий failure() сейчас теряет top-level package_version/sources. В P1-B нужно сохранить точную source provenance для ошибки, не менять успешный docs contract и не делать выводы из одного error URL.

## 9. Offline replay

Replay — детерминированная проверка retrieval без модели и без live tool.

Доступно: 59 fingerprints/statuses/call sequence, 42 safe argument projections, requested version для 33 из них, task reference versions termr 1.0.1/climenu 0.2.0/validate 1.1.7, provider code и B1 official_resources URLs/statuses. Недоступно: args для 17 events, per-event error.details, фактический resolved archive version/source URL и archive/manual bytes. В checked-in дереве нет этих package archives. CSV оставляет неизвестное пустым.

Для replay всех 59 нужны безопасно сохранённые исходные args и pinned source fixtures каждого package/version. Если 17 args не удастся восстановить, знаменатель replay — только 42, а оставшиеся помечаются excluded_missing_request_projection. Не восстанавливать их по соседним вызовам или похожести fingerprint.

План:
1. Зафиксировать repo, package, version, release/category, fixed source URL, checksum/content digest и UTC checked_at. HTTP заменить httpx.MockTransport; archive читать ограниченно в памяти, не распаковывать на диск, R не запускать.
2. Прогнать прежний и новый resolver на одинаковых bytes/args. Раздельно считать exact alias, нормализованный alias/topic, export-to-topic match, fuzzy suggestion, unresolved, source/version unavailable.
3. Считать docs miss предотвращённым только если точные version-scoped docs реально получены. Fuzzy suggestion сам по себе не retrieval success.
4. Проверить false positives по отдельным oracle: exported declaration — NAMESPACE; alias/topic — Rd/AnIndex. Ноль ложных заявлений verified export/alias; runtime-callability не заявлять.
5. Результаты retrieval replay не считать экспериментом AI агента.

После появления offline fixtures проверки можно запускать pytest с MockTransport; B1 historical artifacts останутся нетронутыми.

## 10. Критерии и дизайн B2

B2 не запускался. Метрики на уровне trial: docs_not_found; успешные verified docs lookups; exact/alias/fuzzy discovery; unique failed names; final answer correctness; scorer abstention; MCP calls/adoption; correction attempts/recovery. Дополнительно: latency p50/p95, response bytes/tokens, source verification и неверные recommendations. Calls внутри одного trial зависимы и не являются независимыми observations.

Предлагаемый небольшой design: задачи D01-termr, D01-climenu, D03-validate, negative/ambiguous discovery, version-bound lookup и non-discovery control. Пять paired repetitions на задачу, порядок условий рандомизировать. Control/Treatment различаются только доступностью нового tool; prompts, server description, остальные tools, model settings, tasks, scorer и pinned fixtures одинаковы. Не совмещать добавление tool с изменением server-level description.

Предлагаемые заранее заданные пороги: offline replay — 0 false verified exports/aliases и рост exact/verified docs resolution против baseline; B2 — минимум 30% меньше docs_not_found на discovery tasks, без ухудшения scorer correctness и abstention на negative/control cases. Публиковать pair deltas и raw counts; при малом N выводы считать exploratory. Чтобы оценить отдельно server description, провести отдельный эксперимент с той же реализацией/toolset/prompts, меняя только description. Успех retrieval replay не доказывает, что агент выберет tool или корректно применит ответ.

## 11. Риски, unknowns и план P1-B

Открытые вопросы: отсутствуют 17 request args и 59 raw error details; нет package source/manual snapshots, поэтому реальные имена/topics не adjudicated; static NAMESPACE parse не доказывает runtime binding; exportPattern/dynamic directives требуют partial/unknown; aliases/manuals/archive могут различаться по completeness; current CRAN version меняется; B1 не показывает, использовал ли агент существующие alias hints. Control/Treatment в B1 малы и различались server description, поэтому 33→26 — только описательная разница.

Приоритеты:
1. Зафиксировать semantics identity, export/re-export, method, alias/topic и per-field completeness; собрать pinned offline fixtures с digest.
2. Добавить provider operation list_package_functions в PackageRepository и использовать безопасный version-matched archive parse для CRAN и Bioc; без R/package execution.
3. Зарегистрировать bounded tool list_package_functions с query/limit/offset, provenance, version pin и понятным description.
4. Обогатить get_function_docs errors verified alias suggestions, topic/version/source metadata и явным export/callability status.
5. Добавить MockTransport tests: multiple aliases per topic, exported-but-undocumented/re-export, non-export topic, S3/S4, dynamic export, version drift, source unavailable, empty/fuzzy suggestions и payload cap.
6. Выполнить offline replay; если inputs для 17 misses не восстановлены — отчётно ограничить его 42/59.
7. Только после нулевой false-verified ошибки review результатов и запускать отдельный one-variable B2.

## 12. Проверка и evidence

Создан inventory ровно на 59 строк с 59 unique fingerprints; 42 события имеют projected package/name, 17 оставлены неизвестными. JSON/Markdown согласованы по 59 unresolved root causes. Tests не запускались: implementation не менялся, этап — offline audit/artifacts. Сеть и внешние сервисы не использовались.

Локальные evidence:
- MCP schemas/routing: src/cran_knowledge_mcp/server.py:266–305, 993–1170, 1627–1635.
- Service/errors/version/output: src/cran_knowledge_mcp/service.py:51, 139, 164–181, 352–493, 1558–1680, 2174–2229.
- Providers/releases: providers/protocol.py:9–19, providers/base.py:105–326, providers/cran.py:39–190, providers/bioconductor.py:14–108, releases.py:23–101.
- Alias parsing/hints: parsers.py:86–176; tests/test_function_docs_hints.py.
- HTTP/cache: http.py:25–31, 96–285; providers/base.py:23–24, 141–231.
- R manuals: providers/r_documentation.py:24–28, 98–106, 455–675, 810–884.
- Server instructions: src/cran_knowledge_mcp/mcp_discovery.py:7–46.
- B1 local run: benchmarks/codex_r/results/20261026T104750Z-f78eabf1/{mcp_calls.csv,mcp_observations_v2.jsonl,events.json,experiment.json}; previous audit: benchmarks/codex_r/reports/b1_discovery_offline_audit_20261026.md/.json.
- Pinned package metadata (URLs/version/status, not bodies): benchmarks/codex_r/knowledge_pilot/verifier/official_resources.json, metadata/D01.json, metadata/D03.json.

