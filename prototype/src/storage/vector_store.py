from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from src.config import METADATA_PATH, VECTOR_INDEX_PATH


@dataclass
class VectorRecord:
    message_id: int
    content: str
    sender: str
    timestamp: str
    app_name: str | None


class VectorStore:
    def __init__(self, index_path: Path | None = None, metadata_path: Path | None = None) -> None:
        self.index_path = index_path or VECTOR_INDEX_PATH
        self.metadata_path = metadata_path or METADATA_PATH
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.nn = NearestNeighbors(metric="cosine")
        self._fitted = False
        self.metadata: list[VectorRecord] = []

    def build(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            raise ValueError("Cannot build vector index with empty records")
        texts = [record.content for record in records]
        matrix = self.vectorizer.fit_transform(texts)
        self.nn.fit(matrix)
        self.metadata = list(records)
        self._fitted = True
        self._persist(matrix)

    def _persist(self, matrix) -> None:
        VECTOR_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"vectorizer": self.vectorizer, "nn": self.nn, "matrix": matrix}, self.index_path)
        with self.metadata_path.open("w", encoding="utf-8") as fh:
            json.dump([record.__dict__ for record in self.metadata], fh, indent=2)

    def load(self) -> None:
        if not self.index_path.exists() or not self.metadata_path.exists():
            raise FileNotFoundError("Vector index files missing; run ingestion first.")
        payload = joblib.load(self.index_path)
        self.vectorizer = payload["vectorizer"]
        self.nn = payload["nn"]
        matrix = payload["matrix"]
        with self.metadata_path.open("r", encoding="utf-8") as fh:
            metadata_dicts = json.load(fh)
        self.metadata = [VectorRecord(**item) for item in metadata_dicts]
        self._fitted = True
        self._matrix = matrix  # store for querying

    def query(self, text: str, k: int = 5) -> List[VectorRecord]:
        if not self._fitted:
            raise RuntimeError("Vector index not built. Load or build before querying.")
        query_vector = self.vectorizer.transform([text])
        distances, indices = self.nn.kneighbors(query_vector, n_neighbors=min(k, len(self.metadata)))
        ranked: list[VectorRecord] = []
        for idx in indices[0]:
            ranked.append(self.metadata[idx])
        return ranked

    def iter_metadata(self) -> Iterable[VectorRecord]:
        return iter(self.metadata)
