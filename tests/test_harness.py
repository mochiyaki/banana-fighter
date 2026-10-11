import json

from banana_fighter.agent import DEFAULT_PARAMS, HeuristicAgent, RandomAgent, clamp_params, default_strategy
from banana_fighter.evaluator import Evaluator
from banana_fighter.game_env import BananaBrawlEnv
from banana_fighter.optimizer import RuleOptimizer
from banana_fighter.recursive_harness import HarnessConfig, RecursiveHarness, load_checkpoint
from banana_fighter.storage import JsonlStore
from banana_fighter.telemetry import ConsoleTracer
from banana_fighter.types import Evaluation, Mistake


def _harness(tmp_path, agent, **cfg):
    config = HarnessConfig(iterations=cfg.pop("iterations", 4), episodes_per_iteration=cfg.pop("episodes", 6),
                           checkpoints_dir=tmp_path / "ckpt", **cfg)
    return RecursiveHarness(BananaBrawlEnv(), agent, Evaluator(), RuleOptimizer(seed=1),
                            JsonlStore(tmp_path / "mem"), ConsoleTracer(tmp_path / "logs"), config, run_id="test")


def test_loop_runs_persists_and_checkpoints(tmp_path):
    h = _harness(tmp_path, HeuristicAgent())
    result = h.run()
    assert result.iterations_run == 4
    assert len(result.history) == 4
    assert result.best_score == max(ev.score for ev in result.history)
    # best strategy on disk matches the result
    store = JsonlStore(tmp_path / "mem")
    assert store.load_best_strategy().version == result.best_strategy.version
    assert len(store.load_evaluations()) == 4
    assert len(store.recent_episodes(100)) == 4 * 6
    # checkpoints
    ckpts = sorted((tmp_path / "ckpt").glob("test-iter*.json"))
    assert len(ckpts) == 4
    best, score = load_checkpoint(tmp_path / "ckpt" / "latest.json")
    assert best.version == result.best_strategy.version and score == result.best_score
    # the last iteration's checkpoint records the best, not necessarily the candidate
    last = json.loads(ckpts[-1].read_text())
    assert last["best"]["score"] == result.best_score


def test_versions_advance_and_rejected_candidates_revert_to_best(tmp_path):
    h = _harness(tmp_path, HeuristicAgent(), iterations=6)
    result = h.run()
    versions = [ev.strategy_version for ev in result.history]
    assert versions[0] == 0
    assert versions == sorted(versions) and len(set(versions)) == len(versions)
    # every proposed strategy's parent is the best-so-far at the time
    store = JsonlStore(tmp_path / "mem")
    rows = [json.loads(l) for l in (tmp_path / "mem" / "strategies.jsonl").read_text().splitlines()]
    best_so_far = None
    for row in rows:
        if best_so_far is not None:
            assert row["parent_version"] == best_so_far
        if row["is_best"]:
            best_so_far = row["version"]


def test_fixed_seeds_make_same_strategy_reproducible(tmp_path):
    h = _harness(tmp_path, HeuristicAgent(), iterations=1)
    s = default_strategy()
    a = [e.total_reward for e in h.play_batch(1, s)]
    b = [e.total_reward for e in h.play_batch(1, s)]
    assert a == b


def test_heuristic_beats_random(tmp_path):
    ev = Evaluator()
    h_rand = _harness(tmp_path / "r", RandomAgent(), iterations=1, episodes=12)
    h_heur = _harness(tmp_path / "h", HeuristicAgent(), iterations=1, episodes=12)
    s = default_strategy()
    rand_score, _ = ev.score(h_rand.play_batch(1, s))
    heur_score, _ = ev.score(h_heur.play_batch(1, s))
    assert heur_score > rand_score


def test_rule_optimizer_moves_params_toward_fixes():
    strat = default_strategy()
    ev = Evaluation(iteration=1, strategy_version=0, score=0.0, metrics={"episodes": 3.0},
                    mistakes=[Mistake("unguarded_heavy", 9, "", []), Mistake("attack_into_block", 6, "", [])], summary="")
    child = RuleOptimizer(seed=0).propose(strat, ev, [ev], [], exploration=0.0)
    assert child.version == 1 and child.parent_version == 0
    assert child.params["defend_vs_heavy"] > strat.params["defend_vs_heavy"]
    assert child.params["respect_block"] > strat.params["respect_block"]
    assert any("heavy" in line for line in child.playbook)
    assert child.params == clamp_params(child.params)


def test_clamp_params_bounds_and_defaults():
    p = clamp_params({"aggression": 7, "rest_threshold": -5})
    assert p["aggression"] == 1.0 and p["rest_threshold"] == 0.0
    assert p["heavy_pref"] == DEFAULT_PARAMS["heavy_pref"]
