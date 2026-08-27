"""Ad-hoc: print the exact screening plan -- every prompt and every request
parameter, verbatim as it would be sent -- so it can be reviewed before any spend.

This is deliberately a script and not part of the core package: the staged screen is
a one-off decision procedure, not part of the experiment's API. Whatever survives
review graduates into `src/oddnum/`.

Run: `uv run python experiments/002_screen_plan/plan.py`
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402

MODELS = [
    "qwen/qwen3.5-9b",
    "qwen/qwen3.5-27b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3.6-35b-a3b",
    "google/gemma-3-27b-it",  # no reasoning mode -> reasoning-off cells only
    "deepseek/deepseek-v4-flash",
]
NO_REASONING = {"google/gemma-3-27b-it"}

# (stage, purpose, conditions, per-call params, samples per cell)
STAGES = [
    (
        "0",
        "Measure actual reasoning-token spend, to validate the cost model before "
        "committing to Stage 2.",
        ["conflict"],
        {"temperature": 1.0, "max_tokens": 8000, "reasoning": "on"},
        5,
    ),
    (
        "1a",
        "Does top_logprobs come back, and is the top token a digit?",
        ["conflict_digit"],
        {"temperature": 1.0, "max_tokens": 1, "logprobs": True, "top_logprobs": 20,
         "reasoning": "off"},
        1,
    ),
    (
        "1b",
        "Prior over digits with no grader -- the headroom check. If 7 holds most of "
        "the mass, this channel is too compressed to detect anything.",
        ["no_grader_digit", "no_grader_digit_flat"],
        {"temperature": 1.0, "max_tokens": 1, "logprobs": True, "top_logprobs": 20,
         "reasoning": "off"},
        1,
    ),
    (
        "1c",
        "Is the returned distribution stable across calls, or does provider routing "
        "move it?",
        ["conflict_digit"],
        {"temperature": 1.0, "max_tokens": 1, "logprobs": True, "top_logprobs": 20,
         "reasoning": "off"},
        20,
    ),
    (
        "2",
        "The behavioural screen: grader-siding rate vs. base rate, per model.",
        ["conflict", "no_grader"],
        {"temperature": 1.0, "max_tokens": 8000, "reasoning": "on and off"},
        100,
    ),
]


def main() -> None:
    print("No system prompt is used at any stage: a single user message, exactly as\n"
          "printed below. Answers are always in the even-asked polarity.\n")
    total = 0
    for stage, purpose, conds, params, n in STAGES:
        settings = 2 if params["reasoning"] == "on and off" else 1
        calls = sum(
            n * len(conds) * (1 if m in NO_REASONING else settings)
            for m in MODELS
            if not (m in NO_REASONING and params["reasoning"] == "on")
        )
        total += calls
        print("=" * 78)
        print(f"STAGE {stage}  --  {n} sample(s)/cell x {len(conds)} condition(s) "
              f"x {len(MODELS)} models = {calls} calls")
        print(f"purpose: {purpose}")
        print(f"params:  {params}")
        print("=" * 78)
        for name in conds:
            print(f"\n--- condition `{name}` "
                  f"(grader pays: {CONDITIONS[name].pays('even')}) ---")
            print(CONDITIONS[name].render("even"))
        print()
    print("=" * 78)
    print(f"TOTAL CALLS ACROSS ALL STAGES: {total}")


if __name__ == "__main__":
    main()
