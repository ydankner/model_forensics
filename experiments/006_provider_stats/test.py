"""Is the between-provider difference in P(odd) statistically real?

The claim under test: within a (condition, model) cell, which backend OpenRouter
routed to explains the variation in P(odd). Three things are computed per cell:

* Kruskal-Wallis H -- rank-based, so it does not assume normality. But it leans on
  asymptotics that are shaky with groups of n=1..3, so it is not relied on alone.
* A permutation F-test -- shuffles provider labels within the cell and recomputes F.
  Distribution-free and exact up to Monte-Carlo error, which is what small groups
  need.
* eta^2, the share of total variance attributable to provider. With near-zero
  within-provider variance any test will return a tiny p, so the effect size is the
  more honest number to report.

CONFOUND, stated up front: provider was assigned by OpenRouter's router, not by us.
If routing drifted over time, a time effect would masquerade as a provider effect.
The interleaving check at the bottom tests whether providers are mixed through the
call sequence or arrive in blocks.

Free: reads the cache, makes no API calls.
Run: `uv run --with httpx --with python-dotenv --with scipy python
      experiments/006_provider_stats/test.py`
"""

import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.sample import CACHE_PATH, Spec, run_sync  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "005_stage1_digit"))
from digit import MODELS, REPS, digit_mass, p_odd  # noqa: E402

CELLS = ["digit_explicit", "digit_verbal", "digit_third_party", "conflict_digit"]
N_PERM = 20000
RNG = np.random.default_rng(0)


def f_stat(groups: list[np.ndarray]) -> float:
    """One-way F. Returns 0 when there is no within-group variance to divide by."""
    grand = np.concatenate(groups)
    k, n = len(groups), len(grand)
    ss_b = sum(len(g) * (g.mean() - grand.mean()) ** 2 for g in groups)
    ss_w = sum(((g - g.mean()) ** 2).sum() for g in groups)
    if ss_w <= 0:
        return float("inf") if ss_b > 0 else 0.0
    return (ss_b / (k - 1)) / (ss_w / (n - k))


def eta_sq(groups: list[np.ndarray]) -> float:
    grand = np.concatenate(groups)
    ss_b = sum(len(g) * (g.mean() - grand.mean()) ** 2 for g in groups)
    ss_t = ((grand - grand.mean()) ** 2).sum()
    return ss_b / ss_t if ss_t > 0 else 0.0


def perm_p(groups: list[np.ndarray]) -> float:
    """Permutation p-value for the one-way F, shuffling group labels."""
    obs = f_stat(groups)
    if obs == 0.0:
        return 1.0
    sizes = [len(g) for g in groups]
    pool = np.concatenate(groups)
    hits = 0
    for _ in range(N_PERM):
        RNG.shuffle(pool)
        idx, perm = 0, []
        for s in sizes:
            perm.append(pool[idx:idx + s])
            idx += s
        if f_stat(perm) >= obs:
            hits += 1
    return (1 + hits) / (1 + N_PERM)


def main() -> None:
    specs = [
        Spec(model=m, prompt=CONDITIONS[c].render("even"), condition=c, rep=i,
             reasoning=False, max_tokens=1, logprobs=True, top_logprobs=20)
        for m in MODELS
        for c in CELLS
        for i in range(REPS)
    ]
    results = run_sync(specs, concurrency=20)  # cached

    grouped: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for r in results:
        got = None if r.error else digit_mass(r)
        if got is None:
            continue
        po, tot = p_odd(got[0])
        if tot > 0.5:
            grouped[(r.spec.condition, r.spec.model)][r.provider or "?"].append(po)

    print(f"{'condition':<20} {'model':<20} {'k':>3} {'n':>4} {'range of means':>18} "
          f"{'eta^2':>7} {'KW p':>10} {'perm p':>9}")
    print("-" * 100)
    for (cond, model), byprov in sorted(grouped.items()):
        usable = {p: v for p, v in byprov.items() if len(v) >= 2}
        if len(usable) < 2:
            continue
        groups = [np.array(v) for v in usable.values()]
        means = [g.mean() for g in groups]
        try:
            kw = stats.kruskal(*groups).pvalue
        except ValueError:
            kw = float("nan")
        print(f"{cond:<20} {model.split('/')[-1]:<20} {len(groups):>3} "
              f"{sum(len(g) for g in groups):>4} "
              f"{min(means):>8.1%} -{max(means):>7.1%} "
              f"{eta_sq(groups):>7.2f} {kw:>10.2e} {perm_p(groups):>9.4f}")

    # --- confound check: are providers interleaved in time, or blocked? --------
    print("\n--- routing over time (are provider labels blocked?) ---")
    con = sqlite3.connect(CACHE_PATH)
    for cond, model in [("digit_explicit", "qwen/qwen3.6-35b-a3b")]:
        rows = []
        for i in range(REPS):
            s = Spec(model=model, prompt=CONDITIONS[cond].render("even"),
                     condition=cond, rep=i, reasoning=False, max_tokens=1,
                     logprobs=True, top_logprobs=20)
            row = con.execute("SELECT response, ts FROM responses WHERE key=?",
                              (s.key(),)).fetchone()
            if row:
                import json
                rows.append((row[1], json.loads(row[0]).get("provider", "?")))
        rows.sort()
        seq = [p for _, p in rows]
        runs = 1 + sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        print(f"{cond} / {model.split('/')[-1]}: {len(seq)} calls, "
              f"{len(set(seq))} providers, {runs} runs")
        print("  order:", " ".join(p[:4] for p in seq))
        print(f"  (a low run count means providers arrived in blocks -> time is "
              f"confounded with provider; {runs} runs out of {len(seq)} calls)")
        print(f"  span: {max(t for t, _ in rows) - min(t for t, _ in rows):.1f} s")


if __name__ == "__main__":
    main()
