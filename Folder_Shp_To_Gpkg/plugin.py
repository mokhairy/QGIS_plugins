import os
import sqlite3
import tempfile
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox
from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsVectorFileWriter, QgsVectorLayer


class FolderShpToGpkgPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.configure_style_action = None
        self.menu = self.tr("&Folder SHP to GPKG")
        self.icon_path = (
            Path(__file__).resolve().parent / "icons" / "folder_to_gpkg.svg"
        )
        self.style_template_key = "FolderSHPtoGPKG/default_style_template_gpkg"

    def tr(self, message):
        return QCoreApplication.translate("FolderShpToGpkgPlugin", message)

    def initGui(self):
        self.action = QAction(
            QIcon(str(self.icon_path)),
            self.tr("Import Folder Shapefiles to GeoPackage"),
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

    def _message(self, text, level=Qgis.Info, duration=10):
        self.iface.messageBar().pushMessage("Folder SHP to GPKG", text, level=level, duration=duration)
        QgsMessageLog.logMessage(text, "FolderSHPtoGPKG", level)

    def _get_style_template_path(self):
        path = (QSettings().value(self.style_template_key, "", type=str) or "").strip()
        if not path:
            return None

        style_path = Path(path).expanduser()
        if not style_path.exists():
            self._message(
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
            f"Default style template set: {template_path}",
            level=Qgis.Success,
            duration=8,
        )

    def _unique_name(self, name, used_names):
        base_name = (name or "layer").strip() or "layer"
        candidate = base_name
        index = 2
        while candidate in used_names:
            candidate = f"{base_name}_{index}"
            index += 1
        used_names.add(candidate)
        return candidate

    def _get_shapefiles(self, folder_path):
        folder = Path(folder_path)
        return sorted(
            [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".shp"],
            key=lambda p: p.name.lower(),
        )

    def _save_style_to_gpkg(self, source_layer, gpkg_path, gpkg_layer_name):
        output_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={gpkg_layer_name}",
            gpkg_layer_name,
            "ogr",
        )
        if not output_layer.isValid():
            raise RuntimeError("Could not open exported layer to save style.")

        tmp_qml = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".qml", delete=False) as tmp_file:
                tmp_qml = tmp_file.name

            _, saved_ok = source_layer.saveNamedStyle(tmp_qml)
            if not saved_ok:
                raise RuntimeError("Could not serialize source layer style.")

            _, loaded_ok = output_layer.loadNamedStyle(tmp_qml)
            if not loaded_ok:
                raise RuntimeError("Could not load style into exported GeoPackage layer.")

            output_layer.saveStyleToDatabase(
                source_layer.name(),
                "Saved by Folder SHP to GPKG plugin",
                True,
                "",
            )
        finally:
            if tmp_qml and os.path.exists(tmp_qml):
                os.remove(tmp_qml)

    def _read_template_styles(self, template_gpkg_path):
        template_path = Path(template_gpkg_path).expanduser()
        if not template_path.exists():
            raise RuntimeError(f"Style template GeoPackage not found: {template_path}")

        with sqlite3.connect(str(template_path)) as conn:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='layer_styles' LIMIT 1"
            ).fetchone()
            if not has_table:
                raise RuntimeError(
                    "Template GeoPackage does not contain a layer_styles table."
                )

            rows = conn.execute(
                """
                SELECT f_table_name, styleQML, COALESCE(useAsDefault, 0) AS is_default, id
                FROM layer_styles
                WHERE styleQML IS NOT NULL AND styleQML <> ''
                ORDER BY is_default DESC, id DESC
                """
            ).fetchall()

        by_layer_name = {}
        for layer_name, style_qml, _, _ in rows:
            if layer_name and layer_name not in by_layer_name:
                by_layer_name[layer_name] = style_qml
        return by_layer_name

    def _apply_template_styles_to_gpkg(self, target_gpkg_path, target_layer_names, template_gpkg_path):
        style_map = self._read_template_styles(template_gpkg_path)
        if not style_map:
            return 0, list(target_layer_names), []

        applied = 0
        missing = []
        errors = []

        for layer_name in target_layer_names:
            style_qml = style_map.get(layer_name)
            if not style_qml:
                missing.append(layer_name)
                continue

            output_layer = QgsVectorLayer(
                f"{target_gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr",
            )
            if not output_layer.isValid():
                errors.append(f"{layer_name}: could not open target layer for template style.")
                continue

            tmp_qml = None
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".qml",
                    delete=False,
                    mode="w",
                    encoding="utf-8",
                ) as tmp_file:
                    tmp_qml = tmp_file.name
                    tmp_file.write(style_qml)

                _, loaded_ok = output_layer.loadNamedStyle(tmp_qml)
                if not loaded_ok:
                    errors.append(f"{layer_name}: could not load template style QML.")
                    continue

                output_layer.saveStyleToDatabase(
                    layer_name,
                    f"Default style from template {Path(template_gpkg_path).name}",
                    True,
                    "",
                )
                applied += 1
            except Exception as exc:
                errors.append(f"{layer_name}: {exc}")
            finally:
                if tmp_qml and os.path.exists(tmp_qml):
                    os.remove(tmp_qml)

        return applied, missing, errors

    def _load_and_export(self, shapefiles, output_gpkg):
        project = QgsProject.instance()
        used_layer_names = set()
        exported_layers = []
        skipped_layers = []
        style_errors = []
        first_write = True
        loaded_count = 0

        for shp_path in shapefiles:
            source_name = shp_path.stem
            source_layer = QgsVectorLayer(str(shp_path), source_name, "ogr")
            if not source_layer.isValid():
                skipped_layers.append(f"{shp_path.name}: invalid layer")
                continue

            project.addMapLayer(source_layer)
            loaded_count += 1

            gpkg_layer_name = self._unique_name(source_name, used_layer_names)
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = gpkg_layer_name
            options.fileEncoding = "UTF-8"
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteFile
                if first_write
                else QgsVectorFileWriter.CreateOrOverwriteLayer
            )

            error_code, error_message, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                source_layer,
                output_gpkg,
                project.transformContext(),
                options,
            )

            if error_code != QgsVectorFileWriter.NoError:
                message = error_message or "Unknown write error"
                skipped_layers.append(f"{shp_path.name}: {message}")
                continue

            exported_layers.append(gpkg_layer_name)
            first_write = False

            try:
                self._save_style_to_gpkg(source_layer, output_gpkg, gpkg_layer_name)
            except Exception as exc:
                style_errors.append(f"{gpkg_layer_name}: {exc}")

        if not exported_layers:
            raise RuntimeError(
                "No shapefiles were exported. Check layer validity and output write permissions."
            )

        return loaded_count, exported_layers, skipped_layers, style_errors

    def _ask_project_save_to_gpkg(self, default_gpkg_path):
        project_gpkg_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            self.tr("Save Project To GeoPackage"),
            default_gpkg_path,
            self.tr("GeoPackage (*.gpkg)"),
        )
        if not project_gpkg_path:
            return

        if not project_gpkg_path.lower().endswith(".gpkg"):
            project_gpkg_path = f"{project_gpkg_path}.gpkg"

        ok = QgsProject.instance().write(project_gpkg_path)
        if ok:
            self._message(f"Project saved to GeoPackage: {project_gpkg_path}", level=Qgis.Success)
        else:
            self._message(
                "Could not save project into the selected GeoPackage.",
                level=Qgis.Critical,
                duration=12,
            )

    def _create_new_project_from_gpkg(self, gpkg_path, gpkg_layer_names):
        created = self.iface.newProject(True)
        if not created:
            raise RuntimeError("New project creation canceled.")

        project = QgsProject.instance()
        loaded_count = 0
        load_errors = []
        style_apply_errors = []

        for layer_name in gpkg_layer_names:
            gpkg_layer = QgsVectorLayer(
                f"{gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr",
            )
            if not gpkg_layer.isValid():
                load_errors.append(f"{layer_name}: could not load GeoPackage layer")
                continue

            _, style_ok = gpkg_layer.loadDefaultStyle()
            if not style_ok:
                style_apply_errors.append(
                    f"{layer_name}: default style not found in GeoPackage"
                )

            project.addMapLayer(gpkg_layer)
            loaded_count += 1

        if loaded_count == 0:
            raise RuntimeError("Could not load any GeoPackage layers into the new project.")

        return loaded_count, load_errors, style_apply_errors

    def run(self):
        folder_path = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(),
            self.tr("Select Folder Containing Shapefiles"),
            str(Path.home()),
        )
        if not folder_path:
            return

        default_gpkg = str(Path(folder_path) / f"{Path(folder_path).name or 'layers'}.gpkg")
        output_gpkg, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            self.tr("Create Output GeoPackage"),
            default_gpkg,
            self.tr("GeoPackage (*.gpkg)"),
        )
        if not output_gpkg:
            return

        style_template_path = self._get_style_template_path()

        if not output_gpkg.lower().endswith(".gpkg"):
            output_gpkg = f"{output_gpkg}.gpkg"

        output_path = Path(output_gpkg)
        if output_path.exists():
            answer = QMessageBox.question(
                self.iface.mainWindow(),
                "Overwrite GeoPackage",
                f"The file already exists:\n{output_gpkg}\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            try:
                output_path.unlink()
            except Exception as exc:
                self._message(
                    f"Could not overwrite output file: {exc}",
                    level=Qgis.Critical,
                    duration=12,
                )
                return

        shapefiles = self._get_shapefiles(folder_path)
        if not shapefiles:
            self._message(
                f"No .shp files found in folder: {folder_path}",
                level=Qgis.Warning,
            )
            return

        try:
            loaded_count, exported_layers, skipped_layers, style_errors = self._load_and_export(
                shapefiles,
                output_gpkg,
            )
        except Exception as exc:
            self._message(str(exc), level=Qgis.Critical, duration=12)
            return

        if skipped_layers:
            QgsMessageLog.logMessage(
                "\n".join(skipped_layers),
                "FolderSHPtoGPKG",
                Qgis.Warning,
            )

        if style_errors:
            QgsMessageLog.logMessage(
                "\n".join(style_errors),
                "FolderSHPtoGPKG",
                Qgis.Warning,
            )
            self._message(
                f"Exported {len(exported_layers)} layer(s), but {len(style_errors)} style(s) could not be saved.",
                level=Qgis.Warning,
                duration=12,
            )

        self._message(
            f"Loaded {loaded_count} layer(s), exported {len(exported_layers)} to {output_gpkg}.",
            level=Qgis.Success,
            duration=12,
        )

        template_applied = 0
        template_missing = []
        template_errors = []
        if style_template_path:
            try:
                template_applied, template_missing, template_errors = self._apply_template_styles_to_gpkg(
                    output_gpkg,
                    exported_layers,
                    style_template_path,
                )
            except Exception as exc:
                template_errors.append(str(exc))

        if template_errors:
            QgsMessageLog.logMessage(
                "\n".join(template_errors),
                "FolderSHPtoGPKG",
                Qgis.Warning,
            )

        self._message(
            f"Template styles applied: {template_applied}, missing template styles: {len(template_missing)}.",
            level=Qgis.Info,
            duration=10,
        )

        try:
            new_loaded_count, new_load_errors, style_apply_errors = self._create_new_project_from_gpkg(
                output_gpkg,
                exported_layers,
            )
        except Exception as exc:
            self._message(str(exc), level=Qgis.Critical, duration=12)
            return

        if new_load_errors:
            QgsMessageLog.logMessage(
                "\n".join(new_load_errors),
                "FolderSHPtoGPKG",
                Qgis.Warning,
            )

        if style_apply_errors:
            QgsMessageLog.logMessage(
                "\n".join(style_apply_errors),
                "FolderSHPtoGPKG",
                Qgis.Warning,
            )

        self._message(
            f"New project created with {new_loaded_count} GeoPackage layer(s); styles applied automatically.",
            level=Qgis.Success,
            duration=12,
        )
        self._message(
            "Select a GeoPackage in the next dialog to save the QGIS project.",
            level=Qgis.Info,
            duration=8,
        )
        self._ask_project_save_to_gpkg(output_gpkg)
