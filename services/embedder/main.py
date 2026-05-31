from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    _model = SentenceTransformer(_MODEL_NAME, device="cuda")
    yield


app = FastAPI(lifespan=lifespan)


class EmbedRequest(BaseModel):
    text: str


class EmbedBatchRequest(BaseModel):
    texts: list[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/embed")
def embed(req: EmbedRequest):
    vec = _model.encode(req.text, normalize_embeddings=True).tolist()
    return {"embedding": vec}


@app.post("/embed/batch")
def embed_batch(req: EmbedBatchRequest):
    vecs = _model.encode(req.texts, normalize_embeddings=True, batch_size=64).tolist()
    return {"embeddings": vecs}
