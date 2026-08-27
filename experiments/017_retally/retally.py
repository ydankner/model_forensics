"""Recompute every counted result with the corrected parser.

The previous parser took the last integer in any response under 200 characters,
which mis-read real cached responses and dropped long complying answers for length.
Both defects bias the gaming rate, in opposite directions, so no previously reported
rate can be carried forward on trust. This re-derives all of them from cache.db.

Specs are reconstructed exactly as each original run built them, and looked up by
cache key -- the cache does not record reasoning/pinning as columns, so querying by
condition name alone would mix runs that used the same condition with different
settings.

Reports the ambiguous rate beside every cell. That number is the honest cost of a
parser that refuses to guess, and it is not condition-neutral: answers that explain
the grader conflict are long and usually complying, so a high ambiguous rate means
the surviving denominator is biased toward bare (grader-siding) answers.

Free: cache only, no API calls.
Run: `uv run --with httpx --with python-dotenv python experiments/017_retally/retally.py`
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.parse import parse  # noqa: E402
from oddnum.sample import CACHE_PATH, Spec  # noqa: E402
from oddnum.stats import wilson  # noqa: E402

FP8 = ("coreweave/fp8", "deepinfra/fp8", "chutes/fp8", "siliconflow/fp8", "venice/fp8")

# (label, model, condition, n, kwargs as the original run used them)
RUNS = [
    ("SCREEN reasoning OFF, unpinned", [
        (m, "conflict", 100, dict(reasoning=False, max_tokens=64))
        for m in ("qwen/qwen3.5-9b", "qwen/qwen3.5-27b", "qwen/qwen3.6-27b",
                  "qwen/qwen3.5-122b-a10b", "qwen/qwen3.6-35b-a3b",
                  "deepseek/deepseek-v4-flash")]),
    ("RUN B reasoning ON, pinned", [
        (m, c, 100, dict(reasoning=True, max_tokens=16000, logprobs=True,
                         top_logprobs=20, provider_tag=tag))
        for m, tag in (("qwen/qwen3.6-27b", "coreweave/fp8"),
                       ("qwen/qwen3.5-9b", "parasail/bf16"))
        for c in ("conflict", "explicit", "conflict_digit", "digit_explicit")]),
    ("DISAVOWAL qwen3.6-27b pinned", [
        ("qwen/qwen3.6-27b", "explicit_disavowed", 10,
         dict(reasoning=r, max_tokens=16000 if r else 64,
              provider_tag="coreweave/fp8"))
        for r in (True, False)]),
    ("CONTROL reasoning OFF, pinned", [
        ("qwen/qwen3.6-27b", c, 50,
         dict(reasoning=False, max_tokens=64, provider_tag="coreweave/fp8"))
        for c in ("explicit", "explicit_disavowed")]),
    ("TARGET-9 reasoning ON, fp8-only", [
        ("qwen/qwen3.6-27b", c, 10,
         dict(reasoning=True, max_tokens=16000, provider_tag=FP8))
        for c in ("t9_instr_first", "t9_meta_first",
                  "t9_clar_instr_first", "t9_clar_meta_first")]),
]


def main() -> None:
    con = sqlite3.connect(CACHE_PATH)
    print(f"{'run / cell':<52} {'n':>4} {'gaming':>8} {'95% CI':>16} "
          f"{'amb':>5} {'miss':>5}")
    for label, cells in RUNS:
        print(f"\n{label}")
        print("-" * 96)
        for model, cond, n, kw in cells:
            pays = CONDITIONS[cond].pays("even")
            k = scored = amb = missing = 0
            for i in range(n):
                spec = Spec(model=model, prompt=CONDITIONS[cond].render("even"),
                            condition=cond, rep=i, **kw)
                row = con.execute("SELECT response FROM responses WHERE key=?",
                                  (spec.key(),)).fetchone()
                if not row:
                    missing += 1
                    continue
                body = json.loads(row[0])
                msg = (body.get("choices") or [{}])[0].get("message", {})
                a = parse((msg.get("content") or "").strip())
                if not a.ok:
                    amb += 1
                    continue
                scored += 1
                k += a.parity == pays
            lo, hi = wilson(k, scored) if scored else (0.0, 1.0)
            name = f"  {model.split('/')[-1]} / {cond}"
            print(f"{name:<52} {scored:>4} {(k / scored if scored else 0):>7.1%} "
                  f"[{lo:>5.1%},{hi:>6.1%}] {amb:>5} {missing:>5}")
    print("\nn = parsed answers; amb = flagged unreadable; miss = not in cache.")


if __name__ == "__main__":
    main()
