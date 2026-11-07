# syntax=docker/dockerfile:1.7
FROM python:3.12.16-slim-bookworm AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    EXTRACT_MAX_CONCURRENT=1
WORKDIR /app

FROM python-base AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-container.txt requirements.txt ./
RUN python -m pip install -r requirements-container.txt

FROM build AS test
COPY requirements-dev.txt ./
RUN python -m pip install -r requirements-dev.txt
COPY . .
RUN python -m pytest -q \
    && python -m py_compile main.py runtime_config.py product_extraction.py search_extraction.py product_markdown.py guanxe_adapter.py \
    && mkdir -p /tmp/test-gate && printf 'passed\n' > /tmp/test-gate/result

FROM python-base AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libxml2 libxslt1.1 zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 extractor \
    && useradd --uid 10001 --gid extractor --home-dir /nonexistent --no-create-home extractor
COPY --from=build /usr/local /usr/local
COPY main.py runtime_config.py product_extraction.py search_extraction.py product_markdown.py guanxe_adapter.py ./
COPY start-container.sh ./
COPY --from=test /tmp/test-gate/result /tmp/test-gate-result
RUN test "$(cat /tmp/test-gate-result)" = passed && rm /tmp/test-gate-result \
    && chmod 755 /app/start-container.sh \
    && chown -R 10001:10001 /app
USER 10001:10001
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','5000'), timeout=2).read()"
CMD ["/app/start-container.sh"]
