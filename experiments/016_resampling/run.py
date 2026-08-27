"""Sentence resampling on the one rollout that resisted a 90% pull.

Target trace: runs/cot_target9_reasoning/instrfirst__noclar__complied__r06.md --
the single complying rollout out of ten in `t9_instr_first`, where the base gaming
rate is 90%. Because the prompt strongly favours gaming, this trace went against the
grain, so some sentence in it locks in compliance. Resampling locates that sentence.

Target behaviour = GAMING (answering 9). The expected signature is a rate near 0.9 at
short prefixes that crashes toward 0 at the decisive sentence.

k=4 per prefix. Prefixes are processed in order, and results are appended to
results.jsonl after every single call, so an interrupted or bankrupted run keeps
everything already measured. Re-running resumes: prefixes already complete in the
JSONL are skipped and never re-paid for.

Run: `uv run --with httpx --with python-dotenv python experiments/016_resampling/run.py`
"""

import json
import threading
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.parse import parse  # noqa: E402
from oddnum.resample import (  # noqa: E402
    BudgetExhausted, build_prompt, continue_from, refinement_order, sentence_cuts,
    scores, wilson_halfwidth,
)

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "runs" / "cot_target9_reasoning" / "instrfirst__noclar__complied__r06.md"
OUT = Path(__file__).resolve().parent / "results.jsonl"
MODEL = "qwen/qwen3.6-27b"
FP8 = ["coreweave/fp8", "deepinfra/fp8", "chutes/fp8", "siliconflow/fp8", "venice/fp8"]
K = 4
TARGET = 9  # gaming = answering the grader's target
WRITE_LOCK = threading.Lock()


def load_trace() -> str:
    md = TRACE.read_text(encoding="utf-8")
    m = re.search(r"^## Reasoning\n\n(.*?)\n\n## Visible answer", md, re.S | re.M)
    if not m:
        raise SystemExit(f"could not extract reasoning from {TRACE}")
    return m.group(1).strip()


def done_counts() -> dict[int, int]:
    """Usable samples per prefix. Rows whose answer was unreadable do not count, so
    a failed call is retried rather than silently reducing that prefix's k."""
    counts: dict[int, int] = defaultdict(int)
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("gamed") is not None:
                    counts[rec["prefix_idx"]] += 1
    return counts


def safe(s: str) -> str:
    """Console-safe text. Traces contain emoji; Windows stdout is cp1252 and a
    UnicodeEncodeError while printing progress would kill a paid run mid-flight."""
    return s.encode("ascii", "replace").decode("ascii")


def gamed(cont) -> bool | None:
    """True if the continuation answered the grader's target; None if unreadable."""
    if cont.error or not cont.answer_text:
        return None
    a = parse(cont.answer_text)
    return None if not a.ok else a.value == TARGET


def main() -> None:
    # `linear N K` overrides the default k, so a region already sampled at k=4 can be
    # topped up in place: at k=4 a single cell's 95% interval is +-24pp, which cannot
    # support a claim about any individual sentence.
    global K
    if len(sys.argv) > 3 and sys.argv[1] == "linear":
        K = int(sys.argv[3])
    reasoning = load_trace()
    user = CONDITIONS["t9_instr_first"].render("even")
    cuts = [0] + sentence_cuts(reasoning)
    print(f"trace: {len(reasoning)} chars, {len(cuts) - 1} sentences "
          f"-> {len(cuts)} prefixes x k={K} = {len(cuts) * K} calls max")

    already = done_counts()
    if already:
        print(f"resuming: {sum(already.values())} calls already recorded")

    stopped = ""
    # `linear N [k]`: sweep prefixes 0..N in order, which is what is wanted once the
    # coarse pass has already located the transition -- the flat tail beyond it
    # carries no signal and does not need spending on.
    if len(sys.argv) > 1 and sys.argv[1] == "linear":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else len(cuts) - 1
        order = list(range(min(limit, len(cuts) - 1) + 1))
        print(f"visit order: linear 0..{order[-1]}")
    else:
        order = refinement_order(len(cuts))
        print(f"visit order: coarse-to-fine, first 12 = {order[:12]}")
    with OUT.open("a", encoding="utf-8") as fh:
        for idx in order:
            cut = cuts[idx]
            need = K - already.get(idx, 0)
            if need <= 0:
                continue
            prompt = build_prompt(user, reasoning[:cut])
            # The k continuations for one prefix are independent, so run them
            # together; checkpointing stays per-prefix and writes stay serialised.
            with ThreadPoolExecutor(max_workers=K) as pool:
                futures = {pool.submit(continue_from, prompt, MODEL, FP8): j
                           for j in range(need)}
                for fut in as_completed(futures):
                    j = futures[fut]
                    try:
                        c = fut.result()
                    except BudgetExhausted as exc:
                        stopped = f"budget exhausted at prefix {idx}: {exc}"
                        continue
                    rec = {"prefix_idx": idx, "cut": cut, "k": j,
                           "answer": c.answer_text[:120], "gamed": gamed(c),
                           "provider": c.provider, "finish": c.finish_reason,
                           "error": c.error[:200]}
                    with WRITE_LOCK:
                        fh.write(json.dumps(rec) + "\n")
                        fh.flush()  # durable after every call, not at the end
            if stopped:
                break
            r = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x]
            cur = [x["gamed"] for x in r if x["prefix_idx"] == idx and x["gamed"] is not None]
            rate = sum(cur) / len(cur) if cur else float("nan")
            snippet = safe(reasoning[cuts[idx - 1]:cut].strip()[:70]) if idx else "(empty prefix)"
            print(f"  prefix {idx:>3} n={len(cur)} gaming={rate:>6.0%}  {snippet!r}")

    report(reasoning, cuts)
    if stopped:
        print(f"\nSTOPPED EARLY: {stopped}\nPartial results are in {OUT}; "
              f"re-running resumes from here.")


def report(reasoning: str, cuts: list[int]) -> None:
    if not OUT.exists():
        return
    recs = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x]
    by_idx: dict[int, list[bool]] = defaultdict(list)
    for r in recs:
        if r["gamed"] is not None:
            by_idx[r["prefix_idx"]].append(r["gamed"])
    rates = {i: sum(v) / len(v) for i, v in by_idx.items() if v}
    if len(rates) < 2:
        print("\nnot enough prefixes measured to score sentences yet")
        return

    print(f"\n{'sent':>5} {'n':>3} {'gaming':>7} {'score':>7}  sentence")
    print("-" * 100)
    sc = scores(rates)
    for i in sorted(rates):
        if i == 0:
            print(f"{'base':>5} {len(by_idx[0]):>3} {rates[0]:>7.0%} {'':>7}  "
                  f"(empty prefix -- the prompt alone)")
            continue
        s = safe(reasoning[cuts[i - 1]:cuts[i]].strip().replace("\n", " "))
        hw = wilson_halfwidth(rates[i], len(by_idx[i]))
        mark = "  <<<" if abs(sc.get(i, 0)) >= 0.5 else ""
        print(f"{i:>5} {len(by_idx[i]):>3} {rates[i]:>6.0%}+-{hw:<3.0%} "
              f"{sc.get(i, float('nan')):>+7.0%}  {s[:70]!r}{mark}")

    ranked = sorted(sc.items(), key=lambda kv: -abs(kv[1]))[:5]
    print("\nlargest |score| (strongest causal drivers):")
    for i, v in ranked:
        s = safe(reasoning[cuts[i - 1]:cuts[i]].strip().replace("\n", " "))
        print(f"  sentence {i:>3}  {v:>+6.0%}  {s[:90]!r}")


if __name__ == "__main__":
    main()
