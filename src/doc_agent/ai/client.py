"""Thin wrapper around the Anthropic Messages API.

Phase 0 surface: just enough to verify connectivity.
Phases 1+ will extend this with conversation memory, streaming, prompt caching, and tools.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from anthropic import Anthropic, APIError

from doc_agent.config import settings
from doc_agent.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class PingResult:
    """Outcome of a connectivity probe."""

    ok: bool
    model: str
    latency_ms: float
    error: str | None = None
    reply: str | None = None


class AIClient:
    """Anthropic Messages API client."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Put it in your .env file or "
                "export it before running doc-agent commands."
            )
        self._client = Anthropic(api_key=key, base_url=settings.anthropic_base_url)
        self.model = model or settings.ai_model

    def ping(self, prompt: str = "Reply with the single word: pong") -> PingResult:
        """Send a tiny message and return latency + reply.

        Used by `doc-agent ping` to verify the API key, base URL, and model
        selection are all wired correctly. Costs about 10 output tokens.
        """
        t0 = time.perf_counter()
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else ""
            return PingResult(
                ok=True,
                model=self.model,
                latency_ms=(time.perf_counter() - t0) * 1000,
                reply=text,
            )
        except APIError as e:
            log.debug("Anthropic APIError on ping", exc_info=True)
            return PingResult(
                ok=False,
                model=self.model,
                latency_ms=(time.perf_counter() - t0) * 1000,
                error=f"{type(e).__name__}: {e}",
            )
        except Exception as e:  # network errors, timeouts, etc.
            log.debug("Unexpected error on ping", exc_info=True)
            return PingResult(
                ok=False,
                model=self.model,
                latency_ms=(time.perf_counter() - t0) * 1000,
                error=f"{type(e).__name__}: {e}",
            )
