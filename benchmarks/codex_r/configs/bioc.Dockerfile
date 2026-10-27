# Adds the E02/E03 Bioconductor 3.22 pins on top of the frozen scorer image.
# Build-time network only; scoring and trials stay networkless. CRAN pins are asserted unchanged.
ARG BASE=codex-r-benchmark:pilot
FROM ${BASE}
USER 0:0
COPY configs/bioc_install.R /config/bioc_install.R
RUN Rscript --vanilla /config/bioc_install.R && chmod -R a+rX /opt/benchmark-library /config
USER 65534:65534
WORKDIR /candidate
CMD ["bash"]
