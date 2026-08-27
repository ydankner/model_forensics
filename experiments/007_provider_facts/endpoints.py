"""What quantisation does each backend actually serve?

The n=50 sweep found up to a 10x spread in P(odd) across backends serving nominally
the same weights. OpenRouter publishes per-endpoint quantisation, which is a more
authoritative answer than anything a web search will turn up, so ask it directly.

Free: public endpoint, no key required.
Run: `uv run --with httpx python experiments/007_provider_facts/endpoints.py`
"""

import httpx

MODELS = ["qwen/qwen3.6-35b-a3b", "qwen/qwen3.6-27b", "qwen/qwen3.5-9b"]
# Backends the sweep actually routed to, so the table can be read against the data.
SEEN = {"AkashML", "Darkbloom", "Phala", "Io Net", "CoreWeave", "Parasail", "Venice"}


def main() -> None:
    for slug in MODELS:
        r = httpx.get(f"https://openrouter.ai/api/v1/models/{slug}/endpoints", timeout=60)
        data = r.json().get("data", {})
        eps = data.get("endpoints", [])
        print(f"=== {slug} ({len(eps)} endpoints) ===")
        print(f"  {'provider':<18} {'quant':<10} {'ctx':>8} {'$/Mout':>8}  seen")
        for e in sorted(eps, key=lambda e: str(e.get("provider_name"))):
            name = e.get("provider_name", "?")
            quant = str(e.get("quantization"))
            ctx = e.get("context_length") or 0
            pout = float((e.get("pricing") or {}).get("completion", 0)) * 1e6
            mark = "  <-- in sweep" if name in SEEN else ""
            print(f"  {name:<18} {quant:<10} {ctx:>8} {pout:>8.3f}{mark}")
        print()


if __name__ == "__main__":
    main()
