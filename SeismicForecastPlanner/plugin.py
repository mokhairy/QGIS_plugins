import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .seismic_forecast_dialog import SeismicForecastDialog


class SeismicForecastPlannerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def tr(self, text):
        return QCoreApplication.translate("SeismicForecastPlannerPlugin", text)

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(
            QIcon(icon_path),
            self.tr("Seismic Forecast Planner"),
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToMenu(self.tr("&Seismic Forecast Planner"), self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

        if self.action is not None:
            self.iface.removePluginMenu(self.tr("&Seismic Forecast Planner"), self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def show_dialog(self):
        if self.dialog is None:
            self.dialog = SeismicForecastDialog(self.iface)

        self.dialog.refresh_layers()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
