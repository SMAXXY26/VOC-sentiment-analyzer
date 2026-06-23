"""DPO smoke test — validate the preference-tuning pipeline on the golden pairs.

Standalone (no unsloth): trl DPOTrainer + peft LoRA, starting from the BASE model (there is
no SFT adapter). Defaults to the cached Qwen2.5-0.5B-Instruct so it runs fast in BF16 on 8GB
with no 15GB download — the point is to prove the data + training loop work end-to-end, not
to ship a model. Swap --model to the 7B base (+ 4-bit) for a real run.

Usage:
    python training/dpo_smoke.py --data training/data/dpo.jsonl
    python training/dpo_smoke.py --model Qwen/Qwen2.5-7B-Instruct --max-steps 5   # bigger base
"""

import argparse
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="training/data/dpo.jsonl")
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--output-dir", default="training/checkpoints/dpo-smoke")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=5e-5)
    args = ap.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import DPOConfig, DPOTrainer

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = args.data if os.path.isabs(args.data) else os.path.join(repo, args.data)

    print(f"[dpo-smoke] base model: {args.model}")
    tok = AutoTokenizer.from_pretrained(args.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, device_map="cuda"
    )

    ds = load_dataset("json", data_files=data_path, split="train")
    print(f"[dpo-smoke] {len(ds)} preference pairs from {args.data}")

    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    cfg = DPOConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs if args.max_steps == -1 else 1,
        max_steps=args.max_steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        beta=args.beta,
        max_length=1024,
        logging_steps=1,
        save_strategy="epoch",
        save_total_limit=1,
        bf16=True,
        report_to="none",
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,           # peft adapter → base weights serve as the frozen reference
        args=cfg,
        train_dataset=ds,
        processing_class=tok,
        peft_config=lora,
    )

    print("[dpo-smoke] training...")
    result = trainer.train()
    trainer.save_model(args.output_dir)
    print(f"[dpo-smoke] done. adapter saved to {args.output_dir}")
    print(f"[dpo-smoke] final train loss: {result.training_loss:.4f}")


if __name__ == "__main__":
    main()
