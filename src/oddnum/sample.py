"""Async OpenRouter sampling with an on-disk cache.

Every response is cached under a hash of the exact request, so re-running a stage
costs nothing and results are reproducible. The provider that actually served each
call is recorded: OpenRouter routes to third-party backends, and the same model can
land on different ones between calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv

API_URL = "https://openrouter.ai/api/v1/chat/completions"
ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "cache.db"


@dataclass(frozen=True)
class Spec:
    """One request. `tag` fields are carried through to the result for analysis."""

    model: str
    prompt: str
    condition: str
    rep: int = 0
    reasoning: bool | None = None
    max_tokens: int = 8000
    temperature: float = 1.0
    logprobs: bool = False
    top_logprobs: int | None = None
    # OpenRouter endpoint tag(s), e.g. "deepinfra/bf16", or a tuple to restrict
    # routing to a set (tried in order, no fallback outside it). Unpinned, a "model"
    # is a mixture over backends whose behaviour differs by up to 10x; note that
    # backends at the SAME declared quantisation also differ substantially, so a
    # tuple restricts the mixture rather than eliminating it
    # (see experiments/007_provider_facts/by_quant.py).
    provider_tag: str | tuple[str, ...] | None = None

    def payload(self) -> dict:
        provider: dict = {"require_parameters": True}
        if self.provider_tag is not None:
            order = ([self.provider_tag] if isinstance(self.provider_tag, str)
                     else list(self.provider_tag))
            provider |= {"order": order, "allow_fallbacks": False}
        body: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": self.prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            # Fail loudly rather than silently dropping unsupported parameters.
            "provider": provider,
        }
        if self.reasoning is not None:
            body["reasoning"] = {"enabled": self.reasoning}
        if self.logprobs:
            body["logprobs"] = True
            if self.top_logprobs is not None:
                body["top_logprobs"] = self.top_logprobs
        return body

    def key(self) -> str:
        blob = json.dumps({**self.payload(), "rep": self.rep}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class Result:
    spec: Spec
    text: str = ""
    reasoning_text: str = ""
    provider: str = ""
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)
    logprobs: list | None = None
    error: str = ""

    @property
    def reasoning_tokens(self) -> int:
        details = self.usage.get("completion_tokens_details") or {}
        return details.get("reasoning_tokens", 0)


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(CACHE_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS responses ("
        "  key TEXT PRIMARY KEY, model TEXT, condition TEXT, rep INTEGER,"
        "  response TEXT, ts REAL)"
    )
    return con


def _is_error_body(body: dict) -> str:
    """Error text if this response carries a failure, else "".

    OpenRouter returns HTTP 200 with a populated `choices` array whose *choice* holds
    the provider error (`finish_reason: "error"`, `content: null`). Checking only for
    a top-level "error" key lets those through as an empty answer that is
    indistinguishable from a genuine non-answer -- and, worse, caches them, so a
    re-run never retries.
    """
    if "error" in body and not body.get("choices"):
        return json.dumps(body["error"])[:500]
    choices = body.get("choices") or []
    if not choices:
        return json.dumps(body)[:500]
    ch = choices[0]
    if ch.get("error") or ch.get("finish_reason") == "error":
        return json.dumps(ch.get("error", "finish_reason=error"))[:500]
    return ""


def _parse(spec: Spec, body: dict) -> Result:
    err = _is_error_body(body)
    if err:
        return Result(spec, error=err)
    choice = body["choices"][0]
    msg = choice.get("message", {})
    return Result(
        spec=spec,
        text=(msg.get("content") or "").strip(),
        reasoning_text=(msg.get("reasoning") or ""),
        provider=body.get("provider", ""),
        finish_reason=choice.get("finish_reason", ""),
        usage=body.get("usage", {}) or {},
        logprobs=(choice.get("logprobs") or {}).get("content"),
    )


async def _one(client: httpx.AsyncClient, spec: Spec, sem: asyncio.Semaphore,
               con: sqlite3.Connection) -> Result:
    key = spec.key()
    row = con.execute("SELECT response FROM responses WHERE key=?", (key,)).fetchone()
    if row:
        return _parse(spec, json.loads(row[0]))

    async with sem:
        for attempt in range(5):
            try:
                r = await client.post(API_URL, json=spec.payload(), timeout=180)
                if r.status_code in (429, 500, 502, 503, 529):
                    await asyncio.sleep(2**attempt)
                    continue
                body = r.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                if attempt == 4:
                    return Result(spec, error=f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(2**attempt)
                continue
            # Only cache real answers -- never transport errors, and never a
            # provider error smuggled inside a choice (see _is_error_body).
            if not _is_error_body(body):
                con.execute(
                    "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?,?)",
                    (key, spec.model, spec.condition, spec.rep, json.dumps(body), time.time()),
                )
                con.commit()
            return _parse(spec, body)
    return Result(spec, error="exhausted retries")


async def run(specs: list[Spec], concurrency: int = 8) -> list[Result]:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set (expected in .env)")
    con = _db()
    sem = asyncio.Semaphore(concurrency)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(headers=headers) as client:
        return await asyncio.gather(*(_one(client, s, sem, con) for s in specs))


def run_sync(specs: list[Spec], concurrency: int = 8) -> list[Result]:
    return asyncio.run(run(specs, concurrency))
