"""Turns an Evaluation into the next Strategy.

- RuleOptimizer  deterministic (seeded) hill-climber: each named mistake nudges the parameters
                 that should fix it, plus a little exploration noise. Zero API cost.
- LLMOptimizer   Claude reads the strategy, the evaluation, the version history, and the worst
                 episodes, then rewrites params + playbook with a rationale. Falls back to the
                 rule optimizer on any API problem so a run never stalls.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any, Protocol

from .agent import DEFAULT_PARAMS, PARAM_SPEC, clamp_params
from .llm import structured_call
from .types import Episode, Evaluation, Strategy

log = logging.getLogger("banana_fighter.optimizer")

# mistake kind -> (param deltas, playbook advice)
MISTAKE_FIXES: dict[str, tuple[dict[str, float], str]] = {
    "unguarded_heavy": ({"defend_vs_heavy": +0.15}, "When the enemy telegraphs a heavy attack at close range, block or dodge."),
    "ignored_charge": ({"defend_vs_heavy": +0.2, "dodge_pref": +0.1}, "A charged enemy will heavy-attack next turn for 150% damage: dodge, block, or retreat."),
    "stumble": ({"rest_threshold": +6.0}, "Never pick an action you cannot afford; check stamina before heavy or special."),
    "whiff": ({}, "Only light/heavy at close range; special reaches mid range. Advance first otherwise."),
    "attack_into_block": ({"respect_block": +0.15}, "Do not throw light or heavy attacks into a telegraphed block; rest or use special instead."),
    "rest_under_fire": ({"rest_only_at_range": +0.15, "rest_threshold": -2.0}, "Retreat before resting unless the enemy is clearly resting or blocking."),
    "missed_punish": ({"punish_rest": +0.15, "aggression": +0.05}, "When the enemy rests or idles at close range, hit it with the heaviest attack you can afford."),
    "wasted_defense": ({"aggression": +0.05}, "Do not block or dodge when the enemy cannot reach you."),
}
MAX_PLAYBOOK = 12


class Optimizer(Protocol):
    name: str

    def propose(self, strategy: Strategy, evaluation: Evaluation, history: list[Evaluation],
                episodes: list[Episode], exploration: float) -> Strategy: ...


def _merge_playbook(playbook: list[str], additions: list[str]) -> list[str]:
    out = list(playbook)
    for line in additions:
        if line not in out:
            out.append(line)
    return out[-MAX_PLAYBOOK:]


class RuleOptimizer:
    name = "rule"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def propose(self, strategy, evaluation, history, episodes, exploration):
        params = dict(clamp_params(strategy.params))
        advice: list[str] = []
        episodes_n = max(1.0, evaluation.metrics.get("episodes", 1.0))
        changes: list[str] = []
        for mistake in evaluation.mistakes:
            fix = MISTAKE_FIXES.get(mistake.kind)
            if not fix:
                continue
            deltas, line = fix
            weight = min(1.0, mistake.count / episodes_n)  # ~1 per episode saturates
            if weight < 0.15:
                continue
            for key, delta in deltas.items():
                params[key] += delta * weight
                changes.append(f"{key}{delta * weight:+.3f} ({mistake.kind} x{mistake.count})")
            advice.append(line)

        # Exploration: jitter one or two params so plateaus do not become dead ends.
        for key in self.rng.sample(list(PARAM_SPEC), k=2):
            lo, hi, _ = PARAM_SPEC[key]
            jitter = self.rng.gauss(0, exploration) * (hi - lo)
            params[key] += jitter
            changes.append(f"{key}{jitter:+.3f} (explore)")

        params = clamp_params(params)
        notes = f"rule optimizer from v{strategy.version} (score {evaluation.score}): " + "; ".join(changes)
        return strategy.child(params, _merge_playbook(strategy.playbook, advice), notes)


STRATEGY_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "description": "What you concluded from the evaluation and why these changes should help."},
        "name": {"type": "string", "description": "Short memorable name for the new strategy version."},
        "params": {
            "type": "object",
            "properties": {k: {"type": "number", "description": f"{spec[2]} (range {spec[0]}-{spec[1]})"} for k, spec in PARAM_SPEC.items()},
            "required": list(PARAM_SPEC),
            "additionalProperties": False,
        },
        "playbook": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_PLAYBOOK,
                     "description": "Complete replacement playbook: concrete, situation -> action rules."},
    },
    "required": ["rationale", "name", "params", "playbook"],
    "additionalProperties": False,
}


def compress_episode(ep: Episode, max_steps: int = 40) -> str:
    rows = [
        f"t{s.turn} d={s.state.get('distance_name')} hp={s.state.get('player_hp')}/{s.state.get('enemy_hp')} "
        f"st={s.state.get('player_stamina')} tele={s.info.get('telegraph')} -> {s.action} => {s.info.get('player_result')}, "
        f"enemy {s.info.get('enemy_action')}, dealt {s.info.get('damage_dealt')} took {s.info.get('damage_taken')}"
        for s in ep.steps[:max_steps]
    ]
    return f"episode {ep.episode_id} vs {ep.final_state.get('enemy_personality')} -> {ep.outcome} (reward {ep.total_reward:.1f})\n" + "\n".join(rows)


class LLMOptimizer:
    name = "llm"

    def __init__(self, client: Any, rules: str, *, model: str = "claude-opus-5", effort: str = "high",
                 tracer: Any = None, run_id: str = "", seed: int = 0, worst_episodes: int = 2):
        self.client = client
        self.rules = rules
        self.model = model
        self.effort = effort
        self.tracer = tracer
        self.run_id = run_id
        self.worst_episodes = worst_episodes
        self.fallback = RuleOptimizer(seed)

    def _system(self) -> str:
        spec = "\n".join(f"- {k}: range {lo}-{hi}. {desc}" for k, (lo, hi, desc) in PARAM_SPEC.items())
        return (
            "You are the strategy coach inside a recursive training harness for a game bot. The bot just "
            "played a batch of episodes with the current strategy; you get the evaluation (score, metrics, "
            "named mistakes with examples), the score history of earlier versions, and the worst episodes "
            "move by move. Propose the next strategy version: adjust the numeric parameters and rewrite the "
            "playbook so the named mistakes stop happening without reintroducing earlier ones. Prefer a few "
            "decisive changes over many small ones, and avoid repeating a version that already scored poorly.\n\n"
            f"GAME RULES\n{self.rules}\n"
            f"PARAMETERS (used directly by the rule-based player; guidance for the LLM player)\n{spec}\n"
        )

    def propose(self, strategy, evaluation, history, episodes, exploration):
        worst = sorted(episodes, key=lambda e: e.total_reward)[: self.worst_episodes]
        hist = "\n".join(f"- v{h.strategy_version}: score {h.score} | {h.summary}" for h in history[-8:]) or "(none)"
        user = (
            f"CURRENT STRATEGY\n{json.dumps(strategy.to_dict(), indent=2)}\n\n"
            f"EVALUATION OF CURRENT STRATEGY\n{json.dumps(evaluation.to_dict(), indent=2)}\n\n"
            f"HISTORY (older versions)\n{hist}\n\n"
            f"WORST EPISODES THIS ITERATION\n" + "\n\n".join(compress_episode(e) for e in worst) +
            f"\n\nExploration hint: {exploration:.2f} (higher = the harness has plateaued; take bigger swings)."
        )
        result = structured_call(self.client, model=self.model, system=self._system(), user=user,
                                 schema=STRATEGY_SCHEMA, effort=self.effort, max_tokens=16000)
        if self.tracer:
            self.tracer.llm_call(self.run_id, "optimizer", self.model, user, result.text, result.usage)
        if not result.data:
            log.warning("LLM optimizer unusable (%s); falling back to rule optimizer", result.error)
            return self.fallback.propose(strategy, evaluation, history, episodes, exploration)
        d = result.data
        params = clamp_params({**DEFAULT_PARAMS, **d["params"]})
        playbook = [line.strip() for line in d["playbook"] if line.strip()][:MAX_PLAYBOOK] or strategy.playbook
        return strategy.child(params, playbook, notes=f"llm optimizer: {d['rationale']}", name=d.get("name") or strategy.name)


def make_optimizer(kind: str, *, client: Any, rules: str, model: str, effort: str, tracer: Any, run_id: str, seed: int) -> Optimizer:
    if kind == "rule":
        return RuleOptimizer(seed)
    if kind == "llm":
        if client is None:
            log.warning("BF_OPTIMIZER=llm but no Anthropic client; using rule optimizer instead")
            return RuleOptimizer(seed)
        return LLMOptimizer(client, rules, model=model, effort=effort, tracer=tracer, run_id=run_id, seed=seed)
    raise SystemExit(f"unknown optimizer {kind!r}; expected rule or llm")
