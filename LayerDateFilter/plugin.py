import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .date_filter_dialog import DateFilterDialog


class LayerDateFilterPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def tr(self, text):
        return QCoreApplication.translate("LayerDateFilterPlugin", text)

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(
            QIcon(icon_path),
            self.tr("Layer Date Filter"),
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToMenu(self.tr("&Layer Date Filter"), self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

        if self.action is not None:
            self.iface.removePluginMenu(self.tr("&Layer Date Filter"), self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def show_dialog(self):
        if self.dialog is None:
            self.dialog = DateFilterDialog(self.iface)

        self.dialog.refresh_layers()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
