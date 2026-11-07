import logging
import io
import os
import threading

import pytest

os.environ.setdefault("EXTRACT_API_TOKEN", "test-secret")

import main
from runtime_config import load_runtime_config


def test_defaults_preserve_native_runtime_values():
    config = load_runtime_config({})
    assert config.port == 5000
    assert config.request_timeout == (5.0, 10.0)
    assert config.log_level == "INFO"
    assert config.max_concurrent_extractions == 0


def test_coolify_timeout_overrides_and_log_level():
    config = load_runtime_config({
        "PORT": "5000",
        "EXTRACT_CONNECT_TIMEOUT": "10",
        "EXTRACT_READ_TIMEOUT": "20",
        "EXTRACT_LOG_LEVEL": "debug",
        "EXTRACT_MAX_CONCURRENT": "1",
    })
    assert config.request_timeout == (10.0, 20.0)
    assert config.log_level == "DEBUG"
    assert config.max_concurrent_extractions == 1


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_supported_log_levels(level):
    assert load_runtime_config({"EXTRACT_LOG_LEVEL": level}).log_level == level


@pytest.mark.parametrize("env", [
    {"PORT": "0"}, {"PORT": "65536"}, {"PORT": "5000.5"},
    {"EXTRACT_CONNECT_TIMEOUT": "0"}, {"EXTRACT_READ_TIMEOUT": "-1"},
    {"EXTRACT_CONNECT_TIMEOUT": "0.01"},
    {"EXTRACT_CONNECT_TIMEOUT": "nan"}, {"EXTRACT_READ_TIMEOUT": "inf"},
    {"EXTRACT_READ_TIMEOUT": "121"}, {"EXTRACT_LOG_LEVEL": "TRACE"},
    {"EXTRACT_MAX_CONCURRENT": "-1"}, {"EXTRACT_MAX_CONCURRENT": "2"},
])
def test_invalid_runtime_environment_fails_closed(env):
    with pytest.raises(RuntimeError):
        load_runtime_config(env)


def test_create_app_applies_port_timeout_and_logging(monkeypatch):
    monkeypatch.setenv("PORT", "5088")
    monkeypatch.setenv("EXTRACT_CONNECT_TIMEOUT", "10")
    monkeypatch.setenv("EXTRACT_READ_TIMEOUT", "20")
    monkeypatch.setenv("EXTRACT_LOG_LEVEL", "DEBUG")
    app = main.create_app("test-secret")
    assert app.config["PORT"] == 5088
    assert app.config["UPSTREAM_TIMEOUT"] == (10.0, 20.0)
    assert main.LOG.level == logging.DEBUG


def test_fetch_uses_configured_timeout_without_logging_url_or_secret(monkeypatch):
    class Response:
        status_code = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        encoding = "utf-8"
        is_redirect = False
        is_permanent_redirect = False

        def iter_content(self, chunk_size):
            yield b"<html><body>ok</body></html>"

        def close(self):
            pass

    class Session:
        trust_env = True

        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

        def close(self):
            pass

    monkeypatch.setenv("EXTRACT_CONNECT_TIMEOUT", "10")
    monkeypatch.setenv("EXTRACT_READ_TIMEOUT", "20")
    monkeypatch.setenv("EXTRACT_LOG_LEVEL", "DEBUG")
    app = main.create_app("sensitive-token-value")
    session = Session()
    monkeypatch.setattr(main.requests, "Session", lambda: session)
    monkeypatch.setattr(main.socket, "getaddrinfo", lambda *args, **kwargs: [
        (None, None, None, None, ("93.184.216.34", 0))
    ])
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    main.LOG.addHandler(handler)
    try:
        with app.test_request_context("/"):
            main._fetch_page("https://example.com/private?token=query-secret")
    finally:
        main.LOG.removeHandler(handler)
        handler.close()
    assert session.calls[0][1]["timeout"] == (10.0, 20.0)
    logs = log_buffer.getvalue()
    assert "status=200" in logs
    assert "bytes=" in logs
    assert "query-secret" not in logs
    assert "sensitive-token-value" not in logs


@pytest.mark.parametrize("error_name", ["ConnectTimeout", "ReadTimeout"])
def test_timeout_categories_are_logged_without_exception_text(monkeypatch, error_name):
    exception = getattr(main.requests, error_name)("https://private.example/?secret=query-secret")

    class Session:
        trust_env = True

        def get(self, url, **kwargs):
            raise exception

        def close(self):
            pass

    monkeypatch.setenv("EXTRACT_LOG_LEVEL", "DEBUG")
    app = main.create_app("sensitive-token-value")
    monkeypatch.setattr(main.requests, "Session", Session)
    monkeypatch.setattr(main.socket, "getaddrinfo", lambda *args, **kwargs: [
        (None, None, None, None, ("93.184.216.34", 0))
    ])
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    main.LOG.addHandler(handler)
    try:
        with app.test_request_context("/"):
            with pytest.raises(main.ExtractionError) as caught:
                main._fetch_page("https://example.com/")
    finally:
        main.LOG.removeHandler(handler)
        handler.close()
    assert (caught.value.code, caught.value.status) == ("upstream_timeout", 504)
    logs = log_buffer.getvalue()
    assert error_name in logs
    assert "query-secret" not in logs
    assert "private.example" not in logs
    assert "sensitive-token-value" not in logs


def test_streaming_timeout_wrapped_by_requests_is_classified_safely(monkeypatch):
    class ReadTimeoutError(Exception):
        pass

    wrapped = main.requests.ConnectionError("private request detail")
    wrapped.__cause__ = ReadTimeoutError("sensitive body detail")

    class Response:
        status_code = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        encoding = "utf-8"
        is_redirect = False
        is_permanent_redirect = False

        def iter_content(self, chunk_size):
            raise wrapped
            yield b""  # Make this a generator and keep the exception in iteration.

        def close(self):
            pass

    class Session:
        def get(self, url, **kwargs):
            return Response()

        def close(self):
            pass

    monkeypatch.setenv("EXTRACT_LOG_LEVEL", "DEBUG")
    app = main.create_app("sensitive-token-value")
    monkeypatch.setattr(main.requests, "Session", Session)
    monkeypatch.setattr(main.socket, "getaddrinfo", lambda *args, **kwargs: [
        (None, None, None, None, ("93.184.216.34", 0))
    ])
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    main.LOG.addHandler(handler)
    try:
        with app.test_request_context("/"):
            with pytest.raises(main.ExtractionError) as caught:
                main._fetch_page("https://example.com/")
    finally:
        main.LOG.removeHandler(handler)
        handler.close()
    assert (caught.value.code, caught.value.status) == ("upstream_timeout", 504)
    logs = log_buffer.getvalue()
    assert "ReadTimeoutError" in logs
    assert "private request detail" not in logs
    assert "sensitive body detail" not in logs
    assert "sensitive-token-value" not in logs


def test_validation_rejects_missing_token_and_bad_port(monkeypatch):
    monkeypatch.delenv("EXTRACT_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="EXTRACT_API_TOKEN"):
        main.create_app()
    monkeypatch.setenv("EXTRACT_API_TOKEN", "test-secret")
    monkeypatch.setenv("PORT", "70000")
    with pytest.raises(RuntimeError, match="PORT"):
        main.create_app()


def test_packaging_files_keep_render_path_and_image_only_compose():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    compose = (root / "compose.coolify.yaml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    startup = (root / "start-container.sh").read_text(encoding="utf-8")
    assert "# Web Content Extractor" in readme
    assert '"service":"extractwebsite"' in readme
    assert "pip install -r requirements.txt" in readme
    assert "build:" not in compose
    assert "ports:" not in compose
    assert "${WEB_CONTENT_EXTRACTOR_IMAGE:?" in compose
    immutable_reference = "ghcr.io/petaz1987/web-content-extractor@sha256:<placeholder-digest>"
    assert f"`{immutable_reference}`" in readme
    assert "Illustrative format only, not a real digest" in readme
    assert "USER 10001:10001" in dockerfile
    runtime_stage = dockerfile.split("FROM python-base AS runtime", 1)[1]
    assert "EXTRACT_API_TOKEN=" not in runtime_stage
    assert "--workers 1" in startup
    assert "--threads 2" in startup
    assert "--timeout 0" in startup
    assert "--graceful-timeout 30" in startup


def test_single_extraction_slot_keeps_health_available(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def slow_extract(url):
        entered.set()
        assert release.wait(timeout=3)
        return {"ok": True}

    monkeypatch.setattr(main, "extract_web_content", slow_extract)
    monkeypatch.setenv("EXTRACT_MAX_CONCURRENT", "1")
    app = main.create_app("test-secret")
    statuses = []

    def extraction_request():
        with app.test_client() as client:
            response = client.get(
                "/extract?url=https://example.com",
                headers={"Authorization": "Bearer test-secret"},
            )
            statuses.append(response.status_code)

    thread = threading.Thread(target=extraction_request)
    thread.start()
    assert entered.wait(timeout=1)
    with app.test_client() as client:
        assert client.get("/health").status_code == 200
        busy = client.get(
            "/extract?url=https://example.com&mode=product",
            headers={"Authorization": "Bearer test-secret"},
        )
        assert busy.status_code == 503
        assert busy.json["error"]["code"] == "extraction_busy"
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert statuses == [200]


def test_default_concurrency_remains_unlimited_for_native_runtime(monkeypatch):
    monkeypatch.delenv("EXTRACT_MAX_CONCURRENT", raising=False)
    entered = []
    both_entered = threading.Event()
    release = threading.Event()
    count_lock = threading.Lock()

    def slow_extract(url):
        with count_lock:
            entered.append(url)
            if len(entered) == 2:
                both_entered.set()
        assert release.wait(timeout=3)
        return {"ok": True}

    monkeypatch.setattr(main, "extract_web_content", slow_extract)
    app = main.create_app("test-secret")
    statuses = []

    def extraction_request(url):
        with app.test_client() as client:
            response = client.get(
                f"/extract?url=https://example.com/{url}",
                headers={"Authorization": "Bearer test-secret"},
            )
            statuses.append(response.status_code)

    threads = [threading.Thread(target=extraction_request, args=(f"{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    assert both_entered.wait(timeout=1)
    release.set()
    for thread in threads:
        thread.join(timeout=2)
    assert statuses == [200, 200]
