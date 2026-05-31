"""Quantize the merged model to AWQ 4-bit using autoawq + calibration data from SFT export.

Requires: pip install autoawq
Output is a vLLM-ready model — serve with --quantization awq_marlin.

Usage:
    python training/quantize_awq.py --model training/merged/ --out training/quantized/
    python training/quantize_awq.py --model training/merged/ --out training/quantized/ \
        --calib-data training/data/sft.jsonl
"""
import argparse
import json
import random

AWQ_CONFIG = {
    "zero_point": True,
    "q_group_size": 128,
    "w_bit": 4,
    "version": "GEMM",   # GEMM for compatibility; vLLM will use Marlin kernel automatically
}


def load_calib_texts(jsonl_path: str, n: int = 128) -> list[str]:
    texts = []
    with open(jsonl_path) as f:
        for line in f:
            record = json.loads(line)
            convs = record.get("conversations", [])
            flat = " ".join(c["value"] for c in convs)
            texts.append(flat[:512])   # truncate for calibration efficiency
    random.shuffle(texts)
    return texts[:n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",      default="training/merged/")
    parser.add_argument("--out",        default="training/quantized/")
    parser.add_argument("--calib-data", default="training/data/sft.jsonl",
                        help="JSONL file to use as AWQ calibration data")
    parser.add_argument("--calib-n",    type=int, default=128,
                        help="Number of calibration samples (default: 128)")
    args = parser.parse_args()

    from awq import AutoAWQForCausalLM
    from transformers import AutoTokenizer

    print(f"Loading merged model from: {args.model}")
    model = AutoAWQForCausalLM.from_pretrained(args.model, low_cpu_mem_usage=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)

    calib_data = None
    if args.calib_data:
        try:
            calib_data = load_calib_texts(args.calib_data, args.calib_n)
            print(f"Loaded {len(calib_data)} calibration samples from {args.calib_data}")
        except FileNotFoundError:
            print(f"Calibration file not found ({args.calib_data}), using default samples")

    print(f"Quantizing to AWQ 4-bit (config: {AWQ_CONFIG})…")
    model.quantize(tokenizer, quant_config=AWQ_CONFIG, calib_data=calib_data)

    print(f"Saving quantized model to: {args.out}")
    model.save_quantized(args.out)
    tokenizer.save_pretrained(args.out)

    print("\nDone. Serve with vLLM:")
    print(f"  vllm serve {args.out} \\")
    print( "    --quantization awq_marlin \\")
    print( "    --max-model-len 1024 \\")
    print( "    --gpu-memory-utilization 0.82 \\")
    print( "    --dtype half --max-num-seqs 2 --enforce-eager")


if __name__ == "__main__":
    main()
