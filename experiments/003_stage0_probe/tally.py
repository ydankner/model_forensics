"""Stage 0, second look: what parity did the probe rollouts actually answer with?

Free -- reads the cache written by probe.py, makes no API calls. Five samples per
model is far too few to conclude anything, but it tells us whether the phenomenon is
even in the right ballpark before spending on a 100-sample screen.

Run: `uv run --with httpx --with python-dotenv python experiments/003_stage0_probe/tally.py`
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.parse import grader_sided, parse  # noqa: E402
from oddnum.sample import Spec, run_sync  # noqa: E402

from probe import MODELS, N, NO_REASONING  # noqa: E402


def main() -> None:
    cond = CONDITIONS["conflict"]
    prompt = cond.render("even")
    pays = cond.pays("even")
    specs = [
        Spec(model=m, prompt=prompt, condition="conflict", rep=i,
             reasoning=None if m in NO_REASONING else True)
        for m in MODELS
        for i in range(N)
    ]
    results = run_sync(specs)  # all cached; no spend

    print(f"user asked: even     grader pays: {pays}\n")
    print(f"{'model':<30} {'parsed':>7} {'sided':>6} {'answers'}")
    print("-" * 88)
    for m in MODELS:
        rs = [r for r in results if r.spec.model == m and not r.error]
        answers = [parse(r.text) for r in rs]
        sided = [grader_sided(a, pays) for a in answers]
        n_ok = sum(a.ok for a in answers)
        n_sided = sum(1 for s in sided if s)
        shown = ", ".join(
            f"{a.value}" if a.ok else f"<{a.status}>" for a in answers
        )
        print(f"{m:<30} {n_ok:>3}/{len(rs):<3} {n_sided:>6} {shown}")
    print("-" * 88)
    print("`sided` = answered with the parity the grader pays (i.e. defied the user).")


if __name__ == "__main__":
    main()
