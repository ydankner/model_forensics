"""Provenance check on the reasoning traces: are they verbatim, and are they complete?

Three things to establish before any claim rests on trace content:

  1. What does extract.py add? (Only headers -- but verify against raw JSON.)
  2. Is the "Here's a thinking process:" preamble and its numbering the model's own
     text, or an artefact of our formatting?
  3. Is `message.reasoning` the FULL chain of thought, or a provider-side summary?
     Some providers return summarised reasoning. The test: compare the reported
     `reasoning_tokens` against the token count implied by the returned string. If
     the string is much shorter than the billed reasoning tokens, it is a summary
     and every quote drawn from it is suspect.

Free: reads cache.db only.
Run: `uv run python experiments/009_cot/provenance.py`
"""

import json
import sqlite3
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "cache.db"
CHARS_PER_TOKEN = 4.0  # rough for English; only used as an order-of-magnitude check


def main() -> None:
    con = sqlite3.connect(CACHE_PATH)
    rows = con.execute(
        "SELECT model, condition, response FROM responses "
        "WHERE model='qwen/qwen3.6-27b' AND condition='explicit'"
    ).fetchall()

    print(f"{len(rows)} cached qwen3.6-27b/explicit responses\n")

    # --- 1. structure of the raw response ---------------------------------
    body = json.loads(rows[0][2])
    msg = body["choices"][0]["message"]
    print("top-level keys :", sorted(body.keys()))
    print("message keys   :", sorted(msg.keys()))
    usage = body.get("usage", {})
    print("usage keys     :", sorted(usage.keys()))
    print("usage detail   :", usage.get("completion_tokens_details"))

    # OpenRouter marks summarised vs verbatim reasoning here when present.
    rd = msg.get("reasoning_details")
    if rd:
        print("reasoning_details types:", [d.get("type") for d in rd])
        print("reasoning_details keys :", sorted(rd[0].keys()))
    else:
        print("reasoning_details: ABSENT")

    # --- 2. is the preamble the model's own text? -------------------------
    reasoning = msg.get("reasoning") or ""
    print("\n--- first 400 chars of raw `reasoning`, repr, verbatim from cache ---")
    print(repr(reasoning[:400]))

    preamble = sum(
        1 for _, _, r in rows
        if (json.loads(r)["choices"][0]["message"].get("reasoning") or "")
        .lstrip().startswith("Here's a thinking process")
    )
    numbered = sum(
        1 for _, _, r in rows
        if "1.  **" in ((json.loads(r)["choices"][0]["message"].get("reasoning") or ""))
        or "1. **" in ((json.loads(r)["choices"][0]["message"].get("reasoning") or ""))
    )
    print(f"\nrollouts whose reasoning STARTS with \"Here's a thinking process\": "
          f"{preamble}/{len(rows)}")
    print(f"rollouts containing markdown-numbered headers (`1. **`): {numbered}/{len(rows)}")

    # --- 3. complete, or summarised? --------------------------------------
    print("\n--- billed reasoning tokens vs tokens implied by the returned string ---")
    print(f"{'reas_tokens':>12} {'chars':>8} {'implied_tok':>12} {'ratio':>7}")
    ratios = []
    for _, _, r in rows[:12]:
        b = json.loads(r)
        rt = (b.get("usage", {}).get("completion_tokens_details") or {}).get(
            "reasoning_tokens", 0)
        s = b["choices"][0]["message"].get("reasoning") or ""
        implied = len(s) / CHARS_PER_TOKEN
        ratio = implied / rt if rt else 0.0
        ratios.append(ratio)
        print(f"{rt:>12} {len(s):>8} {implied:>12.0f} {ratio:>7.2f}")
    if ratios:
        print(f"\nmedian ratio implied/billed = {statistics.median(ratios):.2f}")
        print("~1.0 => the returned string accounts for the billed reasoning "
              "(verbatim).\n<<1.0 => the string is far shorter than what was billed "
              "(summary or truncation).")


if __name__ == "__main__":
    main()
