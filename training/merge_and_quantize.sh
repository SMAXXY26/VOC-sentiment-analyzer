#!/usr/bin/env bash
# Full post-training pipeline: merge LoRA → quantize to AWQ → smoke test with vLLM
# Run from the project root: bash training/merge_and_quantize.sh
set -e

ADAPTER=${1:-training/checkpoints/dpo-adapter}
MERGED=training/merged
QUANTIZED=training/quantized
CALIB=training/data/sft.jsonl

echo "=== Step 1: Merge LoRA adapter into full BF16 model ==="
python training/merge_lora.py --adapter "$ADAPTER" --out "$MERGED"

echo ""
echo "=== Step 2: Quantize to AWQ 4-bit ==="
python training/quantize_awq.py --model "$MERGED" --out "$QUANTIZED" --calib-data "$CALIB"

echo ""
echo "=== Step 3: Smoke test — list model files ==="
ls -lh "$QUANTIZED"

echo ""
echo "=== Ready to serve ==="
echo "Run vLLM with:"
echo "  vllm serve $QUANTIZED \\"
echo "    --quantization awq_marlin \\"
echo "    --max-model-len 1024 \\"
echo "    --gpu-memory-utilization 0.82 \\"
echo "    --dtype half --max-num-seqs 2 --enforce-eager"
echo ""
echo "Then benchmark:"
echo "  conda run -n ml_env python tests/benchmark_vllm.py --out tests/results_finetuned.json"
