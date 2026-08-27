"""Standalone figure: gaming rate against reasoning-prefix length.

Produces a PNG (for pasting into a document) and an SVG (for anything that will be
resized) in docs/. Regenerate after more sampling; no API calls.

The band is the 95% Wilson interval, so it widens exactly where sampling is thin --
the transition region carries ~50 samples per point, the tail 4. That is honest about
where the resolution actually is, which a bare line would hide.

Run: `uv run --with matplotlib python experiments/020_curve/plot.py`
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.resample import sentence_cuts  # noqa: E402
from oddnum.stats import wilson  # noqa: E402

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "runs" / "cot_target9_reasoning" / "instrfirst__noclar__complied__r06.md"
RESULTS = ROOT / "experiments" / "016_resampling" / "results.jsonl"
OUT = ROOT / "docs" / "gaming_rate_by_prefix"

INK = "#141922"
MUTED = "#5d6675"
BRICK = "#a8402e"
RULE = "#d8dce4"


def main() -> None:
    md = TRACE.read_text(encoding="utf-8")
    reasoning = re.search(r"^## Reasoning\n\n(.*?)\n\n## Visible answer",
                          md, re.S | re.M).group(1).strip()
    n_sent = len(sentence_cuts(reasoning))

    by: dict[int, list[bool]] = defaultdict(list)
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("gamed") is not None:
                by[rec["prefix_idx"]].append(rec["gamed"])

    xs = sorted(by)
    rate = [sum(by[i]) / len(by[i]) for i in xs]
    lo, hi = zip(*(wilson(sum(by[i]), len(by[i])) for i in xs))
    total = sum(len(v) for v in by.values())

    # Every tail prefix reads 0/4, so each point's own interval runs to ~49% and a
    # filled band paints a slab over two thirds of the figure -- visually implying
    # the tail might sit near 50%. Pooling those points is the honest summary: 119
    # independent prefixes all at zero is a very tight bound. So the band is drawn
    # only where sampling supports it, the sparse region gets per-point ticks, and
    # the pooled bound is stated outright.
    deep = [i for i in xs if len(by[i]) >= 10]
    tail = [i for i in xs if len(by[i]) < 10]
    t_k = sum(sum(by[i]) for i in tail)
    t_n = sum(len(by[i]) for i in tail)
    t_lo, t_hi = wilson(t_k, t_n) if t_n else (0, 0)

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.edgecolor": RULE, "axes.labelcolor": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    })
    fig, (ax, axn) = plt.subplots(
        2, 1, figsize=(9, 4.2), dpi=220, sharex=True,
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.12})

    ax.fill_between([i for i in deep],
                    [wilson(sum(by[i]), len(by[i]))[0] for i in deep],
                    [wilson(sum(by[i]), len(by[i]))[1] for i in deep],
                    color=BRICK, alpha=0.16, linewidth=0,
                    label="95% Wilson interval (n≥10)")
    # No per-point interval for the sparse tail: at n=4 each one runs to ~49% and
    # together they build a wall that reads as "the tail might be at 50%". They carry
    # no individual information; the pooled bound below does the work.
    ax.plot(xs, rate, color=BRICK, linewidth=1.6, zorder=3)
    ax.plot(xs, rate, "o", color="white", markeredgecolor=BRICK,
            markeredgewidth=1.2, markersize=3.4, zorder=4)

    ax.set_ylim(-0.04, 1.06)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylabel("gaming rate")
    ax.set_title("Resampled gaming rate by reasoning-prefix length",
                 loc="left", fontsize=11, pad=10)
    ax.grid(axis="y", color=RULE, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right", fontsize=8)
    if tail:
        ax.annotate(f"tail pooled: {t_k}/{t_n} gaming, 95% upper bound {t_hi:.1%}",
                    xy=(min(tail), 0.015), xytext=(min(tail) + 6, 0.17),
                    fontsize=8, color=MUTED,
                    arrowprops=dict(arrowstyle="-", color=RULE, linewidth=0.8))

    axn.fill_between(xs, [len(by[i]) for i in xs], step="mid",
                     color=MUTED, alpha=0.28, linewidth=0)
    axn.set_ylabel("samples", fontsize=8)
    axn.set_xlabel("sentences of the reasoning trace included in the prefix")
    axn.set_xlim(0, n_sent)
    axn.set_ylim(0, max(len(v) for v in by.values()) * 1.15)
    axn.grid(axis="y", color=RULE, linewidth=0.6, alpha=0.7)
    axn.set_axisbelow(True)
    for a in (ax, axn):
        for side in ("top", "right"):
            a.spines[side].set_visible(False)

    fig.tight_layout()
    # Placed in figure coordinates after tight_layout, so it sits below the axis
    # label instead of colliding with it.
    fig.subplots_adjust(bottom=0.20)
    fig.text(0.01, 0.015,
             f"qwen3.6-27b · {total:,} continuations · the trace is {n_sent} "
             f"sentences long · interval shown where n≥10",
             fontsize=7.5, color=MUTED, va="bottom")

    for ext in ("png", "svg"):
        fig.savefig(f"{OUT}.{ext}", bbox_inches=None,
                    facecolor="white" if ext == "png" else "none")
    print(f"wrote {OUT}.png and {OUT}.svg")
    print(f"  {len(xs)} sampled prefixes of {n_sent}, {total} continuations")


if __name__ == "__main__":
    main()
