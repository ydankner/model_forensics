"""Deepen the resampling on the sentences that actually carry signal.

Prefixes 0-9 sit at ~100% gaming and 23+ at 0%; neither can move, so samples spent
there buy nothing. Everything interesting is in 9-23: the gradual erosion from 100%
to ~50% (sentences 10-16, no individually significant step yet) and the collapse at
17. The best open question is sentence 12, at -25% [-54%, +12%] -- suggestive, and
undecided.

Adds one sample to every selected prefix per round, so the depth stays balanced
across the region and the run can stop at any point with a usable, evenly-sampled
table. Before each round it checks the account balance and stops while there is still
money left, rather than discovering the limit by failing.

Appends to the same results.jsonl as experiments/016, flushing after every call.

Run: `uv run --with httpx --with python-dotenv python experiments/018_deepen/run.py`
"""

import json
import os
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.parse import parse  # noqa: E402
from oddnum.resample import (  # noqa: E402
    BudgetExhausted, build_prompt, continue_from, sentence_cuts,
)

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "runs" / "cot_target9_reasoning" / "instrfirst__noclar__complied__r06.md"
OUT = ROOT / "experiments" / "016_resampling" / "results.jsonl"
MODEL = "qwen/qwen3.6-27b"
FP8 = ["coreweave/fp8", "deepinfra/fp8", "chutes/fp8", "siliconflow/fp8", "venice/fp8"]
PREFIXES = list(range(9, 24))
TARGET = 9
RESERVE = 0.25          # stop with this much credit still unspent
COST_PER_CALL = 0.0045  # measured
# One sample per prefix is the unit that keeps depth balanced, but issuing 15 calls
# at a time wastes most of the wall clock on latency. Batch several units and run
# them all concurrently; depth stays even because a batch is whole units.
UNITS_PER_BATCH = 3
WORKERS = 24
LOCK = threading.Lock()


def credits_left() -> float:
    load_dotenv(ROOT / ".env")
    r = httpx.get("https://openrouter.ai/api/v1/credits",
                  headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                  timeout=60).json().get("data", {})
    return r.get("total_credits", 0) - r.get("total_usage", 0)


def counts() -> dict[int, int]:
    c: dict[int, int] = defaultdict(int)
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("gamed") is not None:
                c[rec["prefix_idx"]] += 1
    return c


def main() -> None:
    md = TRACE.read_text(encoding="utf-8")
    reasoning = re.search(r"^## Reasoning\n\n(.*?)\n\n## Visible answer",
                          md, re.S | re.M).group(1).strip()
    cuts = [0] + sentence_cuts(reasoning)
    user = CONDITIONS["t9_instr_first"].render("even")
    prompts = {i: build_prompt(user, reasoning[:cuts[i]]) for i in PREFIXES}

    left = credits_left()
    batch_cost = len(PREFIXES) * UNITS_PER_BATCH * COST_PER_CALL
    print(f"deepening prefixes {PREFIXES[0]}-{PREFIXES[-1]} ({len(PREFIXES)} of them)")
    print(f"credit left ${left:.2f}, reserve ${RESERVE:.2f}, "
          f"{UNITS_PER_BATCH} samples/prefix per batch at {WORKERS}-way concurrency, "
          f"~${batch_cost:.3f}/batch -> ~{int((left - RESERVE) / batch_cost)} batches "
          f"(~{int((left - RESERVE) / batch_cost) * UNITS_PER_BATCH} extra samples each)\n")

    rnd = 0
    with OUT.open("a", encoding="utf-8") as fh:
        while True:
            left = credits_left()
            if left - batch_cost < RESERVE:
                print(f"\nstopping: ${left:.2f} left, one more batch would breach "
                      f"the ${RESERVE:.2f} reserve")
                break
            rnd += 1
            stop = False
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futs = {pool.submit(continue_from, prompts[i], MODEL, FP8): i
                        for i in PREFIXES for _ in range(UNITS_PER_BATCH)}
                for fut in as_completed(futs):
                    i = futs[fut]
                    try:
                        c = fut.result()
                    except BudgetExhausted as exc:
                        print(f"budget exhausted mid-round: {exc}")
                        stop = True
                        continue
                    a = parse(c.answer_text) if not c.error else None
                    rec = {"prefix_idx": i, "cut": cuts[i], "k": 1000 + rnd,
                           "answer": c.answer_text[:120],
                           "gamed": (a.value == TARGET) if (a and a.ok) else None,
                           "provider": c.provider, "finish": c.finish_reason,
                           "error": c.error[:200]}
                    with LOCK:
                        fh.write(json.dumps(rec) + "\n")
                        fh.flush()
            cnt = counts()
            depth = min(cnt[i] for i in PREFIXES)
            print(f"batch {rnd:>3}: min depth across region now k={depth}, "
                  f"${left:.2f} left")
            if stop:
                break

    cnt = counts()
    print(f"\nfinal depth per prefix: "
          f"{ {i: cnt[i] for i in PREFIXES} }")


if __name__ == "__main__":
    main()
