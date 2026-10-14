import os
import sys
import sqlite3
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

os.environ.setdefault("HF_HUB_OFFLINE", "0")  # use downloaded model, skip network checks
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("knowledge-vault")
DB_PATH = Path.home() / ".knowledge_vault" / "vault.db"
DUPLICATE_THRESHOLD = 0.95  # similarity at or above this counts as duplicate

_model = None
_lock = threading.Lock()


def get_desktop_path() -> Path:
    """Resolve the user's Desktop directory across Windows (including OneDrive Desktop), macOS, and Linux."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            )
            desktop_val, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            expanded = Path(os.path.expandvars(desktop_val))
            if expanded.exists():
                return expanded
        except Exception:
            pass

    # Standard fallbacks
    candidates = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "OneDrive" / "Documents" / "Desktop",
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path.home() / "Desktop"


def get_model():
    """Load the embedding model once safely using a lock."""
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed(text: str) -> bytes:
    """Convert text to an embedding stored as bytes."""
    vec = get_model().encode(text, normalize_embeddings=True)
    return vec.astype(np.float32).tobytes()


def get_db():
    """Connect to SQLite and ensure tables and columns exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            tags TEXT DEFAULT '',
            source TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            embedding BLOB
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS links (
            note_a INTEGER,
            note_b INTEGER,
            PRIMARY KEY (note_a, note_b)
        )""")

    # Schema migration: ensure 'source' and 'updated_at' columns exist
    cols = [col[1] for col in conn.execute("PRAGMA table_info(notes)").fetchall()]
    if "source" not in cols:
        conn.execute("ALTER TABLE notes ADD COLUMN source TEXT DEFAULT ''")
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE notes ADD COLUMN updated_at TEXT DEFAULT ''")

    return conn


@mcp.tool()
def ping() -> str:
    """Check that the vault server is running."""
    return "pong"


@mcp.tool()
def save_note(text: str, tags: str = "", force: bool = False, source: str = "") -> str:
    """Save a note, snippet, or idea to the vault.
    text: content of the note.
    tags: optional comma-separated labels, e.g. 'redis,caching'.
    force: if True, save even if a duplicate or near-identical note exists.
    source: optional file path or URL where this note originated."""
    emb = embed(text)
    conn = get_db()
    if not force:
        new = np.frombuffer(emb, dtype=np.float32)
        rows = conn.execute(
            "SELECT id, text, embedding FROM notes WHERE embedding IS NOT NULL"
        ).fetchall()
        for r in rows:
            v = np.frombuffer(r["embedding"], dtype=np.float32)
            if float(np.dot(new, v)) >= DUPLICATE_THRESHOLD:
                conn.close()
                return (
                    f"Not saved: a very similar note already exists "
                    f"(#{r['id']}: \"{r['text']}\"). Use force=true to save anyway."
                )
    cur = conn.execute(
        "INSERT INTO notes (text, tags, source, embedding) VALUES (?, ?, ?, ?)",
        (text, tags, source, emb),
    )
    conn.commit()
    note_id = cur.lastrowid
    conn.close()
    return f"Saved note #{note_id}"


@mcp.tool()
def search_notes(query: str, limit: int = 5) -> list[dict]:
    """Search saved notes by semantic meaning.
    query: what you want to find.
    limit: max number of results to return."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, text, tags, source, created_at, embedding FROM notes "
        "WHERE embedding IS NOT NULL"
    ).fetchall()
    conn.close()
    if not rows:
        return []

    q = np.frombuffer(embed(query), dtype=np.float32)
    # Vectorized cosine similarity computation
    emb_matrix = np.array([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    scores = np.dot(emb_matrix, q)

    scored = [
        (float(scores[i]), rows[i])
        for i in range(len(rows))
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "id": r["id"],
            "text": r["text"],
            "tags": r["tags"],
            "source": r["source"] if "source" in r.keys() and r["source"] else "",
            "saved": r["created_at"],
            "score": round(s, 3),
        }
        for s, r in scored[:limit]
    ]


@mcp.tool()
def link_notes(note_a: int, note_b: int) -> str:
    """Connect two related notes by their IDs so they can be explored together."""
    if note_a == note_b:
        return "A note can't be linked to itself."
    a, b = sorted((note_a, note_b))
    conn = get_db()
    found = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE id IN (?, ?)", (a, b)
    ).fetchone()[0]
    if found != 2:
        conn.close()
        return "One of those note ids doesn't exist."
    conn.execute("INSERT OR IGNORE INTO links VALUES (?, ?)", (a, b))
    conn.commit()
    conn.close()
    return f"Linked #{a} and #{b}"


@mcp.tool()
def summarize_topic(topic: str, limit: int = 8, min_score: float = 0.25) -> dict:
    """Gather notes relevant to a topic plus their link graph for context-aware AI synthesis."""
    notes = [n for n in search_notes(topic, limit) if n["score"] >= min_score]
    ids = [n["id"] for n in notes]
    links = []
    if ids:
        marks = ",".join("?" * len(ids))
        conn = get_db()
        links = [
            [r["note_a"], r["note_b"]]
            for r in conn.execute(
                f"SELECT note_a, note_b FROM links "
                f"WHERE note_a IN ({marks}) AND note_b IN ({marks})",
                ids + ids,
            )
        ]
        conn.close()
    return {"topic": topic, "notes": notes, "links": links}


# ============================================================================
# Desktop Notes Access & Ingestion Tools
# ============================================================================

@mcp.tool()
def import_file(file_path: str, tags: str = "", force: bool = False) -> str:
    """Import a local text or markdown note file into the vault.
    file_path: absolute path or path relative to the Desktop/Documents folder.
    tags: optional comma-separated tags to label the note with.
    force: re-import and update even if content is unchanged."""
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        desktop_candidate = get_desktop_path() / file_path
        if desktop_candidate.exists():
            path = desktop_candidate
        else:
            path = path.resolve()

    if not path.exists() or not path.is_file():
        return f"File not found: {file_path}"

    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as e:
        return f"Error reading file {path}: {str(e)}"

    if not content:
        return f"File is empty: {path}"

    abs_source = str(path.resolve())
    conn = get_db()
    existing = conn.execute(
        "SELECT id, text FROM notes WHERE source = ?", (abs_source,)
    ).fetchone()

    emb = embed(content)

    if existing:
        if not force and existing["text"] == content:
            conn.close()
            return f"Note #{existing['id']} already in sync with {path.name} (unchanged)."
        conn.execute(
            """UPDATE notes 
               SET text = ?, tags = COALESCE(NULLIF(?, ''), tags), embedding = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (content, tags, emb, existing["id"]),
        )
        conn.commit()
        note_id = existing["id"]
        conn.close()
        return f"Updated note #{note_id} from {path.name} ({len(content)} chars)"

    cur = conn.execute(
        "INSERT INTO notes (text, tags, source, embedding) VALUES (?, ?, ?, ?)",
        (content, tags, abs_source, emb),
    )
    conn.commit()
    note_id = cur.lastrowid
    conn.close()
    return f"Imported note #{note_id} from {path.name} ({len(content)} chars)"


@mcp.tool()
def sync_desktop_notes(
    folder_path: str = "",
    recursive: bool = False,
    extensions: str = ".md,.txt",
) -> dict:
    """Scan the Desktop (or a specified folder) and ingest all markdown/text notes into the vault.
    folder_path: folder to scan. If left empty, scans the user's Desktop folder.
    recursive: if True, scans subfolders as well.
    extensions: comma-separated list of extensions to include, e.g. '.md,.txt'."""
    if folder_path.strip():
        scan_dir = Path(folder_path).expanduser().resolve()
    else:
        scan_dir = get_desktop_path()

    if not scan_dir.exists() or not scan_dir.is_dir():
        return {"error": f"Directory not found: {scan_dir}"}

    ext_list = [e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
                for e in extensions.split(",") if e.strip()]

    pattern = "**/*" if recursive else "*"
    all_files = [p for p in scan_dir.glob(pattern) if p.is_file() and p.suffix.lower() in ext_list]

    added = []
    updated = []
    unchanged = []
    errors = []

    for file_path in all_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace").strip()
            if not content:
                continue

            abs_source = str(file_path.resolve())
            conn = get_db()
            existing = conn.execute(
                "SELECT id, text FROM notes WHERE source = ?", (abs_source,)
            ).fetchone()

            if existing:
                if existing["text"] == content:
                    unchanged.append(file_path.name)
                    conn.close()
                    continue
                emb = embed(content)
                conn.execute(
                    """UPDATE notes 
                       SET text = ?, embedding = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (content, emb, existing["id"]),
                )
                conn.commit()
                updated.append({"id": existing["id"], "file": file_path.name})
            else:
                emb = embed(content)
                default_tag = file_path.parent.name if recursive else "desktop"
                cur = conn.execute(
                    "INSERT INTO notes (text, tags, source, embedding) VALUES (?, ?, ?, ?)",
                    (content, default_tag, abs_source, emb),
                )
                conn.commit()
                added.append({"id": cur.lastrowid, "file": file_path.name})
            conn.close()
        except Exception as e:
            errors.append({"file": file_path.name, "error": str(e)})

    return {
        "folder": str(scan_dir),
        "total_files_scanned": len(all_files),
        "added": added,
        "updated": updated,
        "unchanged_count": len(unchanged),
        "errors": errors,
    }


@mcp.tool()
def read_desktop_note(file_path: str) -> str:
    """Read the live contents of a note file from the desktop or local filesystem.
    file_path: path to the note file."""
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        desktop_candidate = get_desktop_path() / file_path
        if desktop_candidate.exists():
            path = desktop_candidate
        else:
            path = path.resolve()

    if not path.exists() or not path.is_file():
        return f"File not found: {file_path}"

    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file {path}: {str(e)}"


@mcp.tool()
def list_desktop_sources() -> list[dict]:
    """List all notes that were imported from local files/desktop, along with their IDs and sources."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, text, tags, source, created_at, updated_at FROM notes WHERE source != '' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "source": r["source"],
            "preview": r["text"][:100] + ("..." if len(r["text"]) > 100 else ""),
            "tags": r["tags"],
            "updated_at": r["updated_at"] if "updated_at" in r.keys() else r["created_at"],
        }
        for r in rows
    ]


# Pre-warm model in background
threading.Thread(target=get_model, daemon=True).start()


def main():
    """Run the FastMCP server, or execute CLI commands if arguments are provided."""
    import sys
    args = sys.argv[1:]

    if not args or args[0] == "serve":
        # Default MCP server mode (used by Claude Desktop / Cursor)
        mcp.run()
        return

    command = args[0].lower()

    if command == "sync":
        folder = args[1] if len(args) > 1 else ""
        print(f"Scanning and syncing notes from: {folder or get_desktop_path()}...")
        res = sync_desktop_notes(folder_path=folder)
        print(f"Scanned: {res.get('total_files_scanned', 0)} files")
        print(f"Added: {len(res.get('added', []))} new notes")
        for item in res.get('added', []):
            print(f"  + Added: {item['file']} (Note #{item['id']})")
        print(f"Updated: {len(res.get('updated', []))} modified notes")
        print(f"Unchanged: {res.get('unchanged_count', 0)} notes")

    elif command == "search":
        if len(args) < 2:
            print("Usage: uv run knowledge-vault search <query>")
            return
        query = " ".join(args[1:])
        print(f"Searching vault for: '{query}'...\n")
        results = search_notes(query, limit=5)
        if not results:
            print("No matching notes found.")
            return
        for r in results:
            print(f"--- Note #{r['id']} (Score: {r['score']}) ---")
            print(f"Content: {r['text']}")
            if r.get('source'):
                print(f"Source:  {r['source']}")
            if r.get('tags'):
                print(f"Tags:    {r['tags']}")
            print()

    elif command == "save":
        if len(args) < 2:
            print("Usage: uv run knowledge-vault save <text> [tags]")
            return
        text = args[1]
        tags = args[2] if len(args) > 2 else ""
        res = save_note(text, tags)
        print(res)

    elif command in ("list", "sources"):
        sources = list_desktop_sources()
        print(f"Found {len(sources)} desktop/local source notes:\n")
        for s in sources:
            print(f"#{s['id']}: {s['source']}")
            print(f"   Preview: {s['preview']}")
            print()

    else:
        print("Knowledge Vault CLI")
        print("Commands:")
        print("  uv run knowledge-vault sync              - Scan & sync desktop notes")
        print("  uv run knowledge-vault search <query>    - Search notes by meaning")
        print("  uv run knowledge-vault save <text>       - Save a quick note")
        print("  uv run knowledge-vault list              - List all imported sources")
        print("  uv run knowledge-vault serve             - Run MCP server mode")


if __name__ == "__main__":
    main()
