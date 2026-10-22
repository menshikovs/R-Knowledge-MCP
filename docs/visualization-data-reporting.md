# R visualization, transformation and reporting intelligence

The visualization tools add bounded, static analysis for the R packages
`ggplot2`, `ggraph`, `tidyr`, `plotly` and `knitr`. The tools use a lexical R
scanner to identify calls and simple named arguments. They never run R, parse
arbitrary R expressions, inspect local files, render a report or send source
code and schemas to an external service.

`get_visualization_docs(package, function, package_version)` retrieves the
literal Rd alias from the current CRAN source archive, after validating the
archive against the package index. It reports package version and provenance.
When a caller asks for a different version, the tool returns an explicit
`requested_version_unavailable` error instead of silently returning current
documentation. It does not claim full historical CRAN archive support.

`get_visualization_workflow` groups live, version-checked Rd results for a
small fixed set of workflows: tidyr to ggplot, graph visualization, interactive
ggplotly conversion, and reproducible report figures. The workflow descriptions
are concise navigation aids; each function reference has its own package
version, source and check time. Missing packages or aliases remain explicit
errors, and the tool does not generate or run example code.

`analyze_ggplot_code` separates mappings inside `aes()` from fixed geom
arguments, lists common layer calls and checks simple mapped names against an
optional caller-supplied schema. It flags deprecated `aes_string()`-family
calls with a link to current official ggplot2 documentation. Schema warnings
are hints: data passed through wrappers, expressions, layer-specific data and
tidy evaluation can change what a mapping refers to.

`analyze_ggraph_code` reports constructors, literal layout names and node/edge
layers. It associates mappings with their enclosing node or edge geom before
checking optional node and edge schemas. It does not choose a best layout or
prove the type or validity of a graph object.

`analyze_tidyr_pipeline` reports recognized transformations and a conservative
output-column sketch for simple `pivot_longer()` selections. For
`pivot_wider()`, it checks only whether caller-supplied candidate keys cover a
simple `id_cols + names_from` key. Actual duplicate rows, name expansion,
list-columns, type negotiation and row values cannot be proven from source and
metadata alone. It flags `separate()` as superseded and links the official
tidyr reference.

`analyze_ggplotly_compatibility` reports `ggplotly()` use and a narrowly
documented `geom_function()` conversion limitation from Plotly's R docs. This
is an example documented by Plotly, not a complete or version-independent
compatibility matrix. Rendering and widget behavior must be checked by the
client in its own environment.

`analyze_knitr_chunks` inspects fenced R chunks, selected knitr options,
duplicate labels and simple `dependson` labels. In QMD, Quarto `#|` cell
options are reported separately from knitr header options. It does not render
documents, execute chunks, resolve child documents or infer cache validity.

Analysis results label their scope as lexical heuristics and return
`not_executed=true`. Optional `package_versions` are explicitly supplied by a
client and compared with current CRAN metadata; the result distinguishes those
values from the latest CRAN version. Optional `renv_lock` is bounded JSON text
provided by the caller. The server extracts package version strings only; it
does not read a path, restore a library, or claim that the lock represents an
installed environment. Lock-only values are marked client-supplied and
unverified.

The static findings reference primary documentation where a rule is known:

- [ggplot2 aesthetics](https://ggplot2.tidyverse.org/reference/aes.html) and
  [deprecated mapping helpers](https://ggplot2.tidyverse.org/reference/aes_.html)
- [ggraph layouts](https://ggraph.data-imaginist.com/articles/Layouts.html)
- [tidyr `pivot_wider()`](https://tidyr.tidyverse.org/reference/pivot_wider.html)
  and [`separate()`](https://tidyr.tidyverse.org/reference/separate.html)
- [Plotly ggplot2 conversion](https://plotly.com/ggplot2/getting-started/) and
  its [`geom_function()` example](https://plotly.com/ggplot2/layers/geoms/geom_function/)
- [knitr chunk options and caching](https://yihui.org/knitr/options/)

The documentation links provide current reference context. Exact function
documentation and versions come from the package source archive when requested.
