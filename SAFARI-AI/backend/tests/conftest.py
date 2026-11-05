import json
from dataclasses import replace
from pathlib import Path

import pytest

from services.catalog import seed_catalog
from services.common.settings import load_settings
from services.common.store import JsonStore
from services.engine import Assistant
from services.sources.harvest import refresh_api
from services.sources.tanapa_api import ApiSnapshot

FIXTURES = Path(__file__).parent / "fixtures"


def snapshot() -> ApiSnapshot:
    return ApiSnapshot(**json.loads((FIXTURES / "tanapa_api_snapshot.json").read_text(encoding="utf-8")))


def offline_settings():
    return replace(load_settings(), llm_api_key="", llm_base_url="", refresh_hours=0)


@pytest.fixture(autouse=True)
def _offline(tmp_path, monkeypatch):
    monkeypatch.setenv("SAFARI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SAFARI_STORE", "memory")
    monkeypatch.setenv("SAFARI_REFRESH_HOURS", "0")
    for name in ("DEEPSEEK_API_KEY", "SAFARI_LLM_API_KEY", "SAFARI_ADMIN_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def build_assistant(with_api: bool = True) -> Assistant:
    store = JsonStore(None)
    assistant = Assistant(store, settings=offline_settings())
    seed_catalog(store, assistant.embedder)
    if with_api:
        refresh_api(store, assistant.embedder, snapshot=snapshot())
    return assistant


@pytest.fixture
def assistant() -> Assistant:
    return build_assistant()
