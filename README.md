# 🍌 banana-fighter

https://mochiyaki.github.io/app9/ 👈 Demo Game Link here or opt to run it locally following the guide below

Clone this repo
```
git clone https://github.com/mochiyaki/banana-fighter
```

Enter the directory
```
cd banana-fighter
```

Play the game
```
node serve.mjs
```

## Recursive harnessing
A **recursive training harness** for a game-playing bot. Instead of training a network from
scratch, the bot uses a decision engine (Claude, or a tunable rule set) and wraps it in a loop
that repeatedly **plays → evaluates → names its mistakes → rewrites its strategy → plays again**,
keeping only the versions that score better.

![screenshot](https://raw.githubusercontent.com/mochiyaki/banana-fighter/master/recursive_harness.png)

copy and paste easy flowchart
```
            ┌──────────────────────────────────────────────────────┐
            │                 recursive_harness.py                 │
            │                                                      │
  strategy  │   play N episodes ──► evaluate ──► optimize ──┐      │
  v(k)  ───►│   (game_env + agent)  (evaluator)  (optimizer)│      │
            │        ▲                                      │      │
            │        └── accept if better, else revert ◄────┘ v(k+1)
            └──────────────────────────────────────────────────────┘
                 │ experiences, evaluations, strategies  │ events
                 ▼                                       ▼
            storage.py (JSONL ─or─ MongoDB)      telemetry.py (log ─or─ Raindrop)
```

## Quick start

```bash
uv sync                          # Python >=3.10; installs the anthropic SDK + pytest
uv run banana-fighter run -n 20 -e 12   # 20 iterations x 12 episodes, fully offline
uv run banana-fighter play       # watch the best strategy play one episode, move by move
uv run banana-fighter history    # score per iteration
uv run banana-fighter show-best  # the stored best strategy (params + playbook)
uv run pytest                    # 20 tests, < 1 s
```

Without an API key the harness runs the **rule-based agent** and **rule-based optimizer**: it is
deterministic, free, and fast (20 iterations in about a second). A typical offline run takes the
built-in game from a 50% win rate to 100% in roughly ten iterations.

### Turning on Claude

```bash
cp .env.example .env            # then set ANTHROPIC_API_KEY (or run `ant auth login`)
uv run banana-fighter run --agent llm --optimizer llm -n 10 -e 6
```

| Flag / env             | Options               | What it controls                                                           |
|------------------------|-----------------------|----------------------------------------------------------------------------|
| `--agent` / `BF_AGENT` | `heuristic` `llm` `random` | Who picks each move. `llm` = Claude reads the state + playbook and answers with one action. |
| `--optimizer` / `BF_OPTIMIZER` | `rule` `llm`  | Who writes the next strategy. `llm` = Claude reads the evaluation, history, and worst episodes and rewrites params + playbook. |
| `BF_MODEL`             | default `claude-opus-5` | Model for both roles.                                                     |
| `BF_AGENT_EFFORT`      | default `low`         | Per-move thinking effort (moves are cheap decisions).                      |
| `BF_OPTIMIZER_EFFORT`  | default `high`        | Per-iteration strategy rewrite effort.                                     |

The two roles mix freely: `--agent heuristic --optimizer llm` is the cheapest way to use Claude
(one call per iteration, not per move) and still get natural-language reasoning about failures.
Claude calls use JSON-schema structured output, prompt caching on the stable system prompt, and
Anthropic's server-side refusal fallback (`fallbacks: "default"`) on Claude Opus 5 / Fable models.
Any API error or refusal degrades to the rule-based path for that move / iteration, so a run never
stalls.

## How the loop works

1. **Play.** `RecursiveHarness.play_batch` runs `episodes` games with the current `Strategy`. Seeds
   are fixed per iteration by default so two versions are compared on identical opponents
   (`--fresh-seeds` to randomize instead).
2. **Evaluate.** `Evaluator` scores the batch (`60 × win_rate + 0.4 × HP margin`) and runs a set of
   **mistake detectors** over every move: `whiff`, `stumble`, `unguarded_heavy`, `ignored_charge`,
   `attack_into_block`, `rest_under_fire`, `missed_punish`, `wasted_defense`. Each comes with a count
   and concrete examples (episode, turn, state). Named mistakes are what make the loop recursive
   rather than blind search: the optimizer is told *what* went wrong, not just the score.
3. **Accept or revert.** A candidate replaces the best only if it scores higher. Otherwise the
   harness reverts to the best and grows the exploration knob; an accept resets it.
4. **Optimize.** The optimizer proposes `v(k+1)` from the best strategy, with the full score
   history and the rejected candidates' evaluations in context, so it does not re-propose losers.
5. **Checkpoint.** Every iteration writes `checkpoints/<run>-iterNNN.json` and `checkpoints/latest.json`
   (candidate, evaluation, best so far, exploration). Resume with `--resume` (stored best) or
   `--from-checkpoint path`.

Stop early with `--target <score>` or `--patience <n>` (consecutive rejections).

![screenshot](https://raw.githubusercontent.com/mochiyaki/banana-fighter/master/curve.png)

### The Strategy object

```json
{
  "version": 11, "name": "baseline", "parent_version": 10,
  "params":   {"aggression": 0.51, "defend_vs_heavy": 0.925, "respect_block": 0.919, "...": "..."},
  "playbook": ["When the enemy telegraphs a heavy attack at close range, block or dodge.", "..."],
  "notes":    "why this version exists (optimizer rationale)"
}
```

`params` drive the heuristic agent directly; `playbook` is natural-language guidance the LLM agent
reads. Both optimizers edit both, so you can tune cheaply offline with the heuristic agent, then hand
the resulting playbook to the LLM agent (or the reverse).

## Layout

```
banana_fighter/
├── main.py               CLI: run | play | show-best | history
├── recursive_harness.py  the loop, acceptance rule, checkpoints
├── game_env.py           GameEnv protocol + BananaBrawlEnv (built-in deterministic fighter)
├── agent.py              RandomAgent, HeuristicAgent, LLMAgent; Strategy defaults + PARAM_SPEC
├── evaluator.py          score + mistake detectors
├── optimizer.py          RuleOptimizer, LLMOptimizer
├── llm.py                one structured_call() wrapper around the Anthropic SDK
├── storage.py            ExperienceStore: JsonlStore (default), MongoStore
├── telemetry.py          Tracer: ConsoleTracer (log + events.jsonl), RaindropTracer
├── config.py             Settings from env / .env
└── types.py              Observation, Step, Episode, Evaluation, Strategy
memory/        experiences.jsonl, evaluations.jsonl, strategies.jsonl, best_strategy.json
checkpoints/   per-iteration snapshots
logs/          harness.log, events.jsonl
tests/
```

## Plugging in a real game - please see above (banana-fighter)

The harness only depends on the `GameEnv` protocol in `game_env.py`:

```python
class GameEnv(Protocol):
    name: str
    actions: list[str]
    def reset(self, seed: int) -> Observation      # Observation(turn, state: dict, legal_actions, text)
    def step(self, action: str) -> StepResult       # StepResult(observation, reward, done, info)
    def rules(self) -> str                          # text the LLM agent/optimizer read
```

Implement it over screen capture + input injection, a browser (the LLM agent already takes a text
observation; add an image block for vision), or an emulator, then register it in `ENVS`. Put
whatever your game reports into `info` (hit/miss, damage, etc.) and add matching detectors to
`evaluator.py`: that is the only game-specific part of the evaluation.

The built-in **Banana Brawl** is a turn-based 1v1 fighter with telegraphed (mostly honest) enemy
intents, stamina management, three enemy personalities that rotate with the seed, and an enemy that
reads the player back (blocks more after you attack, punishes rests and whiffs). Random play wins
~2% of games; the hand-written baseline ~55%.

## Storage: JSONL now, MongoDB later

`BF_STORAGE=jsonl` (default) writes to `memory/`. Switch to MongoDB with:

```bash
uv sync --extra mongo
BF_STORAGE=mongo MONGODB_URI=mongodb://localhost:27017 MONGODB_DB=banana_fighter uv run banana-fighter run
```

`MongoStore` keeps the same interface (`experiences`, `evaluations`, `strategies` collections, the best
strategy flagged with `is_best`), so nothing else changes. It has been exercised against an in-memory
Mongo (mongomock), then process to play it against a live server.

## Telemetry: logs now, then Raindrop

Console + `logs/events.jsonl` are always on. Add [Raindrop](https://raindrop.ai) with:

```bash
uv sync --extra raindrop
RAINDROP_API_KEY=... RAINDROP_PROJECT_ID=... uv run banana-fighter run --optimizer llm
```

`RaindropTracer` sends one `harness_iteration` AI event per iteration (strategy as input, evaluation
summary as output, metrics and mistake counts as properties), a positive/negative **signal** on it for
accepted/rejected candidates, and an `llm_agent` / `llm_optimizer` event per Claude call, all under
the run id as `convo_id`. Written against the `raindrop-ai` SDK's `Raindrop(api_key, project_id=...)`,
`track_ai`, `track_signal`, `flush` signatures (a live Raindrop project).

## Iteration of the harness

- Vision: give `LLMAgent` an image block alongside the text observation for pixel-based games.
- Opponent curriculum: weight seeds toward the personality the current best loses to.
- Meta-optimization: let the LLM optimizer also propose new mistake detectors when the score plateaus.
- Parallel episodes for a real game (the loop is sequential today because the toy env is instant).

## Multiple agent force workflow

![screenshot](https://raw.githubusercontent.com/mochiyaki/banana-fighter/master/multiple_agent_force_workflow.png)

Special thanks **MongoDB Atlas Sandbox**, AWS, Cursor, **Raindrop**
