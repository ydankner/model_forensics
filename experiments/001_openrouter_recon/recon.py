"""Ad-hoc: what does OpenRouter actually offer for the lens models?

Answers two questions before we commit to a sampling design:
  1. Which of the models with a fitted lens expose `logprobs` / `top_logprobs`?
     (If we can read token probabilities, parity can be measured with far fewer
     samples than counting sampled outputs.)
  2. What do they cost per token, so screen cost can be projected under both
     no-reasoning and reasoning-on assumptions rather than guessed.

No API key needed -- /api/v1/models is public.
Run: `uv run --with httpx python experiments/001_openrouter_recon/recon.py`
"""

import httpx

# HF lens dir -> OpenRouter slug. qwen3.5-4b is absent from OpenRouter entirely.
LENS_MODELS = {
    "qwen3.5-4b": None,
    "qwen3.5-9b": "qwen/qwen3.5-9b",
    "qwen3.5-27b": "qwen/qwen3.5-27b",
    "qwen3.6-27b": "qwen/qwen3.6-27b",
    "qwen3.5-122b-a10b": "qwen/qwen3.5-122b-a10b",
    "qwen3.6-35b-a3b": "qwen/qwen3.6-35b-a3b",
    "gemma-3-27b-it": "google/gemma-3-27b-it",
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
}

# Screen shape: samples per cell, and per-call token counts under two regimes.
N = 100
PROMPT_TOKENS = 60
OUT_NO_COT = 8
OUT_COT = 1200  # rough reasoning-on budget for "pick a number" tasks

# The single-token logprob channel: constrain the answer to one digit (0-9), so
# parity is fully determined by one token and `top_logprobs` gives P(odd) exactly.
# One call per cell instead of N -- but only with reasoning OFF (see below).
N_LOGPROB = 1
OUT_LOGPROB = 1
N_CONDITIONS = 17


def main() -> None:
    data = httpx.get("https://openrouter.ai/api/v1/models", timeout=60).json()["data"]
    by_id = {m["id"]: m for m in data}

    print(f"{'lens model':<20} {'logprobs':<10} {'reasoning':<10} "
          f"{'$/Mtok in':>10} {'$/Mtok out':>11} {'no-CoT':>8} {'CoT':>8}")
    print("-" * 82)

    totals = [0.0, 0.0]
    for lens, slug in LENS_MODELS.items():
        if slug is None or slug not in by_id:
            print(f"{lens:<20} {'-- not served on OpenRouter --'}")
            continue
        m = by_id[slug]
        params = set(m.get("supported_parameters", []))
        pin = float(m["pricing"]["prompt"]) * 1e6
        pout = float(m["pricing"]["completion"]) * 1e6

        def cost(out_tokens: int) -> float:
            return N * (PROMPT_TOKENS * pin + out_tokens * pout) / 1e6

        c_plain, c_cot = cost(OUT_NO_COT), cost(OUT_COT)
        totals[0] += c_plain
        totals[1] += c_cot
        print(f"{lens:<20} "
              f"{('yes' if 'logprobs' in params else 'no'):<10} "
              f"{('yes' if 'reasoning' in params else 'no'):<10} "
              f"{pin:>10.3f} {pout:>11.3f} {c_plain:>8.3f} {c_cot:>8.3f}")

    print("-" * 82)
    print(f"{'TOTAL per 100-sample cell, all served models':<54}"
          f"{totals[0]:>16.2f} {totals[1]:>8.2f}  (USD)")

    # Single-token logprob channel, priced across the whole design.
    lp = sum(
        N_LOGPROB * (PROMPT_TOKENS * float(by_id[s]["pricing"]["prompt"])
                     + OUT_LOGPROB * float(by_id[s]["pricing"]["completion"]))
        for s in LENS_MODELS.values() if s in by_id
    )
    print(f"\nsingle-token logprob channel: ${lp:.6f} per condition (all 7 models), "
          f"${lp * N_CONDITIONS:.5f} for all {N_CONDITIONS} conditions")
    print(f"  ...at 20 repeats/cell to check provider determinism: "
          f"${lp * N_CONDITIONS * 20:.4f}")
    print("\ntop_logprobs supported by: ", ", ".join(
        sorted(lens for lens, s in LENS_MODELS.items()
               if s in by_id and "top_logprobs" in set(by_id[s].get("supported_parameters", [])))
    ) or "(none)")


if __name__ == "__main__":
    main()
