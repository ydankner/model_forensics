"""Ad-hoc: eyeball every rendered condition in both polarities.

Not a test -- these prompts are the experiment, so they get read by a human before
any money is spent. Run: `uv run python experiments/000_render_check/check.py`
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from oddnum.env import CONDITIONS  # noqa: E402

for name, cond in CONDITIONS.items():
    for asked in ("even", "odd"):
        pays = cond.pays(asked)
        flag = "CONFLICT" if cond.conflicting(asked) else "aligned/none"
        print(f"=== {name} | asked={asked} | grader pays {pays} | {flag} ===")
        print(cond.render(asked))
        print()
