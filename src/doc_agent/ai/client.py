"""Wrapper around the Anthropic Messages API.

Phase 1 surface:
  - `ping()` — small connectivity probe.
  - `chat(messages, system=...)` — multi-turn chat, blocking, returns ChatResult.
  - `chat_stream(messages, on_text=..., system=...)` — streaming chat; calls back
    on each text chunk, returns the final ChatResult once the stream ends.

Retries are applied automatically to transient errors (rate limits, connection
drops, 5xx). Non-retryable errors (auth, bad request) propagate immediately.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from doc_agent.config import settings
from doc_agent.utils.logger import get_logger

log = get_logger(__name__)

# Transient errors we retry with exponential backoff.
RETRYABLE = (
    RateLimitError,
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
)


@dataclass
class PingResult:
    """Outcome of a connectivity probe."""

    ok: bool
    model: str
    latency_ms: float
    error: str | None = None
    reply: str | None = None


@dataclass
class ChatResult:
    """Outcome of a chat call."""

    ok: bool
    text: str
    model: str
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    raw: object | None = field(default=None, repr=False)


class AIClient:
    """Anthropic Messages API client."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 4,
        base_retry_delay: float = 1.0,
    ) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Put it in your .env file or "
                "export it before running doc-agent commands."
            )
        self._client = Anthropic(api_key=key, base_url=settings.anthropic_base_url)
        self.model = model or settings.ai_model
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay

    # ----- retry helper ----------------------------------------------------
    def _with_retry(self, fn: Callable, *, what: str = "API call"):
        """Call fn(); retry on transient errors with exponential backoff."""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return fn()
            except RETRYABLE as e:
                last_exc = e
                if attempt + 1 >= self.max_retries:
                    break
                delay = self.base_retry_delay * (2**attempt)
                log.warning(
                    "%s failed (attempt %d/%d): %s. Retrying in %.1fs",
                    what,
                    attempt + 1,
                    self.max_retries,
                    type(e).__name__,
                    delay,
                )
                time.sleep(delay)
            except (AuthenticationError, BadRequestError):
                raise  # non-retryable, surface immediately
            except APIStatusError as e:
                # Retry 5xx, fail fast on 4xx
                if 500 <= getattr(e, "status_code", 0) < 600 and attempt + 1 < self.max_retries:
                    last_exc = e
                    delay = self.base_retry_delay * (2**attempt)
                    log.warning("%s status %s — retrying in %.1fs", what, e.status_code, delay)
                    time.sleep(delay)
                    continue
                raise
        assert last_exc is not None  # for type checkers
        raise last_exc

    # ----- ping ------------------------------------------------------------
    def ping(self, prompt: str = "Reply with the single word: pong") -> PingResult:
        """Send a tiny message and return latency + reply."""
        t0 = time.perf_counter()
        try:
            resp = self._with_retry(
                lambda: self._client.messages.create(
                    model=self.model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": prompt}],
                ),
                what="ping",
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

    # ----- chat (blocking) -------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        model: str | None = None,
    ) -> ChatResult:
        """Send a multi-turn chat request and return the final reply.

        `messages` must contain only user/assistant turns — pass the system
        prompt separately via `system` (Anthropic carries it as a top-level field).
        """
        t0 = time.perf_counter()
        kwargs: dict = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            resp = self._with_retry(
                lambda: self._client.messages.create(**kwargs), what="chat"
            )
            text = "".join(block.text for block in resp.content if block.type == "text")
            usage = resp.usage
            return ChatResult(
                ok=True,
                text=text,
                model=resp.model,
                stop_reason=resp.stop_reason or "",
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                latency_ms=(time.perf_counter() - t0) * 1000,
                raw=resp,
            )
        except Exception as e:
            log.debug("Chat call failed", exc_info=True)
            return ChatResult(
                ok=False,
                text="",
                model=kwargs["model"],
                latency_ms=(time.perf_counter() - t0) * 1000,
                error=f"{type(e).__name__}: {e}",
            )

    # ----- chat (streaming) ------------------------------------------------
    def chat_stream(
        self,
        messages: list[dict],
        *,
        on_text: Callable[[str], None] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        model: str | None = None,
    ) -> ChatResult:
        """Streaming chat. `on_text` is invoked for each text chunk as it arrives.

        Returns a ChatResult with the full assembled text and usage stats.
        Streaming is *not* automatically retried — if the stream fails partway,
        the caller decides whether to retry. Initial connection errors before
        any chunks arrive will surface as ChatResult(ok=False, ...).
        """
        t0 = time.perf_counter()
        kwargs: dict = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature

        text_parts: list[str] = []
        try:
            with self._client.messages.stream(**kwargs) as stream:
                for chunk in stream.text_stream:
                    text_parts.append(chunk)
                    if on_text:
                        on_text(chunk)
                final = stream.get_final_message()
            usage = final.usage
            return ChatResult(
                ok=True,
                text="".join(text_parts),
                model=final.model,
                stop_reason=final.stop_reason or "",
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                latency_ms=(time.perf_counter() - t0) * 1000,
                raw=final,
            )
        except Exception as e:
            log.debug("Streaming chat failed", exc_info=True)
            return ChatResult(
                ok=False,
                text="".join(text_parts),  # whatever we got before the failure
                model=kwargs["model"],
                latency_ms=(time.perf_counter() - t0) * 1000,
                error=f"{type(e).__name__}: {e}",
            )
