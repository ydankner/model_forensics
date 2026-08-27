"""Is the rep-to-rep spread provider routing, or the model itself?

Several cells in the n=50 sweep have very large spread (sd up to 23pp) while others
are pinned at sd=0.0. OpenRouter routes to third-party backends that differ in
quantisation and serving stack, so the obvious suspect is that a "model" here is
really a mixture over backends. If the variance is between providers rather than
within them, every number in the sweep is a weighted average over an uncontrolled
variable, and provider has to be pinned before any of it is reportable.

Free: reads the cache, makes no API calls.
Run: `uv run --with httpx --with python-dotenv python experiments/005_stage1_digit/providers.py`
"""

import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402

from digit import MODELS, REPS, digit_mass, p_odd  # noqa: E402

# The cells with the largest spread, plus a pinned-at-zero control.
CELLS = ["digit_explicit", "digit_verbal", "digit_third_party", "conflict_digit"]


def main() -> None:
    specs = [
        Spec(model=m, prompt=CONDITIONS[c].render("even"), condition=c, rep=i,
             reasoning=False, max_tokens=1, logprobs=True, top_logprobs=20)
        for m in MODELS
        for c in CELLS
        for i in range(REPS)
    ]
    results = run_sync(specs, concurrency=20)  # all cached

    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for r in results:
        got = None if r.error else digit_mass(r)
        if got is None:
            continue
        po, tot = p_odd(got[0])
        if tot > 0.5:
            grouped[(r.spec.condition, r.spec.model, r.provider or "?")].append(po)

    print(f"{'condition':<20} {'model':<26} {'provider':<16} {'n':>4} "
          f"{'mean P(odd)':>12} {'sd':>7}")
    print("-" * 92)
    for cell in CELLS:
        keys = sorted(k for k in grouped if k[0] == cell)
        for c, m, prov in keys:
            v = grouped[(c, m, prov)]
            sd = statistics.stdev(v) if len(v) > 1 else 0.0
            print(f"{c:<20} {m.split('/')[-1]:<26} {prov:<16} {len(v):>4} "
                  f"{sum(v) / len(v):>12.1%} {sd:>7.1%}")
        print()


if __name__ == "__main__":
    main()
