"""Mine *observed* DPO pairs by running the live model and catching its real mistakes.

Unlike golden_dpo.py (hand-crafted `rejected`), this asks the actual served model — via
the same guided/structured-output path the production pipeline uses (get_llm +
with_structured_output) — to decide the three gold-labelled dimensions:

    category · sentiment · escalate

Where the model's decision disagrees with the gold label it emits a minimal contrastive
pair:

    rejected = the model's actual decision      ← what it really got wrong
    chosen   = the gold decision                ← the correction

WHY a small decision schema and not the full analysis: vLLM here runs at
--max-model-len 1024 (see CLAUDE.md). The full 4-section analysis rambles past that cap
under structured output (LengthFinishReasonError) — the CombinedClassification stage was
designed for --max-model-len 2048. The three gold dimensions are tiny and always close
inside 1024, so we can observe real errors today without restarting vLLM. The escalate
dimension is the documented weak spot (eval/README.md: 68.8%), which is exactly what DPO
targets.

It also measures *ambiguity*: each item is sampled `--samples` times at non-zero
temperature; if the decision flips across samples the item is unstable — a high-value DPO
target. Ambiguity is reported and (optionally) the unstable items are prioritised.

Output is decision-format JSONL ({prompt, chosen, rejected} where chosen/rejected are the
small decision JSON). It is a *separate* file from the full-schema golden set — do not
concatenate the two formats into one training run.

Usage:
    python training/observe_dpo.py --out training/data/dpo_observed.jsonl
    python training/observe_dpo.py --samples 5            # also quantify ambiguity
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Literal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel  # noqa: E402

# Same taxonomy/sentiment vocab as analyzer/schemas.py.
CATEGORIES = ("Billing", "Product", "Support", "Shipping", "Account", "Onboarding", "Other")


class Decision(BaseModel):
    """Tiny schema: always closes inside the 1024-token budget."""
    category: Literal["Billing", "Product", "Support", "Shipping", "Account", "Onboarding", "Other"]
    sentiment: Literal["positive", "negative", "neutral"]
    escalate: bool


# IMPORTANT: keep this prompt SHORT. This vLLM build has no working guided decoding
# (guided_json/guided_choice/tool-calling all free-run), so output is bounded only by the
# token budget. A long prompt eats the 1024 ceiling and the AWQ model rambles to the cap
# (LengthFinishReasonError). Measured yield: short prompt = 15/16 vs long prompt = 3/16.
DECISION_SYS = "You are a CX analyst. Classify the customer feedback."

# The prompt baked into each DPO record. Mirrors DECISION_SYS so the trained behaviour
# matches what we measured.
PROMPT_TMPL = (
    "<|im_start|>system\n" + DECISION_SYS + "<|im_end|>\n"
    "<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
)


def _decision_json(category: str, sentiment: str, escalate: bool) -> str:
    return json.dumps({"category": category, "sentiment": sentiment, "escalate": escalate},
                      separators=(",", ":"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"))
    p.add_argument("--eval-file", default="eval/data/cx_eval.jsonl")
    p.add_argument("--out", default="training/data/dpo_observed.jsonl")
    p.add_argument("--append", action="store_true")
    p.add_argument("--samples", type=int, default=0,
                   help="extra samples per item at --temp to measure decision ambiguity (0 = skip)")
    p.add_argument("--temp", type=float, default=0.7)
    args = p.parse_args()

    os.environ.setdefault("VLLM_BASE_URL", args.url)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    from langchain_core.messages import HumanMessage, SystemMessage

    from analyzer.llm import get_llm

    try:
        from training._report import banner, step, summary, warn
    except Exception:
        def banner(t, s=""): print(f"== {t} == {s}")
        def step(m): print(f" - {m}")
        def warn(m): print(f" ! {m}")
        def summary(t, **k): print(t, k)

    banner("Observed DPO mining", f"decision schema · {args.url}")

    # Fail fast if the endpoint is down — we never fabricate observations.
    import urllib.request
    health = args.url.rsplit("/v1", 1)[0] + "/health"
    try:
        urllib.request.urlopen(health, timeout=4)
    except Exception as exc:
        warn(f"vLLM endpoint not reachable at {health}: {exc}")
        warn("Start vLLM on the dev laptop (see CLAUDE.md) then re-run.")
        sys.exit(2)

    with open(os.path.join(repo_root, args.eval_file)) as f:
        items = [json.loads(line) for line in f if line.strip()]
    step(f"{len(items)} gold items from {args.eval_file}")

    # method="json_schema" routes through vLLM's native response_format/xgrammar grammar.
    # This is the ballooning-proof path: the grammar forces the JSON to close, so output
    # stays short and cannot free-run to the token cap (unlike the default function_calling
    # path, which needs --enable-auto-tool-choice/--tool-call-parser and otherwise emits
    # <tool_call> garbage on this server).
    greedy = get_llm(temperature=0.0).with_structured_output(Decision, method="json_schema")
    sampler = (get_llm(temperature=args.temp).with_structured_output(Decision, method="json_schema")
               if args.samples else None)

    def classify(model, text, retries: int = 3) -> Decision | None:
        # Retry the occasional LengthFinishReasonError: greedy decode on this AWQ build is
        # not bit-deterministic, so a re-call usually closes cleanly.
        last = ""
        for _ in range(retries):
            try:
                return model.invoke([SystemMessage(content=DECISION_SYS), HumanMessage(content=text)])
            except Exception as exc:
                last = type(exc).__name__
        step(f"   call failed after {retries} tries: {last}")
        return None

    pairs = []
    diverged_dims = Counter()
    call_fail = 0
    ambiguity_rows = []

    for item in items:
        t0 = time.perf_counter()
        d = classify(greedy, item["text"])
        latency = (time.perf_counter() - t0) * 1000
        if d is None:
            call_fail += 1
            continue

        diverged = []
        if d.category.lower() != item["category"].lower():
            diverged.append(f"category({d.category}->{item['category']})")
            diverged_dims["category"] += 1
        if d.sentiment.lower() != item["sentiment"].lower():
            diverged.append(f"sentiment({d.sentiment}->{item['sentiment']})")
            diverged_dims["sentiment"] += 1
        if bool(d.escalate) != bool(item["escalate"]):
            diverged.append(f"escalate({d.escalate}->{item['escalate']})")
            diverged_dims["escalate"] += 1

        if diverged:
            pairs.append({
                "prompt": PROMPT_TMPL.format(text=item["text"]),
                "chosen": _decision_json(item["category"], item["sentiment"], bool(item["escalate"])),
                "rejected": _decision_json(d.category, d.sentiment, bool(d.escalate)),
            })
            step(f"[ERROR {', '.join(diverged)}] {item['text'][:48]}")
        else:
            step(f"[ok] {item['text'][:55]} ({latency:.0f}ms)")

        # Ambiguity: how often does the greedy decision flip under sampling?
        if sampler is not None:
            decisions = [(d.category, d.sentiment, d.escalate)]
            for _ in range(args.samples):
                sd = classify(sampler, item["text"])
                if sd:
                    decisions.append((sd.category, sd.sentiment, sd.escalate))
            uniq = len(set(decisions))
            flip = round((uniq - 1) / max(len(decisions) - 1, 1), 2)
            ambiguity_rows.append((flip, uniq, item["text"][:55]))

    out_path = args.out if os.path.isabs(args.out) else os.path.join(repo_root, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "a" if args.append else "w") as f:
        for rec in pairs:
            f.write(json.dumps(rec) + "\n")

    summary(
        "Observed DPO mining complete",
        gold_items=len(items),
        observed_pairs=len(pairs),
        call_failures=call_fail,
        diverged_dimensions=dict(diverged_dims),
        output=out_path,
    )

    if ambiguity_rows:
        ambiguity_rows.sort(reverse=True)
        unstable = [r for r in ambiguity_rows if r[0] > 0]
        step(f"Ambiguity: {len(unstable)}/{len(ambiguity_rows)} items had an unstable decision across {args.samples} samples")
        for flip, uniq, text in ambiguity_rows[:10]:
            tag = "UNSTABLE" if flip > 0 else "stable  "
            step(f"  [{tag}] flip_rate={flip} distinct={uniq}  {text}")

    if not pairs:
        warn("0 observed errors — model matched gold on all three dimensions for every item.")


if __name__ == "__main__":
    main()
