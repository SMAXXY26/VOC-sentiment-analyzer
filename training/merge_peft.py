"""Merge a peft LoRA adapter into its base model → full BF16 model (no unsloth).

Reads the base model id from the adapter's own adapter_config.json unless --base is given.

Usage:
    python training/merge_peft.py --adapter training/checkpoints/dpo-draft --out training/merged/dpo-draft
"""

import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="training/checkpoints/dpo-draft")
    ap.add_argument("--out", default="training/merged/dpo-draft")
    ap.add_argument("--base", default=None, help="override base model id (else read from adapter_config.json)")
    args = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    adapter = args.adapter if os.path.isabs(args.adapter) else os.path.join(repo, args.adapter)
    out = args.out if os.path.isabs(args.out) else os.path.join(repo, args.out)

    base_id = args.base
    if base_id is None:
        with open(os.path.join(adapter, "adapter_config.json")) as f:
            base_id = json.load(f)["base_model_name_or_path"]
    print(f"[merge] base: {base_id}")
    print(f"[merge] adapter: {adapter}")

    base = AutoModelForCausalLM.from_pretrained(base_id, dtype=torch.bfloat16, device_map="cpu")
    model = PeftModel.from_pretrained(base, adapter)
    print("[merge] merging adapter into base weights...")
    merged = model.merge_and_unload()

    os.makedirs(out, exist_ok=True)
    merged.save_pretrained(out, safe_serialization=True)
    AutoTokenizer.from_pretrained(base_id).save_pretrained(out)
    print(f"[merge] full BF16 model saved to: {out}")


if __name__ == "__main__":
    main()
