FROM codex-r-benchmark@sha256:467944b2623c0e7a6f9cbbf24022616911cd834dd2a2200bd39fbe295666eca5

USER 0:0
ARG CODEX_VERSION=0.163.0
ARG CODEX_ARCHIVE_SHA256=582646c6bf0561eb0de540f7fc85b9121b0091a826bc6e96830b7f1722122182

RUN set -eu; \
    test "$CODEX_VERSION" = "0.163.0"; \
    test "$CODEX_ARCHIVE_SHA256" = "582646c6bf0561eb0de540f7fc85b9121b0091a826bc6e96830b7f1722122182"; \
    mkdir -p /tmp/codex-release; \
    curl --fail --silent --show-error --location \
      "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-package-x86_64-unknown-linux-musl.tar.gz" \
      --output /tmp/codex-release/codex.tar.gz; \
    echo "$CODEX_ARCHIVE_SHA256  /tmp/codex-release/codex.tar.gz" | sha256sum --check --status; \
    mkdir -p /opt/codex; \
    tar --extract --gzip --no-same-owner --file /tmp/codex-release/codex.tar.gz --directory /opt/codex; \
    test -x /opt/codex/bin/codex; \
    /opt/codex/bin/codex --version; \
    rm -rf /tmp/codex-release

ENV PATH="/opt/codex/bin:/opt/codex/codex-path:${PATH}" \
    CODEX_HOME=/tmp/codex-home \
    CODEX_DISABLE_UPDATE_PROMPT=1
USER 65534:65534
WORKDIR /candidate
ENTRYPOINT ["/opt/codex/bin/codex"]
CMD ["--version"]
