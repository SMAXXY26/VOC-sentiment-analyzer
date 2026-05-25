### DEV STAGE — used by docker-compose for local development (GPU passthrough, code mounted)
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS dev

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3.10 python3-pip python3.10-dev \
    git curl build-essential ca-certificates \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace
CMD ["/bin/bash"]

### PROD STAGE — used by k3s (no GPU, no vllm, source code baked in)
FROM python:3.10-slim AS prod

RUN apt-get update && apt-get install -y \
    build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only torch first (~200MB vs ~2GB GPU build).
# sentence-transformers will reuse this instead of pulling the GPU wheel.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.prod.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace
COPY analyzer/ ./analyzer/
COPY vectordb/ ./vectordb/
COPY ingestion/ ./ingestion/
COPY run_pipeline.py ./

CMD ["uvicorn", "analyzer.api:app", "--host", "0.0.0.0", "--port", "8080"]
