"""Matched reasoning-off control for the disavowal test.

The disavowal arm gave 70% siding with reasoning off. To claim the disavowal line is
inert without reasoning, it has to be compared against the SAME prompt minus that one
line, in the same format (free-form) and the same reasoning setting. The 53.1% figure
on hand is the digit-constrained variant, which is not a valid comparison: the digit
constraint suppresses siding by ~28pp on its own.

n=50 per arm so the difference has a usable interval; reasoning-off free-form calls
are ~$0.01 for the pair.

Run: `uv run --with httpx --with python-dotenv python experiments/010_disavow/control.py`
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.parse import parse  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402
from oddnum.stats import diff_ci, wilson  # noqa: E402

MODEL = "qwen/qwen3.6-27b"
TAG = "coreweave/fp8"
ARMS = ["explicit", "explicit_disavowed"]
N = 50


def main() -> None:
    specs = [
        Spec(model=MODEL, prompt=CONDITIONS[c].render("even"), condition=c, rep=i,
             reasoning=False, max_tokens=64, provider_tag=TAG)
        for c in ARMS
        for i in range(N)
    ]
    print(f"reasoning OFF, free-form, n={N}/arm, {len(specs)} calls\n")
    results = run_sync(specs, concurrency=12)

    stats = {}
    print(f"{'arm':<20} {'ok':>7} {'sided':>6} {'rate':>7} {'95% CI':>16}  top answers")
    print("-" * 88)
    for c in ARMS:
        pays = CONDITIONS[c].pays("even")
        rs = [r for r in results if r.spec.condition == c]
        answers = [parse(r.text) for r in rs if not r.error]
        scored = [a for a in answers if a.ok]
        k = sum(1 for a in scored if a.parity == pays)
        n = len(scored)
        stats[c] = (k, n)
        lo, hi = wilson(k, n)
        counts: dict[int, int] = {}
        for a in scored:
            counts[a.value] = counts.get(a.value, 0) + 1
        top = ", ".join(f"{v}x{ct}" for v, ct in
                        sorted(counts.items(), key=lambda kv: -kv[1])[:5])
        print(f"{c:<20} {n:>3}/{len(rs):<3} {k:>6} {(k / n if n else 0):>7.1%} "
              f"[{lo:>5.1%},{hi:>6.1%}]  {top}")

    (k1, n1), (k2, n2) = stats[ARMS[0]], stats[ARMS[1]]
    lo, hi = diff_ci(k1, n1, k2, n2)
    print("-" * 88)
    print(f"effect of adding the disavowal line (no-disavowal minus disavowal): "
          f"{k1 / n1 - k2 / n2:+.1%}  95% CI [{lo:+.1%}, {hi:+.1%}]")
    print("An interval spanning 0 means the disavowal line is inert without reasoning.")


if __name__ == "__main__":
    main()
