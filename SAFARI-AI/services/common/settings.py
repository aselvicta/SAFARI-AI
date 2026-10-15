"""Runtime settings from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path
    data_dir: Path
    store: str
    database_url: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    tzs_per_usd: float = 2555.0
    refresh_hours: float = 12.0
    admin_token: str = ""

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)


def _load_dotenv(path: Path) -> None:
    if not path.exists() or "PYTEST_CURRENT_TEST" in os.environ:
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def load_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    data_dir = Path(os.environ.get("SAFARI_DATA_DIR", ROOT / ".data"))
    return Settings(
        root=ROOT,
        data_dir=data_dir,
        store=os.environ.get("SAFARI_STORE", "memory").lower(),
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql://safari:safari@localhost:5432/safari_ai",
        ),
        llm_base_url=_first("DEEPSEEK_BASE_URL", "SAFARI_LLM_BASE_URL").rstrip("/"),
        llm_api_key=_first("DEEPSEEK_API_KEY", "SAFARI_LLM_API_KEY"),
        llm_model=_first("DEEPSEEK_MODEL", "SAFARI_LLM_MODEL", default="deepseek-chat"),
        tzs_per_usd=_float("SAFARI_TZS_PER_USD", 2555.0),
        refresh_hours=_float("SAFARI_REFRESH_HOURS", 12.0),
        admin_token=_first("SAFARI_ADMIN_TOKEN"),
    )


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default
