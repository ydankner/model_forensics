"""Pull the reasoning traces out of the cache and write them to files for reading.

Reads cache.db DIRECTLY rather than going through `oddnum.sample.run`: an analysis
script must not be able to issue API calls. (The first version of this went through
run_sync, which silently re-issued every rollout that had errored and was therefore
never cached -- slow, and it spends money to produce no new data.)

The Run B rollouts are the first in this project with a chain of thought worth
reading: implicit conditions sit at exactly 0% siding, explicit ones at 47-75%. Two
questions the rates cannot answer:

  * in the implicit condition, does the model mention the grader at all, and does it
    try (and fail) to evaluate `output % 2`?
  * in the explicit condition, when it sides with the grader, does it acknowledge
    that the user asked for the opposite -- and does that acknowledgement survive
    into the visible answer, or live only in the reasoning?

Output goes to runs/cot/ and is kept: these traces are the raw material for the
write-up, and re-deriving them costs money.

Run: `uv run python experiments/009_cot/extract.py`
"""

import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.parse import parse  # noqa: E402
# CACHE_PATH is defined locally rather than imported from oddnum.sample: importing
# that module pulls in the HTTP client, and this script must not be able to call out.

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "cache.db"
OUTDIR = ROOT / "runs" / "cot"
CONDS = ["conflict", "explicit", "conflict_digit", "digit_explicit"]
PER_BUCKET = 8  # traces written per bucket; the rest are summarised as counts


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE_PATH)
    rows = con.execute(
        "SELECT model, condition, response FROM responses WHERE condition IN "
        f"({','.join('?' * len(CONDS))})", CONDS
    ).fetchall()

    buckets: dict[tuple[str, str, str], list[tuple[str, str]]] = defaultdict(list)
    lengths: dict[tuple[str, str], list[int]] = defaultdict(list)
    for model, cond, blob in rows:
        body = json.loads(blob)
        if not body.get("choices"):
            continue
        msg = body["choices"][0].get("message", {})
        reasoning = (msg.get("reasoning") or "").strip()
        if not reasoning:  # reasoning-off rollouts from Run A
            continue
        text = (msg.get("content") or "").strip()
        ans = parse(text)
        pays = CONDITIONS[cond].pays("even")
        outcome = ("unparsed" if not ans.ok
                   else "sided" if ans.parity == pays else "complied")
        buckets[(model, cond, outcome)].append((reasoning, text))
        lengths[(model, cond)].append(len(reasoning))

    print(f"{'model':<14} {'condition':<16} {'n':>4} {'median':>8} {'p90':>8} "
          f"{'max':>8}  {'~words (median)':>15}")
    print("-" * 80)
    for (m, c), v in sorted(lengths.items()):
        v.sort()
        med = statistics.median(v)
        print(f"{m.split('/')[-1]:<14} {c:<16} {len(v):>4} {med:>8.0f} "
              f"{v[max(0, int(0.9 * len(v)) - 1)]:>8} {max(v):>8}  {med / 5.5:>15.0f}")

    print("\nwritten:")
    for (m, c, outcome), items in sorted(buckets.items()):
        short = m.split("/")[-1]
        path = OUTDIR / f"{short}__{c}__{outcome}.md"
        picked = items[:PER_BUCKET]
        with path.open("w", encoding="utf-8") as f:
            f.write(f"# {short} | condition `{c}` | outcome: {outcome}\n\n"
                    f"User asked for: **even**. Grader pays: "
                    f"**{CONDITIONS[c].pays('even')}**.\n\n"
                    f"## Prompt\n\n```\n{CONDITIONS[c].render('even')}\n```\n\n"
                    f"{len(items)} rollouts in this bucket; {len(picked)} shown.\n")
            for i, (reasoning, text) in enumerate(picked):
                f.write(f"\n---\n\n## Rollout {i} — answered `{text[:60]}`\n\n"
                        f"### Reasoning\n\n{reasoning}\n\n"
                        f"### Visible answer\n\n```\n{text}\n```\n")
        print(f"  {path.name:<48} {len(items):>4} rollouts")


if __name__ == "__main__":
    main()
