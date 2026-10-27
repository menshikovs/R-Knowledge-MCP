# Codex executor connection hang: расследование

Проверка: 2026-10-26, 10:37 UTC. Инцидент: `20261026T101505Z-5544127a`,
trial `b1-discovery-D03-R1-control`. Внешние sessions и model calls при расследовании
не создавались. Уже существовавшие изменения рабочего дерева сохранены.

## 1. Root cause

**not established** для первоначального зависания. Старые артефакты не позволяют
установить, остановился ли executor на регистрации, WebSocket/rendezvous, Noise
handshake или доставке readiness-события приложению. TCP ESTABLISHED этого не различает.

Подтверждены два дефекта наблюдаемости: отсутствие `environment.status` трактовалось
надписью watchdog как «not connected»; runtime по умолчанию скрывал info/warn события
регистрации и подключения. Они исправлены как диагностика, а не объявлены причиной hang.

## 2. Evidence

- Сохранённый `result.json`: session created на 4.8 s, executor started на 5.2 s,
  watchdog на 50.9 s; API probe HTTP 200, `api_environment_status=null`,
  `api_environment_error=null`. `events.json` содержит пустой список.
  Это не доказывает ни наличие SSE headers, ни отсутствие байтов/keepalive в потоке.
- В отличие от исходного описания, **удаление последней remote session подтверждено**:
  `session_deleted=true`, `cleanup_operations.delete_session.status=confirmed`, HTTP 200.
  Docker removals и workspace cleanup также confirmed. Это подтверждение сохранённого
  ответа клиента, а не новая независимая инвентаризация сервиса.
- Фактическая среда Ubuntu venv: Python **3.14.4**, HTTPX **0.28.1**, MCP SDK **1.30.0**.
  Пакет `openai` не установлен. `ManagedAgentsClient` — локальный HTTPX-клиент;
  `wait_for_executor()` в проверенном пути отсутствует. MCP SDK обслуживает MCP,
  но не выполняет регистрацию Codex executor.
- Проверен именно executor image инцидента:
  `sha256:ab9eefda7d00d6872d1e62f5e3fba2a683317f6969b3ac3ab5bfa94f42c9976d`.
  Его `--version` сообщает **codex-cli 0.163.0**; `exec-server --help` поддерживает
  используемые `--remote` и `--environment-id`, transport по умолчанию **noise**.
- Изучены исходники тега `rust-v0.163.0`: `remote.rs`, `remote/registration_retry.rs`,
  `remote/connection_diagnostics.rs`, CLI `exec_server_command.rs`,
  `exec_server_telemetry.rs`, `arg0/src/lib.rs`; локальные HTTPX `_client.py` и `_models.py`.
  Default stderr filter runtime — error; registration/rendezvous success — info,
  retry и rendezvous failures — warn.
  Источники: [remote registration](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/exec-server/src/remote.rs),
  [stderr filter](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/cli/src/exec_server_telemetry.rs),
  [PATH aliases](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/arg0/src/lib.rs).
- Предупреждение PATH aliases воспроизведено при `--version` и `--help` без сети и
  ключей. В `arg0` оно возникает из-за запрета размещать aliases под системным temp,
  до попытки создать эти aliases; CLI продолжает работу. Это **не свидетельство EACCES**
  на регистрацию и не подтверждённая причина hang.
- Настоящий binary дополнительно проверен на синтетическом loopback registry:
  два контейнера делили namespace контейнера с `network=none`; ключ был синтетическим.
  Проверены ожидаемый registration route и Authorization, registry вернул 401,
  Codex завершился с явным authentication error. Ни Agents API, ни внешняя сеть,
  ни модель в этом эксперименте не использовались. Следовательно, устойчивое
  молчание исходного контейнера не объясняется автоматически таким же fatal 401.

Контракт self-hosted запуска и требования к ownership environment key сверены с
[OpenAI Docs: Self-hosted sandboxes](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted).
Текущий документированный SelfHosted response не обещает поля `environment.status`:
[Create session reference](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/methods/create).

## 3. Connection lifecycle

1. `main()` проверяет ключи и образы, планирует trials; `run_trial()` готовит workspace,
   bridge network и при необходимости MCP container.
2. `SimpleClient.create_simple_session()` выполняет единственный POST session с
   application key. Проверяются session ID, environment ID, тип self_hosted,
   reviewed origin/path endpoint, выбранные model/effort.
3. **Из ответа**, без конструирования собственного endpoint, берутся
   `environment.remote_url` и `environment.id`. URL передаётся executor без изменения;
   session ID применяется только в application API routes. Environment key передаётся
   как `CODEX_API_KEY` через child environment, application credentials исключаются.
4. `send_and_stream()` начинает Docker startup в daemon thread независимо от получения
   SSE headers. Основной поток открывает SSE GET; после headers ждёт startup Future,
   затем делает session GET и читает SSE lines. Это синхронная реализация, не asyncio.
   HTTPX 0.28.1 возвращает headers до чтения body, а `iter_lines()` может ждать байты.
5. Codex инициирует регистрацию сам. Для noise transport он регистрирует executor key,
   получает rendezvous allocation, устанавливает исходящий WebSocket, затем обслуживает
   авторизованные Noise streams harness. Ни живой процесс, ни регистрация, ни WebSocket
   по отдельности не равны readiness всей session.
6. Runner отправляет input один раз после `agent.session.environment.connected`.
   В обычном режиме сохранён прежний optional fallback на `environment.status=connected`;
   отсутствие этого поля не восстанавливает пропущенное событие. Probe принимает
   readiness только по SSE-событию и физически блокирует `submit_task()`.
7. По завершении/ошибке/отмене выполняются независимые bounded cleanup attempts.
   Продолжительность trial ограничивает прежний SIGALRM; 45 s watchdog остаётся
   наблюдением, без abort/retry.

Потенциальное окно между executor startup и SSE subscription существует; первоначальные
логи не устанавливают, произошло ли readiness-событие внутри этого окна. Не объявляем
race подтверждённым. Восстановление потока по saved items не гарантирует восстановление
всех промежуточных событий: [OpenAI Docs: Events and items](https://developers.openai.com/api/docs/guides/agents-api/sessions/events).

## 4. Standard vs B1

Путь session → Docker → регистрация → SSE → input **общий**. B1 меняет выбранные tasks,
порядок/идентификаторы trials, scorer selection/provenance и MCP discovery variant.
Control/Treatment передаётся в MCP container; для одинаковых task/effort/mode session
request остаётся одинаковым. Standard может выбирать другие tasks и without-MCP.
Дополнительная MCP-подготовка происходит до создания session. Оснований приписывать
сам механизм подключения B1 нет.

## 5. Fix

Добавлен `connection.jsonl`: закрытый набор стадий, фактическое UTC время,
monotonic elapsed и интервал с предыдущей записью, HTTP status, известные error codes,
категории исключений и boolean-сравнения binding. Файл append-only, flush/fsync при
каждой записи, максимум 512 записей. Межстадийные интервалы — время наблюдений,
а не скрытая серверная длительность TLS/handshake.

Узкий `RUST_LOG` включает info только для проверенного `codex_exec_server::remote`,
сохраняя стандартный error-level и выключенные OTEL log targets. Debug, request bodies,
response bodies, credentials, URLs, IDs и пользовательские payloads в новый журнал
не записываются. Из runtime stderr извлекаются только фиксированные markers,
HTTP statuses и закрытый набор error/rejection kinds. `false` у marker означает
«не наблюдался», а не доказательство отсутствия события.

Watchdog при отсутствующем API status сообщает `executor connection unknown`.
При фактически несовпадающем session/environment binding input блокируется.
Добавлен отдельный connection-only probe: одна session, без MCP и input, sampling
состояния процесса/registration/WebSocket каждые 2 s, bounded wait и cleanup.
Планирование, scorer, descriptions/digests, trial timeout, SDK и образы не изменены.

## 6. Files changed

- `benchmarks/codex_r/run_simple.py` — подключение диагностики и safe binding guard.
- `benchmarks/codex_r/connection_diagnostics.py` — журнал и проекция runtime evidence.
- `benchmarks/codex_r/probe_executor_connection.py` — отдельно разрешаемый probe без input.
- `tests/test_codex_connection_diagnostics.py` — offline regression tests.
- Этот отчёт. Ранее существовавшие изменения остальных файлов не относятся к расследованию.

## 7. Tests

В Ubuntu WSL2, `.venv-wsl/bin/python`:

```text
-m pytest tests/test_codex_connection_diagnostics.py tests/test_codex_simple.py
  tests/test_codex_simple_interrupts.py tests/test_codex_simple_resume.py -q
82 passed

-m pytest tests/test_codex_connection_diagnostics.py
  tests/test_codex_executor_contract_integration.py tests/test_codex_managed_agents.py
  tests/test_codex_simple.py tests/test_codex_simple_interrupts.py
  tests/test_codex_simple_resume.py -q
169 passed

-m pytest tests/test_codex_connection_diagnostics.py
  tests/test_codex_simple_interrupts.py -k "connection or watchdog" -q
28 passed, 26 deselected (после последних изменений)

-m pytest tests/test_mcp_discovery.py -q
14 passed (Standard/B1 requests, порядок, Control/Treatment, digests)

-m ruff check .
All checks passed!

-m ruff format --check .
241 files already formatted
```

В этих тестах network/subprocess/Docker вызовы запрещены или заменены mocks;
используются HTTPX MockTransport и synthetic SSE/process evidence. Проверяются
успех, одно input, pending/timeout, 401/403 и registration failure, mismatched binding,
отмена, process exit, cleanup, unconfirmed deletion и отсутствие секретов/payloads.
Отдельный ручной Docker loopback эксперимент выше не входит в pytest.
Первоначальный Windows pytest не смог создать temp directory из-за доступа;
проверки перенесены в запрошенный WSL.
Полный pytest не запускался: выполнен набор затронутого connection lifecycle и B1.
Образы не пересобирались, Dockerfiles и runtime binaries не менялись.

## 8. Remaining uncertainty

| Гипотеза | Итог |
| --- | --- |
| H1 SDK/runtime mismatch | OpenAI SDK не используется; flags и local registration поддержаны. Совместимость с реальным сервисом не доказана. |
| H2 Auth/TLS/handshake | Fatal synthetic 401 корректно виден. Реальный ответ на регистрацию и WSS handshake инцидента неизвестен. |
| H3 Binding | Код использует правильные поля без подмены URL. Исторический returned environment ID не сохранён для независимого сравнения. |
| H4 Ожидание/SSE | Отсутствующий `environment.status` не доказывает pending. Момент SSE headers и первое событие исторически неизвестны. |
| H5 Filesystem | PATH warning не является отказом регистрации. Полное отсутствие любых файловых проблем этим не доказано. |
| H6 Launch | Аргументы, ключевая переменная, UID, cwd соответствуют проверенному контракту. Исторический bind mount до interruption повторно не исследован. |
| H7 Ordering | Startup не блокируется на SSE headers; окно раннего события существует. Факт потери события не доказан. |

## 9. Next safe experiment

**Только после отдельного разрешения пользователя**, в терминале Ubuntu с уже
настроенными application и restricted environment credentials выполнить один probe:

```bash
.venv-wsl/bin/python -m benchmarks.codex_r.probe_executor_connection \
  --allow-session-create \
  --executor-image sha256:ab9eefda7d00d6872d1e62f5e3fba2a683317f6969b3ac3ab5bfa94f42c9976d \
  --seconds 60 \
  --output benchmarks/codex_r/results/connection-probe-manual-20261026
```

Команда **не выполнялась**. Флаг — явный operator gate, а не разрешение от имени
пользователя и не обещание бесплатности session. Output directory должен быть новым.
Нет B1, model input, scorer или повторной session.

Читать только `connection.jsonl`:

| Наблюдение | Что оно различает |
| --- | --- |
| authentication HTTP 401/403 | Явный registration/auth rejection, а не простой pending. |
| binding_mismatch или protocol rejection | Несовместимый binding/registration response. |
| registration_completed, затем TLS/I/O/HTTP rejection | Регистрация прошла; сбой находится на rendezvous/WebSocket этапе. |
| registration_retry_observed | Runtime повторяет строго определённые upstream registration conflicts/auth-service outages; это не retry benchmark/model input. |
| rendezvous_connected без environment.connected | WSS установлен; дальше остаются harness/Noise authorization/readiness/SSE, нельзя объявлять полное подключение. |
| нет sse_headers_received | Приложение ждёт открытия SSE, а не получает readiness events. |
| environment_connected | Readiness-событие действительно дошло; input probe всё равно не отправляет. |
| running=false и exit_code | Executor завершился до readiness. |

Если регистрация и WSS проходят, но readiness не приходит, одного клиентского probe
недостаточно для однозначного разделения внутренней ошибки harness и потерянного
server-side события. Тогда нужен provider-side trace за сохранённое UTC окно,
доступный владельцу session. Этот остаточный предел наблюдаемости указан явно;
успех offline-тестов не является успешным реальным подключением.

## 10. Risks

Инструментирование привязано к проверенным markers Codex 0.163.0; после смены binary
нужна повторная проверка исходников. Дополнительные fsync и info logs немного влияют
на время запуска; logs ограничены прежними Docker limits. Bind mount, UID 65534,
read-only rootfs, caps, no-new-privileges и лимиты ресурсов сохранены. Probe не
содержит model input, однако session остаётся реальным API-ресурсом и требует
разрешения. Журнал не заменяет server-side handshake trace и не позволяет восстановить
утраченные данные исходного запуска. Публикация, push, merge и paid trials не выполнялись.
