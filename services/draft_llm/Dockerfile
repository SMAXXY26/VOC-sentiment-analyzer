FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive
# build-essential + python3-dev: AWQ's Triton GEMM kernel JIT-compiles a CUDA helper
# (driver.c) at first inference; the pytorch *runtime* base ships no C compiler, so
# without these every /v1/chat/completions 500s ("Failed to find C compiler") and the
# chatbot falls back to the human-agent message.
RUN apt-get update && apt-get install -y curl build-essential python3-dev && rm -rf /var/lib/apt/lists/*
ENV CC=gcc

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
