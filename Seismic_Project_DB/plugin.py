from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog
from qgis.core import Qgis, QgsMessageLog, QgsProject

try:
    from .package_project_shapefiles import package_current_project_shapefiles
except ImportError:
    from .scripts.package_project_shapefiles import package_current_project_shapefiles


class SeismicProjectDbPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.configure_style_action = None
        self.menu = self.tr("&Seismic Project DB")
        self.icon_path = (
            Path(__file__).resolve().parent / "icons" / "shp_to_gpkg.svg"
        )
        self.style_template_key = "SeismicProjectDB/default_style_template_gpkg"

    def tr(self, message):
        return QCoreApplication.translate("SeismicProjectDbPlugin", message)

    def initGui(self):
        self.action = QAction(
            QIcon(str(self.icon_path)),
            self.tr("Package Project Shapefiles to GeoPackage"),
            self.iface.mainWindow(),
        )
        self.configure_style_action = QAction(
            self.tr("Set Default Style Template GeoPackage..."),
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.configure_style_action.triggered.connect(self.configure_style_template)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addPluginToMenu(self.menu, self.configure_style_action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is None:
            return
        self.iface.removePluginMenu(self.menu, self.action)
        if self.configure_style_action is not None:
            self.iface.removePluginMenu(self.menu, self.configure_style_action)
        self.iface.removeToolBarIcon(self.action)
        self.action = None
        self.configure_style_action = None

    def _default_output_path(self):
        project = QgsProject.instance()
        home_path = project.homePath()
        project_name = project.baseName() or "project_layers"
        return str(Path(home_path or Path.home()) / f"{project_name}.gpkg")

    def _message(self, title, text, level=Qgis.Info, duration=8):
        self.iface.messageBar().pushMessage(title, text, level=level, duration=duration)
        QgsMessageLog.logMessage(text, "SeismicProjectDB", level)

    def _get_style_template_path(self):
        path = (QSettings().value(self.style_template_key, "", type=str) or "").strip()
        if not path:
            return None

        style_path = Path(path).expanduser()
        if not style_path.exists():
            self._message(
                "Seismic Project DB",
                f"Configured style template not found: {style_path}",
                level=Qgis.Warning,
                duration=10,
            )
            return None
        return str(style_path)

    def configure_style_template(self):
        current = self._get_style_template_path() or str(Path.home())
        template_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            self.tr("Select Default Style Template GeoPackage"),
            current,
            self.tr("GeoPackage (*.gpkg)"),
        )
        if not template_path:
            return

        QSettings().setValue(self.style_template_key, template_path)
        self._message(
            "Seismic Project DB",
            f"Default style template set: {template_path}",
            level=Qgis.Success,
            duration=8,
        )

    def run(self):
        output_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            self.tr("Save Project Package As"),
            self._default_output_path(),
            self.tr("GeoPackage (*.gpkg)"),
        )

        if not output_path:
            return

        style_template_path = self._get_style_template_path()

        try:
            gpkg_path, layer_names, result = package_current_project_shapefiles(
                output_path,
                overwrite=True,
                style_template_gpkg=style_template_path,
            )
        except Exception as exc:
            self._message("Seismic Project DB", str(exc), level=Qgis.Critical, duration=12)
            return

        style_errors = (result or {}).get("style_errors", [])
        if style_errors:
            QgsMessageLog.logMessage(
                "\n".join(style_errors),
                "SeismicProjectDB",
                Qgis.Warning,
            )

        template_applied = int((result or {}).get("template_styles_applied", 0) or 0)
        template_missing = (result or {}).get("template_styles_missing", []) or []
        template_errors = (result or {}).get("template_style_errors", []) or []

        if template_errors:
            QgsMessageLog.logMessage(
                "\n".join(template_errors),
                "SeismicProjectDB",
                Qgis.Warning,
            )

        self._message(
            "Seismic Project DB",
            (
                f"Exported {len(layer_names)} layer(s) to {gpkg_path}. "
                f"Template styles applied: {template_applied}. "
                f"Missing template styles: {len(template_missing)}. "
                f"Style save warnings: {len(style_errors)}."
            ),
            level=Qgis.Success,
            duration=12,
        )
