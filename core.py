"""
core.py – pure-Python logic (no Qt) for building the KOReader collection.lua.

Key design decisions
--------------------
* Books and tags are sourced from $CALIBRE_HOME/metadata.db via sqlite3.
* collection.lua is always written to / read from $CALIBRE_HOME/collection.lua.
* "instapaper" block is preserved verbatim from an existing file.
* Collection settings["order"] is assigned by descending book-count
  (most books = lowest order number).
  "instapaper" is always order=1 when present; remaining collections start
  at order=2 (or order=1 when instapaper is absent).

Public API
----------
collection_lua_path(calibre_home) -> str
build_collection_data(calibre_home, koreader_base, existing_lua_data=None) -> dict
render_lua(data) -> str
parse_existing_lua(text) -> dict
"""

import os
import re
import sqlite3


# ── Path helpers ──────────────────────────────────────────────────────────────

def collection_lua_path(calibre_home):
    """Absolute path to collection.lua inside the Calibre library root."""
    return os.path.join(calibre_home, 'collection.lua')


def metadata_db_path(calibre_home):
    return os.path.join(calibre_home, 'metadata.db')


# ── Lua rendering ─────────────────────────────────────────────────────────────

def _lua_string(s):
    """Escape and quote a Python string as a Lua double-quoted string."""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _render_value(val, indent=0):
    pad  = '    ' * indent
    pad1 = '    ' * (indent + 1)

    if isinstance(val, bool):
        return 'true' if val else 'false'
    if isinstance(val, int):
        return str(val)
    if isinstance(val, str):
        return _lua_string(val)
    if isinstance(val, dict):
        if not val:
            return '{}'
        lines = ['{']
        for k, v in val.items():
            key_part = f'[{k}]' if isinstance(k, int) else f'[{_lua_string(k)}]'
            lines.append(f'{pad1}{key_part} = {_render_value(v, indent + 1)},')
        lines.append(pad + '}')
        return '\n'.join(lines)
    raise TypeError(f'Unsupported type for Lua rendering: {type(val)}')


def render_lua(data):
    """
    Render the top-level collection dict as a collection.lua string.
    data  –  { collection_name: { numeric_entries..., "settings": {...} } }
    """
    lines = ['-- ./settings/collection.lua', 'return {']
    for name, body in data.items():
        lines.append(f'    [{_lua_string(name)}] = {_render_value(body, 1)},')
    lines.append('}')
    return '\n'.join(lines) + '\n'


# ── Existing collection.lua parser ────────────────────────────────────────────

def parse_existing_lua(text):
    """
    Parse a KOReader collection.lua into a Python dict.
    Returns {} on any parse failure (safe fallback).
    """
    try:
        return _lua_to_python(text)
    except Exception:
        return {}


_TOKEN_RE = re.compile(
    r'--[^\n]*'            # line comment
    r'|"(?:[^"\\]|\\.)*"'  # double-quoted string
    r'|\d+'                # integer
    r'|true|false|nil'     # booleans / nil
    r'|return'             # top-level keyword
    r'|[=,{}\[\]]'         # punctuation
    r'|\w+'                # bare word (shouldn't appear in values)
    r'|\s+'                # whitespace
)


def _tokenize(text):
    return [
        m.group(0) for m in _TOKEN_RE.finditer(text)
        if not m.group(0).startswith('--') and m.group(0).strip()
    ]


def _unescape(s):
    return s[1:-1].replace('\\"', '"').replace('\\\\', '\\')


def _parse_value(tokens, pos):
    tok = tokens[pos]
    if tok == '{':
        return _parse_table(tokens, pos)
    if tok.startswith('"'):
        return pos + 1, _unescape(tok)
    if tok in ('true', 'false'):
        return pos + 1, tok == 'true'
    if tok == 'nil':
        return pos + 1, None
    if re.fullmatch(r'\d+', tok):
        return pos + 1, int(tok)
    raise ValueError(f'Unexpected token {tok!r} at index {pos}')


def _parse_table(tokens, pos):
    if tokens[pos] == 'return':
        pos += 1
    assert tokens[pos] == '{', f'Expected {{, got {tokens[pos]!r}'
    pos += 1
    result = {}
    seq = 1
    while tokens[pos] != '}':
        if tokens[pos] == '[':
            pos += 1
            key_tok = tokens[pos]; pos += 1
            assert tokens[pos] == ']'; pos += 1
            assert tokens[pos] == '='; pos += 1
            key = _unescape(key_tok) if key_tok.startswith('"') else int(key_tok)
            pos, val = _parse_value(tokens, pos)
            result[key] = val
        else:
            pos, val = _parse_value(tokens, pos)
            result[seq] = val
            seq += 1
        if pos < len(tokens) and tokens[pos] == ',':
            pos += 1
    return pos + 1, result


def _lua_to_python(text):
    tokens = _tokenize(text)
    _, result = _parse_table(tokens, 0)
    return result


# ── SQLite queries ────────────────────────────────────────────────────────────

def _query_all_tags(conn):
    """All distinct tag names used in the library, alphabetically."""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM tags ORDER BY name").fetchall()]


def _query_all_books(conn):
    """id, title, author_sort, path, last_modified, pubdate for every book."""
    return conn.execute(
        "SELECT id, title, author_sort, path, last_modified, pubdate "
        "FROM books ORDER BY id"
    ).fetchall()


def _query_books_for_tag(conn, tag):
    """Same columns as _query_all_books but filtered to one tag."""
    return conn.execute(
        """
        SELECT b.id, b.title, b.author_sort, b.path, b.last_modified, b.pubdate
        FROM books b
        JOIN books_tags_link btl ON b.id = btl.book
        JOIN tags t              ON t.id  = btl.tag
        WHERE t.name = ?
        ORDER BY b.id
        """,
        (tag,)
    ).fetchall()


# ── Book resolution helpers ───────────────────────────────────────────────────

def _find_epub(calibre_home, book_path):
    """
    Resolve a Calibre relative book folder (books.path) to the absolute
    host path of its .epub file.  Returns None when no epub is found.
    book_path uses forward slashes in metadata.db on all platforms.
    """
    folder = os.path.join(calibre_home, book_path.replace('/', os.sep))
    if not os.path.isdir(folder):
        return None
    for fname in os.listdir(folder):
        if fname.lower().endswith('.epub'):
            return os.path.join(folder, fname)
    return None


def _parse_ts(ts_str):
    """
    Parse a Calibre ISO-8601 timestamp string to a float (POSIX seconds).
    Returns 0.0 on any failure.  Only relative ordering matters here.
    """
    if not ts_str:
        return 0.0
    s = ts_str.strip().replace(' ', 'T')
    s = re.sub(r'[+-]\d{2}:\d{2}$', '', s)   # strip timezone offset
    s = re.sub(r'Z$', '', s)                   # strip trailing Z
    s = re.sub(r'\.\d+$', '', s)               # strip sub-seconds
    try:
        import datetime, calendar
        dt = datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S')
        return float(calendar.timegm(dt.timetuple()))
    except Exception:
        return 0.0


def _to_device_path(host_epub_path, calibre_home, koreader_base):
    """Replace the host Calibre root with the KOReader device root."""
    hp = host_epub_path.replace('\\', '/')
    ch = calibre_home.replace('\\', '/').rstrip('/')
    kb = koreader_base.rstrip('/')
    return (kb + hp[len(ch):]) if hp.startswith(ch) else hp


# ── Entry builder ─────────────────────────────────────────────────────────────

def _rows_to_entries(rows, calibre_home, koreader_base):
    """
    Convert DB rows → numbered entry dict for one collection.

    Ordering: max(last_modified, pubdate) descending (order 1 = most recent).
    Rows whose folder contains no .epub on disk are silently skipped.
    """
    books = []
    for _id, _title, _author, book_path, last_modified, pubdate in rows:
        host_path = _find_epub(calibre_home, book_path)
        if not host_path:
            continue
        ts = max(_parse_ts(last_modified), _parse_ts(pubdate))
        books.append((ts, host_path))

    books.sort(key=lambda x: (-x[0], x[1]))   # desc timestamp, then path

    return {
        i: {
            'file':  _to_device_path(hp, calibre_home, koreader_base),
            'order': i,
        }
        for i, (_, hp) in enumerate(books, start=1)
    }


def _collection_settings(order):
    return {
        'filter': {'add': {'filetype': 'epub'}},
        'order':  order,
    }


# ── Main builder ──────────────────────────────────────────────────────────────

def build_collection_data(calibre_home, koreader_base, existing_lua_data=None):
    """
    Build the full collection dict ready for render_lua().

    Order assignment for settings["order"]
    ──────────────────────────────────────
    • "instapaper" is always order=1 (when present).
    • All other collections (library + per-tag) are ranked by descending
      book count.  Ties broken alphabetically.
      Numbering starts at 2 if instapaper is present, otherwise at 1.
    """
    db_path = metadata_db_path(calibre_home)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(
            f'Calibre metadata.db not found at:\n  {db_path}\n'
            'Check the Calibre library path in plugin preferences.')

    conn = sqlite3.connect(db_path)
    try:
        all_tags  = _query_all_tags(conn)
        all_rows  = _query_all_books(conn)
        tag_rows  = {tag: _query_books_for_tag(conn, tag) for tag in all_tags}
    finally:
        conn.close()

    # ── Build raw entry dicts (no settings key yet) ───────────────────────────
    library_entries = _rows_to_entries(all_rows, calibre_home, koreader_base)

    tag_entries = {}
    for tag in all_tags:
        entries = _rows_to_entries(tag_rows[tag], calibre_home, koreader_base)
        if entries:   # skip tags with no discoverable EPUBs on disk
            tag_entries[tag] = entries

    # ── Rank by book count (desc), ties broken alphabetically ─────────────────
    has_instapaper = bool(existing_lua_data and 'instapaper' in existing_lua_data)
    start_order    = 2 if has_instapaper else 1

    # Build a list of (name, entries) sorted by -len then name
    ranked = sorted(
        [('library', library_entries)] + list(tag_entries.items()),
        key=lambda kv: (-len(kv[1]), kv[0])
    )
    order_map = {name: start_order + i for i, (name, _) in enumerate(ranked)}

    # ── Assemble final result ─────────────────────────────────────────────────
    result = {}

    if has_instapaper:
        block = dict(existing_lua_data['instapaper'])
        block['settings'] = {**block.get('settings', {}), **_collection_settings(1)}
        result['instapaper'] = block

    # Emit library first, then tags, each in ranked order
    for name, entries in ranked:
        entries['settings'] = _collection_settings(order_map[name])
        result[name] = entries

    return result
