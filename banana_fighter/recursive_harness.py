"""The recursive loop: play -> evaluate -> optimize -> play again.

Acceptance is greedy hill-climbing with memory: a candidate strategy is only kept if it beats
the best score so far; otherwise the harness reverts to the best and the optimizer is told what
the rejected candidate scored, so it does not propose it again. Exploration grows while
rejections pile up and resets on an accept. Everything is checkpointed per iteration so a run
can be resumed.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .agent import Agent, default_strategy
from .evaluator import Evaluator
from .game_env import GameEnv
from .optimizer import Optimizer
from .storage import ExperienceStore
from .telemetry import Tracer
from .types import Episode, Evaluation, Step, Strategy

log = logging.getLogger("banana_fighter.harness")


@dataclass
class HarnessConfig:
    iterations: int = 10
    episodes_per_iteration: int = 9       # multiple of 3 -> every enemy personality each round
    seed: int = 0
    target_score: float | None = None     # stop early once the best score reaches this
    patience: int | None = None           # stop after this many consecutive rejections
    exploration: float = 0.05
    exploration_growth: float = 1.5
    max_exploration: float = 0.3
    fixed_seeds: bool = True              # same seeds every iteration -> fair comparison between versions
    checkpoints_dir: Path = Path("checkpoints")


@dataclass
class RunResult:
    run_id: str
    best_strategy: Strategy
    best_score: float
    iterations_run: int
    history: list[Evaluation] = field(default_factory=list)


class RecursiveHarness:
    def __init__(self, env: GameEnv, agent: Agent, evaluator: Evaluator, optimizer: Optimizer,
                 store: ExperienceStore, tracer: Tracer, config: HarnessConfig, run_id: str | None = None):
        self.env = env
        self.agent = agent
        self.evaluator = evaluator
        self.optimizer = optimizer
        self.store = store
        self.tracer = tracer
        self.cfg = config
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]

    # ------------------------------------------------------------------ playing
    def play_episode(self, seed: int, strategy: Strategy) -> Episode:
        obs = self.env.reset(seed)
        self.agent.start_episode(seed)
        steps: list[Step] = []
        total = 0.0
        outcome = "timeout"
        while True:
            action = self.agent.act(obs)
            result = self.env.step(action.name)
            if hasattr(self.agent, "record_outcome"):
                self.agent.record_outcome(result.info)
            steps.append(Step(turn=obs.turn, state=obs.state, action=action.name, reasoning=action.reasoning,
                              reward=result.reward, info=result.info))
            total += result.reward
            obs = result.observation
            if result.done:
                outcome = result.info.get("outcome", "timeout")
                break
        return Episode(episode_id=Episode.new_id(), seed=seed, strategy_version=strategy.version,
                       agent=self.agent.name, steps=steps, total_reward=round(total, 2), outcome=outcome,
                       final_state=obs.state)

    def _seeds(self, iteration: int) -> list[int]:
        base = self.cfg.seed if self.cfg.fixed_seeds else self.cfg.seed + iteration * 10_000
        return [base + i for i in range(self.cfg.episodes_per_iteration)]

    def play_batch(self, iteration: int, strategy: Strategy) -> list[Episode]:
        self.agent.set_strategy(strategy)
        return [self.play_episode(seed, strategy) for seed in self._seeds(iteration)]

    # ------------------------------------------------------------------ the loop
    def run(self, start: Strategy | None = None) -> RunResult:
        cfg = self.cfg
        strategy = start or default_strategy()
        best, best_score = strategy, float("-inf")
        history: list[Evaluation] = []
        exploration = cfg.exploration
        rejections = 0
        next_version = strategy.version + 1
        self.tracer.run_started(self.run_id, {**asdict(cfg), "agent": self.agent.name, "optimizer": self.optimizer.name,
                                              "env": self.env.name, "start_version": strategy.version})
        iterations_run = 0
        for iteration in range(1, cfg.iterations + 1):
            iterations_run = iteration
            self.tracer.iteration_started(self.run_id, iteration, strategy)

            episodes = self.play_batch(iteration, strategy)
            self.store.append_episodes(episodes)
            evaluation = self.evaluator.evaluate(episodes, iteration, strategy.version)
            self.store.append_evaluation(evaluation)
            history.append(evaluation)

            accepted = evaluation.score > best_score
            if accepted:
                best, best_score = strategy, evaluation.score
                rejections = 0
                exploration = cfg.exploration
            else:
                rejections += 1
                exploration = min(cfg.max_exploration, exploration * cfg.exploration_growth)
            self.store.save_strategy(strategy, evaluation.score, is_best=accepted)
            self.tracer.iteration_finished(self.run_id, iteration, strategy, evaluation, accepted, best_score)
            self._checkpoint(iteration, strategy, evaluation, best, best_score, accepted, exploration)

            if cfg.target_score is not None and best_score >= cfg.target_score:
                log.info("target score %.2f reached; stopping", cfg.target_score)
                break
            if cfg.patience is not None and rejections >= cfg.patience:
                log.info("%d consecutive rejections; stopping", rejections)
                break
            if iteration == cfg.iterations:
                break

            # Propose the next version from the *best* strategy, but with the rejected candidate's
            # evaluation in the history so the optimizer learns from the failure too.
            base_eval = evaluation if accepted else self._eval_for(history, best.version) or evaluation
            strategy = self.optimizer.propose(best, base_eval, history, episodes, exploration)
            # Versions are unique across the run even when several candidates branch off the same best.
            strategy.version = next_version
            next_version += 1
            log.debug("proposed v%d (parent v%d): %s", strategy.version, strategy.parent_version, strategy.notes)

        self.tracer.run_finished(self.run_id, best, best_score, iterations_run)
        self.tracer.flush()
        return RunResult(self.run_id, best, best_score, iterations_run, history)

    @staticmethod
    def _eval_for(history: list[Evaluation], version: int) -> Evaluation | None:
        for ev in reversed(history):
            if ev.strategy_version == version:
                return ev
        return None

    def _checkpoint(self, iteration: int, strategy: Strategy, evaluation: Evaluation, best: Strategy,
                    best_score: float, accepted: bool, exploration: float) -> None:
        d = Path(self.cfg.checkpoints_dir)
        d.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "iteration": iteration,
            "strategy": strategy.to_dict(),
            "evaluation": evaluation.to_dict(),
            "accepted": accepted,
            "best": {"strategy": best.to_dict(), "score": best_score},
            "exploration": exploration,
        }
        (d / f"{self.run_id}-iter{iteration:03d}.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
        (d / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True))


def load_checkpoint(path: Path) -> tuple[Strategy, float]:
    data = json.loads(Path(path).read_text())
    return Strategy.from_dict(data["best"]["strategy"]), float(data["best"]["score"])
