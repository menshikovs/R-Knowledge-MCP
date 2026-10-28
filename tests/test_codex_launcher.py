"""Launcher (R/termr front end) checks that need the real runner or a real terminal.

The R unit and headless-UI tests live in benchmarks/codex_r/launcher/tests/testthat and
run here too when R, termr and testthat are installed. Nothing here starts Docker, the
network, or a real benchmark trial.
"""

import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from benchmarks.codex_r import run_simple as simple

LAUNCHER = Path(__file__).resolve().parents[1] / "benchmarks" / "codex_r" / "launcher"
RSCRIPT = shutil.which("Rscript")
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Launcher needs POSIX signals/PTY")


def r_ready(*packages):
    if not RSCRIPT:
        return False
    code = " && ".join(f'requireNamespace("{p}", quietly=TRUE)' for p in packages)
    result = subprocess.run([RSCRIPT, "-e", f"quit(status=!({code}))"], capture_output=True)
    return result.returncode == 0


needs_termr = pytest.mark.skipif(
    not r_ready("termr", "testthat"), reason="R, termr or testthat missing"
)


def r_eval(code):
    source = f'source("{LAUNCHER / "launcher_core.R"}"); {code}'
    result = subprocess.run(
        [RSCRIPT, "-e", source], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def runner_help():
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), pytest.raises(SystemExit):
        simple.main(["--help"])
    return out.getvalue() + err.getvalue()


@needs_termr
def test_launcher_flags_and_choices_match_the_real_runner_parser():
    text = runner_help()
    args = r_eval('cat(build_args(default_config()), sep="\n")').split()
    flags = [a for a in args if a.startswith("--")]
    assert set(flags) >= {"--effort", "--tasks", "--modes", "--repetitions", "--timeout"}
    for flag in {*flags, "--pilot"}:
        assert flag in text, f"runner no longer has {flag}"
    flat = re.sub(r"\s+", " ", text)
    assert "--effort {medium,high}" in flat
    assert "--modes {without-mcp,with-mcp}" in flat
    match = re.search(r"--knowledge-pilot-scorer \{([^}]+)\}", flat)
    assert match is not None
    runner_scorers = set(match.group(1).split(","))
    required_scorers = {"legacy", "knowledge-pilot-v2", "knowledge-pilot-v2.1"}
    assert runner_scorers >= required_scorers
    launcher_scorers = set(r_eval("cat(SCORERS, sep=',')").split(","))
    assert launcher_scorers == runner_scorers
    assert "--pilot {tool-value,full}" in flat
    assert simple.STANDARD_INSTRUCTIONS and set(simple.INSTRUCTION_VARIANTS) == {
        "standard",
        "diagnostic",
    }


@needs_termr
def test_launcher_parses_the_runner_s_real_progress_output():
    record = {}
    progress = simple.Progress("H01-B-1", record, interval=3600)
    out = io.StringIO()
    with redirect_stdout(out):
        progress.event("session created", stage="s")
        progress.event("Docker executor started", detail="x")
    lines = out.getvalue().splitlines()
    expected = ["session created", "Docker executor started (x)"]
    assert len(lines) == len(expected)
    for line, activity in zip(lines, expected, strict=True):
        parsed = r_eval(
            f'x <- parse_runner_line({line!r}); cat(x$kind, x$trial, x$activity, sep="|")'
        )
        assert parsed == f"event|H01-B-1|{activity}"


RUNNER_SPEC = (
    'runner <- list(command="{py}", wd="{root}", info_script="{info}", prefix=c("-m", '
    '"benchmarks.codex_r.run_simple"), require_keys=FALSE); catalog <- load_catalog(runner); '
)


def runner_spec():
    return RUNNER_SPEC.format(
        py=sys.executable, root=LAUNCHER.parents[2], info=LAUNCHER / "runner_info.py"
    )


@needs_termr
def test_launcher_task_catalog_comes_from_the_runner():
    out = r_eval(runner_spec() + "cat(catalog$full, sep=' ')")
    assert out.split() == list(simple.FULL_VERIFIED_TASKS)


@needs_termr
def test_b1_plan_and_scorers_come_from_the_runner_planner():
    order = r_eval(runner_spec() + "cat(catalog$b1_order, sep=' ')").split()
    expected = [
        f"{t['task']}:{t['repetition']}:{t['condition']}"
        for t in simple.planned_b1_trials(list(simple.B1_DISCOVERY_TASKS), 2)
    ]
    assert order == expected and len(order) == 12
    raw = r_eval(runner_spec() + "cat(catalog$b1_scorers, sep=' ')").split()
    scorers = dict(item.split(":") for item in raw)
    assert scorers == {"D03": "knowledge-pilot-v2", "D01": "knowledge-pilot-v2", "C01": "legacy"}
    assert r_eval(runner_spec() + "cat(planned_trials(b1_config(catalog), catalog))") == "12"


@needs_termr
def test_b1_images_are_the_runner_s_images():
    source = Path(simple.__file__).read_text(encoding="utf-8")
    for image in (
        "rkmcp-codex-runtime:codex-0.163.0-bioc",
        "codex-r-benchmark:pilot-bioc",
        "cran-knowledge-mcp:shiny-quarto",
    ):
        assert image in source


@needs_termr
@pytest.mark.parametrize("kind", ["standard", "b1"])
def test_launcher_command_lines_pass_the_runner_s_own_argument_validation(
    kind, tmp_path, monkeypatch
):
    config = "default_config()" if kind == "standard" else "b1_config(catalog)"
    args = r_eval(runner_spec() + f'cat(build_args({config}), sep=" ")').split()
    assert ("--experiment" in args) is (kind == "b1")
    for name in ("OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # Parsing succeeds (no SystemExit) and the run stops at the credential check, before
    # any Docker or API work; the results directory is a temporary one.
    assert simple.main([*args, "--results", str(tmp_path)]) == 1


@needs_termr
def test_launcher_passes_v21_scorer_to_real_runner_without_starting_benchmark(
    tmp_path, monkeypatch
):
    code = (
        runner_spec()
        + 'cfg <- modifyList(default_config(), list(tasks="D01", scorer="knowledge-pilot-v2.1")); '
        + 'cat(build_args(cfg), sep=" ")'
    )
    args = r_eval(code).split()
    scorer_index = args.index("--knowledge-pilot-scorer")
    assert args[scorer_index + 1] == "knowledge-pilot-v2.1"
    for name in ("OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert simple.main([*args, "--results", str(tmp_path)]) == 1
    assert not list(tmp_path.glob("*/result.json"))


@needs_termr
def test_launcher_resume_command_is_accepted_by_the_runner_parser(tmp_path, monkeypatch):
    run = tmp_path / "20261026T100000Z-aaaaaaaa"
    run.mkdir()
    with pytest.raises(SystemExit) as exit_info:  # parser error: missing experiment.json
        simple.main(["--effort", "medium", "--resume", str(run)])
    assert exit_info.value.code == 2


TAB = chr(9)


def load_info():
    spec = importlib.util.spec_from_file_location("runner_info", LAUNCHER / "runner_info.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_run(root, name, experiment=None, aggregate=None, trials=None):
    import json

    run = root / name
    run.mkdir(parents=True)
    if experiment is not None:
        (run / "experiment.json").write_text(json.dumps(experiment), encoding="utf-8")
    if aggregate is not None:
        (run / "results.json").write_text(json.dumps(aggregate), encoding="utf-8")
    for trial_id, record in (trials or {}).items():
        (run / trial_id).mkdir()
        (run / trial_id / "result.json").write_text(json.dumps(record), encoding="utf-8")
    return run


def b1_manifest(run_id):
    plan = [
        {
            "trial_id": f"b1-discovery-D03-R1-{c}",
            "task": "D03",
            "mode": "with-mcp",
            "repetition": 1,
            "condition": c,
            "execution_order": i,
        }
        for i, c in enumerate(("control", "treatment"), start=1)
    ]
    return {
        "run_id": run_id,
        "experiment_id": "b1-discovery",
        "effort": "medium",
        "created_at_utc": "2026-10-26T10:00:00Z",
        "trial_count": 2,
        "trial_plan": plan,
    }


def b1_record(run_id, condition, **extra):
    order = {"control": 1, "treatment": 2}[condition]
    return {
        "run_id": run_id,
        "trial_id": f"b1-discovery-D03-R1-{condition}",
        "task": "D03",
        "mode": "with-mcp",
        "repetition": 1,
        "condition": condition,
        "execution_order": order,
        **extra,
    }


def test_run_index_reports_only_what_is_recorded(tmp_path):
    info = load_info()
    rid = "20261026T100000Z-aaaaaaaa"
    run = write_run(
        tmp_path,
        rid,
        b1_manifest(rid),
        [
            b1_record(
                rid,
                "control",
                status="scored",
                score={"passed": 4, "total": 4},
                cleanup_completed=True,
            )
        ],
    )
    described = info.describe(run)
    assert (described["experiment"], described["total"], described["recorded"]) == (
        "b1-discovery",
        "2",
        "1",
    )
    assert described["status"] == "partial" and described["resume"] == "ok"
    assert described["cleanup"] == "complete"


def test_run_index_marks_interrupted_incomplete_and_unknown_runs(tmp_path):
    info = load_info()
    rid = "20261026T090000Z-bbbbbbbb"
    interrupted = write_run(
        tmp_path,
        rid,
        b1_manifest(rid),
        [
            b1_record(
                rid,
                "control",
                status="interrupted",
                interrupted=True,
                score=None,
                cleanup_completed=False,
            )
        ],
    )
    described = info.describe(interrupted)
    assert described["status"] == "interrupted" and described["cleanup"] == "incomplete"
    # No manifest and no results: nothing is invented.
    empty = info.describe(write_run(tmp_path, "20261026T080000Z-cccccccc"))
    assert empty["status"] == "unknown" and empty["total"] == "unknown"
    assert empty["resume"].startswith("blocked")
    # A manifest-less run that only has an error record keeps its recorded status.
    early = info.describe(
        write_run(tmp_path, "20261026T070000Z-dddddddd", aggregate=[{"status": "interrupted"}])
    )
    assert early["status"] == "interrupted" and early["resume"].startswith("blocked")


def test_run_index_blocks_runs_the_runner_refuses_to_resume(tmp_path):
    info = load_info()
    rid = "20261026T100000Z-eeeeeeee"
    # The trial directory exists without a finalized result: the runner refuses to repeat it.
    run = write_run(tmp_path, rid, b1_manifest(rid))
    (run / "b1-discovery-D03-R1-control").mkdir()
    described = info.describe(run)
    assert described["resume"].startswith("blocked: trial b1-discovery-D03-R1-control has no final")


def test_run_index_lists_newest_first_and_ignores_other_directories(tmp_path, capsys):
    info = load_info()
    for name in ("20261026T080000Z-cccccccc", "20261026T100000Z-aaaaaaaa", "not-a-run"):
        write_run(tmp_path, name)
    info.runs(str(tmp_path), 5)
    ids = [line.split(TAB)[0] for line in capsys.readouterr().out.splitlines()]
    assert ids == ["20261026T100000Z-aaaaaaaa", "20261026T080000Z-cccccccc"]


def test_run_index_summary_uses_recorded_scores_only(tmp_path, capsys):
    info = load_info()
    rid = "20261026T100000Z-ffffffff"
    run = write_run(
        tmp_path,
        rid,
        b1_manifest(rid),
        [b1_record(rid, "control", status="interrupted", score=None, cleanup_completed=False)],
    )
    info.summary(str(run))
    fields = capsys.readouterr().out.strip().split(TAB)
    assert fields[1:] == ["control", "D03", "interrupted", "none", "incomplete"]


@needs_termr
def test_r_unit_and_headless_ui_suite_passes():
    code = (
        'library(testthat); r <- test_dir("%s", reporter="silent", stop_on_failure=FALSE); '
        "d <- as.data.frame(r); cat(sum(d$failed), sum(d$error), sum(d$nb), sep=' ')"
        % (LAUNCHER / "tests" / "testthat")
    )
    result = subprocess.run(
        [RSCRIPT, "-e", code], capture_output=True, text=True, timeout=600, check=False
    )
    last = result.stdout.strip().splitlines()[-1].split() if result.stdout.strip() else []
    failed, errors, expectations = (last + ["x", "x", "0"])[:3]
    assert (failed, errors) == ("0", "0"), result.stdout + result.stderr
    assert int(expectations) > 100


def pty_module():
    spec = importlib.util.spec_from_file_location("pty_drive", LAUNCHER / "tests" / "pty_drive.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["pty_drive"] = module
    spec.loader.exec_module(module)
    return module


@needs_termr
def test_real_terminal_ctrl_c_stops_gracefully_and_leaves_no_runner():
    drive = pty_module()
    session = drive.Session("sigint")
    try:
        assert session.read(10, "READY")
        session.send("f5")
        assert session.read(5, "RUNNING")
        runner = session.runner_pids()
        assert len(runner) == 1
        session.send("ctrl+c")
        assert "experiment is running" in session.text.lower()
        session.send("tab")
        session.send("enter", pause=0.5)
        assert session.read(3, "STOPPING")
        for _ in range(100):
            if not session.alive():
                break
            session.read(0.1)
        assert not session.alive()
        assert not drive.pid_alive(runner[0])
    finally:
        session.close()


@needs_termr
@pytest.mark.parametrize("how", ["SIGTERM", "SIGHUP", "SIGKILL"])
def test_runner_is_interrupted_when_the_launcher_dies_abnormally(how):
    import os
    import signal
    import time

    drive = pty_module()
    session = drive.Session("sigint")
    try:
        assert session.read(10, "READY")
        session.send("f5")
        assert session.read(5, "RUNNING")
        runner = session.runner_pids()
        assert len(runner) == 1
        os.kill(session.pid, getattr(signal, how))
        os.waitpid(session.pid, 0)  # an interactive shell reaps its job
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and drive.pid_alive(runner[0]):
            time.sleep(0.2)
        assert not drive.pid_alive(runner[0]), "runner was left orphaned"
    finally:
        session.close()


@needs_termr
@pytest.mark.skipif(
    not Path(
        os.environ.get("BENCH_PYTHON")
        or Path(__file__).resolve().parents[1] / ".venv-wsl" / "bin" / "python"
    ).exists(),
    reason="needs BENCH_PYTHON or the .venv-wsl virtual environment of the real runner",
)
def test_real_entry_point_starts_blocks_without_keys_and_quits():
    drive = pty_module()
    session = drive.Session(
        "ok",
        rows=24,
        cols=100,
        entry=LAUNCHER / "run.R",
        unset=("OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY"),
    )
    try:
        assert session.read(30, "Benchmark launcher")
        assert session.read(5, "Not exported in this shell")
        session.send("f5")
        assert "RUNNING" not in session.text
        session.send("f10")
        for _ in range(50):
            if not session.alive():
                break
            session.read(0.1)
        assert not session.alive()
    finally:
        session.close()
