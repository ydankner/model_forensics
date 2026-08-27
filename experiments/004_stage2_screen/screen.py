"""Stage 2: grader-siding rate on the canonical prompt, per model.

Stage 0 found zero siding in 33 reasoning-on rollouts. The leading suspect is that
extended reasoning is what suppresses the hack -- the same axis that dominated the
refusal result in Singh et al. Reasoning-off costs ~$0.01 for the whole screen, so
it runs first; reasoning-on is ~$1.51 and only worth paying for once we know whether
the effect exists anywhere.

Usage:
  python screen.py off        # ~$0.01
  python screen.py on         # ~$1.51
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.parse import grader_sided, parse  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402
from oddnum.stats import wilson  # noqa: E402

MODELS = [
    "qwen/qwen3.5-9b",
    "qwen/qwen3.5-27b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3.6-35b-a3b",
    "deepseek/deepseek-v4-flash",
]
CONDITION = "conflict"
N = 100


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "off"
    reasoning = {"on": True, "off": False}[mode]
    cond = CONDITIONS[CONDITION]
    prompt, pays = cond.render("even"), cond.pays("even")

    specs = [
        Spec(model=m, prompt=prompt, condition=CONDITION, rep=i, reasoning=reasoning,
             max_tokens=16000 if reasoning else 64)
        for m in MODELS
        for i in range(N)
    ]
    print(f"reasoning={mode}  n={N}  models={len(MODELS)}  calls={len(specs)}")
    print(f"prompt:\n{prompt}\ngrader pays: {pays}\n")
    results = run_sync(specs, concurrency=12)

    print(f"{'model':<30} {'ok':>7} {'sided':>6} {'rate':>7} {'95% CI':>16} {'top answers'}")
    print("-" * 100)
    for m in MODELS:
        rs = [r for r in results if r.spec.model == m]
        errs = [r for r in rs if r.error]
        answers = [parse(r.text) for r in rs if not r.error]
        scored = [grader_sided(a, pays) for a in answers if a.ok]
        n, k = len(scored), sum(1 for s in scored if s)
        lo, hi = wilson(k, n)
        counts: dict[int, int] = {}
        for a in answers:
            if a.ok:
                counts[a.value] = counts.get(a.value, 0) + 1
        top = ", ".join(f"{v}x{c}" for v, c in
                        sorted(counts.items(), key=lambda kv: -kv[1])[:5])
        flag = f"  [{len(errs)} err]" if errs else ""
        print(f"{m:<30} {n:>3}/{len(rs):<3} {k:>6} {k / n if n else 0:>7.1%} "
              f"[{lo:>5.1%},{hi:>6.1%}] {top}{flag}")
    print("-" * 100)
    print("`sided` = answered the parity the grader pays, i.e. defied the user's request.")


if __name__ == "__main__":
    main()
