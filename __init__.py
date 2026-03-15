from calibre.customize import InterfaceActionBase


class KOReaderCollectionsPlugin(InterfaceActionBase):
    """
    Calibre plugin that exports the library as a KOReader collection.lua file.

    Generates:
      - A "library" collection containing all EPUB books in the library.
      - One collection per Calibre tag, containing all EPUBs with that tag.
      - Preserves any existing "instapaper" collection from a previous collection.lua.

    Book ordering within each collection is determined by
    max(last_modified, pubdate/timestamp) — most recently touched first.
    """

    name                    = 'KOReader Collections Exporter'
    description             = ('Export Calibre library and tags as a KOReader '
                               'collection.lua file, preserving instapaper entries.')
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'calibre-koreader-plugin'
    version                 = (1, 0, 0)
    minimum_calibre_version = (5, 0, 0)

    #: Defers GUI loading — the real plugin lives in ui.py
    actual_plugin = 'calibre_plugins.koreader_collections.ui:KOReaderCollectionsAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.koreader_collections.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
        ac = self.actual_plugin_
        if ac is not None:
            ac.apply_settings()
