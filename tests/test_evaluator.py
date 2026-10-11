from banana_fighter.evaluator import Evaluator
from banana_fighter.types import Episode, Step


def _ep(steps, outcome, player_hp, enemy_hp, eid="e1"):
    return Episode(episode_id=eid, seed=0, strategy_version=0, agent="t", steps=steps, total_reward=0.0,
                   outcome=outcome, final_state={"player_hp": player_hp, "enemy_hp": enemy_hp, "enemy_personality": "aggressive"})


def _step(turn, action, state, info):
    base_state = {"distance": 0, "distance_name": "close", "player_stamina": 50, "enemy_charged": False, "player_hp": 50}
    base_info = {"telegraph": "idle", "player_result": "hit", "enemy_action": "idle", "damage_taken": 0, "damage_dealt": 0}
    return Step(turn=turn, state={**base_state, **state}, action=action, reasoning="", reward=0.0, info={**base_info, **info})


def test_detects_named_mistakes():
    steps = [
        _step(1, "light", {"distance": 2, "distance_name": "far"}, {"player_result": "whiff"}),
        _step(2, "heavy", {}, {"telegraph": "heavy", "enemy_action": "heavy", "damage_taken": 25}),
        _step(3, "rest", {}, {"enemy_action": "attack", "damage_taken": 15}),
        _step(4, "block", {}, {"telegraph": "rest", "enemy_action": "rest"}),
        _step(5, "heavy", {}, {"telegraph": "block", "enemy_action": "block", "player_result": "blocked", "damage_dealt": 5}),
        _step(6, "light", {"enemy_charged": True}, {"telegraph": "heavy", "enemy_action": "heavy", "damage_taken": 37}),
    ]
    ev = Evaluator().evaluate([_ep(steps, "loss", 0, 60)], iteration=1, strategy_version=0)
    kinds = {m.kind: m.count for m in ev.mistakes}
    assert kinds["whiff"] == 1
    assert kinds["unguarded_heavy"] == 2  # turns 2 and 6
    assert kinds["ignored_charge"] == 1
    assert kinds["rest_under_fire"] == 1
    assert kinds["missed_punish"] == 1
    assert kinds["attack_into_block"] == 1
    assert ev.mistakes[0].count >= ev.mistakes[-1].count
    assert ev.mistakes[0].examples[0]["episode_id"] == "e1"


def test_score_rewards_wins_and_margin():
    ev = Evaluator()
    win, _ = ev.score([_ep([], "win", 80, 0), _ep([], "win", 60, 0, "e2")])
    loss, _ = ev.score([_ep([], "loss", 0, 50), _ep([], "loss", 0, 90, "e2")])
    mixed, metrics = ev.score([_ep([], "win", 80, 0), _ep([], "loss", 0, 50, "e2")])
    assert win > mixed > loss
    assert metrics["win_rate"] == 0.5
