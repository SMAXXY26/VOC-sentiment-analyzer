"""Build a curated *golden* DPO preference set from the repo's own labelled data.

`export_dpo_data.py` mines the live `review_queue` for human corrections — but that
queue is empty until reviewers submit corrections via POST /review/<id>. This script
bootstraps DPO with a hand-curated golden set built entirely from data already in the
repo, so you can run `dpo_train.py` today.

Sources (both already in the tree):
  - eval/data/cx_eval.jsonl        16 hand-labelled gold items (text/category/sentiment/escalate)
  - vectordb/seeds/examples.json    8 seed examples (richer: intensity/risk_level/churn/emotions)

For every item:
  chosen   = a full, schema-valid analysis consistent with the gold label
  rejected = chosen with ONE realistic, named error applied — the failure modes the
             7B AWQ model actually exhibits (see eval/README.md: escalate_accuracy is
             the weakest dimension at 68.8%, and real output drifts off-taxonomy, e.g.
             the "Returns & Refunds" category seen in results_clothing.json).

Output is byte-compatible with export_dpo_data.py (same SYSTEM_PROMPT, ChatML prompt,
and compact JSON), so golden pairs and live review-queue corrections can be concatenated
into one dpo.jsonl.

Usage:
    python training/golden_dpo.py --out training/data/dpo.jsonl
    python training/golden_dpo.py --append --out training/data/dpo.jsonl   # add to existing
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Kept identical to export_dpo_data.py so the two data sources are interchangeable.
SYSTEM_PROMPT = """You are a Customer Experience (CX) analyst. Given a raw customer feedback message, analyze it and return a structured JSON analysis with the following fields:

{
  "taxonomy": {"category": "...", "subcategory": "...", "confidence": 0.0},
  "sentiment": {"sentiment": "...", "emotions": [], "intensity": 0},
  "signals": {"churn_risk": false, "upsell_opportunity": false, "feature_requests": [], "bug_reports": [], "competitor_mentions": []},
  "risk": {"escalate": false, "risk_level": "...", "reason": "...", "suggested_action": "..."}
}

Return only the JSON object."""

# Schema taxonomy (analyzer/schemas.py: TaxonomyCategory Literal). The golden set only
# ever puts these in `chosen`; off-list values appear only in `rejected` as drift errors.
VALID_CATEGORIES = {"Billing", "Product", "Support", "Shipping", "Account", "Onboarding", "Other"}

# Seed-file categories -> schema categories (the seed file predates the Literal).
SEED_CATEGORY_MAP = {
    "Billing": "Billing",
    "Product Quality": "Product",
    "Technical Issue": "Product",
    "Onboarding": "Onboarding",
    "Account Management": "Account",
    "Customer Support": "Support",
}


def build_prompt(raw_text: str) -> str:
    return f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n{raw_text}<|im_end|>\n<|im_start|>assistant\n"


def slim(analysis: dict) -> str:
    """Compact JSON, same shape/ordering convention as export_dpo_data.slim_analysis."""
    keep = {k: analysis.get(k, {}) for k in ("taxonomy", "sentiment", "signals", "risk")}
    return json.dumps(keep, separators=(",", ":"))


def A(category, subcategory, confidence, sentiment, emotions, intensity,
      churn_risk, upsell, feature_requests, bug_reports, competitor_mentions,
      escalate, risk_level, reason, suggested_action) -> dict:
    """Assemble a full schema-valid analysis (the `chosen` answer)."""
    return {
        "taxonomy": {"category": category, "subcategory": subcategory, "confidence": confidence},
        "sentiment": {"sentiment": sentiment, "emotions": emotions, "intensity": intensity},
        "signals": {
            "churn_risk": churn_risk,
            "upsell_opportunity": upsell,
            "feature_requests": feature_requests,
            "bug_reports": bug_reports,
            "competitor_mentions": competitor_mentions,
        },
        "risk": {
            "escalate": escalate,
            "risk_level": risk_level,
            "reason": reason,
            "suggested_action": suggested_action,
        },
    }


def perturb(chosen: dict, changes: dict) -> dict:
    """Produce a `rejected` analysis by applying dotted-path overrides to a copy of `chosen`.

    e.g. {"risk.escalate": False, "taxonomy.category": "Returns & Refunds"}
    """
    rej = copy.deepcopy(chosen)
    for dotted, value in changes.items():
        section, field = dotted.split(".")
        rej[section][field] = value
    return rej


# ----------------------------------------------------------------------------------
# GOLDEN PAIRS — every `chosen` is grounded in eval/data/cx_eval.jsonl or the seed file.
# `error` names the realistic failure mode; `changes` is how `rejected` diverges.
# ----------------------------------------------------------------------------------
GOLDEN: list[dict] = [
    # ---- eval/data/cx_eval.jsonl (gold category/sentiment/escalate asserted below) ----
    {
        "text": "I was charged twice for the same order and no one will respond to my emails.",
        "chosen": A("Billing", "Duplicate Charge", 0.95, "negative", ["frustrated", "angry"], 8,
                    True, False, [], [], [], True, "high",
                    "Double charge plus no support response — financial harm and churn risk.",
                    "Refund the duplicate charge and have an agent reply within the hour."),
        "error": "under-escalation: model leaves a billed-twice + ignored customer un-escalated",
        "changes": {"risk.escalate": False, "risk.risk_level": "medium", "signals.churn_risk": False},
    },
    {
        "text": "How do I update the credit card on file for my subscription?",
        "chosen": A("Billing", "Payment Method Update", 0.9, "neutral", ["neutral"], 2,
                    False, False, [], [], [], False, "low",
                    "Routine self-service billing question, no dissatisfaction.",
                    "Send the link to update the payment method in account settings."),
        "error": "over-escalation: a calm how-to is treated as urgent",
        "changes": {"risk.escalate": True, "risk.risk_level": "high", "sentiment.sentiment": "negative"},
    },
    {
        "text": "The headphones stopped working after three days, the left ear is completely dead.",
        "chosen": A("Product", "Defective Unit", 0.92, "negative", ["disappointed", "frustrated"], 6,
                    False, False, [], ["Left ear of headphones dead after three days"], [], False, "medium",
                    "Early product failure; warranty/replacement path, not an emergency.",
                    "Offer a warranty replacement and a prepaid return label."),
        "error": "over-escalation: ordinary defect escalated as critical",
        "changes": {"risk.escalate": True, "risk.risk_level": "high"},
    },
    {
        "text": "Honestly the build quality is fantastic, best purchase I've made all year.",
        "chosen": A("Product", "Quality Praise", 0.95, "positive", ["happy", "satisfied"], 7,
                    False, True, [], [], [], False, "low",
                    "Strong unsolicited praise; promoter and upsell candidate.",
                    "Thank the customer and invite a review or referral."),
        "error": "missed upsell + wrong sentiment on clear praise",
        "changes": {"sentiment.sentiment": "neutral", "signals.upsell_opportunity": False},
    },
    {
        "text": "Your support agent was incredibly patient and solved my issue in five minutes.",
        "chosen": A("Support", "Positive Feedback", 0.95, "positive", ["grateful", "satisfied"], 7,
                    False, False, [], [], [], False, "low",
                    "Praise for a support interaction; no action needed beyond acknowledgement.",
                    "Pass the kudos to the agent and close."),
        "error": "category confusion: support praise filed under Product",
        "changes": {"taxonomy.category": "Product"},
    },
    {
        "text": "I've been on hold for two hours and got hung up on twice. This is unacceptable.",
        "chosen": A("Support", "Long Wait / Dropped Call", 0.93, "negative", ["angry", "frustrated"], 8,
                    True, False, [], [], [], True, "high",
                    "Repeated failed contact attempts and explicit anger — high churn risk.",
                    "Call the customer back directly and prioritise resolution."),
        "error": "under-escalation: the model's weakest dimension (68.8% on eval)",
        "changes": {"risk.escalate": False, "risk.risk_level": "medium", "signals.churn_risk": False},
    },
    {
        "text": "My package says delivered but it never arrived at my address.",
        "chosen": A("Shipping", "Lost / Misdelivered Package", 0.9, "negative", ["confused", "frustrated"], 5,
                    False, False, [], [], [], False, "medium",
                    "Delivery discrepancy needing investigation; recoverable, not an emergency.",
                    "Open a carrier trace and offer a reship or refund."),
        "error": "off-taxonomy drift: Shipping relabelled to an invented category",
        "changes": {"taxonomy.category": "Logistics", "risk.escalate": True},
    },
    {
        "text": "Can you tell me the estimated delivery date for order 48213?",
        "chosen": A("Shipping", "Delivery ETA Inquiry", 0.92, "neutral", ["neutral"], 2,
                    False, False, [], [], [], False, "low",
                    "Plain order-status question, no sentiment signal.",
                    "Provide the tracking link and ETA for the order."),
        "error": "over-escalation of a neutral status query",
        "changes": {"sentiment.sentiment": "negative", "risk.escalate": True, "risk.risk_level": "high"},
    },
    {
        "text": "Shipping took three weeks longer than promised and the box was crushed.",
        "chosen": A("Shipping", "Late Delivery / Damaged Packaging", 0.9, "negative", ["disappointed", "annoyed"], 5,
                    False, False, [], ["Box arrived crushed"], [], False, "medium",
                    "Service shortfall but resolvable with a goodwill gesture.",
                    "Apologise, offer a partial credit, and flag the carrier."),
        "error": "over-escalation: a recoverable shipping complaint marked critical",
        "changes": {"risk.escalate": True, "risk.risk_level": "critical"},
    },
    {
        "text": "I can't log into my account, the password reset email never arrives.",
        "chosen": A("Account", "Login / Password Reset", 0.9, "negative", ["frustrated"], 5,
                    False, False, [], ["Password reset email not delivered"], [], False, "medium",
                    "Access blocker; fixable via support, no escalation yet.",
                    "Manually trigger a reset and verify the email is not bouncing."),
        "error": "category confusion: account access issue misfiled as Support",
        "changes": {"taxonomy.category": "Support"},
    },
    {
        "text": "Please close my account and delete all of my personal data permanently.",
        "chosen": A("Account", "Data Deletion Request", 0.95, "negative", ["resigned", "firm"], 5,
                    True, False, [], [], [], True, "high",
                    "Explicit GDPR/erasure + closure request — compliance-sensitive and terminal churn.",
                    "Route to the privacy/compliance team and confirm deletion within SLA."),
        "error": "under-escalation: compliance/erasure request not escalated",
        "changes": {"risk.escalate": False, "risk.risk_level": "low", "signals.churn_risk": False},
    },
    {
        "text": "The setup wizard was confusing and I gave up halfway through onboarding.",
        "chosen": A("Onboarding", "Setup Friction", 0.9, "negative", ["confused", "frustrated"], 5,
                    True, False, [], [], [], False, "medium",
                    "Abandoned onboarding is a leading churn indicator but not an emergency.",
                    "Proactively offer a guided setup session before they lapse."),
        "error": "over-escalation while also missing the real churn signal",
        "changes": {"risk.escalate": True, "risk.risk_level": "high", "signals.churn_risk": False},
    },
    {
        "text": "Loved how quick it was to get started, the tutorial walked me through everything.",
        "chosen": A("Onboarding", "Smooth Onboarding", 0.95, "positive", ["happy", "satisfied"], 7,
                    False, True, [], [], [], False, "low",
                    "Successful activation and praise; good expansion moment.",
                    "Acknowledge and surface relevant next-step features."),
        "error": "sentiment misread of clear positive onboarding feedback",
        "changes": {"sentiment.sentiment": "neutral", "signals.upsell_opportunity": False},
    },
    {
        "text": "I'm fine, I just want to cancel my plan before the next billing cycle.",
        "chosen": A("Billing", "Cancellation Request", 0.9, "neutral", ["calm"], 3,
                    True, False, [], [], [], False, "medium",
                    "Calm but explicit cancellation — churn is certain, tone is not hostile.",
                    "Process the cancellation and offer a retention option without pressure."),
        "error": "sentiment trap: 'I'm fine' read as negative + falsely escalated",
        "changes": {"sentiment.sentiment": "negative", "risk.escalate": True, "risk.risk_level": "high"},
    },
    {
        "text": "This is the third defective unit you've sent me. I'm contacting my lawyer.",
        "chosen": A("Product", "Repeat Defect / Legal Threat", 0.95, "negative", ["angry", "frustrated"], 9,
                    True, False, [], ["Third defective unit received"], [], True, "critical",
                    "Repeat failures plus an explicit legal threat — top-priority churn and risk.",
                    "Escalate to a manager, replace immediately, and log the legal exposure."),
        "error": "under-escalation: legal threat downgraded (the 68.8% weak dimension)",
        "changes": {"risk.escalate": False, "risk.risk_level": "medium", "signals.churn_risk": False},
    },
    {
        "text": "Just confirming the warranty covers accidental damage, is that right?",
        "chosen": A("Support", "Warranty Clarification", 0.9, "neutral", ["neutral"], 2,
                    False, False, [], [], [], False, "low",
                    "Pre-sale/coverage clarification with no dissatisfaction.",
                    "Confirm the warranty terms for accidental damage."),
        "error": "over-escalation of a neutral coverage question",
        "changes": {"risk.escalate": True, "risk.risk_level": "medium", "sentiment.sentiment": "negative"},
    },

    # ---- vectordb/seeds/examples.json (richer labels reused directly) ----
    {
        "text": "I was charged twice for my subscription this month and support hasn't responded in 3 days. I'm going to cancel if this isn't fixed immediately.",
        "chosen": A("Billing", "Duplicate Charge", 0.95, "negative", ["frustrated", "angry"], 9,
                    True, False, [], [], [], True, "high",
                    "Double-charge, 3 days of silence, explicit cancellation threat.",
                    "Refund now and have a human respond same-day to retain the account."),
        "error": "missed churn signal despite an explicit cancellation threat",
        "changes": {"signals.churn_risk": False, "risk.escalate": False},
    },
    {
        "text": "The new dashboard is fantastic! Exactly what I needed. Would love a dark mode option and ability to export to Excel.",
        "chosen": A("Product", "Feature Request", 0.92, "positive", ["happy", "satisfied"], 7,
                    False, True, ["Dark mode", "Excel export"], [], [], False, "low",
                    "Happy customer volunteering concrete feature requests.",
                    "Thank them and log dark mode + Excel export to the roadmap."),
        "error": "dropped the feature_requests extraction (signals emptied)",
        "changes": {"signals.feature_requests": [], "signals.upsell_opportunity": False},
    },
    {
        "text": "App crashes every time I try to generate a report on iOS. This has been happening for two weeks and is blocking my entire team.",
        "chosen": A("Product", "App Crash", 0.93, "negative", ["frustrated", "disappointed"], 8,
                    True, False, [], ["iOS app crashes on report generation"], [], True, "high",
                    "Reproducible crash blocking a whole team for two weeks.",
                    "File a P1 bug, give a workaround, and update the customer daily."),
        "error": "missed bug_report extraction + under-escalation of a team-blocking crash",
        "changes": {"signals.bug_reports": [], "risk.escalate": False, "risk.risk_level": "medium"},
    },
    {
        "text": "Switched from a competitor last month and the onboarding was smooth. Support team was very helpful. Happy with the decision so far.",
        "chosen": A("Onboarding", "New Customer", 0.93, "positive", ["happy", "satisfied", "grateful"], 8,
                    False, True, [], [], [], False, "low",
                    "Newly switched, positive early experience — prime expansion moment.",
                    "Welcome them and schedule a value check-in."),
        "error": "over-escalation of clearly positive onboarding feedback",
        "changes": {"risk.escalate": True, "risk.risk_level": "high", "sentiment.sentiment": "neutral"},
    },
    {
        "text": "I need a team collaboration feature urgently. My entire company uses this tool but we can't share workspaces. We're actively evaluating alternatives.",
        "chosen": A("Product", "Missing Feature", 0.9, "neutral", ["anxious", "disappointed"], 6,
                    True, False, ["Shared workspaces / team collaboration"], [], [], True, "medium",
                    "Blocking feature gap with an explicit competitor-evaluation churn signal.",
                    "Escalate to product and engage the account before they switch."),
        "error": "missed churn despite an explicit 'evaluating alternatives' statement",
        "changes": {"signals.churn_risk": False, "risk.escalate": False, "risk.risk_level": "low"},
    },
    {
        "text": "My account was locked without warning and I lost access to 2 years of historical data. This is unacceptable and I am consulting my lawyer.",
        "chosen": A("Account", "Account Lockout", 0.96, "negative", ["angry", "frustrated"], 10,
                    True, False, [], [], [], True, "critical",
                    "Lockout, data-loss claim, and a legal threat — maximum severity.",
                    "Restore access immediately, escalate to legal, and assign an owner."),
        "error": "under-escalation: critical lockout + legal threat downgraded",
        "changes": {"risk.escalate": False, "risk.risk_level": "medium", "signals.churn_risk": False},
    },
    {
        "text": "Response times from support have improved significantly over the past month. Keep it up!",
        "chosen": A("Support", "Positive Feedback", 0.93, "positive", ["satisfied", "happy"], 6,
                    False, False, [], [], [], False, "low",
                    "Positive trend feedback on support; encouragement, no action needed.",
                    "Share with the support team and close."),
        "error": "sentiment misread of encouragement as negative complaint",
        "changes": {"sentiment.sentiment": "negative", "risk.escalate": True},
    },
    {
        "text": "The pricing is too high compared to competitors offering similar features. Considering downgrading.",
        "chosen": A("Billing", "Pricing Concern", 0.9, "negative", ["dissatisfied", "hesitant"], 6,
                    True, False, [], [], ["competitors"], False, "medium",
                    "Price-driven downgrade consideration with a competitor comparison — churn risk.",
                    "Offer a value review or right-sized plan before they downgrade."),
        "error": "missed churn + dropped competitor_mention on a price-comparison complaint",
        "changes": {"signals.churn_risk": False, "signals.competitor_mentions": []},
    },
]


def _load_gold_labels(repo_root: str) -> dict[str, dict]:
    """Map gold text -> {category, sentiment, escalate} from the eval set, for cross-checking."""
    path = os.path.join(repo_root, "eval", "data", "cx_eval.jsonl")
    labels: dict[str, dict] = {}
    if not os.path.exists(path):
        return labels
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            labels[row["text"].strip()] = row
    return labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="training/data/dpo.jsonl")
    parser.add_argument("--append", action="store_true", help="Append to --out instead of overwriting")
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        from training._report import banner, step, summary, warn
    except Exception:  # allow running without rich installed
        def banner(t, s=""): print(f"== {t} == {s}")
        def step(m): print(f" - {m}")
        def warn(m): print(f" ! {m}")
        def summary(t, **k): print(t, k)

    banner("Golden DPO set", "eval gold set + seed examples → chosen/rejected pairs")

    gold_labels = _load_gold_labels(repo_root)
    step(f"Loaded {len(gold_labels)} gold labels from eval/data/cx_eval.jsonl for cross-check")

    # Integrity checks: chosen must be schema-valid and must not contradict gold labels.
    problems = 0
    for item in GOLDEN:
        c = item["chosen"]
        cat = c["taxonomy"]["category"]
        if cat not in VALID_CATEGORIES:
            warn(f"chosen has off-taxonomy category {cat!r}: {item['text'][:50]}")
            problems += 1
        gl = gold_labels.get(item["text"].strip())
        if gl:
            for field, got in (("category", cat),
                               ("sentiment", c["sentiment"]["sentiment"]),
                               ("escalate", c["risk"]["escalate"])):
                if gl.get(field) != got:
                    warn(f"chosen.{field}={got!r} != gold {gl.get(field)!r}: {item['text'][:50]}")
                    problems += 1
        # The rejected answer must actually differ from chosen.
        if perturb(c, item["changes"]) == c:
            warn(f"rejected == chosen (no-op perturbation): {item['text'][:50]}")
            problems += 1

    if problems:
        warn(f"{problems} integrity problem(s) — fix before training.")
        sys.exit(1)

    out_path = args.out if os.path.isabs(args.out) else os.path.join(repo_root, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    mode = "a" if args.append else "w"
    with open(out_path, mode) as f:
        for item in GOLDEN:
            record = {
                "prompt": build_prompt(item["text"]),
                "chosen": slim(item["chosen"]),
                "rejected": slim(perturb(item["chosen"], item["changes"])),
            }
            f.write(json.dumps(record) + "\n")

    # Error-mode breakdown for transparency.
    from collections import Counter
    modes = Counter(item["error"].split(":")[0] for item in GOLDEN)
    summary(
        "Golden DPO export complete",
        pairs_written=len(GOLDEN),
        from_eval_gold=sum(1 for i in GOLDEN if i["text"].strip() in gold_labels),
        from_seeds=sum(1 for i in GOLDEN if i["text"].strip() not in gold_labels),
        error_modes=dict(modes),
        mode="append" if args.append else "overwrite",
        output=out_path,
    )


if __name__ == "__main__":
    main()
