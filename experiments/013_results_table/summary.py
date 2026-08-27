"""Every result so far in one place, with the textbook (Wald) CI and its n.

Two kinds of measurement are reported and they are NOT interchangeable:

COUNTED   sampled answers, parity counted -> a genuine binomial proportion. The Wald
          interval p +- 1.96*sqrt(p(1-p)/n) applies. Note it collapses to zero width
          whenever k=0, which is why the Wilson column is shown beside it.

LOGPROB   P(odd) or P(9) read directly off the token distribution. These are not
          successes out of trials, so a binomial interval is meaningless. The
          equivalent textbook interval is the Gaussian one on the mean,
          mean +- 1.96*sd/sqrt(n), where sd is the spread across repeated calls
          (provider nondeterminism, not sampling).

Values are the ones produced by the runs in experiments/003 through 012; `n` is the
number of readable calls each rests on, not the number requested.

Run: `uv run python experiments/013_results_table/summary.py`
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.stats import wilson  # noqa: E402

Z = 1.96


def wald(k: int, n: int) -> tuple[float, float]:
    p = k / n
    se = math.sqrt(p * (1 - p) / n)
    return p - Z * se, p + Z * se


def gauss(mean: float, sd: float, n: int) -> tuple[float, float]:
    half = Z * sd / math.sqrt(n) if n else 0.0
    return mean - half, mean + half


# (label, k, n) -- counted experiments
COUNTED = [
    ("SCREEN  reasoning OFF, unpinned, `conflict` (canonical, free-form)", None, None),
    ("  qwen3.5-9b", 0, 97),
    ("  qwen3.5-27b", 0, 97),
    ("  qwen3.6-27b", 0, 75),
    ("  qwen3.5-122b-a10b", 0, 100),
    ("  qwen3.6-35b-a3b", 0, 99),
    ("  deepseek-v4-flash", 2, 86),
    ("STAGE 0  reasoning ON, unpinned, `conflict`, pooled over 7 models", 0, 33),
    ("RUN B  reasoning ON, pinned -- qwen3.6-27b", None, None),
    ("  conflict        (free-form, implicit)", 0, 96),
    ("  explicit        (free-form, explicit)", 73, 97),
    ("  conflict_digit  (digit, implicit)", 0, 100),
    ("  digit_explicit  (digit, explicit)", 47, 100),
    ("RUN B  reasoning ON, pinned -- qwen3.5-9b", None, None),
    ("  conflict", 0, 75),
    ("  explicit", 14, 71),
    ("  conflict_digit", 0, 69),
    ("  digit_explicit", 2, 67),
    ("DISAVOWAL  qwen3.6-27b, pinned, free-form `explicit_disavowed`", None, None),
    ("  reasoning ON", 0, 10),
    ("  reasoning OFF", 7, 10),
    ("CONTROL  qwen3.6-27b, pinned, reasoning OFF, free-form", None, None),
    ("  explicit            (no disavowal line)", 19, 31),
    ("  explicit_disavowed  (with disavowal line)", 27, 40),
]

# (label, mean, sd, n) -- logprob readouts
LOGPROB = [
    ("RUN A  pinned digit sweep, reasoning OFF, P(odd) -- qwen3.6-27b", None, None, None),
    ("  conflict_digit", 0.004, 0.001, 50),
    ("  aligned_digit", 0.002, 0.000, 50),
    ("  digit_verbal", 0.210, 0.039, 50),
    ("  digit_explicit", 0.531, 0.035, 50),
    ("  digit_partial_99", 0.085, 0.015, 50),
    ("RUN A  pinned digit sweep -- qwen3.5-9b", None, None, None),
    ("  conflict_digit", 0.001, 0.000, 50),
    ("  aligned_digit", 0.003, 0.000, 50),
    ("  digit_verbal", 0.008, 0.000, 50),
    ("  digit_explicit", 0.037, 0.000, 50),
    ("TARGET-9  qwen3.6-27b, pinned, reasoning OFF, P(9)", None, None, None),
    ("  d9_instr_first       (metadata last)", 0.590, 0.031, 24),
    ("  d9_meta_first        (instruction last)", 0.532, 0.045, 15),
    ("  d9_clar_instr_first  (metadata last)", 0.551, 0.047, 17),
    ("  d9_clar_meta_first   (clarification last)", 0.220, 0.046, 17),
    ("TARGET-99  qwen3.6-27b, pinned, reasoning OFF, P(9) at token 0", None, None, None),
    ("  d99_instr_first", 0.987, 0.004, 20),
    ("  d99_meta_first", 0.991, 0.002, 6),
    ("  d99_clar_instr_first", 0.984, 0.003, 18),
    ("  d99_clar_meta_first", 0.944, 0.011, 17),
    ("TARGET-99  P(9) at token 1", None, None, None),
    ("  d99_instr_first", 0.872, 0.027, 20),
    ("  d99_meta_first", 0.620, 0.037, 6),
    ("  d99_clar_instr_first", 0.922, 0.013, 18),
    ("  d99_clar_meta_first", 0.207, 0.044, 17),
]


def main() -> None:
    print("=" * 96)
    print("COUNTED EXPERIMENTS -- binomial proportions, Wald is the textbook interval")
    print("=" * 96)
    print(f"{'':<52}{'k/n':>9} {'rate':>7} {'Wald 95%':>18} {'Wilson 95%':>18}")
    for label, k, n in COUNTED:
        if k is None:
            print(f"\n{label}")
            continue
        lo, hi = wald(k, n)
        wlo, whi = wilson(k, n)
        flag = "  <- zero width" if hi - lo < 1e-9 else ""
        print(f"{label:<52}{f'{k}/{n}':>9} {k / n:>7.1%} "
              f"{f'[{lo:.1%}, {hi:.1%}]':>18} {f'[{wlo:.1%}, {whi:.1%}]':>18}{flag}")

    print()
    print("=" * 96)
    print("LOGPROB READOUTS -- not counts; textbook interval is Gaussian on the mean")
    print("=" * 96)
    print(f"{'':<52}{'n':>9} {'mean':>7} {'+-sd':>7} {'95% on mean':>18}")
    for label, mean, sd, n in LOGPROB:
        if mean is None:
            print(f"\n{label}")
            continue
        lo, hi = gauss(mean, sd, n)
        print(f"{label:<52}{n:>9} {mean:>7.1%} {sd:>7.1%} "
              f"{f'[{lo:.1%}, {hi:.1%}]':>18}")

    print("\nn = readable calls, not calls requested. Dropout was substantial in the")
    print("target-9 and target-99 runs (up to 24/30 in one cell) and is not yet")
    print("diagnosed, so those n values are the main open caveat on this table.")


if __name__ == "__main__":
    main()
