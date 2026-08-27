"""Sentence resampling: the causal influence of each sentence in a reasoning trace.

Method follows Bogdan et al. as described in the Model Forensics paper: given a
completed trace with sentences s_1..s_n, resample k continuations from the prefix
s_1..s_{i-1} ("before") and k from s_1..s_i ("after"); the score of s_i is the
difference in target-behaviour rate between after and before. Sentences with the
largest scores are the strongest causal drivers.

Two implementation notes that matter:

* `before(i)` and `after(i-1)` are the same prefix, so only n+1 distributions are
  needed rather than 2n. Each is sampled once and reused, halving the cost.
* Continuations use the raw /completions endpoint with the chat template applied by
  hand, leaving the prompt open inside `<think>`. That makes the model literally
  continue the token sequence, which is what the method requires. The chat-messages
  API cannot do this: an assistant message carrying the partial reasoning produces a
  fresh trace rather than a continuation (verified in experiments/015_resampling).

Prefixes are cut at sentence boundaries located in the ORIGINAL string, so every
prefix is an exact substring and reconstruction is lossless.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
COMPLETIONS_URL = "https://openrouter.ai/api/v1/completions"

# Sentence end, or a newline/bullet boundary -- reasoning traces are often laid out
# as list items that are not terminated with a full stop.
BOUNDARY = re.compile(r"(?<=[.!?])[ \t]+|\n+")


def sentence_cuts(text: str, min_len: int = 25) -> list[int]:
    """Offsets at which the trace can be cut, one per sentence boundary.

    Segments shorter than `min_len` are merged forward. Without this, list markers
    ("1.", "-") and other fragments become their own "sentences", which wastes
    resampling budget on units that carry no content.
    """
    # Cut at m.start(), i.e. BEFORE the inter-sentence whitespace, so a prefix ends
    # on the sentence-final character. Cutting at m.end() leaves a trailing space on
    # ~2/3 of prefixes, and a prompt ending in a bare space forces the next token to
    # be a non-space-prefixed variant -- a tokenisation artefact that would add
    # prefix-dependent bias to exactly the quantity being measured.
    cuts = [m.start() for m in BOUNDARY.finditer(text)]
    if not cuts or cuts[-1] != len(text):
        cuts.append(len(text))
    out: list[int] = []
    prev = 0
    for c in cuts:
        if len(text[prev:c].strip()) >= min_len:
            out.append(c)
            prev = c
    if not out or out[-1] != len(text):
        out.append(len(text))
    return out


def refinement_order(n: int) -> list[int]:
    """Visit order over prefix indices 0..n-1: endpoints, then progressive halving.

    A left-to-right sweep that runs out of budget leaves the back of the trace
    entirely unmeasured. This order yields a coarse map of the whole trace almost
    immediately and refines it uniformly, so stopping at any point still gives a
    usable picture of where the behaviour changes.
    """
    if n <= 0:
        return []
    if n == 1:
        return [0]
    seen = {0, n - 1}
    order = [0, n - 1]
    stride = max(1, (n - 1) // 2)
    while stride >= 1:
        for i in range(0, n, stride):
            if i not in seen:
                seen.add(i)
                order.append(i)
        if stride == 1:
            break
        stride //= 2
    return order


CONTROL_TOKENS = ("<|im_start|>", "<|im_end|>", "<think>", "</think>")


def build_prompt(user_message: str, reasoning_prefix: str) -> str:
    """Qwen chat template, left open inside the thinking block.

    Raises if the prefix contains template control tokens. Traces taken from the
    `reasoning` field never do, but the raw /completions endpoint returns `</think>`
    verbatim, so a prefix reconstructed from a continuation could silently break out
    of the template and condition the model on a fabricated conversation.
    """
    for tok in CONTROL_TOKENS:
        if tok in reasoning_prefix:
            raise ValueError(f"reasoning prefix contains control token {tok!r}")
    return (f"<|im_start|>user\n{user_message}<|im_end|>\n"
            f"<|im_start|>assistant\n<think>\n{reasoning_prefix}")


class BudgetExhausted(RuntimeError):
    """Raised when the provider reports the account is out of credit."""


@dataclass
class Continuation:
    answer_text: str
    reasoning: str
    provider: str
    finish_reason: str
    error: str = ""


def continue_from(prompt: str, model: str, provider_order: list[str],
                  max_tokens: int = 3000, temperature: float = 1.0,
                  timeout: float = 240.0) -> Continuation:
    """One continuation from a mid-thought prefix. Raises BudgetExhausted on 402."""
    load_dotenv(ROOT / ".env")
    key = os.environ["OPENROUTER_API_KEY"]
    body = {
        "model": model, "prompt": prompt, "max_tokens": max_tokens,
        "temperature": temperature,
        "provider": {"order": provider_order, "allow_fallbacks": False,
                     "require_parameters": True},
    }
    try:
        r = httpx.post(COMPLETIONS_URL, headers={"Authorization": f"Bearer {key}"},
                       json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        return Continuation("", "", "", "", error=f"{type(exc).__name__}: {exc}")

    if r.status_code == 402:
        raise BudgetExhausted(r.text[:300])
    try:
        data = r.json()
    except json.JSONDecodeError:
        return Continuation("", "", "", "", error=f"HTTP {r.status_code}: {r.text[:200]}")

    if not data.get("choices"):
        msg = json.dumps(data.get("error", data))[:300]
        if "insufficient" in msg.lower() or "credit" in msg.lower():
            raise BudgetExhausted(msg)
        return Continuation("", "", "", "", error=msg)

    ch = data["choices"][0]
    return Continuation(
        answer_text=(ch.get("text") or "").strip(),
        reasoning=(ch.get("reasoning") or ""),
        provider=data.get("provider", ""),
        finish_reason=ch.get("finish_reason", ""),
    )


def scores(rates: dict[int, float]) -> dict[int, float]:
    """Resampling score per sentence: rate(after) - rate(before).

    `rates` maps prefix index (0 = empty prefix, i = through sentence i) to the
    target-behaviour rate. Sentence i scores rates[i] - rates[i-1].
    """
    return {i: rates[i] - rates[i - 1]
            for i in sorted(rates) if i > 0 and (i - 1) in rates}


def wilson_halfwidth(p: float, n: int, z: float = 1.96) -> float:
    """Rough half-width for annotating a rate estimated from n resamples."""
    if n == 0:
        return 1.0
    denom = 1 + z**2 / n
    return z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
