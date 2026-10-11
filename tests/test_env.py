from banana_fighter.game_env import ACTIONS, BananaBrawlEnv


def test_reset_is_deterministic():
    a, b = BananaBrawlEnv(), BananaBrawlEnv()
    oa, ob = a.reset(3), b.reset(3)
    assert oa.state == ob.state
    for action in ["advance", "advance", "light", "block", "heavy"]:
        ra, rb = a.step(action), b.step(action)
        assert ra.info == rb.info and ra.observation.state == rb.observation.state


def test_personality_rotates_with_seed():
    env = BananaBrawlEnv()
    assert {env.reset(s).state["enemy_personality"] for s in range(3)} == {"aggressive", "defensive", "trickster"}


def test_whiff_and_stumble_are_reported():
    env = BananaBrawlEnv()
    env.reset(0)  # starts far away
    res = env.step("light")
    assert res.info["player_result"] == "whiff"
    env.s["player_stamina"] = 5
    res = env.step("heavy")
    assert res.info["player_result"] == "stumble"


def test_episode_terminates():
    env = BananaBrawlEnv(max_turns=15)
    env.reset(1)
    for _ in range(15):
        res = env.step("block")
        if res.done:
            break
    assert res.done and res.info["outcome"] in {"win", "loss", "timeout"}


def test_unknown_action_rejected():
    env = BananaBrawlEnv()
    env.reset(0)
    try:
        env.step("fly")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_all_actions_legal():
    env = BananaBrawlEnv()
    assert env.reset(0).legal_actions == ACTIONS
