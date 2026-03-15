# KOReader Collections Exporter — Calibre Plugin

A Calibre plugin that exports your library as a KOReader `collection.lua` file, with one collection per Calibre tag and a full `library` collection, while preserving any existing `instapaper` entries.

*** THE ENTIRETY OF THIS CODE WAS PRODUCED BY CLAUDE AI ***

---

## Installation

Preferences → Plugins → Load plugin from file → `KOReaderCollections.zip`

Add the toolbar button via Preferences → Toolbars & Menus.

---

## Configuration

Preferences → Plugins → KOReader Collections → Customize:

| Setting | Example |
|---|---|
| Calibre library path | `/Users/<username>/Calibre Library` |
| KOReader books path (on device) | `/home/root/calibre` |

`collection.lua` is always written to and read from `$CALIBRE_HOME/collection.lua`.

---

## How it works

Click the **KOReader Collections** toolbar button. The plugin:

1. Reads `$CALIBRE_HOME/metadata.db` directly via `sqlite3` — no assumptions about the live Calibre DB API.
2. Discovers all distinct tags: `SELECT DISTINCT name FROM tags`.
3. For each collection (library + each tag): joins `books → books_tags_link → tags`, walks the on-disk book folder to find the `.epub` file, and skips anything without one (e.g. MOBI-only books).
4. **Orders entries** within each collection by `max(last_modified, pubdate)` descending — most recently touched = `order = 1`.
5. **Orders collections** by book count descending — most books = lowest `order` number. `instapaper` is always `order = 1` when present; all others start at `2`.
6. Preserves the `instapaper` block verbatim from the existing `$CALIBRE_HOME/collection.lua`.
7. Writes the result back to `$CALIBRE_HOME/collection.lua`, creating the file if it does not exist.

---

## Plugin files

| File | Role |
|---|---|
| `__init__.py` | Plugin metadata, wires to `ui.py` via `actual_plugin` |
| `ui.py` | `InterfaceAction` — adds the **KOReader Collections** toolbar button |
| `core.py` | All pure-Python logic: SQLite queries, entry building, Lua rendering/parsing |
| `config.py` | Preferences widget (Calibre path + device path) |
| `plugin-import-name-koreader_collections.txt` | Required multi-file plugin marker (empty file) |
