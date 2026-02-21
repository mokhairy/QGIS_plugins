from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from qgis.PyQt.QtCore import QCoreApplication, QVariant, QDate
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorLayer,
)

PLUGIN_DIR = Path(__file__).resolve().parent
LIB_DIR = PLUGIN_DIR / "lib"
if LIB_DIR.exists() and str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

DEFAULT_DATA_DIR = PLUGIN_DIR / "data"

ROOT_CANDIDATE = PLUGIN_DIR.parents[2]
SRC_DIR = ROOT_CANDIDATE / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rcm_sim import DailySimulationResult, SimulationConfig, SimulationEngine  # type: ignore  # noqa: E402


class SimulationDialog(QDialog):
    def __init__(self, parent=None, default_dir: Optional[Path] = None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("RCM Daily Production")
        self.default_dir = default_dir or Path.home()

        self.config_edit = QLineEdit()
        self.config_browse = QPushButton("Browse…")
        self.config_browse.clicked.connect(self._choose_config)

        config_row = QHBoxLayout()
        config_row.addWidget(self.config_edit)
        config_row.addWidget(self.config_browse)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)

        self.days_spin = QSpinBox()
        self.days_spin.setMinimum(1)
        self.days_spin.setMaximum(365)
        self.days_spin.setValue(3)

        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("Optional")

        form_layout = QFormLayout()
        form_layout.addRow("Config file", config_row)
        form_layout.addRow("Start date", self.date_edit)
        form_layout.addRow("Number of days", self.days_spin)
        form_layout.addRow("Random seed", self.seed_edit)

        self.message_label = QLabel("")
        self.message_label.setStyleSheet("color: #d63031;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(self.message_label)
        layout.addWidget(buttons)
        self.setLayout(layout)

        sample = self.default_dir / "sample_project.json"
        if sample.exists():
            self.config_edit.setText(str(sample))

    def _choose_config(self) -> None:
        start_dir = str(self.default_dir)
        path, _ = QFileDialog.getOpenFileName(self, "Select simulation config", start_dir, "JSON files (*.json)")
        if path:
            self.config_edit.setText(path)

    def _validate_and_accept(self) -> None:
        config_path = Path(self.config_edit.text().strip())
        if not config_path.exists():
            self.message_label.setText("Config file not found.")
            return
        self.message_label.clear()
        self.accept()

    def values(self) -> dict:
        seed_text = self.seed_edit.text().strip()
        seed_value = None
        if seed_text:
            try:
                seed_value = int(seed_text)
            except ValueError:
                seed_value = None
        return {
            "config_path": self.config_edit.text().strip(),
            "start_date": self.date_edit.date().toPyDate(),
            "days": int(self.days_spin.value()),
            "seed": seed_value,
        }


class RCMProgressPlugin:
    def __init__(self, iface):  # type: ignore[no-untyped-def]
        self.iface = iface
        self.action: Optional[QAction] = None

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("RCMProgressPlugin", message)

    def initGui(self) -> None:  # type: ignore[override]
        icon_path = PLUGIN_DIR / "icon.png"
        self.action = QAction(QIcon(str(icon_path)), self.tr("RCM Daily Production"), self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.tr("&RCM Production"), self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self) -> None:  # type: ignore[override]
        if self.action:
            self.iface.removePluginMenu(self.tr("&RCM Production"), self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self) -> None:
        dialog = SimulationDialog(self.iface.mainWindow(), DEFAULT_DATA_DIR)
        if dialog.exec() != QDialog.Accepted:
            return

        values = dialog.values()
        config_path = values["config_path"]
        start_day = values["start_date"]
        days = values["days"]
        seed = values["seed"]

        try:
            config = SimulationConfig.from_file(config_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self.iface.mainWindow(), self.tr("Config error"), str(exc))
            return

        engine = SimulationEngine(config, seed=seed)
        results = engine.simulate_range(start_day, days)
        if not results:
            QMessageBox.information(self.iface.mainWindow(), self.tr("Simulation"), self.tr("No results generated."))
            return

        layer = self._build_layer(results)
        QgsProject.instance().addMapLayer(layer)

        summary_lines = [
            f"{r.date.isoformat()}: {r.executed_shots} shots / {r.active_receivers} receivers ({r.weather_state})"
            for r in results
        ]
        self.iface.messageBar().pushMessage(
            self.tr("RCM Production"),
            " | ".join(summary_lines),
            level=Qgis.Info,
            duration=12,
        )

    def _build_layer(self, results: List[DailySimulationResult]) -> QgsVectorLayer:
        layer_name = self.tr("RCM Daily Production")
        layer = QgsVectorLayer("Point?crs=EPSG:4326", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("event_time", QVariant.String),
                QgsField("day", QVariant.String),
                QgsField("event_type", QVariant.String),
                QgsField("source_id", QVariant.String),
                QgsField("status", QVariant.String),
                QgsField("crew", QVariant.Int),
                QgsField("sequence", QVariant.Int),
            ]
        )
        layer.updateFields()

        features = []
        for daily in results:
            for event in daily.events:
                feat = QgsFeature(layer.fields())
                feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(event.longitude, event.latitude)))
                feat.setAttribute("event_time", event.event_time.isoformat())
                feat.setAttribute("day", daily.date.isoformat())
                feat.setAttribute("event_type", event.event_type)
                feat.setAttribute("source_id", event.source_id or "")
                feat.setAttribute("status", event.status or "executed")
                feat.setAttribute("crew", event.attributes.get("crew"))
                feat.setAttribute("sequence", event.attributes.get("sequence"))
                features.append(feat)
        provider.addFeatures(features)
        layer.updateExtents()

        self._apply_renderer(layer)
        return layer

    def _apply_renderer(self, layer: QgsVectorLayer) -> None:
        categories = []
        palette = {
            "executed": QColor("#00b894"),
            "repeated": QColor("#d63031"),
            "weather-delay": QColor("#0984e3"),
        }
        for status, color in palette.items():
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol is None:
                continue
            symbol.setColor(color)
            category = QgsRendererCategory(status, symbol, status)
            categories.append(category)
        renderer = QgsCategorizedSymbolRenderer("status", categories)
        layer.setRenderer(renderer)
