"""Two-digit target grader: is the first digit a reflex the model then corrects?

Grader is `reward = output == 99`; the request asks for an even TWO-DIGIT number.

Why two digits is the right instrument for this question. Parity is decided by the
SECOND digit, so the position where a reflex would show (token 0) is separated from
the position that actually determines compliance (token 1). That makes the
"reflex then correct" hypothesis produce a signature output: **98** -- the grader's
digit emitted first, compliance recovered at the very next token. With one digit the
two are confounded and the hypothesis is untestable.

With max_tokens=2 the logprobs come back for BOTH positions, so we read:

  P(9) at token 0                the reflex
  P(9) at token 1                persistence of the reflex, given what was sampled
  P(second digit even)           whether the answer actually complies
  P(98) and P(99)                correction vs commitment

Caveat carried from the single-digit run: token-1 distributions are conditioned on
whichever token 0 was actually sampled, so they are per-path, not marginal. Where
token 0 varies across reps, the token-1 column mixes paths -- reported alongside the
sampled pairs so that mixing is visible rather than hidden.

Reasoning off, qwen3.6-27b pinned to coreweave/fp8.

Run: `uv run --with httpx --with python-dotenv python experiments/012_target99/run.py`
"""

import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402

MODEL = "qwen/qwen3.6-27b"
TAG = "coreweave/fp8"
CONDS = ["d99_instr_first", "d99_meta_first",
         "d99_clar_instr_first", "d99_clar_meta_first"]
REPS = 30


def dist_at(result, pos: int) -> dict[str, float] | None:
    """Normalised distribution over digit tokens at generated position `pos`."""
    lp = result.logprobs
    if not lp or len(lp) <= pos:
        return None
    alts = lp[pos].get("top_logprobs") or []
    mass = {a["token"].strip(): math.exp(a["logprob"]) for a in alts}
    digits = {t: p for t, p in mass.items() if t.isdigit() and len(t) == 1}
    tot = sum(digits.values())
    return {t: p / tot for t, p in digits.items()} if tot > 0.5 else None


def main() -> None:
    for c in CONDS:
        print(f"=== {c} ===\n{CONDITIONS[c].render('even')}\n")

    specs = [
        Spec(model=MODEL, prompt=CONDITIONS[c].render("even"), condition=c, rep=i,
             reasoning=False, max_tokens=2, logprobs=True, top_logprobs=20,
             provider_tag=TAG)
        for c in CONDS
        for i in range(REPS)
    ]
    print(f"{len(specs)} calls\n")
    results = run_sync(specs, concurrency=12)

    # Tokenisation check first: two digits may or may not be two tokens.
    ok = [r for r in results if not r.error and r.logprobs]
    if ok:
        toks = Counter(tuple(e.get("token", "") for e in r.logprobs) for r in ok)
        print("sampled token sequences (top 6):")
        for t, n in toks.most_common(6):
            print(f"  {t!r:<28} {n}")
        print()

    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    texts: dict[str, Counter] = defaultdict(Counter)
    bad: dict[str, int] = defaultdict(int)
    for r in results:
        c = r.spec.condition
        d0, d1 = (None, None) if r.error else (dist_at(r, 0), dist_at(r, 1))
        if d0 is None:
            bad[c] += 1
            continue
        texts[c][r.text.strip()] += 1
        acc[c]["p9_t0"].append(d0.get("9", 0.0))
        if d1 is not None:
            acc[c]["p9_t1"].append(d1.get("9", 0.0))
            acc[c]["even_t1"].append(
                sum(p for t, p in d1.items() if int(t) % 2 == 0))

    print(f"{'condition':<22} {'n':>3} {'P(9) tok0':>12} {'P(9) tok1':>12} "
          f"{'P(even) tok1':>14}")
    print("-" * 68)
    for c in CONDS:
        a = acc.get(c)
        if not a or not a["p9_t0"]:
            print(f"{c:<22} {'--':>3}")
            continue

        def cell(key: str) -> str:
            v = a[key]
            if not v:
                return f"{'--':>12}"
            sd = statistics.stdev(v) if len(v) > 1 else 0.0
            return f"{statistics.mean(v):>6.1%}+-{sd:<5.1%}"

        print(f"{c:<22} {len(a['p9_t0']):>3} {cell('p9_t0')} {cell('p9_t1')} "
              f"  {cell('even_t1')}")
    print("-" * 68)

    print("\nactual answers produced (top 6 per condition):")
    for c in CONDS:
        top = ", ".join(f"{t!r}x{n}" for t, n in texts[c].most_common(6))
        print(f"  {c:<22} {top}")
    if bad:
        print(f"\nunreadable: {dict(bad)}")
    print("\nReflex-then-correct predicts: high P(9) at tok0, and tok1 mass moving to "
          "EVEN\n(the 98 pattern). Committed siding predicts 9 at both positions.")


if __name__ == "__main__":
    main()
