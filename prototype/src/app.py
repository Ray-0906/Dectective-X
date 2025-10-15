from __future__ import annotations

import shutil
from datetime import datetime
from os import getenv
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.ai.query_engine import QueryEngine
from src.ingestion.pipeline import ingest
from src.config import UPLOAD_ROOT

app = FastAPI(title="UFDR Assistant Prototype", version="0.1.0")

env_origin_list = [origin.strip() for origin in getenv("UFDR_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
allow_all = not env_origin_list

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else env_origin_list,
    allow_origin_regex=".*" if allow_all else None,
    allow_credentials=not allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXPECTED_DATA_FILES = {"contacts.csv", "messages.xml"}

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


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


def _resolve_data_root(directory: Path) -> Path:
    entries = list(directory.iterdir())
    filenames = {entry.name.lower() for entry in entries if entry.is_file()}
    if EXPECTED_DATA_FILES.issubset(filenames):
        return directory

    subdirs = [entry for entry in entries if entry.is_dir()]
    if len(subdirs) == 1:
        return _resolve_data_root(subdirs[0])

    return directory


@app.post("/upload-ufdr")
async def upload_ufdr(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must include a filename.")

    unique_dir = UPLOAD_ROOT / f"{datetime.utcnow():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
    unique_dir.mkdir(parents=True, exist_ok=True)

    temp_path = unique_dir / file.filename
    try:
        with temp_path.open("wb") as buffer:
            while True:
                chunk = await file.read(1_048_576)
                if not chunk:
                    break
                buffer.write(chunk)
    finally:
        await file.close()

    suffixes = [suffix.lower() for suffix in temp_path.suffixes]
    format_hint: Optional[str] = None

    if suffixes[-2:] == [".tar", ".gz"]:
        format_hint = "gztar"
    elif suffixes and suffixes[-1] in {".zip", ".tgz"}:
        format_hint = "zip" if suffixes[-1] == ".zip" else "gztar"
    elif suffixes and suffixes[-1] == ".ufdr":
        format_hint = "zip"
    elif suffixes and suffixes[-1] == ".tar":
        format_hint = "tar"

    extraction_root = unique_dir

    if format_hint:
        try:
            shutil.unpack_archive(str(temp_path), str(unique_dir), format=format_hint)
        except (shutil.ReadError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Failed to unpack UFDR archive: {exc}") from exc
        temp_path.unlink(missing_ok=True)
        extraction_root = _resolve_data_root(unique_dir)
    else:
        extraction_root = _resolve_data_root(unique_dir)

    return {"status": "success", "data_path": str(extraction_root)}


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
        "locations": response.locations,
        "graph_insights": response.graph_insights,
        "report": response.report,
        "narrative": response.narrative,
    }
