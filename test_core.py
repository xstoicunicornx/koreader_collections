"""
test_core.py  –  standalone tests for core.py (no Calibre / Qt required).

Creates a temporary directory that mimics a real Calibre library layout:

  $TMP/
    metadata.db          <- in-memory-style, written to disk for sqlite3
    Author1/Book1 (49)/  <- book folder (Calibre style)
      Book1 - Author1.epub
    Author2/Book2 (50)/
      Book2 - Author2.epub
    Author3/Book3 (51)/
      Book3 - Author3.epub
    Author4/Book4 (52)/     <- MOBI only (no .epub file)
      Book4 - Author4.mobi

Run with:
    python test_core.py
"""

import os
import sqlite3
import sys
import tempfile
import shutil

# Make sure we can import core from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    _parse_ts,
    _to_device_path,
    _rows_to_entries,
    _collection_settings,
    build_collection_data,
    collection_lua_path,
    parse_existing_lua,
    render_lua,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

EXISTING_LUA = '''\
-- ./settings/collection.lua
return {
    ["instapaper"] = {
        [1] = {
            ["file"] = "/home/root/xovi/instapaper/article.epub",
            ["order"] = 1,
        },
        ["settings"] = {
            ["filter"] = {
                ["add"] = {
                    ["filetype"] = "epub",
                },
            },
            ["order"] = 1,
        },
    },
    ["library"] = {
        [1] = {
            ["file"] = "/home/root/calibre/Author1/Book1 (49)/Book1 - Author1.epub",
            ["order"] = 1,
        },
        ["settings"] = {
            ["order"] = 2,
        },
    },
}
'''

# (path_relative_to_calibre_home, epub_filename_or_None, last_modified, pubdate, tags)
BOOK_FIXTURES = [
    # Book1: tagged sci-fi + classic; last_modified is newest overall
    ('Author1/Book1 (49)', 'Book1 - Author1.epub',
     '2024-06-01T00:00:00+00:00', '2022-01-01T00:00:00+00:00',
     ['sci-fi', 'classic']),
    # Book2: tagged sci-fi only; pubdate is newer than last_modified
    ('Author2/Book2 (50)', 'Book2 - Author2.epub',
     '2023-01-01T00:00:00+00:00', '2024-03-15T00:00:00+00:00',
     ['sci-fi']),
    # Book3: no tags; oldest timestamps
    ('Author3/Book3 (51)', 'Book3 - Author3.epub',
     '2021-05-10T00:00:00+00:00', '2021-05-10T00:00:00+00:00',
     []),
    # Book4: tagged classic; MOBI only (no .epub) → must be excluded
    ('Author4/Book4 (52)', None,
     '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00',
     ['classic']),
]

KOREADER_BASE = '/home/root/calibre'


def _build_temp_library():
    """
    Create a temp directory tree that looks like a Calibre library,
    populate metadata.db, and create placeholder .epub files.
    Returns the temp directory path.
    """
    tmpdir = tempfile.mkdtemp(prefix='calibre_test_')

    # Create metadata.db
    db_path = os.path.join(tmpdir, 'metadata.db')
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE books (
            id            INTEGER PRIMARY KEY,
            title         TEXT NOT NULL,
            author_sort   TEXT,
            path          TEXT NOT NULL,
            last_modified TEXT,
            pubdate       TEXT
        );
        CREATE TABLE tags (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE books_tags_link (
            id   INTEGER PRIMARY KEY,
            book INTEGER REFERENCES books(id),
            tag  INTEGER REFERENCES tags(id)
        );
    """)

    # Collect unique tags
    all_tags = {}
    for (_, _, _, _, tags) in BOOK_FIXTURES:
        for t in tags:
            if t not in all_tags:
                conn.execute("INSERT INTO tags (name) VALUES (?)", (t,))
                all_tags[t] = conn.execute(
                    "SELECT id FROM tags WHERE name=?", (t,)).fetchone()[0]

    for book_id, (rel_path, epub_fname, last_mod, pubdate, tags) in \
            enumerate(BOOK_FIXTURES, start=1):
        title = rel_path.split('/')[1].split(' (')[0]   # e.g. "Book1"
        author = rel_path.split('/')[0]                  # e.g. "Author1"
        conn.execute(
            "INSERT INTO books (id, title, author_sort, path, last_modified, pubdate) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (book_id, title, author, rel_path, last_mod, pubdate))

        # Create folder + file
        folder = os.path.join(tmpdir, rel_path)
        os.makedirs(folder, exist_ok=True)
        if epub_fname:
            open(os.path.join(folder, epub_fname), 'wb').close()
        else:
            # Create a .mobi instead
            open(os.path.join(folder, title + '.mobi'), 'wb').close()

        for t in tags:
            conn.execute(
                "INSERT INTO books_tags_link (book, tag) VALUES (?, ?)",
                (book_id, all_tags[t]))

    conn.commit()
    conn.close()
    return tmpdir


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _epub_entries(collection_dict):
    """Return the numeric-keyed entries from a collection dict."""
    return {k: v for k, v in collection_dict.items() if isinstance(k, int)}


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_ts():
    assert _parse_ts('2024-06-01T00:00:00+00:00') > _parse_ts('2023-01-01T00:00:00+00:00')
    assert _parse_ts('2024-03-15T00:00:00+00:00') > _parse_ts('2023-01-01T00:00:00+00:00')
    assert _parse_ts(None) == 0.0
    assert _parse_ts('') == 0.0
    print('✓  test_parse_ts')


def test_parse_existing_lua():
    data = parse_existing_lua(EXISTING_LUA)
    assert 'instapaper' in data
    assert 'library' in data
    assert data['instapaper'][1]['file'].endswith('article.epub')
    assert data['instapaper']['settings']['order'] == 1
    print('✓  test_parse_existing_lua')


def test_render_lua_roundtrip():
    data = parse_existing_lua(EXISTING_LUA)
    lua  = render_lua(data)
    assert lua.startswith('-- ./settings/collection.lua\nreturn {')
    data2 = parse_existing_lua(lua)
    assert data2['instapaper'][1]['file'] == data['instapaper'][1]['file']
    print('✓  test_render_lua_roundtrip')


def test_to_device_path():
    host   = '/Users/monica/Calibre Library/Author/Book/book.epub'
    ch     = '/Users/monica/Calibre Library'
    kb     = '/home/root/calibre'
    result = _to_device_path(host, ch, kb)
    assert result == '/home/root/calibre/Author/Book/book.epub', result
    # No match → unchanged
    other = _to_device_path('/elsewhere/book.epub', ch, kb)
    assert other == '/elsewhere/book.epub'
    print('✓  test_to_device_path')


def test_collection_settings_shape():
    s = _collection_settings(3)
    assert s == {'filter': {'add': {'filetype': 'epub'}}, 'order': 3}
    print('✓  test_collection_settings_shape')


# ── Integration tests using real temp library ─────────────────────────────────

def test_library_collection(tmpdir):
    data = build_collection_data(tmpdir, KOREADER_BASE)
    assert 'library' in data

    entries = _epub_entries(data['library'])
    # 3 EPUBs exist on disk (Book4 has no epub)
    assert len(entries) == 3, f'Expected 3 library entries, got {len(entries)}'

    # Order: Book1 max_ts=2024-06-01, Book2 max_ts=2024-03-15, Book3 max_ts=2021-05-10
    paths = [entries[i]['file'] for i in sorted(entries)]
    assert 'Book1' in paths[0], f'Book1 should be order=1, got {paths[0]}'
    assert 'Book2' in paths[1], f'Book2 should be order=2, got {paths[1]}'
    assert 'Book3' in paths[2], f'Book3 should be order=3, got {paths[2]}'

    print('✓  test_library_collection')


def test_path_rewriting(tmpdir):
    data    = build_collection_data(tmpdir, KOREADER_BASE)
    entries = _epub_entries(data['library'])
    for entry in entries.values():
        assert entry['file'].startswith(KOREADER_BASE + '/'), \
            f'Path not rewritten: {entry["file"]}'
        assert tmpdir not in entry['file'], \
            f'Host path leaked into output: {entry["file"]}'
    print('✓  test_path_rewriting')


def test_tag_collections(tmpdir):
    data = build_collection_data(tmpdir, KOREADER_BASE)

    assert 'sci-fi'  in data, f'sci-fi missing. Keys: {list(data.keys())}'
    assert 'classic' in data, f'classic missing. Keys: {list(data.keys())}'

    scifi_entries   = _epub_entries(data['sci-fi'])
    classic_entries = _epub_entries(data['classic'])

    # sci-fi: Books 1 + 2 (both have EPUBs)
    assert len(scifi_entries) == 2, \
        f'sci-fi expected 2 books, got {len(scifi_entries)}'

    # classic: Book1 only — Book4 has no .epub, so excluded
    assert len(classic_entries) == 1, \
        f'classic expected 1 book, got {len(classic_entries)}'
    assert 'Book1' in classic_entries[1]['file']

    # Book3 has no tags → should NOT create a collection for it
    assert len([k for k in data if k not in ('library', 'instapaper')]) == 2

    print('✓  test_tag_collections')


def test_settings_order_by_book_count(tmpdir):
    """
    library(3 books) > sci-fi(2 books) > classic(1 book)
    No instapaper → orders start at 1.
    """
    data = build_collection_data(tmpdir, KOREADER_BASE, existing_lua_data={})
    assert 'instapaper' not in data

    lib_order     = data['library']['settings']['order']
    scifi_order   = data['sci-fi']['settings']['order']
    classic_order = data['classic']['settings']['order']

    assert lib_order < scifi_order < classic_order, \
        f'Expected lib < sci-fi < classic, got {lib_order}, {scifi_order}, {classic_order}'
    assert lib_order == 1, f'library should be order=1 (most books), got {lib_order}'

    print('✓  test_settings_order_by_book_count')


def test_instapaper_preserved_and_order_1(tmpdir):
    existing = parse_existing_lua(EXISTING_LUA)
    data     = build_collection_data(tmpdir, KOREADER_BASE, existing)

    assert 'instapaper' in data
    assert data['instapaper'][1]['file'].endswith('article.epub'), \
        'instapaper entry not preserved'
    assert data['instapaper']['settings']['order'] == 1, \
        'instapaper must always be order=1'

    # All other collections must have order >= 2
    for name, col in data.items():
        if name == 'instapaper':
            continue
        assert col['settings']['order'] >= 2, \
            f'{name} has order {col["settings"]["order"]} but instapaper present'

    print('✓  test_instapaper_preserved_and_order_1')


def test_no_instapaper_stub_when_absent(tmpdir):
    """When no existing file is given, instapaper should NOT appear."""
    data = build_collection_data(tmpdir, KOREADER_BASE, existing_lua_data=None)
    assert 'instapaper' not in data
    print('✓  test_no_instapaper_stub_when_absent')


def test_collection_lua_written_to_calibre_home(tmpdir):
    expected_path = os.path.join(tmpdir, 'collection.lua')
    assert collection_lua_path(tmpdir) == expected_path

    # Simulate write
    data     = build_collection_data(tmpdir, KOREADER_BASE)
    lua_text = render_lua(data)
    with open(expected_path, 'w') as fh:
        fh.write(lua_text)

    assert os.path.isfile(expected_path)
    with open(expected_path) as fh:
        content = fh.read()
    assert '["library"]' in content
    assert KOREADER_BASE in content
    print('✓  test_collection_lua_written_to_calibre_home')


def test_full_render_output(tmpdir):
    existing = parse_existing_lua(EXISTING_LUA)
    data     = build_collection_data(tmpdir, KOREADER_BASE, existing)
    lua      = render_lua(data)

    assert '["instapaper"]' in lua
    assert '["library"]'    in lua
    assert '["sci-fi"]'     in lua
    assert '["classic"]'    in lua
    assert KOREADER_BASE    in lua
    assert tmpdir           not in lua, 'Host path leaked into output!'
    assert '"filetype"'     in lua  # settings filter present in all collections

    # Every collection block must have a settings.filter.filetype = epub entry
    data2 = parse_existing_lua(lua)
    for name, col in data2.items():
        settings = col.get('settings', {})
        assert 'order' in settings, f'{name}: missing settings.order'
        if name != 'instapaper':
            ft = settings.get('filter', {}).get('add', {}).get('filetype')
            assert ft == 'epub', f'{name}: expected filetype=epub, got {ft!r}'

    print('✓  test_full_render_output')
    return lua


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Unit tests (no filesystem)
    test_parse_ts()
    test_parse_existing_lua()
    test_render_lua_roundtrip()
    test_to_device_path()
    test_collection_settings_shape()

    # Integration tests (real temp Calibre library)
    tmpdir = _build_temp_library()
    try:
        test_library_collection(tmpdir)
        test_path_rewriting(tmpdir)
        test_tag_collections(tmpdir)
        test_settings_order_by_book_count(tmpdir)
        test_instapaper_preserved_and_order_1(tmpdir)
        test_no_instapaper_stub_when_absent(tmpdir)
        test_collection_lua_written_to_calibre_home(tmpdir)
        lua = test_full_render_output(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print('All tests passed.')
    print()
    print('=== Sample collection.lua output ===')
    print(lua)
