"""Chatbot test/diagnostic harness.

The draft-only chatbot resolves all order/refund/escalation logic deterministically
in Python (analyzer.chatbot.context_router.build_context); the 1.5B model only phrases
the reply. So this harness checks two layers:

  1. CONTEXT scenarios  — build_context() produces the right EDBMS facts + actions
     for representative customer turns. Offline, deterministic (local SQLite EDBMS).
  2. Conversation flow   — start_conversation → chat → end_conversation lifecycle,
     with the draft model MOCKED so it runs anywhere (session, memory, history).

Usage:
    python -m tests.chatbot_harness            # run automated checks, exit non-zero on failure
    python -m tests.chatbot_harness --live     # phrase replies with the real draft model (needs DRAFT_LLM_URL)
    python -m tests.chatbot_harness --repl      # interactive chat against the live model

Also imported by tests/test_chatbot_harness.py so CI runs the automated checks.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.chatbot import agent  # noqa: E402
from analyzer.chatbot.context_router import build_context  # noqa: E402
from analyzer.chatbot.edbms import authenticate  # noqa: E402

# Each scenario: (label, username|None, turn, [substrings that must ALL appear in CONTEXT]).
# An empty expectation list means CONTEXT must be empty (e.g. guest / small talk).
SCENARIOS: list[tuple[str, str | None, str, list[str]]] = [
    ("order lookup", "alice", "Where is my coffee maker order?", ["Recent orders", "Coffee Maker"]),
    ("refund action", "bob", "I'd like a refund please", ["ACTION done: refund request"]),
    ("complaint action", "bob", "My order arrived damaged", ["complaint ticket", "Recent orders"]),
    ("escalation", "carol", "Let me talk to a human agent", ["escalated to a human"]),
    ("faq", "alice", "What are your delivery times?", ["FAQ[delivery_time]"]),
    ("guest / small talk", None, "hello there", []),  # no uid → empty context
]

_PASSWORD = "pass123"  # demo EDBMS password (alice/bob/carol/... all use this)


def _customer(username: str | None) -> dict:
    if username is None:
        return {"id": None, "username": "guest", "name": "guest", "tier": "guest"}
    cust = authenticate(username, _PASSWORD)
    if not cust:
        raise SystemExit(f"EDBMS auth failed for '{username}' — is the demo data seeded?")
    return cust


# ── Layer 1: deterministic CONTEXT checks ────────────────────────────────────────


def check_context_scenarios(verbose: bool = True) -> tuple[int, int]:
    passed = 0
    for label, username, turn, expected in SCENARIOS:
        cust = _customer(username)
        ctx = build_context(turn, cust)
        if expected:
            ok = all(s in ctx for s in expected)
        else:
            ok = ctx == ""
        passed += ok
        if verbose:
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {label:20s} | ctx: {ctx[:90] or '(empty)'}")
            if not ok:
                print(f"         expected all of: {expected}")
    return passed, len(SCENARIOS)


# ── Layer 2: conversation flow (model mocked) ────────────────────────────────────


class _FakeReply:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    """Stand-in for the draft ChatOpenAI: .bind(**) -> self, .invoke(msgs) -> reply."""

    def bind(self, **_kwargs):
        return self

    def invoke(self, _messages):
        return _FakeReply("[mock] Thanks for reaching out — here to help!")


def check_conversation_flow(verbose: bool = True) -> tuple[int, int]:
    checks: list[tuple[str, bool]] = []
    original = agent.get_draft_llm
    agent.get_draft_llm = lambda *a, **k: _FakeLLM()  # type: ignore[assignment]
    try:
        cust = _customer("alice")
        sid = agent.start_conversation(cust)
        checks.append(("session created", isinstance(sid, str) and len(sid) > 0))

        # Quick replies appear on the first (zero-turn) session.
        checks.append(("initial quick replies", len(agent.get_quick_replies(sid)) > 0))

        r1 = agent.chat(sid, "Hi there")
        checks.append(("reply non-empty", bool(r1.strip())))

        agent.chat(sid, "Thanks")
        hist = agent.get_history(sid)
        # 2 user + 2 assistant turns recorded.
        checks.append(("history accumulates", len(hist) >= 4))

        # No quick replies once the conversation is underway.
        checks.append(("quick replies cleared", agent.get_quick_replies(sid) == []))

        ended = agent.end_conversation(sid)
        checks.append(("end returns a status", isinstance(ended, str) and ended != ""))
        checks.append(("session cleaned up", sid not in agent._sessions))

        # Unknown session id should not raise — chat auto-creates one.
        r = agent.chat("does-not-exist", "hello")
        checks.append(("unknown session handled", bool(r.strip())))
    finally:
        agent.get_draft_llm = original  # type: ignore[assignment]

    passed = sum(ok for _, ok in checks)
    if verbose:
        for name, ok in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return passed, len(checks)


def run_all(verbose: bool = True) -> bool:
    if verbose:
        print("CONTEXT scenarios (deterministic, offline):")
    c_pass, c_total = check_context_scenarios(verbose)
    if verbose:
        print("\nConversation flow (model mocked):")
    f_pass, f_total = check_conversation_flow(verbose)
    total_pass, total = c_pass + f_pass, c_total + f_total
    if verbose:
        print(f"\nTOTAL: {total_pass}/{total} checks passed")
    return total_pass == total


# ── Live / interactive modes ─────────────────────────────────────────────────────


def live_demo() -> None:
    """Phrase replies with the real draft model for manual inspection."""
    print("LIVE mode — using the real draft model (DRAFT_LLM_URL).\n")
    for label, username, turn, _ in SCENARIOS:
        cust = _customer(username)
        sid = agent.start_conversation(cust)
        reply = agent.chat(sid, turn)
        ctx = build_context(turn, cust)
        print(f"## {label}  (user: {username or 'guest'})")
        print(f"   user : {turn}")
        print(f"   ctx  : {ctx[:120] or '(empty)'}")
        print(f"   reply: {reply}\n")
        agent.end_conversation(sid)


def repl() -> None:
    """Interactive chat against the live draft model. Ctrl-C / 'quit' to exit."""
    username = input("Login as (alice/bob/carol/dave/eve, blank=guest): ").strip() or None
    cust = _customer(username)
    sid = agent.start_conversation(cust)
    print(f"Session {sid[:8]}… as {cust['name']}. Type 'quit' to end.\n")
    try:
        while True:
            msg = input("you > ").strip()
            if msg.lower() in {"quit", "exit"}:
                break
            print(f"bot > {agent.chat(sid, msg)}\n")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        print(agent.end_conversation(sid))


def main() -> None:
    p = argparse.ArgumentParser(description="Chatbot test/diagnostic harness.")
    p.add_argument("--live", action="store_true", help="phrase replies with the real draft model")
    p.add_argument("--repl", action="store_true", help="interactive chat against the live model")
    args = p.parse_args()

    if args.repl:
        repl()
    elif args.live:
        live_demo()
    else:
        ok = run_all(verbose=True)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
