FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home app
USER 10001
EXPOSE 8000
ENTRYPOINT ["cran-knowledge-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0"]
