# Stage 2 Methodology Audit of Historical Benchmark Evidence

## 1. Purpose and Scope

This document audits the historical benchmark evidence under `benchmarks/codex_r/results/` and the prior internal audits (`baseline_root_cause_audit.md`, `b1_discovery_offline_audit_20261026.md`, `b1_scorer_v21_rescore_20261026.md`, `p1d_telemetry_architecture.md`, and `p1e_discovery_evidence_audit_20261027.md`) to establish why historical runs cannot support a valid causal claim about R-Knowledge-MCP and what methodological defects Stage 2 resolves.

All inspections of `benchmarks/codex_r/results/` were strictly read-only.

## 2. Historical Corpus Inventory

`calibration.summarize_history()` inspects local git-ignored `results.json` files:

- **Frozen pre-Stage-2 corpus (`before_date="20261028"`)**:
  - **31** run directories (`20261024T171451Z-b00caad0` through `20261027T161629Z-37b7bd6e`).
  - **108** total raw entries across `results.json` files.
  - **103** entries with usable `task` and `mode` identifiers.
  - **88** entries with `status == "scored"` (`6` `error`, `2` `interrupted`, `1` `smoke_transport_observed`, `6` `unsupported_for_automatic_scoring`).
  - **1** entry (`0.97%`) with non-null model token usage (`total_tokens`).
  - Observed wall-clock duration across 101 timed entries: median `82.619s`, IQR `65.986s`, 90th percentile `185.788s`, total `11,039.882s` (`3.07` hours).
- **Unfiltered corpus including post-cutoff exploratory smoke directory (`before_date=""`)**:
  - **32** run directories (adds `20261028T113222Z-e5a013f7` containing 4 entries on `R01` and `R03`).
  - **112** raw entries, **107** with `task`+`mode`, **90** scored (`8` `error`).

## 3. Root-Cause Threats to Causal Validity in Historical Runs

### 3.1 Uncontrolled Confounding Across Runs

Historical runs mixed multiple changes simultaneously across directories:

1. **Prompt and encouragement confounding**: Early discovery runs altered prompt wording or injected ad-hoc tool instructions alongside MCP availability, making it impossible to separate the effect of MCP tool access from prompt engineering (`B − A` vs `C − B`).
2. **Scorer evolution mid-experiment**: Tasks `B01–B03`, `C01–C05`, `D01–D03`, and `E01–E05` were evaluated under three different scorers across time (`legacy`, `knowledge-pilot-v2`, and `knowledge-pilot-v2.1`). In `b1_scorer_v21_rescore_20261026.md`, changing from `v2` (`unknown` claim = `0.5` credit) to `v2.1` (`unknown` claim = abstention) shifted task scores substantially without any change in agent behavior.
3. **Environment and network drift**: Early runs executed with live upstream CRAN/Bioconductor/GitHub access or inconsistent offline snapshot mounting, and container egress was placed on a plain Docker bridge network rather than an isolated or proxy-enforced network.
4. **Non-randomized execution order**: Historical runs executed tasks and modes in fixed deterministic order (`without-mcp` then `with-mcp` or single-mode batches), confounding treatment arm with temporal/rate-limit/cache drift.

### 3.2 Severe Ceiling and Floor Saturation

Across the 31 tasks in the catalogue (using the pre-Stage-2 historical corpus):

- **17 tasks** have fewer than 3 scored Arm A (`without-mcp`) observations (`Stratum S2_calibration_needed`), including `R01–R12`, `C01–C05`, `H01`, `H04`, and `H10`.
- **11 tasks** saturate at the ceiling in Arm A (`mean_a == 1.0` across $n_A \in [2, 6]$): `R01`, `R02`, `R04`, `B01`, `B02`, `B03`, `C01`, `C02`, `C05`, `E02`, `E03`. When baseline performance is already `1.00`, the primary contrast $B - A$ cannot be positive (`> 0`) and can only detect regressions or tool tax.
- **2 tasks** saturate at the floor in both arms (`mean_a == 0.0` and `mean_b == 0.0` across $n_A = 4, n_B = 4$): `E04` and `E05`, driven by unprompted JSON output format requirements (`BEN-002`).
- **Concentrated score variance**: Almost all positive non-zero historical variation between `with-mcp` and `without-mcp` occurred in three tasks (`D01`, `D02`, `D03`), which themselves suffer from frozen candidate-list coupling (`BEN-002`).
- **Result**: **0 of 31 tasks** currently qualify for `S1_confirmatory_core` under the preregistered Arm-A-only screening rule ($n_A \ge 3$ and $0.10 \le \bar{Y}_A \le 0.90$).

### 3.3 Scorer Artifacts and Oracle Coupling (`BEN-002`)

As established in `b1_discovery_offline_audit_20261026.md` and `p1e_discovery_evidence_audit_20261027.md`:

- **`D01–D03` candidate-set coupling**: The `knowledge-pilot-v2.1` scorer checks `recommended_package in task["expected"]["acceptable_packages"]`, which is a short frozen list (`D01`: `survminer`, `ggsurvfit`, `survival`; `D02`: `DESeq2`, `edgeR`, `limma`; `D03`: `SingleCellExperiment`, `Seurat`, `SeuratObject`, `SpatialExperiment`, `SummarizedExperiment`). Valid alternative CRAN/Bioconductor packages receive `0.0` recommendation credit unless pre-registered in the frozen list.
- **`E01`, `E04`, `E05` hidden schema contracts**: The prompts ask for JSON output without specifying exact key names or value types, while the scorer checks exact key/value equality (`api_status`, `tidyverse_status`, `uses_tidyeval`, `lifecycle`).

### 3.4 Statistical Pitfalls Identified During Stage 2 Design

During the Stage 2 statistical audit, a critical flaw was identified in naive block-level randomization inference:

- When each of $K$ tasks is repeated $R > 1$ times ($K \times R$ paired blocks), **block-level sign-flipping** flips the sign of each repetition $(t, r)$ independently.
- Under the **sharp null** ($Y_{t,r}(B) = Y_{t,r}(A)$ for every task and repetition), block-level sign-flipping is exact.
- However, under the scientifically relevant **weak null of zero average effect across tasks with task-level heterogeneity** ($\mathbb{E}[\tau_t] = 0$, $\operatorname{Var}(\tau_t) = \tau^2 > 0$), flipping signs independently across repetitions within the same task cancels out the persistent task effect $\tau_t$ in the null reference distribution! The null variance shrinks by $1/(K R)$ while the true sampling variance of $\bar{D}$ has a $\tau^2 / K$ term that does not shrink with $R$.
- In Monte Carlo verification (`power_simulation.json`, $K = 40, R = 5, \tau = 0.10, \sigma_{\text{rep}} = 0.15$), block-level sign-flipping exhibited an inflated Type I error rate of **`0.0867`** (and **`0.1033`** in the matched power stream) at nominal $\alpha = 0.05$, whereas **task-level sign-flipping** on within-task mean differences $\bar{D}_t$ held empirical Type I error at **`0.0400`**.

### 3.5 Telemetry and Mediator Confounding

- Historical reports frequently conflated **MCP availability** (Arm B assignment) with **actual MCP invocation** (`attempted > 0`). Conditioning on whether the agent chose to call a tool introduces post-treatment selection bias.
- Early telemetry schemas (`1.0` and `1.1`) lacked explicit distinctions between server-side tool execution and client-side tool calls, and `ordinal_unconfirmed` pairing was not distinguished from protocol-ID-confirmed pairing.
- Token usage was recorded in only `1 / 103` historical trials because the Codex CLI wrapper did not consistently emit structured token accounting.

## 4. Summary of Stage 2 Remediations

| Historical Defect | Stage 2 Remediation |
| :--- | :--- |
| Confounded prompt wording vs tool access | Three-arm design: Arm A and Arm B have byte-identical instructions; Arm C adds a single standardized encouragement suffix (`protocol.py`). |
| Post-treatment conditioning on tool use | Primary estimand is Intention-to-Treat ($B - A$) by assigned arm; tool use is analyzed strictly as an observational mediator (`analysis.py`). |
| Inflated Type I error from block-level sign flips under task heterogeneity | Primary test is task-level sign-flip inference on task means $\bar{D}_t$; block-level sign-flipping is retained only as a clearly labeled sharp-null sensitivity output (`analysis.py`, `power.py`). |
| Cherry-picking tasks on treatment effect ($B - A$) | Task stratification (`S1`, `S2`, `RC`, `Q`) uses **Arm A data only** (`calibration.py`). |
| Silent dropping of failed trials | Explicit status taxonomy: `candidate_failure` scored as `0.0` in primary ITT; `infrastructure_failure` / `scoring_error` kept as explicit missingness with Manski worst/best bounds (`records.py`, `analysis.py`). |
| Control-arm MCP leak crashing validation or going unnoticed | `records.validate_record()` accepts schema-valid telemetry on Arm A and flags leaked MCP availability/calls as an explicit invalidating protocol violation (`records.py`). |
| Unverified frozen evidence / scorer drift | 279 evidence, task, oracle, and scorer files pinned by SHA-256 in `frozen_evidence_digests.json` (`manifest.py`). |
