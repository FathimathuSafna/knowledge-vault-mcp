# Knowledge Vault 🧠
### *Local Semantic Memory & Knowledge Graph MCP Server*

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol-orange.svg)](https://modelcontextprotocol.io/)
[![Embeddings](https://img.shields.io/badge/Model-all--MiniLM--L6--v2-green.svg)](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
[![Database](https://img.shields.io/badge/Storage-SQLite-lightgrey.svg)](https://www.sqlite.org/)
[![Tests](https://img.shields.io/badge/Tests-13%20passed-brightgreen.svg)]()

**Knowledge Vault** is a local, privacy-first **Model Context Protocol (MCP)** server that equips LLMs (like Claude Desktop, Cursor, and Antigravity) with long-term semantic memory, desktop note auto-sync, and relational knowledge graph capabilities.

Instead of relying on external cloud APIs or black-box vector stores, Knowledge Vault runs fully locally using local dense vector embeddings (`sentence-transformers`), vectorized NumPy cosine similarity, and SQLite.

---

## ⚡ Key Features

- **🔍 Meaning-Based Semantic Search**: Search your thoughts, code snippets, and notes by meaning rather than rigid keyword matching.
- **💻 Desktop Notes Access & Ingestion**:
  - Automatically locates your Desktop folder (including OneDrive-synced Windows desktops, macOS, and Linux).
  - Ingests markdown (`.md`) and text (`.txt`) files directly into the vector database.
  - Smart sync detects file updates and modifications without duplicate re-embeddings.
  - Retains source file provenance so LLMs can cite or inspect original notes.
- **🛡️ Real-Time Deduplication**: Cosine similarity threshold (`>= 0.95`) prevents duplicate or near-identical notes from cluttering the vault.
- **🕸️ Bi-directional Knowledge Graph**: Link notes together (`#A <-> #B`) to explore associative thoughts and extract context-rich sub-graphs for topic synthesis.
- **🔒 100% Offline & Private**: Everything stays on your local machine in `~/.knowledge_vault/vault.db`.

---

## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph Client ["AI Client (Claude Desktop / Cursor / Antigravity)"]
        LLM["Claude / LLM Agent"]
    end

    subgraph MCP ["Knowledge Vault (FastMCP Server)"]
        Router["FastMCP Tool Router"]
        Model["SentenceTransformer (all-MiniLM-L6-v2)"]
        Sync["Desktop Sync & File Ingestion"]
        VectorEngine["NumPy Vector Similarity & Deduplication"]
    end

    subgraph Storage ["Local Storage"]
        DesktopFiles["Desktop Notes (*.md, *.txt)"]
        DB[("SQLite (~/.knowledge_vault/vault.db)\n• Notes & 384d Vectors\n• Bi-directional Links")]
    end

    LLM <-->|Model Context Protocol (stdio)| Router
    Router --> Model
    Router --> Sync
    Sync <--> DesktopFiles
    Sync --> Model
    Model --> VectorEngine
    Router --> VectorEngine
    VectorEngine <--> DB
```

---

## 🛠️ MCP Tools Overview

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| **`sync_desktop_notes`** | `folder_path`, `recursive`, `extensions` | Scans Desktop (or custom folder) for `.md`/`.txt` files, syncing additions & edits. |
| **`import_file`** | `file_path`, `tags`, `force` | Ingests a specific local file into the vault with semantic vector embedding. |
| **`search_notes`** | `query`, `limit` | Performs vectorized cosine similarity search across all saved notes and returns scores & sources. |
| **`save_note`** | `text`, `tags`, `force`, `source` | Stores a note or snippet with automatic duplicate detection. |
| **`read_desktop_note`**| `file_path` | Reads the live content of a note file from the desktop or local filesystem. |
| **`list_desktop_sources`** | *none* | Lists all notes imported from local files, with source paths and timestamps. |
| **`link_notes`** | `note_a`, `note_b` | Creates a bi-directional graph link between two related notes. |
| **`summarize_topic`** | `topic`, `limit`, `min_score` | Gathers relevant notes + link topology for AI context-aware synthesis. |
| **`ping`** | *none* | Health check verifying that the vault server is responsive. |

---

## 🚀 Quickstart & Setup

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended for fast package and environment management)

### 1. Clone & Install
```bash
git clone https://github.com/your-username/knowledge-vault.git
cd knowledge-vault
uv sync
```

### 2. Run Tests
```bash
uv run pytest
```
All 13 test suites validate semantic search, duplicate blocking, graph links, and desktop file sync.

### 3. CLI Commands (Quick Terminal Usage)
You can test and use the vault directly from your terminal:
```bash
# Scan & sync all desktop notes (.txt and .md)
uv run knowledge-vault sync

# Search notes by semantic meaning
uv run knowledge-vault search "database indexing"

# Save a quick note directly
uv run knowledge-vault save "Python tuples are immutable" "python"

# List all desktop source files imported
uv run knowledge-vault list
```

---

## 🤖 Connecting to Claude Desktop

To connect Claude Desktop to your local Knowledge Vault:

1. Open your Claude Desktop configuration file:
   - **Windows (Standard)**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **Windows (Microsoft Store app)**: `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

2. Add `knowledge-vault` to `mcpServers`:

```json
{
  "mcpServers": {
    "knowledge-vault": {
      "command": "C:\\Users\\SAFNA\\.local\\bin\\uv.exe",
      "args": [
        "--directory",
        "C:\\Users\\SAFNA\\Documents\\knowledge-vault",
        "run",
        "knowledge-vault",
        "serve"
      ]
    }
  }
}
```

3. Restart **Claude Desktop**. You will see the hammer/tools icon with `knowledge-vault` tools active!

### Example Prompts in Claude Desktop:
- *"Sync all the notes from my desktop into my vault."*
- *"What did I write down about cache invalidation or Redis?"*
- *"Import my meeting notes from `~/Desktop/q3_planning.md` and link them to our architecture notes."*
- *"Summarize everything we have saved on authentication and show how those ideas connect."*

---

## 📁 Project Structure

```
knowledge-vault/
├── src/
│   └── knowledge_vault/
│       ├── __init__.py       # Package entrypoint & script exports
│       └── server.py         # FastMCP server, desktop sync, vector engine
├── server.py                 # Root compatibility shim
├── test_vault.py             # 13 comprehensive unit & isolation tests
├── pyproject.toml            # Project metadata & dependencies
└── README.md                 # Documentation
```

---

## 📄 License
MIT License. Free to use, adapt, and build upon!
