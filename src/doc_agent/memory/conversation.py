"""Rolling conversation history with token budgeting, pinning, and persistence."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from doc_agent.ai.tokens import estimate_tokens

Role = Literal["user", "assistant"]


@dataclass
class Message:
    """One chat turn."""

    id: int
    role: Role
    content: str
    timestamp: str  # ISO-8601 UTC
    tokens: int
    pinned: bool = False

    def to_anthropic(self) -> dict:
        """Render in the shape Anthropic's Messages API expects."""
        return {"role": self.role, "content": self.content}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        return cls(
            id=int(d["id"]),
            role=d["role"],
            content=d["content"],
            timestamp=d["timestamp"],
            tokens=int(d.get("tokens", 0)),
            pinned=bool(d.get("pinned", False)),
        )


@dataclass
class ConversationMemory:
    """Rolling chat history with token budgeting and pinning.

    Construct, then call `add()` for each turn. Use `recent()` to get a token-
    budgeted slice ready to send to the Anthropic API. Pinned messages are
    always included regardless of budget pressure.
    """

    max_history: int = 12
    max_token_budget: int = 40000
    response_token_budget: int = 8000
    persist_path: Path | None = None

    _messages: list[Message] = field(default_factory=list)
    _next_id: int = 1

    # ----- mutate ----------------------------------------------------------
    def add(self, role: Role, content: str, *, pinned: bool = False) -> Message:
        """Append a turn and return it."""
        msg = Message(
            id=self._next_id,
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            tokens=estimate_tokens(content),
            pinned=pinned,
        )
        self._messages.append(msg)
        self._next_id += 1
        return msg

    def pin(self, msg_id: int) -> bool:
        m = self._find(msg_id)
        if m is None:
            return False
        m.pinned = True
        return True

    def unpin(self, msg_id: int) -> bool:
        m = self._find(msg_id)
        if m is None:
            return False
        m.pinned = False
        return True

    def delete(self, msg_id: int) -> bool:
        for i, m in enumerate(self._messages):
            if m.id == msg_id:
                del self._messages[i]
                return True
        return False

    def clear(self, *, keep_pinned: bool = True) -> int:
        """Drop messages. Returns the number removed."""
        if keep_pinned:
            kept = [m for m in self._messages if m.pinned]
            removed = len(self._messages) - len(kept)
            self._messages = kept
        else:
            removed = len(self._messages)
            self._messages = []
        return removed

    # ----- query -----------------------------------------------------------
    def all(self) -> list[Message]:
        return list(self._messages)

    def recent(self, *, max_tokens: int | None = None) -> list[dict]:
        """Return a token-budgeted slice ready to hand to the Anthropic API.

        Pinned messages are always included (oldest-first). The remaining budget
        is filled with the most recent unpinned messages. The final order is
        chronological (by id) regardless of how the budget was allocated.
        """
        budget = max_tokens if max_tokens is not None else (
            self.max_token_budget - self.response_token_budget
        )
        budget = max(0, budget)

        pinned = [m for m in self._messages if m.pinned]
        unpinned = [m for m in self._messages if not m.pinned]

        # Pinned go in unconditionally — they're authoritative by definition
        used = sum(m.tokens for m in pinned)
        kept: list[Message] = list(pinned)

        # Walk unpinned from newest to oldest, including what fits
        for m in reversed(unpinned):
            if used + m.tokens > budget:
                continue  # skip this one but keep trying smaller older ones
            kept.append(m)
            used += m.tokens

        # Honor max_history (pinned always survive)
        kept.sort(key=lambda m: m.id)
        if self.max_history and len(kept) > self.max_history:
            pinned_ids = {m.id for m in pinned}
            forced = [m for m in kept if m.id in pinned_ids]
            tail = [m for m in kept if m.id not in pinned_ids]
            slots = max(0, self.max_history - len(forced))
            tail = tail[-slots:] if slots else []
            kept = sorted(forced + tail, key=lambda m: m.id)

        # Anthropic requires strict user/assistant alternation starting with user.
        # If trimming gave us an assistant-first sequence, drop the leading one.
        while kept and kept[0].role != "user":
            kept.pop(0)

        return [m.to_anthropic() for m in kept]

    def stats(self) -> dict:
        """Quick summary — used by `doc-agent memory show`."""
        total = sum(m.tokens for m in self._messages)
        pinned = sum(1 for m in self._messages if m.pinned)
        return {
            "messages": len(self._messages),
            "pinned": pinned,
            "tokens_total": total,
            "tokens_budget": self.max_token_budget - self.response_token_budget,
            "max_history": self.max_history,
        }

    # ----- persistence ----------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        target = path or self.persist_path
        if target is None:
            raise ValueError("No persist_path configured and no path argument passed.")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": 1,
            "max_history": self.max_history,
            "max_token_budget": self.max_token_budget,
            "response_token_budget": self.response_token_budget,
            "next_id": self._next_id,
            "messages": [m.to_dict() for m in self._messages],
        }
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Path) -> ConversationMemory:
        if not path.exists():
            return cls(persist_path=path)
        data = json.loads(path.read_text(encoding="utf-8"))
        mem = cls(
            max_history=int(data.get("max_history", 12)),
            max_token_budget=int(data.get("max_token_budget", 40000)),
            response_token_budget=int(data.get("response_token_budget", 8000)),
            persist_path=path,
        )
        mem._messages = [Message.from_dict(d) for d in data.get("messages", [])]
        mem._next_id = int(data.get("next_id", len(mem._messages) + 1))
        return mem

    # ----- internal --------------------------------------------------------
    def _find(self, msg_id: int) -> Message | None:
        for m in self._messages:
            if m.id == msg_id:
                return m
        return None

    def __iter__(self) -> Iterable[Message]:
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)
