"""Why did every pinned qwen3.5-9b call fail?

Hypothesis: `require_parameters: True` plus `allow_fallbacks: False` is
unsatisfiable for deepinfra/bf16 because that endpoint does not support logprobs.
Evidence for it: in the unpinned sweep, qwen3.5-9b was only ever served by Parasail
and Venice -- never DeepInfra, despite DeepInfra being the cheapest endpoint. That is
what `require_parameters` filtering looks like from the outside.

Tests each candidate 9b endpoint with one call and prints the raw error.

Run: `uv run --with httpx --with python-dotenv python experiments/008_pinned/diagnose.py`
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402

MODEL = "qwen/qwen3.5-9b"
TAGS = ["deepinfra/bf16", "parasail/bf16", "venice/fp8", "siliconflow/fp8"]


def main() -> None:
    prompt = CONDITIONS["digit_explicit"].render("even")
    # With logprobs (what Run A asked for) and without, to isolate the cause.
    specs = [
        Spec(model=MODEL, prompt=prompt, condition="digit_explicit", rep=rep,
             reasoning=False, max_tokens=1, logprobs=lp, top_logprobs=20 if lp else None,
             provider_tag=tag)
        for tag in TAGS
        for lp, rep in ((True, 0), (False, 1))
    ]
    for r in run_sync(specs, concurrency=4):
        lp = "logprobs" if r.spec.logprobs else "plain   "
        if r.error:
            print(f"{r.spec.provider_tag:<18} {lp}  ERROR {r.error[:110]}")
        else:
            got = r.logprobs is not None
            print(f"{r.spec.provider_tag:<18} {lp}  ok, served by {r.provider!r}, "
                  f"text={r.text!r}, logprobs_returned={got}")


if __name__ == "__main__":
    main()
