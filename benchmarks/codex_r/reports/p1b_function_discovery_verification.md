# P1-B — проверка реализации

Реализация завершена. Разрешённый полный offline-прогон WSL завершился: **1474 passed, 0 failed, 43 skipped, 22 deselected**, exit code 0, 1308.63 с (21:48.63).

## Проверки

| Проверка | Результат |
|---|---|
| WSL offline pytest | 1474 passed, 43 skipped, 22 deselected |
| Windows actual PyO3/native targeted pytest | 145 passed, 0 failed, 0 skipped |
| WSL Python fallback targeted pytest | 102 passed, 0 failed, 43 skipped |
| Rust unit tests | 4 passed, 0 failed, 0 ignored |
| cargo fmt --check | passed |
| cargo check --offline | passed |
| cargo clippy --offline --release -- -D warnings | passed |
| WSL Ruff check | All checks passed |
| WSL Ruff format --check | 255 files already formatted |
| Windows maturin wheel build/install/import | passed; ABI_VERSION=3 |
| Native CI YAML parsing | passed; CI itself not executed |

Все 43 пропуска полного WSL-прогона связаны с отсутствием native extension: 9 native availability, 9 actual-PyO3 parity, 1 binding check, 24 existing native parity tests. Они не засчитаны как native passes; actual native проверен отдельно в Windows.

## Точные команды

Из корня репозитория:

```text
wsl -d Ubuntu --cd /mnt/c/programming_pj/cran-mcp --exec .venv-wsl/bin/python -m pytest -q --tb=short -m 'not docker' --ignore=tests/test_codex_launcher.py -o usefixtures=r01a_offline_guard --basetemp=/tmp/cran-mcp-p1b-resumed-review --junitxml=.test-tmp/p1b-resumed-review.xml
.venv-wsl/bin/python -m ruff check .
.venv-wsl/bin/python -m ruff format --check .
```

Targeted suite (Windows actual native и WSL fallback, соответствующим Python):

```text
python -m pytest tests/test_function_discovery.py tests/test_function_docs_hints.py tests/test_function_discovery_replay.py tests/test_native_parity.py tests/test_consolidated_server.py tests/test_prompt_docs_contract.py -q --tb=short -o usefixtures=r01a_offline_guard
```

Из native/, Windows:

```text
cargo fmt --check
cargo check --offline
cargo clippy --offline --release -- -D warnings
cargo test --offline
maturin build --release --offline -i ../.venv/Scripts/python.exe --out target/p1b-wheels
```

Локальный wheel установлен через available pip с --python .venv/Scripts/python.exe, --no-index, --no-deps и --force-reinstall. Импорт cran_knowledge_native и новый input-bound проверены реально собранной библиотекой.

## Ограничения и история проверки

WSL доступен с escalated sandbox execution. Linux Cargo/maturin отсутствуют; Windows wheel собран и импортирован. Добавленный Linux native CI job локально не исполнялся.

R-executing tests/test_codex_launcher.py исключён полностью до collection; 22 Docker-marked tests deselected. Это разрешённый offline-набор, а не безусловная проверка всех runtime/platform вариантов.

Первый Windows full-run: 231 failed, 1225 passed, 74 skipped, 22 deselected. Каталоги внутри evaluator repository и Windows POSIX/private-evidence ограничения сделали его непригодным для release validation. Выявленная checked_at compatibility regression исправлена сохранением прежнего failed envelope; прежний prompt contract test не ослаблен. Промежуточные WSL-прогоны прерывались для исправлений и не засчитаны как полные passes. Предыдущий итоговый процесс исчез после 66% при остановке сеанса; после просьбы пользователя продолжить выполнен новый прогон, успешно завершившийся указанным результатом.

При двух ранних WSL collections существующий launcher test выполнил Rscript dependency-readiness probe. Это раскрыто; дальнейшие прогоны исключили этот файл. Новая MCP реализация не исполняет R, package scripts, NAMESPACE или Rd.

## Research integrity

Replay: 59 событий; 17 excluded missing identity; 42 excluded missing pinned source; 0 evaluated. Historical improvement metrics = null. Synthetic tests не представлены как измеренное улучшение B1 или агентов.

Повторная SHA256-проверка подтвердила сохранность B1 results/experiment/call log/observations, frozen V2.1 evidence и существующего server discovery текста. Значения hashes и полный перечень изменённых P1-B файлов — в соседнем JSON.

Модели, Agents API, B1/B2 trials, Docker и live package requests не запускались; архивы не загружались. B2 подготовлен только как design document.

**Release readiness: NOT READY для безусловного выпуска всего проекта.** Разрешённые offline Python и Windows native проверки прошли; R/Docker и Linux native build остаются непроверенными. Известных нерешённых семантических расхождений Python/native нет. Реализация готова к review в пределах этих явно указанных ограничений.
