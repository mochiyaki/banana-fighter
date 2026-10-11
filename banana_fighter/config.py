"""Environment-driven settings. Reads a local .env if present (no extra dependency)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments, never overrides real env vars."""
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    # Claude
    anthropic_api_key: str | None
    model: str
    agent_effort: str
    optimizer_effort: str
    # harness
    agent: str
    optimizer: str
    env: str
    # storage
    storage: str
    mongodb_uri: str
    mongodb_db: str
    # telemetry
    raindrop_api_key: str | None
    raindrop_project_id: str | None
    run_user: str
    # paths
    memory_dir: Path
    checkpoints_dir: Path
    logs_dir: Path

    @property
    def llm_available(self) -> bool:
        return bool(self.anthropic_api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        g = os.environ.get
        return cls(
            anthropic_api_key=g("ANTHROPIC_API_KEY") or None,
            model=g("BF_MODEL", "claude-opus-5"),
            agent_effort=g("BF_AGENT_EFFORT", "low"),
            optimizer_effort=g("BF_OPTIMIZER_EFFORT", "high"),
            agent=g("BF_AGENT", "heuristic"),
            optimizer=g("BF_OPTIMIZER", "rule"),
            env=g("BF_ENV", "banana-brawl"),
            storage=g("BF_STORAGE", "jsonl"),
            mongodb_uri=g("MONGODB_URI", "mongodb://localhost:27017"),
            mongodb_db=g("MONGODB_DB", "banana_fighter"),
            raindrop_api_key=g("RAINDROP_API_KEY") or None,
            raindrop_project_id=g("RAINDROP_PROJECT_ID") or None,
            run_user=g("BF_RUN_USER", "banana-fighter"),
            memory_dir=Path(g("BF_MEMORY_DIR", PROJECT_ROOT / "memory")),
            checkpoints_dir=Path(g("BF_CHECKPOINTS_DIR", PROJECT_ROOT / "checkpoints")),
            logs_dir=Path(g("BF_LOGS_DIR", PROJECT_ROOT / "logs")),
        )
