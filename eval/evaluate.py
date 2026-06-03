"""Model evaluation harness — measure extraction quality, base vs fine-tuned.

The repo has SFT + DPO scripts but no way to answer "did fine-tuning actually help?".
This runs a labelled eval set (eval/data/cx_eval.jsonl) through one or more models
using the same structured-extraction prompt the SFT data was built from, parses the
JSON, and scores it against the gold labels.

Metrics per model:
  - json_valid_rate   : fraction of responses that parsed as the expected JSON
  - category_accuracy : taxonomy.category exact match
  - sentiment_accuracy: sentiment.sentiment exact match
  - escalate_accuracy : risk.escalate exact match
  - mean_latency_ms

Point it at two endpoints to compare base vs fine-tuned:

    python eval/evaluate.py \
        --model base=http://localhost:8000/v1=Qwen/Qwen2.5-7B-Instruct \
        --model ft=http://localhost:8001/v1=cx-ft-awq \
        --out eval/results.json

Single-model smoke test:

    python eval/evaluate.py --model base=http://localhost:8000/v1=Qwen/Qwen2.5-7B-Instruct-AWQ
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from training.export_sft_data import SYSTEM_PROMPT  # same prompt the model trained on  # noqa: E402

console = Console()


@dataclass
class Scores:
    n: int = 0
    json_valid: int = 0
    category_ok: int = 0
    sentiment_ok: int = 0
    escalate_ok: int = 0
    latencies_ms: list = field(default_factory=list)

    def row(self) -> dict:
        def pct(x):
            return round(100 * x / self.n, 1) if self.n else 0.0

        mean_ms = round(sum(self.latencies_ms) / len(self.latencies_ms), 1) if self.latencies_ms else 0.0
        return {
            "n": self.n,
            "json_valid_rate": pct(self.json_valid),
            "category_accuracy": pct(self.category_ok),
            "sentiment_accuracy": pct(self.sentiment_ok),
            "escalate_accuracy": pct(self.escalate_ok),
            "mean_latency_ms": mean_ms,
        }


def _parse_json(text: str) -> dict | None:
    """Best-effort: strip markdown fences and load the first JSON object."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{") :] if "{" in t else t
    try:
        return json.loads(t[t.find("{") : t.rfind("}") + 1])
    except Exception:
        return None


def _load_eval(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate_model(name: str, url: str, model: str, items: list[dict]) -> Scores:
    llm = ChatOpenAI(model=model, base_url=url, api_key="dummy", temperature=0.0, max_tokens=256)
    s = Scores()
    for item in items:
        s.n += 1
        t0 = time.perf_counter()
        try:
            resp = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=item["text"])])
            s.latencies_ms.append((time.perf_counter() - t0) * 1000)
            parsed = _parse_json(str(resp.content))
        except Exception as exc:
            console.print(f"[yellow]{name}: call failed: {str(exc)[:80]}[/yellow]")
            parsed = None

        if not parsed:
            continue
        s.json_valid += 1
        tax = parsed.get("taxonomy", {}) or {}
        sent = parsed.get("sentiment", {}) or {}
        risk = parsed.get("risk", {}) or {}
        if str(tax.get("category", "")).strip().lower() == item["category"].lower():
            s.category_ok += 1
        if str(sent.get("sentiment", "")).strip().lower() == item["sentiment"].lower():
            s.sentiment_ok += 1
        if bool(risk.get("escalate", False)) == bool(item["escalate"]):
            s.escalate_ok += 1
    return s


def _parse_model_arg(arg: str) -> tuple[str, str, str]:
    name, url, model = arg.split("=", 2)
    return name, url, model


def main():
    p = argparse.ArgumentParser(description="Evaluate CX extraction quality (base vs fine-tuned).")
    p.add_argument("--eval-file", default="eval/data/cx_eval.jsonl")
    p.add_argument("--model", action="append", required=True, help="name=base_url=model_name (repeatable)")
    p.add_argument("--out", default="eval/results.json")
    args = p.parse_args()

    items = _load_eval(args.eval_file)
    console.print(f"[bold cyan]Evaluating on {len(items)} labelled items[/bold cyan]\n")

    results = {}
    for spec in args.model:
        name, url, model = _parse_model_arg(spec)
        console.print(f"[cyan]› {name}[/cyan] ({model} @ {url})")
        results[name] = evaluate_model(name, url, model, items).row()

    table = Table(title="CX Extraction Eval", show_lines=True)
    table.add_column("Metric", style="bold")
    for name in results:
        table.add_column(name, justify="right")
    metric_keys = [
        "n",
        "json_valid_rate",
        "category_accuracy",
        "sentiment_accuracy",
        "escalate_accuracy",
        "mean_latency_ms",
    ]
    for key in metric_keys:
        table.add_row(key, *[str(results[name][key]) for name in results])
    console.print()
    console.print(table)

    # Highlight the base→ft delta when exactly two models are compared.
    if len(results) == 2:
        a, b = list(results)
        console.print(f"\n[bold]Δ ({b} − {a}):[/bold]")
        for key in metric_keys[1:]:
            d = round(results[b][key] - results[a][key], 1)
            color = "green" if (d >= 0) == ("latency" not in key) else "red"
            console.print(f"  {key:20} [{color}]{d:+}[/{color}]")

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    console.print(f"\n[green]Results written to {args.out}[/green]")


if __name__ == "__main__":
    main()
