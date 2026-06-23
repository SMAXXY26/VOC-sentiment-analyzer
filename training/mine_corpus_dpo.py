"""Mine category-correction DPO pairs from an UNLABELLED corpus via self-correction.

observe_dpo.py needs gold labels (it compares to eval/data/cx_eval.jsonl), so it tops out
at ~16 items. To get volume — and specifically to fix the model's habit of defaulting to
"Product" when a feedback item is ambiguous — this mines a large unlabelled CSV using
*prompt-scaffolding self-correction* (an RLAIF-style weak-supervision signal):

    rejected = the model's answer under a BARE prompt        (the biased default)
    chosen   = the model's answer under a SCAFFOLDED prompt   (explicit category
               definitions + "do not default to Product; use Other when unclear"),
               required to be STABLE across --samples re-draws

A pair is emitted only when the two DISAGREE on category. That isolates exactly the cases
where a little guidance pulls the model off a wrong default — the behaviour DPO then bakes
in so the bare model does it unprompted.

This is weak supervision, NOT ground truth: the scaffolded answer can still be wrong. The
stability filter and the disagreement filter keep only the higher-confidence corrections;
treat the output as candidate pairs to spot-check, not gospel. Best combined with the
gold-backed observe_dpo.py pairs and human review-queue corrections.

Output format matches observe_dpo.py (short decision tags: category/sentiment/escalate),
so the two observed files can be concatenated.

Usage:
    python training/mine_corpus_dpo.py --csv data.csv --limit 80 --out training/data/dpo_corpus.jsonl
    python training/mine_corpus_dpo.py --csv data.csv --text-col "Discussion Points" --samples 3
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from typing import Literal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel  # noqa: E402


class Decision(BaseModel):
    category: Literal["Billing", "Product", "Support", "Shipping", "Account", "Onboarding", "Other"]
    sentiment: Literal["positive", "negative", "neutral"]
    escalate: bool


BARE_SYS = "You are a CX analyst. Classify the customer feedback."

# The scaffold spells out the category boundaries and explicitly disarms the Product
# default — the single correction this miner is built to surface.
SCAFFOLD_SYS = (
    "You are a CX analyst. Classify the customer feedback into exactly one category:\n"
    "- Billing: orders, purchase, pricing, invoices, payments, procurement, refunds\n"
    "- Product: the physical product/goods itself — quality, defects, specs, features\n"
    "- Support: help interactions, response time, service quality\n"
    "- Shipping: delivery, logistics, dispatch, packaging\n"
    "- Account: login, access, account/data management\n"
    "- Onboarding: getting started, setup, a new customer's first experience\n"
    "- Other: anything that does not clearly fit the above\n"
    "Do NOT default to Product. Choose Product only when the feedback is specifically about "
    "the product/goods. If the topic is administrative, commercial, or unclear, choose the "
    "best fit above or Other."
)

PROMPT_TMPL = (
    "<|im_start|>system\n" + SCAFFOLD_SYS + "<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
)

JUNK = {"", "xyz", "na", "n/a", "none", "-", "nil", "test"}


def _decision_json(d: Decision) -> str:
    return json.dumps({"category": d.category, "sentiment": d.sentiment, "escalate": d.escalate}, separators=(",", ":"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="data.csv")
    p.add_argument(
        "--text-col",
        default="Discussion Points",
        help="column holding the free-text feedback (default: 'Discussion Points')",
    )
    p.add_argument("--url", default=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"))
    p.add_argument("--out", default="training/data/dpo_corpus.jsonl")
    p.add_argument("--append", action="store_true")
    p.add_argument("--limit", type=int, default=80, help="max corpus rows to process")
    p.add_argument("--samples", type=int, default=3, help="scaffolded re-draws; chosen must be stable across them")
    p.add_argument("--temp", type=float, default=0.4, help="temperature for the stability re-draws")
    p.add_argument("--min-chars", type=int, default=15)
    args = p.parse_args()

    os.environ.setdefault("VLLM_BASE_URL", args.url)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    from langchain_core.messages import HumanMessage, SystemMessage

    from analyzer.llm import get_llm

    try:
        from training._report import banner, step, summary, warn
    except Exception:

        def banner(t, s=""):
            print(f"== {t} == {s}")

        def step(m):
            print(f" - {m}")

        def warn(m):
            print(f" ! {m}")

        def summary(t, **k):
            print(t, k)

    banner("Corpus DPO mining", "unlabelled self-correction · catches Product over-labeling")

    import urllib.request

    health = args.url.rsplit("/v1", 1)[0] + "/health"
    try:
        urllib.request.urlopen(health, timeout=4)
    except Exception as exc:
        warn(f"vLLM not reachable at {health}: {exc}")
        sys.exit(2)

    # Grammar-constrained, short-output path — same as observe_dpo.py.
    bare = get_llm(temperature=0.0).with_structured_output(Decision, method="json_schema")
    scaffold0 = get_llm(temperature=0.0).with_structured_output(Decision, method="json_schema")
    scaffoldT = get_llm(temperature=args.temp).with_structured_output(Decision, method="json_schema")

    def classify(model, sys_prompt, text, retries=3):
        for _ in range(retries):
            try:
                return model.invoke([SystemMessage(content=sys_prompt), HumanMessage(content=text)])
            except Exception:
                continue
        return None

    csv_path = args.csv if os.path.isabs(args.csv) else os.path.join(repo_root, args.csv)
    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        if args.text_col not in reader.fieldnames:
            warn(f"column {args.text_col!r} not found. Available: {reader.fieldnames}")
            sys.exit(1)
        for row in reader:
            txt = (row.get(args.text_col) or "").strip().replace("\n", " ")
            if len(txt) >= args.min_chars and txt.lower() not in JUNK:
                rows.append(txt)
            if len(rows) >= args.limit:
                break
    step(f"{len(rows)} usable rows from {args.csv}::{args.text_col} (limit {args.limit})")

    pairs = []
    corrections = Counter()  # bare_category -> chosen_category
    product_fixes = 0
    skipped_unstable = 0
    skipped_agree = 0
    call_fail = 0

    for txt in rows:
        rej = classify(bare, BARE_SYS, txt)
        cho = classify(scaffold0, SCAFFOLD_SYS, txt)
        if rej is None or cho is None:
            call_fail += 1
            continue

        if rej.category == cho.category:
            skipped_agree += 1
            continue

        # Stability gate: the scaffolded category must hold across temperature re-draws.
        stable = True
        for _ in range(args.samples):
            s = classify(scaffoldT, SCAFFOLD_SYS, txt)
            if s is None or s.category != cho.category:
                stable = False
                break
        if not stable:
            skipped_unstable += 1
            continue

        pairs.append(
            {
                "prompt": PROMPT_TMPL.format(text=txt),
                "chosen": _decision_json(cho),
                "rejected": _decision_json(rej),
            }
        )
        corrections[f"{rej.category}->{cho.category}"] += 1
        if rej.category == "Product" and cho.category != "Product":
            product_fixes += 1
        step(f"[{rej.category}->{cho.category}] {txt[:55]}")

    out_path = args.out if os.path.isabs(args.out) else os.path.join(repo_root, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "a" if args.append else "w") as f:
        for rec in pairs:
            f.write(json.dumps(rec) + "\n")

    summary(
        "Corpus DPO mining complete",
        rows_processed=len(rows),
        pairs_written=len(pairs),
        product_overlabel_fixes=product_fixes,
        corrections=dict(corrections),
        skipped_agree=skipped_agree,
        skipped_unstable=skipped_unstable,
        call_failures=call_fail,
        output=out_path,
    )
    if pairs:
        warn("Weak supervision — spot-check before training. chosen = scaffolded self-label, not gold.")


if __name__ == "__main__":
    main()
