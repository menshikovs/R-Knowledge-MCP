# R09: Reusable Shiny module

Implement `threshold_ui(id)` and `threshold_server(id, values)` with Shiny's module API. UI contains namespaced numeric input 'cutoff' initially 0 and text output 'summary'. values is a reactive numeric vector. Server returns one reactive double sum of finite values >= the cutoff, default 0. Reflect data and cutoff changes, empty vectors, and isolate independent module instances. UI must use the supplied namespace.

Use R 4.5.2 and the supplied runtime lock. Relevant packages: shiny.
Example input is in data/values.csv; scoring uses additional synthetic inputs.

Put deliverables in this workspace. Allow at most 900 seconds, 2 CPUs and 2048 MiB RAM. All attempts receive the same 30,000 actual-model-token budget; the external controller must enforce it. Use only installed packages and local data. Do not install dependencies or fetch external data. No credentials or real databases are provided. Test your work locally. Missing artifacts, syntax/runtime errors, contract/type failures, unsafe SQL or destructive operations are failures. The style of code and cosmetic report/plot choices are not graded.
