"""QLoRA SFT — fine-tune Qwen2.5-7B-Instruct on CX analysis task using unsloth.

Requires: pip install unsloth trl datasets
Run on the full-precision base model, NOT the AWQ version.
After training, use merge_lora.py + quantize_awq.py to get back to a vLLM-ready model.

Usage:
    python training/sft_train.py --data training/data/sft.jsonl
    python training/sft_train.py --data training/data/sft.jsonl --max-steps 1  # dry run
"""
import argparse
import os

BASE_MODEL   = "Qwen/Qwen2.5-7B-Instruct"
OUTPUT_DIR   = "training/checkpoints/sft-adapter"
MAX_SEQ_LEN  = 1024   # matches vLLM --max-model-len


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data",       default="training/data/sft.jsonl")
    parser.add_argument("--model",      default=BASE_MODEL)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--max-steps",  type=int, default=-1,
                        help="Set to 1 for a dry-run smoke test")
    parser.add_argument("--epochs",     type=int, default=3)
    parser.add_argument("--lora-r",     type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    args = parser.parse_args()

    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    print(f"Loading base model: {args.model}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=MAX_SEQ_LEN,
        load_in_4bit=True,
        dtype=None,  # auto
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    print(f"Loading dataset: {args.data}")
    dataset = load_dataset("json", data_files=args.data, split="train")
    print(f"  {len(dataset)} training examples")

    def format_sharegpt(example):
        convs = example["conversations"]
        text = ""
        for turn in convs:
            role = turn["role"]
            value = turn["value"]
            if role == "system":
                text += f"<|im_start|>system\n{value}<|im_end|>\n"
            elif role == "user":
                text += f"<|im_start|>user\n{value}<|im_end|>\n"
            elif role == "assistant":
                text += f"<|im_start|>assistant\n{value}<|im_end|>\n"
        return {"text": text}

    dataset = dataset.map(format_sharegpt, remove_columns=dataset.column_names)

    training_args = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs if args.max_steps == -1 else 1,
        max_steps=args.max_steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,    # effective batch = 8
        warmup_ratio=0.05,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        fp16=not os.getenv("USE_BF16"),   # 4070 supports fp16 fine; bf16 also ok
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=2,
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LEN,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
    )

    print("Starting SFT training...")
    trainer.train()

    print(f"\nSaving adapter to {args.output_dir}")
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print("Done. Run merge_lora.py next to merge weights before quantization.")


if __name__ == "__main__":
    main()
