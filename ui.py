"""
ui.py – InterfaceAction that adds the 'KOReader Collections' toolbar button.

Clicking the button:
  1. Reads prefs for calibre_library_path and koreader_base_path.
  2. Loads an existing $CALIBRE_HOME/collection.lua (to preserve instapaper).
  3. Queries $CALIBRE_HOME/metadata.db for books and tags.
  4. Writes the new collection.lua back to $CALIBRE_HOME/collection.lua.
"""

from calibre.gui2.actions import InterfaceAction


class KOReaderCollectionsAction(InterfaceAction):

    name = 'KOReader Collections'

    action_spec = (
        'KOReader Collections',
        None,
        'Generate / update KOReader collection.lua from the Calibre library',
        None,
    )

    def genesis(self):
        self.qaction.triggered.connect(self.export_collections)

    # ── Main export handler ───────────────────────────────────────────────────

    def export_collections(self):
        from calibre_plugins.koreader_collections.config import prefs
        from calibre_plugins.koreader_collections.core import (
            build_collection_data,
            collection_lua_path,
            parse_existing_lua,
            render_lua,
        )

        try:
            from qt.core import QMessageBox
        except ImportError:
            from PyQt5.Qt import QMessageBox

        calibre_home  = prefs['calibre_library_path']
        koreader_base = prefs['koreader_base_path']
        out_path      = collection_lua_path(calibre_home)

        # ── Preserve existing instapaper block ────────────────────────────────
        existing_data = {}
        try:
            import os
            if os.path.isfile(out_path):
                with open(out_path, 'r', encoding='utf-8') as fh:
                    existing_data = parse_existing_lua(fh.read())
        except Exception as exc:
            QMessageBox.warning(
                self.gui, 'KOReader Collections',
                f'Could not read existing collection.lua — instapaper entries '
                f'will not be preserved.\n\nError: {exc}')

        # ── Build ─────────────────────────────────────────────────────────────
        try:
            data     = build_collection_data(
                calibre_home, koreader_base, existing_data)
            lua_text = render_lua(data)
        except Exception as exc:
            import traceback
            QMessageBox.critical(
                self.gui, 'KOReader Collections — Error',
                f'{exc}\n\n{traceback.format_exc()}')
            return

        # ── Write ─────────────────────────────────────────────────────────────
        try:
            with open(out_path, 'w', encoding='utf-8') as fh:
                fh.write(lua_text)
        except Exception as exc:
            QMessageBox.critical(
                self.gui, 'KOReader Collections — Write Error',
                f'Could not write:\n  {out_path}\n\n{exc}')
            return

        # ── Summary ───────────────────────────────────────────────────────────
        n_library = sum(1 for k in data.get('library', {}) if isinstance(k, int))
        tag_names = [k for k in data if k not in ('instapaper', 'library')]
        instapaper_status = (
            'preserved' if 'instapaper' in existing_data
            else ('present' if 'instapaper' in data else 'absent'))

        QMessageBox.information(
            self.gui, 'KOReader Collections — Done',
            f'Written to:\n  {out_path}\n\n'
            f'  library     : {n_library} book(s)\n'
            f'  tag collections ({len(tag_names)}): '
            f'{", ".join(tag_names[:8])}{"…" if len(tag_names) > 8 else ""}\n'
            f'  instapaper  : {instapaper_status}')

    def apply_settings(self):
        pass
