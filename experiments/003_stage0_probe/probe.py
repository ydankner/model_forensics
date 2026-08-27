"""Stage 0: how many reasoning tokens do these models actually spend?

Every cost projection for the behavioural screen rests on an assumed ~1200 output
tokens per reasoning-on call. This measures the real number on 5 samples per model
before committing to 2,600 calls. Also the first live test of the client, so it
doubles as a smoke test of auth, routing and the `require_parameters` guard.

Run: `uv run --with httpx --with python-dotenv python experiments/003_stage0_probe/probe.py`
"""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402

MODELS = [
    "qwen/qwen3.5-9b",
    "qwen/qwen3.5-27b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3.6-35b-a3b",
    "google/gemma-3-27b-it",  # no reasoning mode
    "deepseek/deepseek-v4-flash",
]
NO_REASONING = {"google/gemma-3-27b-it"}
N = 5

PRICES: dict[str, tuple[float, float]] = {}  # filled from the recon numbers below
# $/Mtok (prompt, completion), from experiments/001_openrouter_recon
PRICES = {
    "qwen/qwen3.5-9b": (0.100, 0.150),
    "qwen/qwen3.5-27b": (0.195, 1.560),
    "qwen/qwen3.6-27b": (0.320, 3.200),
    "qwen/qwen3.5-122b-a10b": (0.260, 2.080),
    "qwen/qwen3.6-35b-a3b": (0.140, 1.000),
    "google/gemma-3-27b-it": (0.080, 0.450),
    "deepseek/deepseek-v4-flash": (0.057, 0.115),
}


def main() -> None:
    prompt = CONDITIONS["conflict"].render("even")
    specs = [
        Spec(model=m, prompt=prompt, condition="conflict", rep=i,
             reasoning=None if m in NO_REASONING else True)
        for m in MODELS
        for i in range(N)
    ]
    print(f"{len(specs)} calls\nprompt:\n{prompt}\n")
    results = run_sync(specs)

    print(f"{'model':<30} {'ok':>3} {'out tok':>9} {'reason tok':>11} "
          f"{'trunc':>6} {'provider':<22} {'$/100 samples':>14}")
    print("-" * 104)
    projected = 0.0
    for m in MODELS:
        rs = [r for r in results if r.spec.model == m]
        ok = [r for r in rs if not r.error]
        if not ok:
            print(f"{m:<30} {0:>3}  ERROR: {rs[0].error[:60]}")
            continue
        out = [r.usage.get("completion_tokens", 0) for r in ok]
        rea = [r.reasoning_tokens for r in ok]
        trunc = sum(r.finish_reason == "length" for r in ok)
        pin, pout = PRICES[m]
        prompt_tok = statistics.mean(r.usage.get("prompt_tokens", 0) for r in ok)
        cost100 = 100 * (prompt_tok * pin + statistics.mean(out) * pout) / 1e6
        projected += cost100
        print(f"{m:<30} {len(ok):>3} {statistics.mean(out):>9.0f} "
              f"{statistics.mean(rea):>11.0f} {trunc:>6} {ok[0].provider[:20]:<22} "
              f"{cost100:>14.3f}")
    print("-" * 104)
    print(f"projected cost of ONE 100-sample condition across all models: ${projected:.2f}")
    print(f"Stage 2 as scoped (conflict only, reasoning on+off): ~${projected:.2f} + ~$0.01")

    print("\n--- sample outputs (first rollout per model) ---")
    for m in MODELS:
        ok = [r for r in results if r.spec.model == m and not r.error]
        if ok:
            print(f"\n[{m}] finish={ok[0].finish_reason!r} -> {ok[0].text[:200]!r}")


if __name__ == "__main__":
    main()
