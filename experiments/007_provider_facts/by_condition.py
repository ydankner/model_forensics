"""Does the backend effect depend on the prompt, or is it a flat offset?

If fp4 simply damped everything, the provider gap would be uniform across conditions.
If instead it only bites where the model has to decode and act on the grader, the gap
should appear in the explicit/verbal conditions and vanish in the implicit ones --
which would tie the quantisation effect to the specific computation of interest.

Free: reads the cache, makes no API calls.
Run: `uv run --with httpx --with python-dotenv python
      experiments/007_provider_facts/by_condition.py`
"""

import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS, DIGIT_CONDITIONS  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "005_stage1_digit"))
from digit import REPS, digit_mass, p_odd  # noqa: E402

MODEL = "qwen/qwen3.6-35b-a3b"
QUANT = {"AkashML": "fp8", "CoreWeave": "fp8", "Io Net": "fp8", "Parasail": "fp8",
         "Venice": "fp8", "Darkbloom": "fp4", "Phala": "unknown"}
MIN_N = 3


def main() -> None:
    specs = [
        Spec(model=MODEL, prompt=CONDITIONS[c].render("even"), condition=c, rep=i,
             reasoning=False, max_tokens=1, logprobs=True, top_logprobs=20)
        for c in DIGIT_CONDITIONS
        for i in range(REPS)
    ]
    results = run_sync(specs, concurrency=20)  # cached

    acc: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in results:
        got = None if r.error else digit_mass(r)
        if got is None:
            continue
        po, tot = p_odd(got[0])
        if tot > 0.5:
            acc[(r.spec.condition, r.provider or "?")].append(po)

    provs = sorted({p for _, p in acc}, key=lambda p: (QUANT.get(p, "z"), p))
    print(f"{MODEL}   (cells shown only where n >= {MIN_N})\n")
    print(f"{'condition':<24}" + "".join(f"{p[:9] + '/' + QUANT.get(p, '?')[:3]:>15}"
                                         for p in provs))
    print("-" * (24 + 15 * len(provs)))
    for c in DIGIT_CONDITIONS:
        row = f"{c:<24}"
        for p in provs:
            v = acc.get((c, p), [])
            row += f"{sum(v) / len(v):>12.1%}({len(v):>2}) "[:15] if len(v) >= MIN_N \
                else f"{'--':>15}"
        print(row)
    print("-" * (24 + 15 * len(provs)))
    print("If fp4 were a flat damper the gap would be constant down the column;\n"
          "if it is specific to decoding the grader, it appears only where the\n"
          "behaviour appears.")

    # The direct fp8-vs-fp4 contrast, condition by condition.
    print("\nAkashML (fp8) vs Darkbloom (fp4), where both have n >= 3:")
    for c in DIGIT_CONDITIONS:
        a, d = acc.get((c, "AkashML"), []), acc.get((c, "Darkbloom"), [])
        if len(a) >= MIN_N and len(d) >= MIN_N:
            ma, md = statistics.mean(a), statistics.mean(d)
            ratio = f"{ma / md:.1f}x" if md > 1e-6 else "n/a"
            print(f"  {c:<24} fp8 {ma:>6.1%}  fp4 {md:>6.1%}   ratio {ratio:>6}")


if __name__ == "__main__":
    main()
