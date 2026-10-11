"""Game environment interface plus a built-in deterministic fighting game ("Banana Brawl").

The harness only depends on the `GameEnv` protocol. Swap in a real game (screen capture +
input injection, a web game via browser automation, an emulator...) by implementing
`reset`, `step`, and a text rendering of the observation.
"""
from __future__ import annotations

import random
from typing import Any, Protocol

from .types import Observation, StepResult

ACTIONS = ["light", "heavy", "special", "block", "dodge", "advance", "retreat", "rest"]
DISTANCE_NAMES = {0: "close", 1: "mid", 2: "far"}
ENEMY_INTENTS = ["attack", "heavy", "block", "charge", "advance", "rest", "idle"]

RULES_TEXT = """\
Banana Brawl: a turn-based 1v1 fighter. You start with 100 HP, the enemy with 130; both have 100 stamina.
Distance is close / mid / far. Each turn the enemy telegraphs an intent (what it is probably
about to do) and you pick one action. Actions:
  light    10 dmg, costs 10 stamina, must be close.
  heavy    25 dmg, costs 25 stamina, must be close. A blocking enemy takes only 20%.
Enemy light attacks do 12 and heavies 30 (45 when charged). The enemy also reads you: it blocks
more after you attack, and attacks more after you rest, stumble, or whiff.
  special  40 dmg, costs 50 stamina, works at close or mid. Block only halves it.
  block    costs 5 stamina, you take 20% of incoming damage.
  dodge    costs 15 stamina, you take 0 damage from attacks this turn.
  advance  move one step closer. retreat moves one step away.
  rest     +30 stamina but you take 150% damage this turn.
Attacking from out of range whiffs (stamina spent, nothing happens). Using an action you lack
stamina for makes you stumble: nothing happens and you take 150% damage. An enemy that is
"charging" will heavy-attack next turn for 150% damage. Enemy telegraphs are usually honest
but not always. You win by reducing the enemy to 0 HP within the turn limit; losing HP first,
or running out of turns, loses.
"""


class GameEnv(Protocol):
    name: str
    actions: list[str]

    def reset(self, seed: int) -> Observation: ...
    def step(self, action: str) -> StepResult: ...
    def rules(self) -> str: ...


class BananaBrawlEnv:
    """Deterministic given `seed`. Enemy personality rotates with the seed so a strategy has to
    generalize across aggressive, defensive, and feinting opponents."""

    name = "banana-brawl"
    actions = ACTIONS
    PERSONALITIES = ("aggressive", "defensive", "trickster")

    def __init__(self, max_turns: int = 40):
        self.max_turns = max_turns
        self.rng = random.Random(0)
        self.s: dict[str, Any] = {}

    # ------------------------------------------------------------------ protocol
    def rules(self) -> str:
        return RULES_TEXT

    def reset(self, seed: int) -> Observation:
        self.rng = random.Random(seed)
        self.s = {
            "turn": 0,
            "player_hp": 100,
            "player_stamina": 100,
            "enemy_hp": 130,
            "enemy_stamina": 100,
            "distance": 2,
            "enemy_personality": self.PERSONALITIES[seed % len(self.PERSONALITIES)],
            "enemy_charged": False,
            "enemy_intent": "advance",
            "player_last": "",
        }
        self.s["enemy_intent"] = self._pick_enemy_intent()
        return self._observe()

    def step(self, action: str) -> StepResult:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}; expected one of {ACTIONS}")
        s = self.s
        s["turn"] += 1
        info: dict[str, Any] = {
            "telegraph": s["enemy_intent"],
            "player_action": action,
            "player_result": "",
            "enemy_action": "",
            "damage_dealt": 0,
            "damage_taken": 0,
        }

        enemy_action = self._resolve_enemy_action()
        info["enemy_action"] = enemy_action

        # --- player action ---------------------------------------------------
        cost = {"light": 10, "heavy": 25, "special": 50, "block": 5, "dodge": 15}.get(action, 0)
        player_stumbled = cost > s["player_stamina"]
        player_blocking = action == "block" and not player_stumbled
        player_dodging = action == "dodge" and not player_stumbled
        vulnerable = player_stumbled or action == "rest"

        if player_stumbled:
            info["player_result"] = "stumble"
        else:
            s["player_stamina"] -= cost
            if action in ("light", "heavy", "special"):
                in_range = s["distance"] == 0 or (action == "special" and s["distance"] <= 1)
                if not in_range:
                    info["player_result"] = "whiff"
                else:
                    dmg = {"light": 10, "heavy": 25, "special": 40}[action]
                    if enemy_action == "block":
                        dmg = int(dmg * (0.5 if action == "special" else 0.2))
                        info["player_result"] = "blocked"
                    elif enemy_action == "dodge":
                        dmg = 0
                        info["player_result"] = "dodged"
                    else:
                        if enemy_action == "rest":
                            dmg = int(dmg * 1.5)
                        info["player_result"] = "hit"
                    s["enemy_hp"] -= dmg
                    info["damage_dealt"] = dmg
            elif action == "advance":
                s["distance"] = max(0, s["distance"] - 1)
                info["player_result"] = "moved"
            elif action == "retreat":
                s["distance"] = min(2, s["distance"] + 1)
                info["player_result"] = "moved"
            elif action == "rest":
                s["player_stamina"] = min(100, s["player_stamina"] + 30)
                info["player_result"] = "rested"
            else:
                info["player_result"] = action  # block / dodge

        # --- enemy action ----------------------------------------------------
        taken = 0
        if enemy_action in ("attack", "heavy"):
            base = 12 if enemy_action == "attack" else 30
            if enemy_action == "heavy" and s["enemy_charged"]:
                base = int(base * 1.5)
            in_range = s["distance"] == 0
            if in_range:
                if player_dodging:
                    taken = 0
                elif player_blocking:
                    taken = int(base * 0.2)
                else:
                    taken = int(base * (1.5 if vulnerable else 1.0))
            else:
                info["enemy_action"] = f"{enemy_action}-whiff"
            s["enemy_stamina"] -= 10 if enemy_action == "attack" else 25
            s["enemy_charged"] = False
        elif enemy_action == "charge":
            s["enemy_charged"] = True
        elif enemy_action == "advance":
            s["distance"] = max(0, s["distance"] - 1)
        elif enemy_action == "rest":
            s["enemy_stamina"] = min(100, s["enemy_stamina"] + 30)
        elif enemy_action == "block":
            s["enemy_stamina"] -= 5
        s["enemy_stamina"] = max(0, s["enemy_stamina"])
        s["player_hp"] -= taken
        info["damage_taken"] = taken
        s["player_last"] = info["player_result"]

        # --- reward / termination -------------------------------------------
        reward = (info["damage_dealt"] - taken) / 10.0
        done = False
        if s["enemy_hp"] <= 0 and s["player_hp"] > 0:
            reward += 10
            done = True
            info["outcome"] = "win"
        elif s["player_hp"] <= 0:
            reward -= 10
            done = True
            info["outcome"] = "loss"
        elif s["turn"] >= self.max_turns:
            reward -= 5
            done = True
            info["outcome"] = "timeout"

        if not done:
            s["enemy_intent"] = self._pick_enemy_intent()
        return StepResult(self._observe(), reward, done, info)

    # ------------------------------------------------------------------ enemy AI
    def _pick_enemy_intent(self) -> str:
        s = self.s
        if s["enemy_charged"]:
            return "heavy"
        if s["enemy_stamina"] < 20:
            return "rest"
        if s["distance"] > 0:
            return "advance" if self.rng.random() < 0.8 else "idle"
        weights = dict({
            "aggressive": {"attack": 4, "heavy": 3, "charge": 2, "block": 1, "rest": 1, "idle": 1},
            "defensive": {"attack": 2, "heavy": 1, "charge": 1, "block": 4, "rest": 2, "idle": 2},
            "trickster": {"attack": 3, "heavy": 2, "charge": 2, "block": 2, "rest": 1, "idle": 2},
        }[s["enemy_personality"]])
        # Reactive: the enemy reads the player too. Mindless aggression gets blocked; resting,
        # stumbling, or whiffing gets punished with a heavy.
        last = s["player_last"]
        if last in ("hit", "blocked", "dodged"):
            weights["block"] *= 2
        elif last in ("rested", "stumble", "whiff"):
            weights["heavy"] *= 2
            weights["attack"] *= 2
        return self.rng.choices(list(weights), weights=list(weights.values()))[0]

    def _resolve_enemy_action(self) -> str:
        """The telegraph is honest most of the time; tricksters feint more often."""
        s = self.s
        honesty = {"aggressive": 0.9, "defensive": 0.85, "trickster": 0.6}[s["enemy_personality"]]
        intent = s["enemy_intent"]
        if s["enemy_charged"]:
            return "heavy"  # a charge always pays off
        if self.rng.random() < honesty:
            return intent
        alternatives = [a for a in ("attack", "block", "dodge", "idle", "heavy") if a != intent]
        return self.rng.choice(alternatives)

    # ------------------------------------------------------------------ rendering
    def _observe(self) -> Observation:
        s = self.s
        state = {k: v for k, v in s.items()}
        state["distance_name"] = DISTANCE_NAMES[s["distance"]]
        text = (
            f"Turn {s['turn']}/{self.max_turns}. You: {s['player_hp']} HP, {s['player_stamina']} stamina. "
            f"Enemy ({s['enemy_personality']}): {s['enemy_hp']} HP, {s['enemy_stamina']} stamina. "
            f"Distance: {state['distance_name']}. "
            f"Enemy telegraph: {s['enemy_intent']}{' (CHARGED - heavy incoming)' if s['enemy_charged'] else ''}."
        )
        return Observation(turn=s["turn"], state=state, legal_actions=list(ACTIONS), text=text)


ENVS = {"banana-brawl": BananaBrawlEnv}


def make_env(name: str) -> GameEnv:
    try:
        return ENVS[name]()
    except KeyError:
        raise SystemExit(f"unknown env {name!r}; available: {sorted(ENVS)}")
