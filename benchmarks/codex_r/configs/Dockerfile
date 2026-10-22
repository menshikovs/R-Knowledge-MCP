FROM rocker/r-ver:4.5.2@sha256:fd4ccdd3a4a6f7ef805e2daeee2a0fe3bf126bc231f36351223baecf5a595a4c
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libcurl4-openssl-dev libssl-dev libxml2-dev libicu-dev \
    libfontconfig1-dev libfreetype6-dev libpng-dev libjpeg-dev libuv1-dev \
    && rm -rf /var/lib/apt/lists/*
# Fixed official release, downloaded at environment-build time only.
RUN curl -fL --retry 2 \
    https://github.com/quarto-dev/quarto-cli/releases/download/v1.8.27/quarto-1.8.27-linux-amd64.deb \
    -o /tmp/quarto.deb && dpkg -i /tmp/quarto.deb && rm /tmp/quarto.deb \
    && test "$(quarto --version)" = "1.8.27"
ENV R_LIBS_USER=/opt/benchmark-library TZ=UTC LC_ALL=C.UTF-8
ENV RENV_CONFIG_CACHE_SYMLINKS=FALSE
COPY configs/renv.lock /config/renv.lock
COPY configs/restore.R /config/restore.R
RUN --mount=type=cache,target=/root/.cache/R/renv \
    mkdir -p /opt/benchmark-project && Rscript --vanilla /config/restore.R \
    && chmod -R a+rX /opt/benchmark-library /config
# No task oracle, reference solution, repository, credentials or Docker socket.
WORKDIR /candidate
USER 65534:65534
CMD ["bash"]
