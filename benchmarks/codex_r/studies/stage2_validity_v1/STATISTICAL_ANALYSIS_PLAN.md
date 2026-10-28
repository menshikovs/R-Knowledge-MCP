# Stage 2 Statistical Analysis Plan (SAP)

## 1. Estimands and Hypotheses

### 1.1 Primary Estimand (Intention-to-Treat, Task-Weighted)

Let $\mathcal{T} = \{1, \dots, K\}$ index the preregistered confirmatory tasks and $r \in \{1, \dots, R_t\}$ index the complete paired blocks for task $t$ where both Arm A and Arm B have observed non-missing primary scores $Y_{t,r}(A), Y_{t,r}(B) \in [0, 1]$.

For each task $t$ with $R_t \ge 1$ complete pairs, define the within-task mean paired difference:

$$\bar{D}_t = \frac{1}{R_t} \sum_{r=1}^{R_t} \bigl(Y_{t,r}(B) - Y_{t,r}(A)\bigr)$$

The primary intention-to-treat (ITT) estimator gives **equal weight to each task** regardless of repetition count $R_t$:

$$\hat{\Delta}_{BA} = \frac{1}{K_{\text{obs}}} \sum_{t=1}^{K_{\text{obs}}} \bar{D}_t$$

where $K_{\text{obs}}$ is the number of planned tasks with at least one complete $(A, B)$ pair.

- **Intention-to-Treat Principle**: Trials are analyzed strictly according to their randomized arm assignment (`A`, `B`, `C`), regardless of whether the model in Arm B or C listed or invoked any MCP tools. Conditioning on observed tool usage is forbidden in the primary and secondary causal contrasts.
- **Primary Null Hypothesis ($H_0^{\text{task}}$)**: Across the population/super-population of tasks, the distribution of task-level expected paired differences $\bar{D}_t$ is symmetric around zero (implying $\mathbb{E}[\bar{D}_t] = 0$).
- **Alternative Hypothesis ($H_1^{\text{task}}$)**: Two-sided, $\mathbb{E}[\bar{D}_t] \neq 0$, tested at nominal significance level $\alpha = 0.05$.

### 1.2 Secondary Contrasts and Multiplicity Control

The secondary family consists of three pre-specified contrasts:

1. **`C-B` (Encouragement Effect on `primary_score`)**: Task-weighted mean paired difference $\hat{\Delta}_{CB}$ between Arm C (`with-mcp-encouraged`) and Arm B (`with-mcp`).
2. **`C-A` (Encouraged Availability Effect on `primary_score`)**: Task-weighted mean paired difference $\hat{\Delta}_{CA}$ between Arm C and Arm A (`without-mcp`).
3. **`B-A:fully_correct` (Binary Perfect-Score Indicator)**: Task-weighted mean paired difference on $I_{t,r} = \mathbb{I}(Y_{t,r} = 1.0)$ between Arm B and Arm A.

Family-wise error rate (FWER) across the 3 secondary contrasts is controlled at $\alpha = 0.05$ using the **Holm step-down procedure** (`analysis.holm_adjust()`):

$$p_{(i)}^{\text{Holm}} = \max_{j \le i} \min\bigl(1,\ (m - j + 1)\, p_{(j)}\bigr), \quad m = 3$$

### 1.3 Observational Mediator & Resource Summaries (Non-Causal)

- **Tool Adoption Rate**: Proportion of trials in Arm B and Arm C with `attempted > 0`, `completed > 0`, and `delivered > 0`.
- **Descriptive Tool-Use Split (`tool_use_split_descriptive`)**: Separates Arm B trials into `used_mcp_in_arm_b` (`attempted > 0`) vs `unused_mcp_in_arm_b` (`attempted == 0`), tagged explicitly with `"warning": "Observational split on post-treatment mediator (attempted > 0); confounded by task difficulty and agent state. Do NOT interpret as causal effect."`
- **Duration and Cost**: Paired task-weighted differences in `duration_sec` and `estimated_cost_usd` (when non-missing).

## 2. Primary Statistical Test vs Sharp-Null Sensitivity Test

### 2.1 Why Block-Level Sign-Flipping Fails Under Task Heterogeneity

Consider the hierarchical data-generating process for paired differences $D_{t,r} = Y_{t,r}(B) - Y_{t,r}(A)$:

$$D_{t,r} = \delta + u_t + e_{t,r}, \quad u_t \sim (0, \tau^2), \quad e_{t,r} \sim (0, 2\sigma_{\text{rep}}^2)$$

Under the weak null of zero average treatment effect across tasks ($\delta = 0$) with task-level treatment heterogeneity ($\tau^2 > 0$):

- The true sampling variance of the grand mean $\bar{D} = \frac{1}{K R}\sum_{t=1}^K \sum_{r=1}^R D_{t,r}$ is:

$$\operatorname{Var}(\bar{D}) = \frac{\tau^2}{K} + \frac{2\sigma_{\text{rep}}^2}{K R}$$

- **Block-level sign-flipping** (`analysis.paired_randomization_test`) flips signs $s_{t,r} \in \{-1, +1\}$ independently for every repetition $(t, r)$. Under independent block flips, the conditional variance of $\bar{D}^* = \frac{1}{KR}\sum_{t,r} s_{t,r} D_{t,r}$ given $\{D_{t,r}\}$ is:

$$\operatorname{Var}_{\text{block}}(\bar{D}^* \mid D) = \frac{1}{K^2 R^2} \sum_{t=1}^K \sum_{r=1}^R D_{t,r}^2 \approx \frac{\tau^2 + 2\sigma_{\text{rep}}^2}{K R}$$

- Notice that the $\tau^2$ term in $\operatorname{Var}_{\text{block}}(\bar{D}^* \mid D)$ is divided by $K R$ instead of $K$! For $R > 1$ and $\tau > 0$, the block-level permutation distribution is systematically too narrow by a factor of:

$$\frac{\operatorname{Var}(\bar{D})}{\mathbb{E}[\operatorname{Var}_{\text{block}}(\bar{D}^* \mid D)]} = \frac{R\tau^2 + 2\sigma_{\text{rep}}^2}{\tau^2 + 2\sigma_{\text{rep}}^2} > 1$$

- At $K = 40, R = 5, \tau = 0.10, \sigma_{\text{rep}} = 0.15$, this variance ratio is $\frac{5(0.01) + 0.045}{0.01 + 0.045} = 1.727$, causing the two-sided $\alpha = 0.05$ block-level sign-flip test to reject at **`0.0867`–`0.1033`** under $\delta = 0$ (`power_simulation.json`).

### 2.2 Primary Procedure: Task-Level Sign-Flip Test (`task_level_sign_flip_test`)

Instead of flipping individual repetitions, the primary test reduces each task to its within-task mean paired difference $\bar{D}_t$ ($t = 1, \dots, K_{\text{obs}}$) and applies sign flips $s_t \in \{-1, +1\}$ at the **task level**:

$$\bar{D}^{*(b)} = \frac{1}{K_{\text{obs}}} \sum_{t=1}^{K_{\text{obs}}} s_t^{(b)} \bar{D}_t$$

- Under task-level sign flips, $\operatorname{Var}_{\text{task}}(\bar{D}^* \mid \bar{D}) = \frac{1}{K^2}\sum_{t=1}^K \bar{D}_t^2 \approx \frac{\tau^2}{K} + \frac{2\sigma_{\text{rep}}^2}{K R}$, which matches $\operatorname{Var}(\bar{D})$ exactly!
- **Exact Enumeration ($K_{\text{obs}} \le 16$)**: Evaluates all $2^{K_{\text{obs}}}$ sign vectors in $\{-1, +1\}^{K_{\text{obs}}}$ (`method = "exact_task_sign_flip"`).
  - *Small-sample resolution note*: Because $(-s)$ has the same magnitude as $s$, the minimum achievable two-sided exact p-value is $2^{-(K_{\text{obs}}-1)}$. Thus $K_{\text{obs}} \le 5$ cannot reach $p \le 0.05$ (`min p = 0.0625` at $K_{\text{obs}} = 5$, `0.125` at $K_{\text{obs}} = 4$). Confirmatory inference requires $K_{\text{obs}} \ge 6$ (and practically $K_{\text{obs}} \ge 20$ for power).
- **Monte Carlo Permutation ($K_{\text{obs}} > 16$)**: Draws $N_{\text{perm}} = 19{,}999$ independent random sign vectors using a deterministic `random.Random(seed)` generator and applies the Phipson-Smyth $+1$ finite-sample correction (`method = "monte_carlo_task_sign_flip_plus_one"`):

$$p = \frac{1 + \sum_{b=1}^{N_{\text{perm}}} \mathbb{I}\bigl(|\bar{D}^{*(b)}| \ge |\hat{\Delta}| - 10^{-12}\bigr)}{1 + N_{\text{perm}}}$$

### 2.3 Confidence Interval: Two-Stage Percentile Bootstrap (`paired_bootstrap_ci`)

For $N_{\text{boot}} = 10{,}000$ resamples (`seed = 20261028`):

1. Sample $K_{\text{obs}}$ tasks **with replacement** from the observed tasks.
2. Within each sampled task $t^*$, sample $R_{t^*}$ paired differences **with replacement** from that task's observed block differences $\{D_{t^*, 1}, \dots, D_{t^*, R_{t^*}}\}$ and compute their task mean.
3. Average the $K_{\text{obs}}$ resampled task means and take the $2.5\%$ and $97.5\%$ quantiles (`method = "two_stage_task_then_block_percentile_bootstrap"`).

*Variance note*: Because Stage 1 resamples tasks (including their realization of within-task noise) and Stage 2 resamples blocks within tasks, the bootstrap variance is $\frac{1}{K}(\tau^2 + 2\sigma_{\text{rep}}^2/R) + \frac{1}{K}(2\sigma_{\text{rep}}^2/R) = \frac{\tau^2}{K} + \frac{4\sigma_{\text{rep}}^2}{KR}$, which is slightly conservative relative to $\frac{\tau^2}{K} + \frac{2\sigma_{\text{rep}}^2}{KR}$ (yielding empirical 95% CI coverage around `0.96–0.98` in simulation).

## 3. Missing Data, Failures, and Sensitivity Analyses

### 3.1 Trial Status Handling (`primary_outcome_score`)

| Trial Status | Primary ITT Handling | Sensitivity (`complete_case_excluding_candidate_failure`) |
| :--- | :--- | :--- |
| `scored` | Observed `primary_score` $\in [0, 1]$ | Observed `primary_score` $\in [0, 1]$ |
| `candidate_failure` | **Assigned `0.0`** (agent crash, timeout, or missing deliverable is an outcome failure of that arm) | Treated as missing (`None`) |
| `infrastructure_failure` | **Explicit missing (`None`)** (Docker daemon error, disk full, host outage) | Explicit missing (`None`) |
| `scoring_error` | **Explicit missing (`None`)** | Explicit missing (`None`) |
| `not_executed` | **Explicit missing (`None`)** | Explicit missing (`None`) |
| `invalidated` | **Explicit missing (`None`)** and logged in `invalidating_violations` (`study_valid = False`) | Explicit missing (`None`) |

### 3.2 Mandatory Sensitivity Outputs in `run_preregistered_analysis`

Every analysis report includes a dedicated `sensitivity` object (which never overwrites `primary`):

1. **`block_level_sharp_null_test`**: Block-level sign-flip p-value (`caveat`: *"Tests the sharp null of zero effect in every repetition; anti-conservative under heterogeneous task effects with zero mean."*).
2. **`manski_bounds`**: Worst-case (`missing B = 0.0, missing A = 1.0`) and best-case (`missing B = 1.0, missing A = 0.0`) task-weighted bounds across all planned blocks (`manski_bounds()`).
3. **`complete_case_excluding_candidate_failure`**: Re-runs `task_level_sign_flip_test` treating `candidate_failure` as missing instead of `0.0`.
4. **`leave_one_task_out`**: Computes $\hat{\Delta}_{BA}^{(-t)}$ omitting each task $t$ one at a time, reporting `min_estimate`, `max_estimate`, and `per_omitted_task` to expose single-task dominance.

