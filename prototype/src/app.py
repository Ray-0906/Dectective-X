from __future__ import annotations

from pathlib import Path
from typing import Optional

from os import getenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.ai.query_engine import QueryEngine
from src.ingestion.pipeline import ingest

app = FastAPI(title="UFDR Assistant Prototype", version="0.1.0")

default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
env_origins = getenv("UFDR_ALLOWED_ORIGINS")
allow_origins = (
    [origin.strip() for origin in env_origins.split(",") if origin.strip()]
    if env_origins
    else default_origins + ["http://localhost", "http://127.0.0.1"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins if allow_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    case_id: str = "CASE-01"
    data_path: Optional[str] = None
    reset: bool = True


class QueryRequest(BaseModel):
    query: str
    limit: int = 5


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
async def trigger_ingest(request: IngestRequest) -> dict:
    path = Path(request.data_path) if request.data_path else None
    stats = ingest(root=path, case_id=request.case_id, reset=request.reset)
    return {"status": "success", "ingested": stats}


@app.post("/query")
async def query(request: QueryRequest) -> dict:
    engine = QueryEngine()
    response = engine.answer(request.query, limit=request.limit)
    return {
        "query": response.query,
        "summary": response.summary,
        "messages": response.messages,
        "calls": response.calls,
        "graph_insights": response.graph_insights,
    }
