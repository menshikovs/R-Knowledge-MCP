"""Exploratory intent/package-detection probe. Labels are the auditor's own judgement (N small, not a validated benchmark)."""
from cran_knowledge_mcp.prompt_intelligence.intent import classify_request, detect_packages

CASES = [
    ("Plot a scatter chart of mpg vs wt with ggplot2", "data_visualization"),
    ("Fit a mixed effects model with lme4 on sleepstudy", "statistical_modeling"),
    ("Run a hypothesis test comparing two groups and report the p-value", "statistical_modeling"),
    ("Write unit tests for my function with testthat", "testing"),
    ("Fix the error: object 'x' not found in my dplyr pipeline", "debugging"),
    ("Fix the failing Shiny app that crashes on startup", "debugging"),
    ("Build a Shiny dashboard with a reactive filter", "shiny_development"),
    ("Speed up this slow loop over a data frame", "performance_optimization"),
    ("Profile memory usage of my script", "performance_optimization"),
    ("Read a CSV with semicolon delimiter and parse dates", "csv_import"),
    ("Clean missing values in a dataset", "data_cleaning"),
    ("Pivot a wide table to long format", "data_transformation"),
    ("Plot the fitted regression model residuals", "data_visualization"),
    ("Create an R package with roxygen2 documentation", "package_development"),
    ("Review the architecture of my R project", "architecture_review"),
    ("Run differential expression with DESeq2 on RNA-seq counts", "bioconductor_analysis"),
    ("Render a Quarto report with parameters", "quarto_reporting"),
    ("Make my analysis reproducible with renv", "reproducibility"),
    ("Validate the input columns before processing", "data_validation"),
    ("Survival analysis with Kaplan-Meier curves", "statistical_modeling"),
    ("Write a query joining orders and customers in SQLite via DBI", "database_query"),
    ("Refactor this long function into smaller ones", "refactoring"),
    ("Test whether the data is normally distributed", "statistical_modeling"),
    ("Benchmark two implementations of a rolling mean", "performance_optimization"),
    ("Explore the iris dataset", "data_analysis"),
    ("Debug why my ggplot legend disappears", "debugging"),
    ("Forecast monthly sales with a time series model", "statistical_modeling"),
    ("Scrape a web page and extract tables", "data_analysis"),
    ("Merge two data frames by id", "data_transformation"),
    ("Export results to an Excel-compatible CSV", "csv_export"),
]
ok = 0
miss = []
for text, expected in CASES:
    got = classify_request(text)
    ok += got == expected
    if got != expected:
        miss.append((text, expected, got))
print(f"category accuracy: {ok}/{len(CASES)}")
for m in miss:
    print("  MISS:", m)
print("package detection false positives on ordinary English:")
for text in ("Validate the input columns before processing", "Set a target for the quarterly goals in my script", "Use a bench of test cases", "Check the janitor reports"):
    print("  ", repr(text), "->", detect_packages(text, None, classify_request(text))[0])
