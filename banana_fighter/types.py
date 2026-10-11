"""Shared data records that flow between env -> agent -> evaluator -> optimizer -> storage."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


@dataclass
class Observation:
    turn: int
    state: dict[str, Any]
    legal_actions: list[str]
    text: str  # human/LLM readable rendering produced by the env


@dataclass
class Action:
    name: str
    reasoning: str = ""


@dataclass
class StepResult:
    observation: Observation
    reward: float
    done: bool
    info: dict[str, Any]


@dataclass
class Step:
    turn: int
    state: dict[str, Any]       # state the agent saw when choosing
    action: str
    reasoning: str
    reward: float
    info: dict[str, Any]        # what the env reports happened (hit/whiff/blocked...)


@dataclass
class Episode:
    episode_id: str
    seed: int
    strategy_version: int
    agent: str
    steps: list[Step]
    total_reward: float
    outcome: str                # win | loss | timeout
    final_state: dict[str, Any]
    created_at: str = field(default_factory=now_iso)

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Episode":
        d = dict(d)
        d.pop("_id", None)
        d["steps"] = [Step(**s) for s in d["steps"]]
        return cls(**d)


@dataclass
class Mistake:
    kind: str
    count: int
    description: str
    examples: list[dict[str, Any]]   # a few {episode_id, turn, action, state} samples


@dataclass
class Evaluation:
    iteration: int
    strategy_version: int
    score: float
    metrics: dict[str, float]
    mistakes: list[Mistake]
    summary: str
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Evaluation":
        d = dict(d)
        d.pop("_id", None)
        d["mistakes"] = [Mistake(**m) for m in d["mistakes"]]
        return cls(**d)


@dataclass
class Strategy:
    """The thing the harness is optimizing.

    `params` drive the heuristic agent directly; `playbook` is natural-language guidance the
    LLM agent reads. Both optimizers may edit both, so the two agents stay interchangeable.
    """

    version: int
    name: str
    params: dict[str, float]
    playbook: list[str]
    notes: str = ""
    parent_version: int | None = None
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Strategy":
        d = dict(d)
        d.pop("_id", None)
        d.pop("is_best", None)
        d.pop("score", None)
        return cls(**d)

    def child(self, params: dict[str, float], playbook: list[str], notes: str, name: str | None = None) -> "Strategy":
        return Strategy(
            version=self.version + 1,
            name=name or self.name,
            params=dict(params),
            playbook=list(playbook),
            notes=notes,
            parent_version=self.version,
        )
