"""Decision-making engines. All agents consume the same `Strategy` object.

- RandomAgent     baseline / sanity check.
- HeuristicAgent  rule-based, driven entirely by `strategy.params`. Runs offline, fast,
                  deterministic per seed. This is what the harness tunes when no API key is set.
- LLMAgent        Claude picks each move from the observation + `strategy.playbook`. Falls back
                  to the heuristic agent for a move if the API errors or refuses.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any, Protocol

from .game_env import ACTIONS
from .llm import structured_call
from .types import Action, Observation, Strategy

log = logging.getLogger("banana_fighter.agent")

ACTION_COST = {"light": 10, "heavy": 25, "special": 50, "block": 5, "dodge": 15}

# name: (min, max, meaning). Shared by the heuristic agent and both optimizers.
PARAM_SPEC: dict[str, tuple[float, float, str]] = {
    "aggression": (0.0, 1.0, "when the enemy telegraphs a normal attack, probability of attacking anyway instead of defending"),
    "heavy_pref": (0.0, 1.0, "when attacking, probability of choosing heavy over light"),
    "defend_vs_heavy": (0.0, 1.0, "probability of blocking/dodging when a heavy attack or charge is telegraphed at close range"),
    "dodge_pref": (0.0, 1.0, "when defending, probability of dodge over block"),
    "rest_threshold": (0.0, 100.0, "rest when stamina drops below this"),
    "rest_only_at_range": (0.0, 1.0, "probability of retreating before resting instead of resting at close range"),
    "special_threshold": (0.0, 100.0, "use special when stamina is at least this (and in range)"),
    "punish_rest": (0.0, 1.0, "probability of attacking when the enemy telegraphs rest/idle at close range"),
    "respect_block": (0.0, 1.0, "when the enemy telegraphs block, probability of not throwing a light/heavy into it"),
}

DEFAULT_PARAMS = {
    "aggression": 0.5,
    "heavy_pref": 0.5,
    "defend_vs_heavy": 0.4,
    "dodge_pref": 0.3,
    "rest_threshold": 20.0,
    "rest_only_at_range": 0.2,
    "special_threshold": 70.0,
    "punish_rest": 0.5,
    "respect_block": 0.3,
}

DEFAULT_PLAYBOOK = [
    "Close the distance, then trade attacks. Keep an eye on stamina.",
]


def default_strategy() -> Strategy:
    return Strategy(version=0, name="baseline", params=dict(DEFAULT_PARAMS), playbook=list(DEFAULT_PLAYBOOK),
                    notes="Hand-written starting point; deliberately unrefined.")


def clamp_params(params: dict[str, float]) -> dict[str, float]:
    out = {}
    for key, (lo, hi, _) in PARAM_SPEC.items():
        val = float(params.get(key, DEFAULT_PARAMS[key]))
        out[key] = round(min(hi, max(lo, val)), 3)
    return out


class Agent(Protocol):
    name: str
    strategy: Strategy

    def set_strategy(self, strategy: Strategy) -> None: ...
    def start_episode(self, seed: int) -> None: ...
    def act(self, obs: Observation) -> Action: ...


class RandomAgent:
    name = "random"

    def __init__(self, strategy: Strategy | None = None):
        self.strategy = strategy or default_strategy()
        self.rng = random.Random(0)

    def set_strategy(self, strategy: Strategy) -> None:
        self.strategy = strategy

    def start_episode(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def act(self, obs: Observation) -> Action:
        return Action(self.rng.choice(obs.legal_actions), "random")


class HeuristicAgent:
    name = "heuristic"

    def __init__(self, strategy: Strategy | None = None):
        self.strategy = strategy or default_strategy()
        self.rng = random.Random(0)

    def set_strategy(self, strategy: Strategy) -> None:
        self.strategy = strategy

    def start_episode(self, seed: int) -> None:
        # Seeded per episode so a strategy's result on a given seed is reproducible.
        self.rng = random.Random((seed * 1_000_003) ^ self.strategy.version)

    def act(self, obs: Observation) -> Action:
        p = clamp_params(self.strategy.params)
        s = obs.state
        rng = self.rng
        stam = s["player_stamina"]
        dist = s["distance"]
        intent = s["enemy_intent"]
        charged = s["enemy_charged"]

        def can(a: str) -> bool:
            return ACTION_COST.get(a, 0) <= stam

        def defend(why: str) -> Action:
            if rng.random() < p["dodge_pref"] and can("dodge"):
                return Action("dodge", why)
            if can("block"):
                return Action("block", why)
            return Action("retreat", why + " (no stamina to block)")

        # 1. a heavy is coming at close range
        if dist == 0 and (charged or intent == "heavy") and rng.random() < p["defend_vs_heavy"]:
            return defend("heavy telegraphed")

        # 2. low stamina
        if stam < p["rest_threshold"]:
            if dist > 0 or intent in ("rest", "idle", "block"):
                return Action("rest", "low stamina, safe moment")
            if rng.random() < p["rest_only_at_range"]:
                return Action("retreat", "low stamina, back off first")
            return Action("rest", "low stamina")

        # 3. not in range
        if dist > 0:
            if dist == 1 and can("special") and stam >= p["special_threshold"]:
                return Action("special", "mid-range special")
            return Action("advance", "closing distance")

        # 4. close range decisions
        if intent in ("rest", "idle"):
            if rng.random() < p["punish_rest"]:
                for a in ("heavy", "light"):
                    if can(a):
                        return Action(a, "punish resting enemy")
        if intent == "block" and rng.random() < p["respect_block"]:
            if can("special") and stam >= p["special_threshold"]:
                return Action("special", "special through block")
            return Action("rest", "enemy blocking, recover stamina") if stam < 90 else defend("wait out block")
        if intent == "attack" and rng.random() > p["aggression"]:
            return defend("attack telegraphed")

        # attack
        if can("special") and stam >= p["special_threshold"]:
            return Action("special", "stamina high, special")
        if rng.random() < p["heavy_pref"] and can("heavy"):
            return Action("heavy", "heavy pressure")
        if can("light"):
            return Action("light", "light pressure")
        return Action("rest", "out of stamina") if not can("block") else Action("block", "out of attack stamina")


ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "description": "One short sentence on why."},
        "action": {"type": "string", "enum": ACTIONS},
    },
    "required": ["reasoning", "action"],
    "additionalProperties": False,
}


class LLMAgent:
    name = "llm"

    def __init__(self, client: Any, rules: str, strategy: Strategy | None = None, *, model: str = "claude-opus-5",
                 effort: str = "low", tracer: Any = None, run_id: str = "", history_len: int = 6):
        self.client = client
        self.rules = rules
        self.strategy = strategy or default_strategy()
        self.model = model
        self.effort = effort
        self.tracer = tracer
        self.run_id = run_id
        self.history_len = history_len
        self.fallback = HeuristicAgent(self.strategy)
        self.history: list[str] = []
        self.fallback_moves = 0

    def set_strategy(self, strategy: Strategy) -> None:
        self.strategy = strategy
        self.fallback.set_strategy(strategy)

    def start_episode(self, seed: int) -> None:
        self.history = []
        self.fallback.start_episode(seed)

    def _system(self) -> str:
        # Stable for the whole iteration -> cached across every move of every episode.
        playbook = "\n".join(f"- {line}" for line in self.strategy.playbook)
        params = "\n".join(f"- {k}: {v} ({PARAM_SPEC[k][2]})" for k, v in clamp_params(self.strategy.params).items())
        return (
            "You are the decision engine for a fighting-game bot. Each turn you get the game state and "
            "reply with exactly one action as JSON.\n\n"
            f"GAME RULES\n{self.rules}\n"
            f"STRATEGY v{self.strategy.version} '{self.strategy.name}' - follow this playbook:\n{playbook}\n\n"
            f"Tuned tendencies (treat as guidance, not hard rules):\n{params}\n"
        )

    def act(self, obs: Observation) -> Action:
        recent = "\n".join(self.history[-self.history_len:]) or "(first move)"
        user = f"Recent moves:\n{recent}\n\nNow: {obs.text}\nLegal actions: {', '.join(obs.legal_actions)}"
        result = structured_call(self.client, model=self.model, system=self._system(), user=user,
                                 schema=ACTION_SCHEMA, effort=self.effort, max_tokens=1024)
        if self.tracer:
            self.tracer.llm_call(self.run_id, "agent", self.model, user, result.text, result.usage)
        if result.data and result.data.get("action") in obs.legal_actions:
            action = Action(result.data["action"], result.data.get("reasoning", ""))
        else:
            self.fallback_moves += 1
            log.warning("LLM move unusable (%s); using heuristic fallback", result.error or "invalid action")
            action = self.fallback.act(obs)
            action.reasoning = f"[fallback] {action.reasoning}"
        self.history.append(f"turn {obs.turn}: {obs.text} -> {action.name}")
        return action

    def record_outcome(self, info: dict[str, Any]) -> None:
        """Let the model see what its last move did (hit/whiff/blocked and damage)."""
        if self.history:
            self.history[-1] += (f" => {info.get('player_result')}, enemy did {info.get('enemy_action')}, "
                                 f"dealt {info.get('damage_dealt')}, took {info.get('damage_taken')}")


def make_agent(kind: str, *, client: Any, rules: str, model: str, effort: str, tracer: Any, run_id: str) -> Agent:
    if kind == "random":
        return RandomAgent()
    if kind == "heuristic":
        return HeuristicAgent()
    if kind == "llm":
        if client is None:
            log.warning("BF_AGENT=llm but no Anthropic client; using heuristic agent instead")
            return HeuristicAgent()
        return LLMAgent(client, rules, model=model, effort=effort, tracer=tracer, run_id=run_id)
    raise SystemExit(f"unknown agent {kind!r}; expected random, heuristic, or llm")
