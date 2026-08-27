"""The provider-variance cells, annotated with each backend's declared quantisation.

Joins two things that were previously reported separately: the per-provider P(odd)
breakdown from the unpinned sweep, and the quantisation each endpoint declares in
OpenRouter's endpoints API. The question is whether the between-backend spread lines
up with precision, or whether backends at the same precision also disagree -- the
latter would mean quantisation is not the explanation.

Reads only the UNPINNED sweep rows. The cache also holds pinned runs for some of
these (model, condition) pairs; mixing them in would double-count and change the
provider mixture, so keys are reconstructed with provider_tag=None and looked up
directly rather than querying by condition name.

No API calls to the model provider; the endpoints metadata request is public.
Run: `uv run --with httpx --with python-dotenv python
      experiments/007_provider_facts/by_quant.py`
"""

import json
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.sample import Spec  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "cache.db"
REPS = 50

# (condition, model) pairs from the provider-variance table.
CELLS = [
    ("digit_explicit", "qwen/qwen3.6-35b-a3b"),
    ("digit_verbal", "qwen/qwen3.6-35b-a3b"),
    ("digit_third_party", "deepseek/deepseek-v4-flash"),
    ("digit_verbal", "deepseek/deepseek-v4-flash"),
    ("digit_explicit", "qwen/qwen3.5-9b"),
    ("digit_third_party", "qwen/qwen3.6-35b-a3b"),
    ("conflict_digit", "qwen/qwen3.6-35b-a3b"),
]


def quant_map(slug: str) -> dict[str, str]:
    r = httpx.get(f"https://openrouter.ai/api/v1/models/{slug}/endpoints", timeout=60)
    eps = r.json().get("data", {}).get("endpoints", [])
    return {e.get("provider_name", "?"): str(e.get("quantization")) for e in eps}


def p_odd_from(body: dict) -> tuple[str, float] | None:
    ch = (body.get("choices") or [{}])[0]
    lp = (ch.get("logprobs") or {}).get("content")
    if not lp:
        return None
    alts = lp[0].get("top_logprobs") or []
    mass = {a["token"].strip(): math.exp(a["logprob"]) for a in alts}
    digits = {t: p for t, p in mass.items() if t.isdigit()}
    tot = sum(digits.values())
    if tot <= 0.5:
        return None
    odd = sum(p for t, p in digits.items() if int(t) % 2 == 1)
    return body.get("provider", "?"), odd / tot


def eta_sq(groups: list[list[float]]) -> float:
    flat = [x for g in groups for x in g]
    grand = statistics.mean(flat)
    ss_b = sum(len(g) * (statistics.mean(g) - grand) ** 2 for g in groups)
    ss_t = sum((x - grand) ** 2 for x in flat)
    return ss_b / ss_t if ss_t > 0 else 0.0


def main() -> None:
    con = sqlite3.connect(CACHE_PATH)
    quants = {m: quant_map(m) for m in {m for _, m in CELLS}}

    for cond, model in CELLS:
        by_prov: dict[str, list[float]] = defaultdict(list)
        for i in range(REPS):
            spec = Spec(model=model, prompt=CONDITIONS[cond].render("even"),
                        condition=cond, rep=i, reasoning=False, max_tokens=1,
                        logprobs=True, top_logprobs=20)
            row = con.execute("SELECT response FROM responses WHERE key=?",
                              (spec.key(),)).fetchone()
            if not row:
                continue
            got = p_odd_from(json.loads(row[0]))
            if got:
                by_prov[got[0]].append(got[1])

        if not by_prov:
            print(f"\n### {cond} / {model.split('/')[-1]} -- no unpinned rows cached")
            continue

        rows = sorted(by_prov.items(), key=lambda kv: -statistics.mean(kv[1]))
        groups = [v for _, v in rows if len(v) >= 2]
        means = [statistics.mean(v) for _, v in rows]
        n_tot = sum(len(v) for _, v in rows)
        print(f"\n### {cond} / {model.split('/')[-1]}   "
              f"n={n_tot}, {len(rows)} backends, "
              f"range {min(means):.1%}-{max(means):.1%}, "
              f"eta^2={eta_sq(groups) if len(groups) >= 2 else float('nan'):.2f}")
        print(f"  {'provider':<16} {'quant':<9} {'n':>4} {'P(odd)':>9}")
        for prov, v in rows:
            q = quants[model].get(prov, "not listed")
            print(f"  {prov:<16} {q:<9} {len(v):>4} {statistics.mean(v):>9.1%}")


if __name__ == "__main__":
    main()
