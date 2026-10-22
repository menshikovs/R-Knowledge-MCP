# Add reproducible historical dependency snapshots and transitive compatibility

Current checks cover official R/Bioconductor mappings, package R constraints and
direct required dependency version/R constraints across the selected release and
current CRAN. They do not claim full installability. Historical releases warn
about mixing in current CRAN candidates.

Acceptance criteria:

- Add pinned, verifiable historical CRAN snapshots while preserving Bioconductor
  release/category/package identity.
- Build and independently test a bounded transitive resolver, including cycles,
  conflicting constraints and unavailable sources.
- Preserve ambiguous, missing and unknown outcomes rather than guessing origins.
- Model platform/system requirements before stronger installation claims.
- Retain per-record source URLs/check times; never evaluate R or package code.
- Test historical CRAN/Bioconductor mismatches and unsatisfiable environments.

This is follow-up work, not a placeholder implementation in the current tools.
