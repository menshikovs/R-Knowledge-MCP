FROM python:3.11-slim@sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8

USER 0:0
WORKDIR /opt/egress
COPY benchmarks/codex_r/exploratory/egress_proxy.py /opt/egress/egress_proxy.py
RUN chown -R 65534:65534 /opt/egress && chmod 0555 /opt/egress/egress_proxy.py
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/opt/egress/egress_proxy.py"]
