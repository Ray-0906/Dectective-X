# AI-Powered UFDR Forensic Assistant Prototype

Hackathon-ready demo that ingests Universal Forensic Data Reports (UFDRs), builds structured evidence stores, and answers investigator questions in natural language using a hybrid SQL + semantic search + knowledge graph pipeline.

Refer to the parent document [AI-Powered Forensic UFDR Assistant – Complete SIH Solution](../AI-Powered%20Forensic%20UFDR%20Assistant%20-%20Complete%20SIH.md) for extended architectural background.

## ✨ Key Capabilities

- **UFDR parsing** for contacts, chats, calls, locations, and media across XML/CSV/HTML exports.
- **Relational storage** (SQLite via SQLAlchemy) with normalized tables and provenance metadata.
- **Vector search** with TF-IDF embeddings for semantic message retrieval.
- **Knowledge graph** (NetworkX) capturing people ↔ messages ↔ keywords ↔ calls ↔ locations.
- **Rule-based NL query engine** that routes requests across SQL, vector index, and graph insights.
- **FastAPI service** exposing `/upload-ufdr` (multipart archive upload), `/ingest`, and `/query` endpoints for rapid demo and integration.
- **Dynamic query reasoning** for natural-language time ranges, foreign contact filtering, and cross-channel evidence (messages, calls, locations).
- **LLM-powered investigation reports** generated with Google Gemini when available, with a deterministic fallback summary when offline.

## 🧱 Project Layout

```
prototype/
├── data/                 # Sample UFDR bundle used during the hackathon demo
├── src/
│   ├── ingestion/        # Parsers & ingestion pipeline
│   ├── storage/          # Database, vector index, knowledge graph helpers
│   ├── ai/               # Natural language query engine
│   └── app.py            # FastAPI entrypoint
├── tests/                # Integration tests for ingestion and querying
├── requirements.txt
└── README.md
```

## 🚀 Quickstart

> Prerequisites: Python 3.11 (or compatible) + virtual environment (already configured in this workspace).

Install dependencies:

```powershell
C:/Users/astra/Desktop/Dectective-X/.venv/Scripts/python.exe -m pip install -r prototype/requirements.txt
```

Navigate into the prototype workspace:

```powershell
cd prototype
```

Ingest the bundled sample UFDR (creates SQLite DB, vector index, and knowledge graph):

```powershell
../.venv/Scripts/python.exe -m src.ingestion.pipeline
```

Start the FastAPI server:

```powershell
../.venv/Scripts/uvicorn.exe src.app:app --reload --port 8000
```

Upload a UFDR archive (optional – the server will extract it and return a data path):

```powershell
curl -X POST http://127.0.0.1:8000/upload-ufdr -F "file=@C:/path/to/export.ufdr"
```

Query the assistant (after ingestion) from a new terminal:

```powershell
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" `
	  -d '{"query": "show foreign crypto messages after 10 pm"}'
```

The JSON response now includes structured evidence arrays plus a Markdown `report` distilling key insights and recommended next steps.

Run the test suite:

```powershell
../.venv/Scripts/python.exe -m pytest
```

Start the React dashboard to drive ingestion and queries visually:

```powershell
cd frontend
npm install
npm run dev -- --host
```

The dashboard lets you either upload a UFDR archive (zip/ufdr/tar.gz) or point to a server-side path; it then triggers ingestion and interactive querying through the FastAPI backend.

### 🌐 Optional: Gemini report generation

Set the following environment variables before starting the API if you want rich narrative reports to be composed by Google Gemini:

```powershell
$env:GEMINI_API_KEY = "<your_api_key>"
# Optional override (defaults to gemini-1.5-flash)
$env:GEMINI_MODEL_NAME = "gemini-1.5-pro"
```

If no key is provided, the backend will still return a concise Markdown report assembled from the retrieved evidence (messages, calls, locations, and graph insights).

## 🔄 Data Flow & AI Orchestration

1. **Ingestion (`src/ingestion/pipeline.py`)**
	- Parses CSV/XML/HTML artifacts.
	- Normalizes content into SQLite tables (`contacts`, `messages`, `calls`, `locations`, `keywords`, `media`).
	- Builds TF-IDF vector index for semantic message search.
	- Creates a node-link knowledge graph (JSON) linking people, communications, and entities.
2. **Query Engine (`src/ai/query_engine.py`)**
	- Classifies user intent (messages, calls, connection analysis) via keyword heuristics.
	- Executes hybrid retrieval: SQL filters, vector similarity, and graph insights.
	- Returns structured evidence snippets plus a human-readable summary.
3. **API Layer (`src/app.py`)**
	- `/ingest`: (re)builds all stores from a UFDR bundle.
	- `/query`: answers natural language prompts with evidence payloads and highlights.

## 🧪 Demo Scenario

Try the following once the API is running:

- `"List messages mentioning crypto from foreign numbers after 10 PM"`
- `"Show connections between John Doe and Bitcoin Broker"`
- `"Calls with non-Indian contacts"`

Each response includes relevant chat transcripts, associated calls, and graph-based relationship hints.

## 🔐 Forensic Integrity Hooks

- Deterministic UFDR path references (`raw_path`, `media_path`) for evidence provenance.
- SHA-256 hashing ready in `storage/database.Media` (populate via future file hashing step).
- `reset_storage()` utility clears state safely for repeatable demo runs.

## 🛣️ Next Steps & Enhancements

- Swap TF-IDF embeddings with domain-tuned language models (e.g., `sentence-transformers`).
- Integrate LLM frameworks (LangChain/LlamaIndex) for richer intent detection and explanations.
- Extend graph analytics (community detection, shortest path, anomaly scoring).
- Add RBAC, audit trails, and tamper-proof hashing for production forensic workflows.
- Build a polished investigator UI (Streamlit/React) with timeline, filter chips, and graph visualization.

## 📄 License

Prototype code for Smart India Hackathon experimentation—adapt and extend as needed for your submission.
