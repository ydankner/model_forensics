"""Generate the interactive resampling artifact from the current results.

Reads the trace and results.jsonl, computes each sentence's resampling score with a
Newcombe interval, and writes a self-contained HTML page to docs/resampling.html.

Re-running regenerates the page from whatever depth the sampling has reached, so
updating the published artifact after more sampling is: run this, publish the same
file path. No API calls.

Encoding, stated here because it is the whole point of the page:
  score = P(gaming | prefix through this sentence) - P(gaming | prefix before it)
  score > 0  the sentence pushes the model toward GAMING      -> red
  score < 0  the sentence pushes it toward COMPLIANCE          -> green
  intensity  proportional to |score|, saturating at 50 points
  solid left rule  the 95% interval excludes zero (a second, non-colour cue)

Run: `uv run --with httpx --with python-dotenv python experiments/019_artifact/build.py`
"""

import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402
from oddnum.resample import sentence_cuts  # noqa: E402
from oddnum.stats import diff_ci, wilson  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "runs" / "cot_target9_reasoning" / "instrfirst__noclar__complied__r06.md"
RESULTS = ROOT / "experiments" / "016_resampling" / "results.jsonl"
OUT = ROOT / "docs" / "resampling.html"
SATURATE = 0.50  # |score| at which the tint reaches full strength
BUCKETS = 12     # intensity steps, emitted as stylesheet classes
MAX_TINT = 0.62  # alpha at full strength


def load() -> tuple[str, list[int], dict[int, list[bool]]]:
    md = TRACE.read_text(encoding="utf-8")
    reasoning = re.search(r"^## Reasoning\n\n(.*?)\n\n## Visible answer",
                          md, re.S | re.M).group(1).strip()
    cuts = [0] + sentence_cuts(reasoning)
    by: dict[int, list[bool]] = defaultdict(list)
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("gamed") is not None:
                by[rec["prefix_idx"]].append(rec["gamed"])
    return reasoning, cuts, by


def sentences(reasoning: str, cuts: list[int], by: dict[int, list[bool]]) -> list[dict]:
    out = []
    for i in range(1, len(cuts)):
        text = reasoning[cuts[i - 1]:cuts[i]]
        aft, bef = by.get(i, []), by.get(i - 1, [])
        item = {"i": i, "text": text, "n_after": len(aft), "n_before": len(bef)}
        if aft and bef:
            ka, kb = sum(aft), sum(bef)
            ra, rb = ka / len(aft), kb / len(bef)
            lo, hi = diff_ci(ka, len(aft), kb, len(bef))
            item |= {"score": ra - rb, "lo": lo, "hi": hi, "rate": ra,
                     "sig": lo > 0 or hi < 0}
        elif aft:
            item |= {"rate": sum(aft) / len(aft)}
        out.append(item)
    return out


def curve(by: dict[int, list[bool]], n_prefix: int) -> str:
    """Sparkline of gaming rate against prefix index, with a CI band."""
    pts = [(i, sum(v) / len(v), *wilson(sum(v), len(v)))
           for i, v in sorted(by.items()) if v and i <= n_prefix]
    if not pts:
        return ""
    W, H = 1000, 120
    x = lambda i: i / n_prefix * W  # noqa: E731
    y = lambda r: H - r * H  # noqa: E731
    line = " ".join(f"{x(i):.1f},{y(r):.1f}" for i, r, _, _ in pts)
    band = (" ".join(f"{x(i):.1f},{y(hi):.1f}" for i, _, _, hi in pts) + " " +
            " ".join(f"{x(i):.1f},{y(lo):.1f}" for i, _, lo, _ in reversed(pts)))
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(r):.1f}" r="2.5" class="dot"'
        f' data-i="{i}"><title>after sentence {i}: {r:.0%} gaming'
        f' (n={len(by[i])})</title></circle>'
        for i, r, _, _ in pts)
    return (f'<svg class="curve" viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
            f'role="img" aria-label="Gaming rate falls from 100% to 0% across the '
            f'first 20 sentences and stays there.">'
            f'<polygon class="band" points="{band}"/>'
            f'<polyline class="line" points="{line}"/>{dots}</svg>')


def render(items: list[dict], reasoning: str, by: dict, cuts: list[int]) -> str:
    spans = []
    for it in items:
        text = html.escape(it["text"])
        if "score" not in it:
            n = it.get("n_after", 0)
            tip = (f"sentence {it['i']} &middot; not yet resampled"
                   if not n else
                   f"sentence {it['i']} &middot; {it['rate']:.0%} gaming after "
                   f"(n={n}) &middot; no measurement before it")
            spans.append(f'<span class="s none" data-tip="{tip}">{text}</span>')
            continue
        s = it["score"]
        # Intensity is carried by a class, not an inline custom property. Inline
        # style attributes are stripped by some sanitising render paths (the page
        # loses every tint when viewed signed-out), and a stylesheet class survives
        # that. It also avoids calc() inside rgb(), which is the more fragile of the
        # two constructs.
        bucket = max(1, min(BUCKETS, round(min(abs(s) / SATURATE, 1.0) * BUCKETS)))
        cls = "s " + ("up" if s > 0 else "down" if s < 0 else "flat") + f" a{bucket}"
        if it["sig"]:
            cls += " sig"
        tip = (f"sentence {it['i']}"
               f"&#10;score {s:+.0%}  95% CI [{it['lo']:+.0%}, {it['hi']:+.0%}]"
               f"&#10;gaming {it['rate']:.0%} after this sentence"
               f"&#10;n = {it['n_after']} after, {it['n_before']} before"
               + ("&#10;interval excludes zero" if it["sig"] else ""))
        spans.append(f'<span class="{cls}" data-tip="{tip}">{text}</span>')

    # One rule per intensity bucket, with the alpha written out literally.
    tints = "\n".join(
        f".s.up.a{b}{{background:rgb(var(--gaming) / {b / BUCKETS * MAX_TINT:.3f})}}\n"
        f".s.down.a{b}{{background:rgb(var(--comply) / {b / BUCKETS * MAX_TINT:.3f})}}"
        for b in range(1, BUCKETS + 1))
    prompt = html.escape(CONDITIONS["t9_instr_first"].render("even"))
    return TEMPLATE.format(prompt=prompt, trace="".join(spans),
                           curve=curve(by, len(cuts) - 1), tints=tints)


TEMPLATE = """<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap">
<title>Resampling Score in compliant CoT</title>
<style>
:root {{
  --paper:#fcfcfd; --panel:#f4f5f8; --ink:#141922; --muted:#5d6675; --rule:#e3e6ed;
  --gaming:168 64 46; --comply:47 107 82; --accent:#3d4a5c;
  --tip-bg:#141922; --tip-ink:#f4f5f8;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --paper:#0d1015; --panel:#161b23; --ink:#e7eaf0; --muted:#8d96a5; --rule:#242b36;
    --gaming:224 112 92; --comply:95 176 138; --accent:#9fb0c7;
    --tip-bg:#e7eaf0; --tip-ink:#0d1015;
  }}
}}
:root[data-theme="dark"] {{
  --paper:#0d1015; --panel:#161b23; --ink:#e7eaf0; --muted:#8d96a5; --rule:#242b36;
  --gaming:224 112 92; --comply:95 176 138; --accent:#9fb0c7;
  --tip-bg:#e7eaf0; --tip-ink:#0d1015;
}}
*{{box-sizing:border-box}}
body{{background:var(--paper);color:var(--ink);margin:0;
  font-family:"IBM Plex Sans",system-ui,sans-serif;line-height:1.5;}}
.wrap{{max-width:60rem;margin:0 auto;padding:3.5rem 1.5rem 6rem;
  display:flex;flex-direction:column;gap:2.5rem}}
h1{{font-family:Newsreader,Georgia,serif;font-weight:500;font-size:clamp(2rem,4.5vw,3rem);
  line-height:1.1;margin:0;text-wrap:balance;letter-spacing:-.01em}}
.lede{{color:var(--muted);max-width:62ch;margin:0;font-size:1.0625rem}}
.eyebrow{{font-size:.6875rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);font-weight:600;margin:0 0 .75rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));gap:1px;
  background:var(--rule);border:1px solid var(--rule);border-radius:2px;overflow:hidden}}
.stat{{background:var(--paper);padding:.9rem 1rem}}
.stat b{{display:block;font-family:"IBM Plex Mono",monospace;font-size:1.5rem;
  font-weight:500;font-variant-numeric:tabular-nums;line-height:1.2}}
.stat span{{font-size:.75rem;color:var(--muted)}}
.panel{{background:var(--panel);border:1px solid var(--rule);border-radius:2px;padding:1.25rem}}
pre{{font-family:"IBM Plex Mono",monospace;font-size:.8125rem;margin:0;
  white-space:pre-wrap;overflow-x:auto;color:var(--ink)}}
.curve{{width:100%;height:120px;display:block;overflow:visible}}
.band{{fill:rgb(var(--gaming)/.13)}}
.line{{fill:none;stroke:rgb(var(--gaming)/.85);stroke-width:2;
  vector-effect:non-scaling-stroke}}
.dot{{fill:var(--paper);stroke:rgb(var(--gaming)/.9);stroke-width:1.5;
  vector-effect:non-scaling-stroke}}
.axis{{display:flex;justify-content:space-between;font-size:.6875rem;color:var(--muted);
  font-family:"IBM Plex Mono",monospace;margin-top:.4rem}}
.trace{{font-family:"IBM Plex Mono",monospace;font-size:.8125rem;line-height:2;
  white-space:pre-wrap;word-break:break-word}}
.s{{border-radius:2px;padding:.12em 0;transition:outline-color .12s}}
{tints}
.s.sig{{box-shadow:inset 3px 0 0 0 rgb(var(--gaming)/1)}}
.s.down.sig{{box-shadow:inset 3px 0 0 0 rgb(var(--comply)/1)}}
.s:hover{{outline:1px solid var(--accent);outline-offset:1px;cursor:help}}
.s.none{{color:var(--muted)}}
.legend{{display:flex;flex-wrap:wrap;gap:1.25rem;align-items:center;font-size:.8125rem;
  color:var(--muted)}}
.chip{{display:inline-flex;align-items:center;gap:.5rem}}
.sw{{width:2.5rem;height:1rem;border-radius:2px;border:1px solid var(--rule)}}
.ramp-up{{background:linear-gradient(90deg,rgb(var(--gaming)/.06),rgb(var(--gaming)/.62))}}
.ramp-down{{background:linear-gradient(90deg,rgb(var(--comply)/.06),rgb(var(--comply)/.62))}}
.sw.sigsw{{box-shadow:inset 3px 0 0 0 var(--accent)}}
ul.sig{{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:.6rem}}
ul.sig li{{display:grid;grid-template-columns:4.5rem 1fr auto;gap:1rem;align-items:baseline;
  font-size:.875rem}}
ul.sig li.empty{{display:block;color:var(--muted)}}
.badge{{font-family:"IBM Plex Mono",monospace;font-weight:500;font-variant-numeric:tabular-nums}}
.badge.up{{color:rgb(var(--gaming))}} .badge.down{{color:rgb(var(--comply))}}
.sigtext{{font-family:"IBM Plex Mono",monospace;font-size:.8125rem}}
.sigci{{color:var(--muted);font-family:"IBM Plex Mono",monospace;font-size:.75rem;
  white-space:nowrap}}
h2{{font-family:Newsreader,Georgia,serif;font-weight:500;font-size:1.5rem;margin:0 0 .6rem}}
.note{{font-size:.8125rem;color:var(--muted);max-width:66ch}}
.note code{{font-family:"IBM Plex Mono",monospace;font-size:.9em}}
#tip{{position:fixed;z-index:20;pointer-events:none;opacity:0;transition:opacity .1s;
  background:var(--tip-bg);color:var(--tip-ink);padding:.6rem .75rem;border-radius:3px;
  font-size:.75rem;line-height:1.5;white-space:pre;max-width:22rem;
  font-family:"IBM Plex Mono",monospace;box-shadow:0 6px 24px rgb(0 0 0/.22)}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style>

<div class="wrap">
  <header>
    <h1>Resampling Score in compliant CoT</h1>
  </header>

  <section>
    <p class="eyebrow">The prompt</p>
    <div class="panel"><pre>{prompt}</pre></div>
  </section>

  <section>
    <p class="eyebrow">Gaming rate by prefix length</p>
    {curve}
    <div class="axis"><span>start of trace</span><span>end of trace</span></div>
    <p class="note">Each point resamples continuations from a prefix ending at that
    sentence. The band is the 95% Wilson interval. The rate falls from 100% to 0%
    across roughly the first twenty sentences and never recovers across the
    remaining hundred-plus.</p>
  </section>

  <section>
    <h2>The trace</h2>
    <div class="legend">
      <span class="chip"><span class="sw ramp-down"></span> pushes toward compliance</span>
      <span class="chip"><span class="sw ramp-up"></span> pushes toward gaming</span>
      <span class="chip"><span class="sw sigsw"></span> interval excludes zero</span>
      <span class="chip">grey = not yet resampled</span>
    </div>
    <p class="note" style="margin:.75rem 0 1.25rem">Hover any sentence for its score,
    95% interval and sample count.</p>
    <div class="trace">{trace}</div>
  </section>

  <section>
    <h2>Reading this honestly</h2>
    <p class="note">A score is a difference between two sampled rates, so its interval
    is wider than either. At small sample counts individual scores are not
    interpretable: an earlier pass at four samples per prefix put one sentence at
    +75%, and deeper sampling moved it to roughly zero. Only sentences marked as
    excluding zero support a claim, and the trustworthy result is the shape of the
    curve rather than any single tint. Intervals are Newcombe; rates are Wilson.</p>
  </section>
</div>

<div id="tip" role="status"></div>
<script>
const tip = document.getElementById('tip');
document.querySelectorAll('.s').forEach(el => {{
  el.addEventListener('mouseenter', e => {{
    tip.textContent = el.dataset.tip.replace(/&middot;/g, '\\u00b7');
    tip.style.opacity = '1';
  }});
  el.addEventListener('mousemove', e => {{
    const r = tip.getBoundingClientRect();
    let x = e.clientX + 14, y = e.clientY + 16;
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 16;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }});
  el.addEventListener('mouseleave', () => {{ tip.style.opacity = '0'; }});
}});
</script>
"""


def main() -> None:
    reasoning, cuts, by = load()
    items = sentences(reasoning, cuts, by)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(items, reasoning, by, cuts), encoding="utf-8")
    measured = [i for i in items if "score" in i]
    print(f"wrote {OUT}")
    print(f"  {len(items)} sentences, {len(measured)} scored, "
          f"{sum(1 for i in items if i.get('sig'))} significant, "
          f"{sum(len(v) for v in by.values())} continuations")


if __name__ == "__main__":
    main()
