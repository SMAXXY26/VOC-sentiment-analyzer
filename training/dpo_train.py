"""DPO preference alignment — train on human-corrected chosen/rejected pairs.

Loads the SFT adapter as starting point (not the base model directly).
Requires at least a few dozen DPO pairs; run export_dpo_data.py first.

Usage:
    python training/dpo_train.py --data training/data/dpo.jsonl
    python training/dpo_train.py --data training/data/dpo.jsonl --max-steps 1  # dry run
"""
import argparse
import os

SFT_ADAPTER  = "training/checkpoints/sft-adapter"
OUTPUT_DIR   = "training/checkpoints/dpo-adapter"
MAX_SEQ_LEN  = 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data",        default="training/data/dpo.jsonl")
    parser.add_argument("--sft-adapter", default=SFT_ADAPTER,
                        help="Path to SFT LoRA adapter (starting point for DPO)")
    parser.add_argument("--output-dir",  default=OUTPUT_DIR)
    parser.add_argument("--max-steps",   type=int, default=-1)
    parser.add_argument("--epochs",      type=int, default=1)
    parser.add_argument("--beta",        type=float, default=0.1,
                        help="DPO temperature — lower = stronger preference signal")
    args = parser.parse_args()

    from datasets import load_dataset
    from trl import DPOConfig, DPOTrainer
    from unsloth import FastLanguageModel

    print(f"Loading SFT adapter from: {args.sft_adapter}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.sft_adapter,
        max_seq_length=MAX_SEQ_LEN,
        load_in_4bit=True,
        dtype=None,
    )

    # Keep LoRA trainable for DPO
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    print(f"Loading DPO dataset: {args.data}")
    dataset = load_dataset("json", data_files=args.data, split="train")
    print(f"  {len(dataset)} preference pairs")

    if len(dataset) < 10:
        print("\nWarning: fewer than 10 DPO pairs — training may be unstable.")
        print("Add more human corrections via POST /review/<feedback_id> first.")

    dpo_config = DPOConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs if args.max_steps == -1 else 1,
        max_steps=args.max_steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_ratio=0.1,
        learning_rate=5e-5,               # lower than SFT — fine adjustments only
        lr_scheduler_type="cosine",
        fp16=not os.getenv("USE_BF16"),
        logging_steps=5,
        save_strategy="epoch",
        save_total_limit=2,
        beta=args.beta,
        loss_type="sigmoid",              # standard DPO loss
        max_prompt_length=MAX_SEQ_LEN // 2,
        max_length=MAX_SEQ_LEN,
        report_to="none",
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,                   # ref_model=None uses the base frozen weights
        args=dpo_config,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )

    print("Starting DPO training...")
    trainer.train()

    print(f"\nSaving DPO adapter to {args.output_dir}")
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print("Done. Run merge_lora.py + quantize_awq.py to produce a vLLM-ready model.")


if __name__ == "__main__":
    main()
