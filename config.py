from calibre.utils.config import JSONConfig

# Stored at  <calibre-config-dir>/plugins/koreader_collections.json
prefs = JSONConfig('plugins/koreader_collections')

prefs.defaults['calibre_library_path'] = '/Users/monica/Calibre Library'
prefs.defaults['koreader_base_path']   = '/home/root/calibre'


try:
    from qt.core import QWidget, QFormLayout, QLineEdit, QLabel
except ImportError:
    from PyQt5.Qt import QWidget, QFormLayout, QLineEdit, QLabel


class ConfigWidget(QWidget):
    """Preferences page shown under Preferences → Plugins."""

    def __init__(self):
        QWidget.__init__(self)
        layout = QFormLayout()
        self.setLayout(layout)

        self.calibre_path = QLineEdit(self)
        self.calibre_path.setText(prefs['calibre_library_path'])
        layout.addRow(QLabel('Calibre library path:'), self.calibre_path)

        self.koreader_path = QLineEdit(self)
        self.koreader_path.setText(prefs['koreader_base_path'])
        layout.addRow(
            QLabel('KOReader books path (on device):'), self.koreader_path)

        note = QLabel(
            '<i>collection.lua is always written to '
            '&lt;Calibre library path&gt;/collection.lua</i>')
        note.setWordWrap(True)
        layout.addRow(note)

    def save_settings(self):
        prefs['calibre_library_path'] = self.calibre_path.text().strip()
        prefs['koreader_base_path']   = self.koreader_path.text().strip()
