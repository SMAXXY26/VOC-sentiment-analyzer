"""Merge LoRA adapter into the base model weights → full BF16 model ready for quantization.

Usage:
    python training/merge_lora.py --adapter training/checkpoints/dpo-adapter --out training/merged/
    python training/merge_lora.py --adapter training/checkpoints/sft-adapter --out training/merged/
"""
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="training/checkpoints/dpo-adapter")
    parser.add_argument("--out",     default="training/merged")
    args = parser.parse_args()

    from unsloth import FastLanguageModel

    print(f"Loading adapter: {args.adapter}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.adapter,
        max_seq_length=1024,
        load_in_4bit=True,
        dtype=None,
    )

    print(f"Merging and saving full BF16 model to: {args.out}")
    model.save_pretrained_merged(
        args.out,
        tokenizer,
        save_method="merged_16bit",   # full BF16, no quantization yet
    )
    print("Done. Run quantize_awq.py next.")


if __name__ == "__main__":
    main()
