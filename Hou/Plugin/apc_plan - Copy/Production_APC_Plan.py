# -*- coding: utf-8 -*-
"""
APC Plan – QGIS 3 Plugin
Author: Hussein Al Shibli | BGP Oman APC
"""

# ---------- Signature ----------
SIGNATURE_TEXT = "Hussein Al Shibli | BGP Oman APC"

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from qgis.core import Qgis, QgsMessageLog
from qgis.utils import iface

from .resources import *
# We no longer import the generated dialog to avoid showing the blank window
# from .APC_Plan_dialog import APCPlanDialog

# Import YOUR script (the dock lives here)
from . import my_apc_script

import os.path


def _log(msg: str, level=Qgis.Info):
    try:
        iface.messageBar().pushMessage("APC Plan", str(msg), level=level, duration=6)
    except Exception:
        pass
    QgsMessageLog.logMessage(str(msg), "APC Plan", level)


class APCPlan:
    def __init__(self, iface_):
        self.iface = iface_
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr("&APC Plan")

    def tr(self, message):
        return QCoreApplication.translate("APCPlan", message)

    def add_action(self, icon_path, text, callback, parent=None, status_tip=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        if status_tip:
            action.setStatusTip(status_tip)
        self.iface.addToolBarIcon(action)
        self.iface.addPluginToMenu(self.menu, action)
        self.actions.append(action)
        return action

    def initGui(self):

        self.toolbar = self.iface.addToolBar("APC Plan")
        self.toolbar.setObjectName("APCPlanToolbar")

        icon_path = ':/plugins/APC_Plan/icons/hou_pdo_red_padded.svg'
        action = QAction(QIcon(icon_path), "APC Plan", self.iface.mainWindow())
        action.setStatusTip("Run custom APC Swath Filter • " + SIGNATURE_TEXT)
        action.triggered.connect(self.run)

        # Make the icon slightly bigger than default (32 px)
        action.setIcon(QIcon(icon_path))
        action.setIconVisibleInMenu(True)
        action.setIconText("Hou")
        action.setToolTip("APC Plan Tool")
        self.toolbar.setIconSize(QtCore.QSize(32, 32))  # <— add this line!

        self.toolbar.addAction(action)
        self.iface.addPluginToMenu("&APC Plan", action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        _log(f"Plugin unloaded — {SIGNATURE_TEXT}")

    def run(self):
        """Just open your dock; do NOT show the default dialog."""
        try:
            msg = my_apc_script.main(self.iface)  # opens your dock
            if msg:
                _log(msg + f" • {SIGNATURE_TEXT}")
        except Exception as e:
            _log(f"⚠️ Error in APC script: {e} • {SIGNATURE_TEXT}", Qgis.Critical)
            QMessageBox.critical(self.iface.mainWindow(), "APC Plan", f"Error: {e}")
