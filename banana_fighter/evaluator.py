"""Scores a batch of episodes and names the recurring mistakes in them.

The mistake taxonomy is what makes the loop *recursive* rather than blind search: the
optimizer receives named, counted failure modes with concrete examples, not just a number.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Callable

from .types import Episode, Evaluation, Mistake, Step

Detector = Callable[[Step], str | None]


def _telegraphed_heavy(step: Step) -> bool:
    return step.info.get("telegraph") in ("heavy", "charge") or step.state.get("enemy_charged")


def detect_whiff(step: Step) -> str | None:
    return "whiff" if step.info.get("player_result") == "whiff" else None


def detect_stumble(step: Step) -> str | None:
    return "stumble" if step.info.get("player_result") == "stumble" else None


def detect_unguarded_heavy(step: Step) -> str | None:
    if step.info.get("telegraph") == "heavy" and step.state.get("distance") == 0:
        if step.action not in ("block", "dodge", "retreat") and step.info.get("damage_taken", 0) >= 20:
            return "unguarded_heavy"
    return None


def detect_attack_into_block(step: Step) -> str | None:
    if step.action in ("light", "heavy") and step.info.get("player_result") == "blocked":
        return "attack_into_block"
    return None


def detect_rest_under_fire(step: Step) -> str | None:
    if step.action == "rest" and step.info.get("damage_taken", 0) > 0:
        return "rest_under_fire"
    return None


def detect_missed_punish(step: Step) -> str | None:
    enemy = step.info.get("enemy_action")
    if enemy in ("rest", "idle") and step.state.get("distance") == 0 and step.action in ("block", "dodge", "retreat"):
        if step.state.get("player_stamina", 0) >= 25:
            return "missed_punish"
    return None


def detect_wasted_defense(step: Step) -> str | None:
    enemy = step.info.get("enemy_action", "")
    if step.action in ("block", "dodge") and not enemy.startswith(("attack", "heavy")) and step.state.get("distance", 2) > 0:
        return "wasted_defense"
    return None


def detect_ignored_charge(step: Step) -> str | None:
    if step.state.get("enemy_charged") and step.state.get("distance") == 0 and step.action not in ("block", "dodge", "retreat"):
        return "ignored_charge"
    return None


DEFAULT_DETECTORS: list[Detector] = [
    detect_whiff,
    detect_stumble,
    detect_unguarded_heavy,
    detect_ignored_charge,
    detect_attack_into_block,
    detect_rest_under_fire,
    detect_missed_punish,
    detect_wasted_defense,
]

MISTAKE_DESCRIPTIONS = {
    "whiff": "Attacked while out of range (stamina wasted, no damage).",
    "stumble": "Chose an action without enough stamina for it (took 150% damage).",
    "unguarded_heavy": "Enemy telegraphed a heavy attack at close range and we neither blocked nor dodged.",
    "ignored_charge": "Enemy was charged (guaranteed 150% heavy) and we did not defend or retreat.",
    "attack_into_block": "Light/heavy attack landed on a blocking enemy (80% of damage lost).",
    "rest_under_fire": "Rested while the enemy was attacking (took 150% damage).",
    "missed_punish": "Enemy rested/idled at close range with plenty of our stamina available, but we defended instead of attacking.",
    "wasted_defense": "Blocked or dodged while out of the enemy's reach.",
}


class Evaluator:
    def __init__(self, detectors: list[Detector] | None = None, examples_per_mistake: int = 3):
        self.detectors = detectors or DEFAULT_DETECTORS
        self.examples_per_mistake = examples_per_mistake

    def score(self, episodes: list[Episode]) -> tuple[float, dict[str, float]]:
        wins = sum(e.outcome == "win" for e in episodes)
        win_rate = wins / len(episodes)
        hp_margin = mean(e.final_state["player_hp"] - e.final_state["enemy_hp"] for e in episodes)
        avg_reward = mean(e.total_reward for e in episodes)
        avg_turns = mean(len(e.steps) for e in episodes)
        # Headline: win rate dominates; HP margin breaks ties and rewards clean wins.
        score = 60 * win_rate + 0.4 * hp_margin
        metrics = {
            "win_rate": round(win_rate, 3),
            "hp_margin": round(hp_margin, 2),
            "avg_reward": round(avg_reward, 2),
            "avg_turns": round(avg_turns, 1),
            "episodes": float(len(episodes)),
        }
        return round(score, 2), metrics

    def find_mistakes(self, episodes: list[Episode]) -> list[Mistake]:
        counts: dict[str, int] = defaultdict(int)
        examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ep in episodes:
            for step in ep.steps:
                for detect in self.detectors:
                    kind = detect(step)
                    if not kind:
                        continue
                    counts[kind] += 1
                    if len(examples[kind]) < self.examples_per_mistake:
                        examples[kind].append(
                            {
                                "episode_id": ep.episode_id,
                                "turn": step.turn,
                                "action": step.action,
                                "telegraph": step.info.get("telegraph"),
                                "enemy_action": step.info.get("enemy_action"),
                                "damage_taken": step.info.get("damage_taken"),
                                "player_hp": step.state.get("player_hp"),
                                "player_stamina": step.state.get("player_stamina"),
                                "distance": step.state.get("distance_name"),
                            }
                        )
        mistakes = [
            Mistake(kind=k, count=c, description=MISTAKE_DESCRIPTIONS.get(k, k), examples=examples[k])
            for k, c in counts.items()
        ]
        mistakes.sort(key=lambda m: m.count, reverse=True)
        return mistakes

    def evaluate(self, episodes: list[Episode], iteration: int, strategy_version: int) -> Evaluation:
        if not episodes:
            raise ValueError("no episodes to evaluate")
        score, metrics = self.score(episodes)
        mistakes = self.find_mistakes(episodes)
        per_ep_steps = sum(len(e.steps) for e in episodes)
        top = ", ".join(f"{m.kind} x{m.count}" for m in mistakes[:3]) or "none"
        losses_by_personality: dict[str, int] = defaultdict(int)
        for e in episodes:
            if e.outcome != "win":
                losses_by_personality[e.final_state.get("enemy_personality", "?")] += 1
        weak_vs = ", ".join(f"{k} ({v})" for k, v in sorted(losses_by_personality.items())) or "none"
        summary = (
            f"score {score} | win rate {metrics['win_rate']:.0%} over {len(episodes)} episodes, "
            f"HP margin {metrics['hp_margin']:+.1f}, {per_ep_steps} moves. "
            f"Top mistakes: {top}. Non-wins vs: {weak_vs}."
        )
        return Evaluation(
            iteration=iteration,
            strategy_version=strategy_version,
            score=score,
            metrics=metrics,
            mistakes=mistakes,
            summary=summary,
        )
