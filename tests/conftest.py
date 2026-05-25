import pytest
import httpx


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires vLLM running on localhost:8000")


def _vllm_available() -> bool:
    try:
        r = httpx.get("http://localhost:8000/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if not _vllm_available():
        skip = pytest.mark.skip(reason="vLLM not running on localhost:8000")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)
