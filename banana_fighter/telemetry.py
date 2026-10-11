"""Run telemetry. Console/file logging is always on; Raindrop (raindrop.ai) is added when a
key is configured (install with `uv sync --extra raindrop`).

Every tracer gets the same hooks, so the harness never branches on which backend is active.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

from .types import Evaluation, Strategy

log = logging.getLogger("banana_fighter")


class Tracer(Protocol):
    def run_started(self, run_id: str, config: dict[str, Any]) -> None: ...
    def iteration_started(self, run_id: str, iteration: int, strategy: Strategy) -> None: ...
    def iteration_finished(self, run_id: str, iteration: int, strategy: Strategy, evaluation: Evaluation,
                           accepted: bool, best_score: float) -> None: ...
    def llm_call(self, run_id: str, role: str, model: str, prompt: str, output: str, usage: dict[str, Any]) -> None: ...
    def run_finished(self, run_id: str, best: Strategy, best_score: float, iterations: int) -> None: ...
    def flush(self) -> None: ...


def setup_logging(logs_dir: Path, verbose: bool = False) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    root = logging.getLogger("banana_fighter")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    if root.handlers:
        return
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    fh = logging.FileHandler(logs_dir / "harness.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)


class ConsoleTracer:
    def __init__(self, logs_dir: Path):
        self.events_path = Path(logs_dir) / "events.jsonl"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)

    def _event(self, kind: str, **payload: Any) -> None:
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": kind, **payload}, default=str) + "\n")

    def run_started(self, run_id, config):
        log.info("run %s started: %s", run_id, json.dumps(config, default=str))
        self._event("run_started", run_id=run_id, config=config)

    def iteration_started(self, run_id, iteration, strategy):
        log.info("iter %d | playing strategy v%d (%s)", iteration, strategy.version, strategy.name)

    def iteration_finished(self, run_id, iteration, strategy, evaluation, accepted, best_score):
        verdict = "ACCEPTED (new best)" if accepted else f"rejected (best {best_score})"
        log.info("iter %d | v%d -> %s | %s", iteration, strategy.version, verdict, evaluation.summary)
        self._event("iteration_finished", run_id=run_id, iteration=iteration, strategy_version=strategy.version,
                    score=evaluation.score, metrics=evaluation.metrics, accepted=accepted, best_score=best_score,
                    mistakes={m.kind: m.count for m in evaluation.mistakes})

    def llm_call(self, run_id, role, model, prompt, output, usage):
        log.debug("llm[%s] %s usage=%s", role, model, usage)
        self._event("llm_call", run_id=run_id, role=role, model=model, usage=usage,
                    prompt_chars=len(prompt), output_chars=len(output))

    def run_finished(self, run_id, best, best_score, iterations):
        log.info("run %s finished after %d iterations. best: v%d score %s", run_id, iterations, best.version, best_score)
        self._event("run_finished", run_id=run_id, best_version=best.version, best_score=best_score, iterations=iterations)

    def flush(self):
        pass


class RaindropTracer:
    """Each harness iteration is one Raindrop AI event; an accepted improvement is a positive
    signal on it, a regression a negative one, so Raindrop's dashboards can rank strategies.
    Individual LLM calls are tracked as their own events keyed to the same convo (run) id."""

    def __init__(self, api_key: str, project_id: str | None, user_id: str):
        try:
            from raindrop import Raindrop
        except ImportError as e:  # pragma: no cover
            raise SystemExit("RaindropTracer needs raindrop-ai: `uv sync --extra raindrop`") from e
        self.rd = Raindrop(api_key=api_key, project_id=project_id, tracing_enabled=False)
        self.user_id = user_id

    @staticmethod
    def _iteration_event_id(run_id: str, iteration: int) -> str:
        return f"{run_id}-iter-{iteration}"

    def run_started(self, run_id, config):
        self.rd.track_ai(user_id=self.user_id, event="harness_run_started", event_id=f"{run_id}-start",
                         convo_id=run_id, input=json.dumps(config, default=str), properties={"run_id": run_id})

    def iteration_started(self, run_id, iteration, strategy):
        pass

    def iteration_finished(self, run_id, iteration, strategy, evaluation, accepted, best_score):
        event_id = self._iteration_event_id(run_id, iteration)
        self.rd.track_ai(
            user_id=self.user_id,
            event="harness_iteration",
            event_id=event_id,
            convo_id=run_id,
            input=json.dumps(strategy.to_dict(), default=str),
            output=evaluation.summary,
            properties={
                "iteration": str(iteration),
                "strategy_version": str(strategy.version),
                "score": str(evaluation.score),
                "best_score": str(best_score),
                "accepted": str(accepted),
                **{f"metric_{k}": str(v) for k, v in evaluation.metrics.items()},
                **{f"mistake_{m.kind}": str(m.count) for m in evaluation.mistakes},
            },
        )
        self.rd.track_signal(
            event_id=event_id,
            name="strategy_accepted" if accepted else "strategy_rejected",
            sentiment="POSITIVE" if accepted else "NEGATIVE",
            comment=evaluation.summary,
        )

    def llm_call(self, run_id, role, model, prompt, output, usage):
        self.rd.track_ai(user_id=self.user_id, event=f"llm_{role}", convo_id=run_id, model=model,
                         input=prompt, output=output, properties={k: str(v) for k, v in usage.items()})

    def run_finished(self, run_id, best, best_score, iterations):
        self.rd.track_ai(user_id=self.user_id, event="harness_run_finished", event_id=f"{run_id}-end", convo_id=run_id,
                         output=json.dumps(best.to_dict(), default=str),
                         properties={"best_score": str(best_score), "iterations": str(iterations)})
        self.flush()

    def flush(self):
        self.rd.flush()


class MultiTracer:
    def __init__(self, tracers: list[Any]):
        self.tracers = tracers

    def __getattr__(self, name: str):
        def fan_out(*args: Any, **kwargs: Any) -> None:
            for t in self.tracers:
                try:
                    getattr(t, name)(*args, **kwargs)
                except Exception:  # telemetry must never kill a training run
                    log.exception("tracer %s.%s failed", type(t).__name__, name)
        return fan_out


def make_tracer(*, logs_dir: Path, raindrop_api_key: str | None, raindrop_project_id: str | None, run_user: str) -> Tracer:
    tracers: list[Any] = [ConsoleTracer(logs_dir)]
    if raindrop_api_key:
        tracers.append(RaindropTracer(raindrop_api_key, raindrop_project_id, run_user))
        log.info("Raindrop telemetry enabled")
    return MultiTracer(tracers)  # type: ignore[return-value]
