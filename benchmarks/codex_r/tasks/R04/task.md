# R04: Grouped logarithmic plot

Implement `plot_measurements(data)` returning a ggplot object. Input has time (numeric), signal (numeric), group (character). Exclude nonfinite time or signal, signal <= 0, and missing group. Plot points and connecting lines: time on x, signal on y, colour and line grouping by group; y uses a log10 scale. Support empty input without error. Choose clear labels/style yourself; cosmetic preferences are not scored.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: ggplot2.
Example input is in data/measurements.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
