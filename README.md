# 🍌 banana-fighter

To train a bot to play a game for you using recursive harnessing, I would recommend building a self-improving agent that repeatedly plays the game, evaluates its performance, identifies mistakes, modifies its strategy, and tries again.

The key idea is that you don't necessarily need to train a neural network from scratch. Instead, you can use an existing LLM or vision model as the decision-making engine, then build a recursive training harness around it.

## recommended architecture
```
game_bot/
├── main.py
├── game_env.py
├── agent.py
├── evaluator.py
├── recursive_harness.py
├── optimizer.py
├── memory/
│   ├── experiences.jsonl
│   └── best_strategy.json
├── checkpoints/
└── logs/
```
