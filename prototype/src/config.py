from pathlib import Path
from typing import Final

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DATA_DIR: Final[Path] = PROJECT_ROOT / "data" / "sample_ufdr"
DB_PATH: Final[Path] = PROJECT_ROOT / "ufdr_assistant.db"
VECTOR_INDEX_PATH: Final[Path] = PROJECT_ROOT / "vector_index.joblib"
METADATA_PATH: Final[Path] = PROJECT_ROOT / "vector_metadata.json"
GRAPH_PATH: Final[Path] = PROJECT_ROOT / "graph.json"

SUSPICIOUS_TERMS: Final[list[str]] = [
    "btc",
    "bitcoin",
    "wallet",
    "crypto",
    "transfer",
    "cash",
    "broker",
]
