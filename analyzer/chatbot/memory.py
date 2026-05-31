"""
Token-capped conversation memory.

Hard budget: MAX_HISTORY_TOKENS (~250) worth of conversation.
Approximation: 1 token ≈ 4 characters (avoids tiktoken dependency).

Pruning strategy: when over budget, drop the oldest user+assistant pair and
fold their content into a one-line `summary` string that is prepended as a
SystemMessage. This keeps the agent aware of early context without spending tokens.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

MAX_HISTORY_TOKENS = 250   # hard ceiling for conversation history
MAX_MSG_CHARS = 400        # cap any single message before storing


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class ConversationMemory:
    messages: list[Message] = field(default_factory=list)
    # Running one-line summary of pruned turns — injected as SystemMessage context
    summary: str = ""

    # ── Write ─────────────────────────────────────────────────────────────────

    def add(self, role: Literal["user", "assistant"], content: str) -> None:
        self.messages.append(Message(role=role, content=content[:MAX_MSG_CHARS]))
        self._prune()

    def _prune(self) -> None:
        """Drop oldest pairs until we're under the token budget."""
        while self._token_count() > MAX_HISTORY_TOKENS and len(self.messages) >= 2:
            oldest = self.messages.pop(0)
            # Try to pop the matching response
            partner = self.messages.pop(0) if self.messages else None
            snippet = oldest.content[:50].replace("\n", " ")
            self.summary = f"[Earlier: {snippet}…]"

    def _token_count(self) -> int:
        total = _approx_tokens(self.summary)
        for m in self.messages:
            total += _approx_tokens(m.content)
        return total

    # ── Read ──────────────────────────────────────────────────────────────────

    def to_langchain_messages(self):
        """Convert to LangChain message objects for the agent."""
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        out = []
        if self.summary:
            out.append(SystemMessage(content=self.summary))
        for m in self.messages:
            cls = HumanMessage if m.role == "user" else AIMessage
            out.append(cls(content=m.content))
        return out

    def for_storage(self) -> str:
        """Compact representation for EOC Qdrant storage."""
        parts = ([self.summary] if self.summary else []) + [
            f"{m.role[:1].upper()}:{m.content[:60]}" for m in self.messages
        ]
        return " | ".join(parts)[:600]

    def turn_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "user")
