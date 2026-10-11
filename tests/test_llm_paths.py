"""The Claude-backed agent and optimizer, exercised offline with a fake client."""
import json
from types import SimpleNamespace

from banana_fighter.agent import LLMAgent, default_strategy
from banana_fighter.game_env import ACTIONS, BananaBrawlEnv
from banana_fighter.llm import structured_call
from banana_fighter.optimizer import LLMOptimizer
from banana_fighter.types import Evaluation, Mistake


class FakeClient:
    """Records the kwargs of each call and replays canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create("beta")))
        self.messages = SimpleNamespace(create=self._create("stable"))

    def _create(self, surface):
        def create(**kwargs):
            self.calls.append((surface, kwargs))
            return self.responses.pop(0)
        return create


def _response(payload=None, stop_reason="end_turn", model="claude-opus-5"):
    text = json.dumps(payload) if payload is not None else ""
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber", explanation="nope") if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="text", text=text)] if text else [],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0),
        model=model,
    )


def test_structured_call_uses_beta_surface_with_fallbacks_for_opus_5():
    client = FakeClient([_response({"ok": True})])
    result = structured_call(client, model="claude-opus-5", system="s", user="u", schema={"type": "object"}, effort="low")
    assert result.data == {"ok": True} and not result.refused
    surface, kwargs = client.calls[0]
    assert surface == "beta"
    assert kwargs["fallbacks"] == "default" and kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_structured_call_uses_stable_surface_for_other_models():
    client = FakeClient([_response({"ok": True})])
    structured_call(client, model="claude-sonnet-5", system="s", user="u", schema={"type": "object"})
    surface, kwargs = client.calls[0]
    assert surface == "stable" and "fallbacks" not in kwargs and "betas" not in kwargs


def test_structured_call_reports_refusal_without_raising():
    client = FakeClient([_response(stop_reason="refusal")])
    result = structured_call(client, model="claude-opus-5", system="s", user="u", schema={})
    assert result.refused and result.data is None and "cyber" in result.error


def test_llm_agent_plays_model_moves_and_falls_back_when_needed():
    env = BananaBrawlEnv()
    obs = env.reset(0)
    client = FakeClient([
        _response({"action": "advance", "reasoning": "close in"}),
        _response(stop_reason="refusal"),                              # -> heuristic fallback
        _response({"action": "fly", "reasoning": "invalid"}),         # -> heuristic fallback
    ])
    agent = LLMAgent(client, env.rules(), model="claude-opus-5")
    agent.start_episode(0)
    a1 = agent.act(obs)
    assert a1.name == "advance" and a1.reasoning == "close in"
    agent.record_outcome(env.step(a1.name).info)
    a2 = agent.act(obs)
    a3 = agent.act(obs)
    assert a2.name in ACTIONS and a3.name in ACTIONS
    assert a2.reasoning.startswith("[fallback]") and a3.reasoning.startswith("[fallback]")
    assert agent.fallback_moves == 2
    # the system prompt carries the playbook; the user turn carries recent history and the state
    _, kwargs = client.calls[-1]
    assert default_strategy().playbook[0] in kwargs["system"][0]["text"]
    assert "Recent moves" in kwargs["messages"][0]["content"] and "=> moved" in kwargs["messages"][0]["content"]


def _evaluation():
    return Evaluation(iteration=1, strategy_version=0, score=10.0, metrics={"episodes": 3.0, "win_rate": 0.3},
                      mistakes=[Mistake("unguarded_heavy", 6, "d", [])], summary="meh")


def test_llm_optimizer_builds_child_from_model_output_and_clamps():
    proposal = {
        "rationale": "defend more",
        "name": "turtle",
        "params": {**default_strategy().params, "defend_vs_heavy": 5.0, "rest_threshold": 30},
        "playbook": ["Block heavies.", "  ", "Punish rests."],
    }
    client = FakeClient([_response(proposal)])
    opt = LLMOptimizer(client, "rules", model="claude-opus-5", effort="high")
    child = opt.propose(default_strategy(), _evaluation(), [_evaluation()], [], exploration=0.1)
    assert child.version == 1 and child.parent_version == 0 and child.name == "turtle"
    assert child.params["defend_vs_heavy"] == 1.0 and child.params["rest_threshold"] == 30.0
    assert child.playbook == ["Block heavies.", "Punish rests."]
    assert child.notes.startswith("llm optimizer: defend more")
    _, kwargs = client.calls[0]
    assert kwargs["output_config"]["effort"] == "high"
    assert "unguarded_heavy" in kwargs["messages"][0]["content"]


def test_llm_optimizer_falls_back_to_rules_on_refusal():
    client = FakeClient([_response(stop_reason="refusal")])
    opt = LLMOptimizer(client, "rules", model="claude-opus-5")
    strat = default_strategy()
    child = opt.propose(strat, _evaluation(), [], [], exploration=0.0)
    assert child.version == 1 and child.notes.startswith("rule optimizer")
    assert child.params["defend_vs_heavy"] > strat.params["defend_vs_heavy"]
