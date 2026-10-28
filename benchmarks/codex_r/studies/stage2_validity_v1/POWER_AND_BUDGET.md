# Stage 2 Power Simulation and Resource Budget

## 1. Generative Simulation Model

[`power.py`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/power.py) evaluates the operating characteristics of the preregistered primary test (`task_level_sign_flip_test`) and two-stage bootstrap CI (`paired_bootstrap_ci`) under the explicit data-generating assumptions recorded in [`power_simulation.json`](file:///c:/programming_pj/cran-mcp/benchmarks/codex_r/studies/stage2_validity_v1/power_simulation.json):

- **Baseline Task Difficulty ($b_t$)**: Drawn independently per task from $\text{Beta}(\alpha = 2.0, \beta = 2.0)$ on $(0, 1)$, with probability $p_{\text{sat}} = 0.25$ of a **ceiling/saturated task** ($b_t = 0.96, u_t = 0.0$).
- **Task-Level Treatment Heterogeneity ($u_t$)**: For non-saturated tasks, $u_t \sim \mathcal{N}(\delta, \tau^2)$ with $\tau = 0.10$. Thus under the null $\delta = 0$, individual tasks have heterogeneous true effects with mean $0$ and standard deviation $0.10$.
- **Repetition Noise ($\epsilon_{t,r}^A, \epsilon_{t,r}^B$)**: Independent $\mathcal{N}(0, \sigma_{\text{rep}}^2)$ with $\sigma_{\text{rep}} = 0.15$.
- **Score Quantization and Clipping**: Raw scores $Y_{t,r}(A) = \text{clip}(b_t + \epsilon_{t,r}^A, 0, 1)$ and $Y_{t,r}(B) = \text{clip}(b_t + u_t + \epsilon_{t,r}^B, 0, 1)$ are quantized to fifths (`0.0, 0.2, 0.4, 0.6, 0.8, 1.0`) to reflect discrete rubric check counts.
- **Simulation Parameters**: `seed = 20261028`, `n_sim = 300` per grid cell, `n_perm = 999`, `n_boot = 400`, two-sided $\alpha = 0.05$.

## 2. Type I Error Verification: Task-Level vs Block-Level Sign Flipping

Under $\delta = 0.0$ with task-level treatment heterogeneity ($\tau = 0.10$) and $25\%$ saturated tasks, `power.simulate_block_vs_task_type_i_error()` compares the primary task-level sign-flip test against the naive block-level sign-flip test on the exact same simulated datasets (`power_simulation.json::type_i_error_comparison_under_task_heterogeneity`):

| Tasks ($K$) | Repetitions ($R$) | Paired Blocks ($K \times R$) | Primary Task-Level Reject Rate ($\alpha=0.05$) | Naive Block-Level Reject Rate ($\alpha=0.05$) | Assessment |
| ---: | ---: | ---: | ---: | ---: | :--- |
| 12 | 2 | 24 | `0.0500` | `0.0633` | Task-level nominal; block-level mildly inflated |
| 20 | 3 | 60 | `0.0367` | `0.0567` | Task-level conservative; block-level above nominal |
| 30 | 3 | 90 | `0.0567` | `0.0900` | **Block-level Type I error inflated to 9.0%** |
| 40 | 5 | 200 | `0.0400` | `0.0867` (`0.1033` in grid stream) | **Block-level Type I error inflated to 8.7%–10.3%** |

This confirms mathematically and empirically why **task-level sign-flipping** is mandatory for the primary test when $R > 1$.

## 3. Complete Power and Coverage Grid (`power_simulation.json`)

| $K$ | $R$ | Total 3-Arm Trials ($3KR$) | True $\delta$ | Mean Empirical $\hat{\Delta}_{BA}$ | Task-Level Reject Rate (Power / Type I) | Block-Level Reject Rate (Sensitivity) | 95% CI Empirical Coverage | Median CI Half-Width |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 2 | 72 | `-0.20` | `-0.1230` | `0.7833` | `0.8167` | `0.9800` | `0.0917` |
| 12 | 2 | 72 | `-0.10` | `-0.0558` | `0.2667` | `0.2967` | `0.9700` | `0.0917` |
| 12 | 2 | 72 | `0.00` | `+0.0014` | **`0.0467`** | `0.0567` | `0.9733` | `0.0917` |
| 12 | 2 | 72 | `+0.10` | `+0.0553` | `0.2733` | `0.3033` | `0.9867` | `0.0875` |
| 12 | 2 | 72 | `+0.20` | `+0.1190` | `0.7833` | `0.8200` | `0.9767` | `0.0917` |
| 12 | 2 | 72 | `+0.30` | `+0.1684` | `0.9500` | `0.9567` | `0.9700` | `0.0958` |
| 12 | 3 | 108 | `0.00` | `-0.0056` | **`0.0367`** | `0.0467` | `0.9600` | `0.0751` |
| 12 | 3 | 108 | `+0.10` | `+0.0568` | `0.3500` | `0.4000` | `0.9800` | `0.0778` |
| 12 | 3 | 108 | `+0.20` | `+0.1180` | `0.8733` | `0.9033` | `0.9800` | `0.0806` |
| 12 | 5 | 180 | `0.00` | `-0.0005` | **`0.0333`** | `0.0733` | `0.9633` | `0.0633` |
| 12 | 5 | 180 | `+0.10` | `+0.0604` | `0.5067` | `0.6200` | `0.9567` | `0.0650` |
| 12 | 5 | 180 | `+0.20` | `+0.1183` | `0.9467` | `0.9633` | `0.9700` | `0.0700` |
| 20 | 2 | 120 | `0.00` | `+0.0029` | **`0.0400`** | `0.0600` | `0.9867` | `0.0700` |
| 20 | 2 | 120 | `+0.10` | `+0.0581` | `0.4367` | `0.4833` | `0.9800` | `0.0700` |
| 20 | 2 | 120 | `+0.20` | `+0.1167` | `0.9233` | `0.9533` | `0.9733` | `0.0725` |
| 20 | 3 | 180 | `0.00` | `+0.0028` | **`0.0533`** | `0.0767` | `0.9733` | `0.0600` |
| 20 | 3 | 180 | `+0.10` | `+0.0574` | `0.5267` | `0.5833` | `0.9733` | `0.0600` |
| 20 | 3 | 180 | `+0.20` | `+0.1184` | `0.9867` | `0.9867` | `0.9800` | `0.0617` |
| 30 | 3 | 270 | `-0.20` | `-0.1190` | `0.9967` | `0.9967` | `0.9700` | `0.0511` |
| 30 | 3 | 270 | `-0.10` | `-0.0598` | `0.7333` | `0.7733` | `0.9800` | `0.0500` |
| 30 | 3 | 270 | `0.00` | `-0.0005` | **`0.0467`** | `0.0867` | `0.9767` | `0.0500` |
| 30 | 3 | 270 | `+0.10` | `+0.0616` | `0.7667` | `0.8167` | `0.9667` | `0.0489` |
| 30 | 3 | 270 | `+0.20` | `+0.1195` | `1.0000` | `1.0000` | `0.9767` | `0.0511` |
| 30 | 5 | 450 | `0.00` | `-0.0018` | **`0.0500`** | `0.0967` | `0.9667` | `0.0413` |
| 30 | 5 | 450 | `+0.10` | `+0.0578` | `0.8367` | `0.9033` | `0.9733` | `0.0413` |
| 40 | 3 | 360 | `0.00` | `+0.0006` | **`0.0400`** | `0.0533` | `0.9733` | `0.0433` |
| 40 | 3 | 360 | `+0.10` | `+0.0581` | `0.8233` | `0.8700` | `0.9800` | `0.0433` |
| 40 | 5 | 600 | `0.00` | `-0.0019` | **`0.0400`** | `0.1033` | `0.9667` | `0.0360` |
| 40 | 5 | 600 | `+0.10` | `+0.0604` | `0.9467` | `0.9667` | `0.9633` | `0.0365` |

*(Note: Because $25\%$ of simulated tasks are saturated and scores are clipped to $[0, 1]$, a latent shift of $\delta = +0.20$ corresponds to an attenuated observable ITT effect $\mathbb{E}[\hat{\Delta}_{BA}] \approx +0.119$, and $\delta = +0.10$ corresponds to $\mathbb{E}[\hat{\Delta}_{BA}] \approx +0.059$.)*

### Minimum Detectable Effect Summary

- **Recommended Confirmatory Design ($K = 30, R = 3$, 270 total trials across 3 arms)**:
  - Achieves **100% power** for latent $\delta = \pm 0.20$ (observable $\Delta \approx \pm 0.12$).
  - Achieves **76.7% power** for latent $\delta = +0.10$ (observable $\Delta \approx +0.06$) with median 95% CI half-width `0.0489`.
- **High-Power Design ($K = 30, R = 5$, 450 total trials; or $K = 40, R = 3$, 360 total trials)**:
  - Achieves **82.3%–83.7% power** for latent $\delta = +0.10$ (observable $\Delta \approx +0.06$).

## 4. Wall-Clock and Session Budget Formulas

From `historical_calibration_summary.json` (101 timed historical runs):

- Observed median trial duration: $t_{\text{med}} = 82.619\text{ s}$ (`1.38 min`).
- Observed 90th-percentile trial duration: $t_{p90} = 185.788\text{ s}$ (`3.10 min`).
- Observed token usage: Missing in `102 / 103` historical runs (`0.97%` coverage); therefore, Stage 2 budgets are parameterized explicitly in **model sessions** ($N_{\text{trials}} = 3 K R$) and **serial wall-clock hours**:

$$\text{Expected Serial Hours} = \frac{3 K R \times 82.619}{3600}, \qquad \text{Conservative (p90) Serial Hours} = \frac{3 K R \times 185.788}{3600}$$

| Stage / Design | Tasks ($K$) | Reps ($R$) | Arms | Total Sessions ($3KR$) | Expected Serial Wall-Clock | Conservative (p90) Serial Wall-Clock |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Arm-A Calibration Pass** (`S2` tasks) | 17 | 3 | 1 (Arm A only) | 51 | `1.17 hours` | `2.63 hours` |
| **3-Arm Pilot** | 8 | 2 | 3 (`A, B, C`) | 48 | `1.10 hours` | `2.48 hours` |
| **Confirmatory Standard** | 30 | 3 | 3 (`A, B, C`) | 270 | `6.20 hours` | `13.93 hours` |
| **Confirmatory High-Power** | 30 | 5 | 3 (`A, B, C`) | 450 | `10.33 hours` | `23.22 hours` |

