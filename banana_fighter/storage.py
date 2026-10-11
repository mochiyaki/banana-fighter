"""Experience / evaluation / strategy persistence.

`JsonlStore` is the default and needs nothing installed. `MongoStore` implements the same
interface on top of pymongo (install with `uv sync --extra mongo`) for when runs outgrow
local files or need to be shared.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Protocol

from .types import Episode, Evaluation, Strategy


class ExperienceStore(Protocol):
    def append_episodes(self, episodes: Iterable[Episode]) -> None: ...
    def append_evaluation(self, evaluation: Evaluation) -> None: ...
    def save_strategy(self, strategy: Strategy, score: float | None, is_best: bool) -> None: ...
    def load_best_strategy(self) -> Strategy | None: ...
    def load_evaluations(self) -> list[Evaluation]: ...
    def recent_episodes(self, n: int, strategy_version: int | None = None) -> list[Episode]: ...
    def close(self) -> None: ...


class JsonlStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.experiences = self.root / "experiences.jsonl"
        self.evaluations = self.root / "evaluations.jsonl"
        self.strategies = self.root / "strategies.jsonl"
        self.best = self.root / "best_strategy.json"

    @staticmethod
    def _append(path: Path, rows: Iterable[dict[str, Any]]) -> None:
        with path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, sort_keys=True) + "\n")

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def append_episodes(self, episodes: Iterable[Episode]) -> None:
        self._append(self.experiences, (e.to_dict() for e in episodes))

    def append_evaluation(self, evaluation: Evaluation) -> None:
        self._append(self.evaluations, [evaluation.to_dict()])

    def save_strategy(self, strategy: Strategy, score: float | None, is_best: bool) -> None:
        row = {**strategy.to_dict(), "score": score, "is_best": is_best}
        self._append(self.strategies, [row])
        if is_best:
            self.best.write_text(json.dumps(row, indent=2, sort_keys=True))

    def load_best_strategy(self) -> Strategy | None:
        if not self.best.exists():
            return None
        return Strategy.from_dict(json.loads(self.best.read_text()))

    def load_evaluations(self) -> list[Evaluation]:
        return [Evaluation.from_dict(d) for d in self._read(self.evaluations)]

    def recent_episodes(self, n: int, strategy_version: int | None = None) -> list[Episode]:
        rows = self._read(self.experiences)
        if strategy_version is not None:
            rows = [r for r in rows if r["strategy_version"] == strategy_version]
        return [Episode.from_dict(r) for r in rows[-n:]]

    def close(self) -> None:
        pass


class MongoStore:
    """Same interface, collections: experiences, evaluations, strategies."""

    def __init__(self, uri: str, db_name: str):
        try:
            from pymongo import DESCENDING, MongoClient
        except ImportError as e:  # pragma: no cover
            raise SystemExit("MongoStore needs pymongo: `uv sync --extra mongo`") from e
        self._desc = DESCENDING
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = self.client[db_name]
        self.experiences = db["experiences"]
        self.evaluations = db["evaluations"]
        self.strategies = db["strategies"]
        self.experiences.create_index([("strategy_version", DESCENDING), ("created_at", DESCENDING)])
        self.strategies.create_index([("is_best", DESCENDING), ("created_at", DESCENDING)])

    def append_episodes(self, episodes: Iterable[Episode]) -> None:
        docs = [e.to_dict() for e in episodes]
        if docs:
            self.experiences.insert_many(docs)

    def append_evaluation(self, evaluation: Evaluation) -> None:
        self.evaluations.insert_one(evaluation.to_dict())

    def save_strategy(self, strategy: Strategy, score: float | None, is_best: bool) -> None:
        if is_best:
            self.strategies.update_many({"is_best": True}, {"$set": {"is_best": False}})
        self.strategies.insert_one({**strategy.to_dict(), "score": score, "is_best": is_best})

    def load_best_strategy(self) -> Strategy | None:
        doc = self.strategies.find_one({"is_best": True}, sort=[("created_at", self._desc)])
        return Strategy.from_dict(doc) if doc else None

    def load_evaluations(self) -> list[Evaluation]:
        return [Evaluation.from_dict(d) for d in self.evaluations.find().sort("created_at", 1)]

    def recent_episodes(self, n: int, strategy_version: int | None = None) -> list[Episode]:
        query = {"strategy_version": strategy_version} if strategy_version is not None else {}
        docs = list(self.experiences.find(query).sort("created_at", self._desc).limit(n))
        return [Episode.from_dict(d) for d in reversed(docs)]

    def close(self) -> None:
        self.client.close()


def make_store(kind: str, *, memory_dir: Path, mongodb_uri: str, mongodb_db: str) -> ExperienceStore:
    if kind == "jsonl":
        return JsonlStore(memory_dir)
    if kind == "mongo":
        return MongoStore(mongodb_uri, mongodb_db)
    raise SystemExit(f"unknown storage {kind!r}; expected jsonl or mongo")
