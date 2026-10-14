import server


def use_temp_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(server, "DB_PATH", test_db)
    if hasattr(server, "_server_module"):
        monkeypatch.setattr(server._server_module, "DB_PATH", test_db)


def test_save_then_search(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    server.save_note("Redis allkeys-lru is good for caches", "redis")
    server.save_note("Python tuples are immutable", "python")
    results = server.search_notes("cache cleanup")
    assert results[0]["tags"] == "redis"
    assert "source" in results[0]


def test_search_empty_vault(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    assert server.search_notes("anything") == []


def test_link_twice_is_ok(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    server.save_note("note one", "")
    server.save_note("note two", "")
    server.link_notes(1, 2)
    server.link_notes(2, 1)
    result = server.summarize_topic("note", min_score=-1.0)
    assert result["links"] == [[1, 2]]


def test_link_missing_note(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    assert "doesn't exist" in server.link_notes(1, 99)


def test_summarize_ignores_unrelated_notes(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    server.save_note("Memcached is a simple in-memory cache", "caching")
    server.save_note("Docker containers share the host kernel", "docker")
    result = server.summarize_topic("caching")
    tags = [n["tags"] for n in result["notes"]]
    assert "caching" in tags
    assert "docker" not in tags


def test_duplicate_is_blocked(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    server.save_note("Redis allkeys-lru is good for caches", "redis")
    result = server.save_note("Redis allkeys-lru is good for caches", "redis")
    assert "Not saved" in result
    assert len(server.search_notes("redis", limit=10)) == 1


def test_force_saves_duplicate(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    server.save_note("Redis allkeys-lru is good for caches", "redis")
    result = server.save_note("Redis allkeys-lru is good for caches", "redis", force=True)
    assert "Saved note" in result


# ============================================================================
# Desktop Notes Access Tests
# ============================================================================

def test_import_file_and_search(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    note_file = tmp_path / "architecture.md"
    note_file.write_text("Kubernetes ingress controllers route external HTTP traffic to services.", encoding="utf-8")

    result = server.import_file(str(note_file), tags="devops,k8s")
    assert "Imported note" in result

    # Check search finds it and returns the source path
    found = server.search_notes("how does HTTP traffic reach kubernetes services?")
    assert len(found) > 0
    assert found[0]["source"] == str(note_file.resolve())
    assert "devops,k8s" in found[0]["tags"]


def test_import_file_not_found(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    result = server.import_file(str(tmp_path / "non_existent.txt"))
    assert "File not found" in result


def test_import_file_update(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    note_file = tmp_path / "ideas.md"
    note_file.write_text("Initial version of project ideas", encoding="utf-8")

    res1 = server.import_file(str(note_file))
    assert "Imported note" in res1

    # Second import without changes -> already in sync
    res2 = server.import_file(str(note_file))
    assert "already in sync" in res2

    # Modify file and re-import -> updated
    note_file.write_text("Updated version: Building an MCP semantic knowledge base", encoding="utf-8")
    res3 = server.import_file(str(note_file))
    assert "Updated note" in res3

    # Verify updated content in search
    results = server.search_notes("MCP semantic knowledge base")
    assert "MCP semantic knowledge base" in results[0]["text"]


def test_sync_desktop_notes(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    folder = tmp_path / "desktop_notes"
    folder.mkdir()

    (folder / "note1.md").write_text("PostgreSQL supports JSONB for semi-structured data.", encoding="utf-8")
    (folder / "note2.txt").write_text("Rust memory safety is guaranteed by borrow checker.", encoding="utf-8")
    (folder / "ignore.pdf").write_text("dummy binary", encoding="utf-8")

    summary = server.sync_desktop_notes(folder_path=str(folder))
    assert summary["total_files_scanned"] == 2
    assert len(summary["added"]) == 2

    # Re-sync without changes
    summary2 = server.sync_desktop_notes(folder_path=str(folder))
    assert summary2["unchanged_count"] == 2
    assert len(summary2["added"]) == 0

    # Modify one file and re-sync
    (folder / "note1.md").write_text("PostgreSQL supports JSONB and GiST/GIN indexes.", encoding="utf-8")
    summary3 = server.sync_desktop_notes(folder_path=str(folder))
    assert len(summary3["updated"]) == 1
    assert summary3["unchanged_count"] == 1


def test_read_desktop_note(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    note_file = tmp_path / "meeting.md"
    content = "# Meeting Notes\n- Discussed Q3 roadmap\n- Decided on MCP architecture"
    note_file.write_text(content, encoding="utf-8")

    read_back = server.read_desktop_note(str(note_file))
    assert read_back == content


def test_list_desktop_sources(tmp_path, monkeypatch):
    use_temp_db(tmp_path, monkeypatch)
    note_file = tmp_path / "todo.txt"
    note_file.write_text("Buy groceries and review PRs", encoding="utf-8")

    server.import_file(str(note_file), tags="personal")
    sources = server.list_desktop_sources()

    assert len(sources) == 1
    assert sources[0]["source"] == str(note_file.resolve())
    assert "Buy groceries" in sources[0]["preview"]