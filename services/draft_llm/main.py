"""Minimal OpenAI-compatible chat completions server for AWQ models.

Exposes /v1/chat/completions and /health on port 8001.
Uses AutoAWQ + transformers — works on Turing (sm75) unlike vllm 0.22.x.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer

_MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct-AWQ"
_model = None
_tokenizer = None
_device = "cuda" if torch.cuda.is_available() else "cpu"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _tokenizer
    from awq import AutoAWQForCausalLM

    _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
    _model = AutoAWQForCausalLM.from_quantized(
        _MODEL_NAME,
        fuse_layers=False,
        trust_remote_code=False,
        safetensors=True,
    )
    yield


app = FastAPI(lifespan=lifespan)


# ── OpenAI-compatible types (subset) ──────────────────────────────────────────


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = _MODEL_NAME
    messages: list[Message]
    max_tokens: int = 170
    temperature: float = 0.3
    stream: bool = False


class Choice(BaseModel):
    index: int = 0
    message: Message
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": _MODEL_NAME, "object": "model"}]}


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
def chat_completions(req: ChatCompletionRequest):
    text = _tokenizer.apply_chat_template(
        [{"role": m.role, "content": m.content} for m in req.messages],
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = _tokenizer(text, return_tensors="pt").to(_device)
    prompt_len = inputs["input_ids"].shape[-1]

    with torch.no_grad():
        output_ids = _model.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            temperature=max(req.temperature, 1e-6),
            do_sample=req.temperature > 0.01,
            pad_token_id=_tokenizer.eos_token_id,
        )

    new_ids = output_ids[0][prompt_len:]
    reply = _tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    completion_len = len(new_ids)

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=int(time.time()),
        model=req.model,
        choices=[Choice(message=Message(role="assistant", content=reply))],
        usage=Usage(
            prompt_tokens=prompt_len,
            completion_tokens=completion_len,
            total_tokens=prompt_len + completion_len,
        ),
    )
