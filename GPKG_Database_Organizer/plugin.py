import os
import sqlite3
import tempfile
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox
from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)


class GpkgDatabaseOrganizerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.menu = self.tr("&GPKG Database Organizer")
        self.icon_path = Path(__file__).resolve().parent / "icons" / "gpkg_db_organizer.svg"

    def tr(self, text):
        return QCoreApplication.translate("GpkgDatabaseOrganizerPlugin", text)

    def initGui(self):
        self.action = QAction(
            QIcon(str(self.icon_path)),
            self.tr("Organize GeoPackage Database by Geometry"),
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is None:
            return
        self.iface.removePluginMenu(self.menu, self.action)
        self.iface.removeToolBarIcon(self.action)
        self.action = None

    def _message(self, text, level=Qgis.Info, duration=10):
        self.iface.messageBar().pushMessage(
            "GPKG Database Organizer",
            text,
            level=level,
            duration=duration,
        )
        QgsMessageLog.logMessage(text, "GPKGDatabaseOrganizer", level)

    def _list_feature_tables(self, gpkg_path):
        with sqlite3.connect(gpkg_path) as conn:
            rows = conn.execute(
                """
                SELECT table_name
                FROM gpkg_contents
                WHERE data_type='features'
                ORDER BY table_name
                """
            ).fetchall()
        return [r[0] for r in rows if r and r[0]]

    def _bucket(self, layer):
        geom = QgsWkbTypes.geometryType(layer.wkbType())
        if geom == Qgis.GeometryType.Point:
            return "point"
        if geom == Qgis.GeometryType.Line:
            return "line"
        if geom == Qgis.GeometryType.Polygon:
            return "polygon"
        return "other"

    def _build_default_qml_templates(self):
        templates = {}
        temp_files = []
        specs = {
            "point": "Point?crs=EPSG:4326",
            "line": "LineString?crs=EPSG:4326",
            "polygon": "Polygon?crs=EPSG:4326",
        }

        for bucket, uri in specs.items():
            layer = QgsVectorLayer(uri, f"__default_{bucket}__", "memory")
            if not layer.isValid():
                raise RuntimeError(f"Could not build default {bucket} style template.")

            with tempfile.NamedTemporaryFile(suffix=".qml", delete=False) as f:
                qml_path = f.name

            _, ok = layer.saveNamedStyle(qml_path)
            if not ok:
                raise RuntimeError(f"Could not save default {bucket} style template.")

            templates[bucket] = qml_path
            temp_files.append(qml_path)

        return templates, temp_files

    def _ordered_layers(self, source_gpkg):
        names = self._list_feature_tables(source_gpkg)
        if not names:
            return [], []

        grouped = {"point": [], "line": [], "polygon": [], "other": []}
        invalid = []

        for name in names:
            layer = QgsVectorLayer(f"{source_gpkg}|layername={name}", name, "ogr")
            if not layer.isValid():
                invalid.append(name)
                continue
            bucket = self._bucket(layer)
            grouped[bucket].append((name, layer, bucket))

        ordered = (
            grouped["point"]
            + grouped["line"]
            + grouped["polygon"]
            + grouped["other"]
        )
        return ordered, invalid

    def _make_output_layer_name(self, source_name, bucket, used_names):
        prefixes = {
            "point": "01_PT",
            "line": "02_LN",
            "polygon": "03_PG",
            "other": "04_OT",
        }
        prefix = prefixes.get(bucket, "04_OT")
        candidate = f"{prefix}__{source_name}"
        index = 2
        while candidate in used_names:
            candidate = f"{prefix}__{source_name}_{index}"
            index += 1
        used_names.add(candidate)
        return candidate

    def _apply_geometry_default_style(self, output_gpkg, out_layer_name, bucket, qml_templates):
        qml_path = qml_templates.get(bucket)
        if not qml_path:
            return None

        out_layer = QgsVectorLayer(
            f"{output_gpkg}|layername={out_layer_name}",
            out_layer_name,
            "ogr",
        )
        if not out_layer.isValid():
            return "output layer could not be opened for style write"

        _, loaded_ok = out_layer.loadNamedStyle(qml_path)
        if not loaded_ok:
            return "default geometry style could not be loaded"

        out_layer.saveStyleToDatabase(
            f"DEFAULT_{bucket.upper()}_STYLE",
            "Default geometry style generated by GPKG Database Organizer",
            True,
            "",
        )
        return None

    def _write_ordered_copy(self, ordered_layers, output_gpkg, qml_templates):
        style_warnings = []
        write_warnings = []
        renamed_layers = []
        used_names = set()

        for i, (source_name, layer, bucket) in enumerate(ordered_layers):
            out_layer_name = self._make_output_layer_name(source_name, bucket, used_names)
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = out_layer_name
            options.fileEncoding = "UTF-8"
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteFile
                if i == 0
                else QgsVectorFileWriter.CreateOrOverwriteLayer
            )

            err_code, err_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                output_gpkg,
                QgsProject.instance().transformContext(),
                options,
            )
            if err_code != QgsVectorFileWriter.NoError:
                write_warnings.append(f"{source_name}: {err_msg or 'write failed'}")
                continue

            style_err = self._apply_geometry_default_style(
                output_gpkg,
                out_layer_name,
                bucket,
                qml_templates,
            )
            if style_err:
                style_warnings.append(f"{out_layer_name}: {style_err}")

            renamed_layers.append((source_name, out_layer_name))

        return write_warnings, style_warnings, renamed_layers

    def run(self):
        source_gpkg, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            self.tr("Select Source GeoPackage"),
            str(Path.home()),
            self.tr("GeoPackage (*.gpkg)"),
        )
        if not source_gpkg:
            return

        source_path = Path(source_gpkg)
        default_output = str(source_path.with_name(f"{source_path.stem}_organized.gpkg"))
        output_gpkg, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            self.tr("Save Organized GeoPackage As"),
            default_output,
            self.tr("GeoPackage (*.gpkg)"),
        )
        if not output_gpkg:
            return

        if not output_gpkg.lower().endswith(".gpkg"):
            output_gpkg = f"{output_gpkg}.gpkg"

        output_path = Path(output_gpkg)
        if output_path.exists():
            overwrite = QMessageBox.question(
                self.iface.mainWindow(),
                "Overwrite GeoPackage",
                f"File exists:\n{output_gpkg}\n\nOverwrite?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if overwrite != QMessageBox.Yes:
                return
            try:
                output_path.unlink()
            except Exception as exc:
                self._message(f"Could not overwrite output file: {exc}", level=Qgis.Critical, duration=12)
                return

        try:
            ordered_layers, invalid = self._ordered_layers(source_gpkg)
        except Exception as exc:
            self._message(f"Could not inspect source GeoPackage: {exc}", level=Qgis.Critical, duration=12)
            return

        if not ordered_layers:
            self._message("No valid feature layers found in source GeoPackage.", level=Qgis.Warning)
            return

        temp_files = []
        try:
            qml_templates, temp_files = self._build_default_qml_templates()
            write_warnings, style_warnings, renamed_layers = self._write_ordered_copy(
                ordered_layers,
                output_gpkg,
                qml_templates,
            )
        except Exception as exc:
            self._message(f"Failed during reorganization: {exc}", level=Qgis.Critical, duration=12)
            return
        finally:
            for path in temp_files:
                if os.path.exists(path):
                    os.remove(path)

        if invalid:
            QgsMessageLog.logMessage(
                "\n".join([f"Invalid source layer: {n}" for n in invalid]),
                "GPKGDatabaseOrganizer",
                Qgis.Warning,
            )

        if write_warnings:
            QgsMessageLog.logMessage(
                "\n".join(write_warnings),
                "GPKGDatabaseOrganizer",
                Qgis.Warning,
            )

        if style_warnings:
            QgsMessageLog.logMessage(
                "\n".join(style_warnings),
                "GPKGDatabaseOrganizer",
                Qgis.Warning,
            )

        if renamed_layers:
            preview = "\n".join([f"{old} -> {new}" for old, new in renamed_layers[:20]])
            QgsMessageLog.logMessage(
                "Renamed output tables for geometry grouping:\n" + preview,
                "GPKGDatabaseOrganizer",
                Qgis.Info,
            )

        self._message(
            (
                f"Organized GeoPackage created: {output_gpkg}. "
                f"Layers processed: {len(ordered_layers)}. "
                f"Write warnings: {len(write_warnings)}. "
                f"Style warnings: {len(style_warnings)}. "
                "Current project layer layout was not changed."
            ),
            level=Qgis.Success,
            duration=14,
        )
