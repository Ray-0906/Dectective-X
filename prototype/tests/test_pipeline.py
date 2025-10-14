from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.query_engine import QueryEngine
from src.config import DB_PATH, GRAPH_PATH, METADATA_PATH, VECTOR_INDEX_PATH
from src.ingestion.pipeline import ingest, reset_storage


class PipelineIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_storage()

    def tearDown(self) -> None:
        reset_storage()

    def test_ingest_creates_artifacts(self) -> None:
        stats = ingest(reset=True)
        self.assertGreater(stats["messages"], 0)
        self.assertTrue(DB_PATH.exists())
        self.assertTrue(VECTOR_INDEX_PATH.exists())
        self.assertTrue(METADATA_PATH.exists())
        self.assertTrue(GRAPH_PATH.exists())

    def test_query_engine_returns_message(self) -> None:
        ingest(reset=True)
        engine = QueryEngine()
        response = engine.answer("show me foreign crypto messages after 10 pm")
        self.assertGreater(len(response.messages), 0)
        self.assertIn("crypto", response.summary.lower())


if __name__ == "__main__":
    unittest.main()
