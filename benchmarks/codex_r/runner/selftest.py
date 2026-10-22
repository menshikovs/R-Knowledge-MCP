"""Validate private R oracles with trusted references and semantic negative controls.

These are infrastructure self-tests, NEVER Codex trials or performance evidence.
"""

import argparse
import json
import tempfile
from pathlib import Path

from bench import ROOT, digest, manifest, score

MUTANTS = {
    "R01": "clean_records <- function(data) data",
    "R02": (
        "summarize_sales <- function(data) data.frame(team=character(),total=double(),n=integer())"
    ),
    "R03": "import_measurements <- function(path) list(data=read.csv(path),problems=data.frame())",
    "R04": (
        "plot_measurements <- function(data) "
        "ggplot2::ggplot(data,ggplot2::aes(time,signal))+ggplot2::geom_point()"
    ),
    "R05": "pivot_visits <- function(data) data",
    "R06": (
        "lookup_accounts <- function(db_path,owner,min_balance) "
        "data.frame(id=integer(),owner=character(),balance=double())"
    ),
    "R07": (
        "revenue_by_region <- function(con,from_date,to_date) "
        "data.frame(region=character(),revenue=double(),orders=integer())"
    ),
    "R08": (
        "make_filter_server <- function(data) function(input,output,session) { "
        "filtered <- shiny::reactive(data()); total <- shiny::reactive(0) }"
    ),
    "R09": (
        "threshold_server <- function(id,values) "
        "shiny::moduleServer(id,function(input,output,session) shiny::reactive(0))"
    ),
    "R11": (
        "summarize_ranges <- function(data) "
        "data.frame(chr=data$chr,bases=as.integer(data$end-data$start+1),segments=1L)"
    ),
    "R12": (
        "build_report <- function(csv_path,output_dir) "
        "list(data=data.frame(),summary=data.frame(),plot=NULL,report='absent.qmd')"
    ),
}


def run(image, task_id_filter=None):
    observations = []
    for task in manifest()["tasks"]:
        task_id = task["id"]
        if task_id_filter is not None and task_id != task_id_filter:
            continue
        name = task["artifacts"][0]
        reference = ROOT / "oracle/selftest" / name
        with tempfile.TemporaryDirectory(prefix="r-oracle-selftest-") as temp:
            work = Path(temp)
            (work / name).write_bytes(reference.read_bytes())
            positive = score(task_id, work, image)
            mutation = (
                "\n" + MUTANTS[task_id] + "\n"
                if task_id != "R10"
                else "\n# Group totals\n\n| group | total | n |\n|---|---|---|\n| A | 12 | 2 |\n"
            )
            if task_id == "R10":
                # Retain YAML but remove executable analysis.
                text = reference.read_text(encoding="utf-8")
                end = text.index("---", 3) + 3
                (work / name).write_text(text[:end] + mutation, encoding="utf-8")
            else:
                with (work / name).open("a", encoding="utf-8") as out:
                    out.write(mutation)
            negative = score(task_id, work, image)
            observations.append(
                {
                    "task": task_id,
                    "reference_sha256": digest(reference),
                    "reference": positive,
                    "semantic_mutant": negative,
                }
            )
            print(
                json.dumps(
                    {"task": task_id, "reference": positive["passed"], "mutant": negative["passed"]}
                ),
                flush=True,
            )
    return {
        "kind": "oracle_selftest_not_agent_trials",
        "image": image,
        "observations": observations,
        "passed": all(
            x["reference"]["status"] == "scored"
            and x["reference"]["passed"] == 4
            and x["semantic_mutant"]["status"] == "scored"
            and x["semantic_mutant"]["passed"] < 4
            for x in observations
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--task", choices=[f"R{i:02}" for i in range(1, 13)])
    args = parser.parse_args()
    result = run(args.image, args.task)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if result["passed"] else 1)
