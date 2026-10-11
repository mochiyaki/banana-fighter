"""CLI: `banana-fighter run|play|show-best|history`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import default_strategy, make_agent
from .config import Settings
from .evaluator import Evaluator
from .game_env import make_env
from .llm import make_client
from .optimizer import make_optimizer
from .recursive_harness import HarnessConfig, RecursiveHarness, load_checkpoint
from .storage import make_store
from .telemetry import log, make_tracer, setup_logging


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="banana-fighter", description="Recursive training harness for a game bot.")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="play -> evaluate -> optimize, repeatedly")
    run.add_argument("-n", "--iterations", type=int, default=10)
    run.add_argument("-e", "--episodes", type=int, default=9, help="episodes per iteration")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--agent", choices=["heuristic", "llm", "random"], help="default: BF_AGENT or heuristic")
    run.add_argument("--optimizer", choices=["rule", "llm"], help="default: BF_OPTIMIZER or rule")
    run.add_argument("--env", help="default: BF_ENV or banana-brawl")
    run.add_argument("--target", type=float, help="stop once best score reaches this")
    run.add_argument("--patience", type=int, help="stop after this many consecutive rejected candidates")
    run.add_argument("--exploration", type=float, default=0.05)
    run.add_argument("--fresh-seeds", action="store_true", help="new seeds each iteration (default: fixed for fair comparison)")
    run.add_argument("--resume", action="store_true", help="start from the stored best strategy")
    run.add_argument("--from-checkpoint", type=Path, help="start from a checkpoint file's best strategy")

    play = sub.add_parser("play", help="watch the current best (or baseline) strategy play")
    play.add_argument("-e", "--episodes", type=int, default=1)
    play.add_argument("--seed", type=int, default=0)
    play.add_argument("--agent", choices=["heuristic", "llm", "random"])
    play.add_argument("--baseline", action="store_true", help="ignore stored best; use the hand-written baseline")

    sub.add_parser("show-best", help="print the stored best strategy")
    sub.add_parser("history", help="print score history from storage")
    return p


def _common(args, settings: Settings):
    setup_logging(settings.logs_dir, args.verbose)
    store = make_store(settings.storage, memory_dir=settings.memory_dir, mongodb_uri=settings.mongodb_uri, mongodb_db=settings.mongodb_db)
    return store


def cmd_run(args, settings: Settings) -> int:
    store = _common(args, settings)
    env = make_env(args.env or settings.env)
    agent_kind = args.agent or settings.agent
    optimizer_kind = args.optimizer or settings.optimizer
    client = make_client() if (agent_kind == "llm" or optimizer_kind == "llm") else None
    if client is not None:
        log.info("Claude model %s (agent effort %s, optimizer effort %s); server-side refusal fallbacks enabled",
                 settings.model, settings.agent_effort, settings.optimizer_effort)
    tracer = make_tracer(logs_dir=settings.logs_dir, raindrop_api_key=settings.raindrop_api_key,
                         raindrop_project_id=settings.raindrop_project_id, run_user=settings.run_user)
    cfg = HarnessConfig(iterations=args.iterations, episodes_per_iteration=args.episodes, seed=args.seed,
                        target_score=args.target, patience=args.patience, exploration=args.exploration,
                        fixed_seeds=not args.fresh_seeds, checkpoints_dir=settings.checkpoints_dir)
    harness = RecursiveHarness(env, None, Evaluator(), None, store, tracer, cfg)  # type: ignore[arg-type]
    harness.agent = make_agent(agent_kind, client=client, rules=env.rules(), model=settings.model,
                               effort=settings.agent_effort, tracer=tracer, run_id=harness.run_id)
    harness.optimizer = make_optimizer(optimizer_kind, client=client, rules=env.rules(), model=settings.model,
                                       effort=settings.optimizer_effort, tracer=tracer, run_id=harness.run_id, seed=args.seed)

    start = None
    if args.from_checkpoint:
        start, score = load_checkpoint(args.from_checkpoint)
        log.info("starting from checkpoint v%d (score %s)", start.version, score)
    elif args.resume:
        start = store.load_best_strategy()
        if start:
            log.info("resuming from stored best v%d", start.version)
        else:
            log.info("no stored best; starting from baseline")

    try:
        result = harness.run(start)
    finally:
        store.close()
    print()
    print(f"best strategy: v{result.best_strategy.version} '{result.best_strategy.name}'  score {result.best_score}")
    print(f"params: {json.dumps(result.best_strategy.params)}")
    print("playbook:")
    for line in result.best_strategy.playbook:
        print(f"  - {line}")
    print(f"\nscores by iteration: {[h.score for h in result.history]}")
    print(f"saved: {settings.memory_dir / 'best_strategy.json'}  checkpoints: {settings.checkpoints_dir}")
    return 0


def cmd_play(args, settings: Settings) -> int:
    store = _common(args, settings)
    env = make_env(settings.env)
    strategy = None if args.baseline else store.load_best_strategy()
    strategy = strategy or default_strategy()
    agent_kind = args.agent or settings.agent
    client = make_client() if agent_kind == "llm" else None
    agent = make_agent(agent_kind, client=client, rules=env.rules(), model=settings.model, effort=settings.agent_effort,
                       tracer=None, run_id="play")
    agent.set_strategy(strategy)
    print(f"strategy v{strategy.version} '{strategy.name}' with {agent.name} agent\n")
    wins = 0
    for i in range(args.episodes):
        seed = args.seed + i
        obs = env.reset(seed)
        agent.start_episode(seed)
        print(f"=== episode {i + 1} (seed {seed}, enemy {obs.state['enemy_personality']}) ===")
        while True:
            action = agent.act(obs)
            res = env.step(action.name)
            if hasattr(agent, "record_outcome"):
                agent.record_outcome(res.info)
            print(f"  {obs.text}\n    -> {action.name:8s} [{action.reasoning}] => {res.info['player_result']}, "
                  f"enemy {res.info['enemy_action']}, dealt {res.info['damage_dealt']}, took {res.info['damage_taken']}")
            obs = res.observation
            if res.done:
                print(f"  OUTCOME: {res.info['outcome']}  (you {obs.state['player_hp']} HP, enemy {obs.state['enemy_hp']} HP)\n")
                wins += res.info["outcome"] == "win"
                break
    print(f"{wins}/{args.episodes} wins")
    store.close()
    return 0


def cmd_show_best(args, settings: Settings) -> int:
    store = _common(args, settings)
    best = store.load_best_strategy()
    store.close()
    if not best:
        print("no best strategy stored yet; run `banana-fighter run` first")
        return 1
    print(json.dumps(best.to_dict(), indent=2))
    return 0


def cmd_history(args, settings: Settings) -> int:
    store = _common(args, settings)
    evals = store.load_evaluations()
    store.close()
    if not evals:
        print("no evaluations stored yet")
        return 1
    for ev in evals:
        print(f"iter {ev.iteration:3d}  v{ev.strategy_version:<3d} score {ev.score:7.2f}  {ev.summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    return {"run": cmd_run, "play": cmd_play, "show-best": cmd_show_best, "history": cmd_history}[args.cmd](args, settings)


if __name__ == "__main__":
    sys.exit(main())
