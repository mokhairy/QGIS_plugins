import os
import sqlite3
import tempfile
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDataSourceUri,
    QgsMapLayerType,
    QgsMessageLog,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorLayer,
    QgsVectorLayerExporter,
)


class PostgisConnectionDialog(QDialog):
    def __init__(self, test_connection_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PostGIS Connection")
        self.setMinimumWidth(460)
        self._test_connection_callback = test_connection_callback

        self.host = QLineEdit()
        self.port = QLineEdit()
        self.dbname = QLineEdit()
        self.schema = QLineEdit()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)

        self.overwrite = QCheckBox("Overwrite existing tables")
        self.overwrite.setChecked(True)
        self.copy_styles = QCheckBox("Copy default layer styles to PostGIS layer_styles")
        self.copy_styles.setChecked(True)
        self.include_attributes = QCheckBox("Include non-spatial attribute tables")
        self.include_attributes.setChecked(True)

        form = QFormLayout()
        form.addRow("Host", self.host)
        form.addRow("Port", self.port)
        form.addRow("Database", self.dbname)
        form.addRow("Schema", self.schema)
        form.addRow("User", self.username)
        form.addRow("Password", self.password)

        self.test_button = QPushButton("Test Connection")
        self.test_button.clicked.connect(self._on_test_connection_clicked)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.test_button)
        layout.addWidget(self.overwrite)
        layout.addWidget(self.copy_styles)
        layout.addWidget(self.include_attributes)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _connection_values(self):
        return {
            "host": self.host.text().strip(),
            "port": self.port.text().strip(),
            "dbname": self.dbname.text().strip(),
            "schema": self.schema.text().strip() or "public",
            "username": self.username.text().strip(),
            "password": self.password.text(),
        }

    def _on_test_connection_clicked(self):
        values = self._connection_values()
        if not all([values["host"], values["port"], values["dbname"], values["username"]]):
            QMessageBox.warning(
                self,
                "Test Connection",
                "Fill host, port, database, and user before testing.",
            )
            return

        ok, message = self._test_connection_callback(
            values["host"],
            values["port"],
            values["dbname"],
            values["username"],
            values["password"],
        )
        if ok:
            QMessageBox.information(self, "Test Connection", message)
        else:
            QMessageBox.critical(self, "Test Connection", message)


class GpkgToPostgisImporterPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.project_action = None
        self.menu = self.tr("&GPKG to PostGIS Importer")
        self.icon_path = Path(__file__).resolve().parent / "icons" / "gpkg_to_postgis.svg"
        self.settings_prefix = "GpkgToPostgisImporter"

    def tr(self, text):
        return QCoreApplication.translate("GpkgToPostgisImporterPlugin", text)

    def initGui(self):
        self.action = QAction(
            QIcon(str(self.icon_path)),
            self.tr("Import GeoPackage to PostGIS"),
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

        self.project_action = QAction(
            QIcon(str(self.icon_path)),
            self.tr("Import Current Project Layers to PostGIS"),
            self.iface.mainWindow(),
        )
        self.project_action.triggered.connect(self.run_project_layers_import)
        self.iface.addPluginToMenu(self.menu, self.project_action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(self.menu, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.project_action is not None:
            self.iface.removePluginMenu(self.menu, self.project_action)
            self.project_action = None

    def _message(self, text, level=Qgis.Info, duration=10):
        self.iface.messageBar().pushMessage(
            "GPKG to PostGIS Importer",
            text,
            level=level,
            duration=duration,
        )
        QgsMessageLog.logMessage(text, "GpkgToPostgisImporter", level)

    def _read_setting(self, key, default=""):
        return QSettings().value(f"{self.settings_prefix}/{key}", default, type=str)

    def _write_setting(self, key, value):
        QSettings().setValue(f"{self.settings_prefix}/{key}", value)

    def _prompt_connection(self):
        dlg = PostgisConnectionDialog(self._test_postgis_connection, self.iface.mainWindow())
        dlg.host.setText(self._read_setting("host", "localhost"))
        dlg.port.setText(self._read_setting("port", "5432"))
        dlg.dbname.setText(self._read_setting("dbname", "postgres"))
        dlg.schema.setText(self._read_setting("schema", "public"))
        dlg.username.setText(self._read_setting("username", "postgres"))

        if dlg.exec_() != QDialog.Accepted:
            return None

        connection = {
            "host": dlg.host.text().strip(),
            "port": dlg.port.text().strip(),
            "dbname": dlg.dbname.text().strip(),
            "schema": dlg.schema.text().strip() or "public",
            "username": dlg.username.text().strip(),
            "password": dlg.password.text(),
            "overwrite": dlg.overwrite.isChecked(),
            "copy_styles": dlg.copy_styles.isChecked(),
            "include_attributes": dlg.include_attributes.isChecked(),
        }

        if not all(
            [
                connection["host"],
                connection["port"],
                connection["dbname"],
                connection["schema"],
                connection["username"],
            ]
        ):
            self._message("Connection fields are required.", level=Qgis.Warning)
            return None

        self._write_setting("host", connection["host"])
        self._write_setting("port", connection["port"])
        self._write_setting("dbname", connection["dbname"])
        self._write_setting("schema", connection["schema"])
        self._write_setting("username", connection["username"])

        return connection

    def _list_tables(self, gpkg_path, include_attributes):
        query = """
            SELECT table_name, data_type
            FROM gpkg_contents
            WHERE data_type IN ('features', 'attributes')
              AND table_name NOT LIKE 'gpkg_%'
              AND table_name NOT LIKE 'rtree_%'
              AND table_name <> 'layer_styles'
            ORDER BY table_name
        """
        with sqlite3.connect(gpkg_path) as conn:
            rows = conn.execute(query).fetchall()

        out = []
        for name, data_type in rows:
            if data_type == "attributes" and not include_attributes:
                continue
            out.append((name, data_type))
        return out

    def _source_layer(self, gpkg_path, table_name):
        return QgsVectorLayer(
            f"{gpkg_path}|layername={table_name}",
            table_name,
            "ogr",
        )

    def _build_pg_uri(
        self,
        host,
        port,
        dbname,
        user,
        password,
        schema,
        table_name,
        geom_col,
        pk_col,
    ):
        uri = QgsDataSourceUri()
        uri.setConnection(host, port, dbname, user, password)
        uri.setDataSource(schema, table_name, geom_col, "", pk_col)
        return uri.uri(False)

    def _ensure_postgis_extension(self, host, port, dbname, user, password):
        try:
            uri = QgsDataSourceUri()
            uri.setConnection(host, port, dbname, user, password)

            metadata = QgsProviderRegistry.instance().providerMetadata("postgres")
            if metadata is None:
                return False, "PostgreSQL provider is not available in this QGIS installation."

            conn = metadata.createConnection(uri.uri(False), {})
            if conn is None:
                return False, "Could not create PostgreSQL connection."

            conn.execSql("CREATE EXTENSION IF NOT EXISTS postgis;")
            conn.execSql("SELECT postgis_full_version();")
            return True, None
        except Exception as exc:
            return False, str(exc)

    def _sanitize_identifier(self, name, fallback="table"):
        cleaned = "".join(ch.lower() if ch.isalnum() or ch == "_" else "_" for ch in name)
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        cleaned = cleaned.strip("_")
        if not cleaned:
            cleaned = fallback
        if cleaned[0].isdigit():
            cleaned = f"t_{cleaned}"
        return cleaned[:63]

    def _test_postgis_connection(self, host, port, dbname, user, password):
        try:
            uri = QgsDataSourceUri()
            uri.setConnection(host, port, dbname, user, password)

            metadata = QgsProviderRegistry.instance().providerMetadata("postgres")
            if metadata is None:
                return False, "PostgreSQL provider is not available in this QGIS installation."

            conn = metadata.createConnection(uri.uri(False), {})
            if conn is None:
                return False, "Connection could not be created."

            return True, f"Connection successful to {dbname} on {host}:{port}."
        except Exception as exc:
            return False, f"Connection failed: {exc}"

    def _copy_style_to_postgis(self, source_layer, pg_uri, table_name, load_source_default_style=True):
        if load_source_default_style:
            source_layer.loadDefaultStyle()

        tmp_qml = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".qml", delete=False) as f:
                tmp_qml = f.name

            _, saved_ok = source_layer.saveNamedStyle(tmp_qml)
            if not saved_ok:
                return "could not serialize source style"

            target_layer = QgsVectorLayer(pg_uri, table_name, "postgres")
            if not target_layer.isValid():
                return "could not open target PostGIS layer for style save"

            _, loaded_ok = target_layer.loadNamedStyle(tmp_qml)
            if not loaded_ok:
                return "could not load source style into target layer"

            target_layer.saveStyleToDatabase(
                table_name,
                "Imported from GeoPackage",
                True,
                "",
            )
            return None
        finally:
            if tmp_qml and os.path.exists(tmp_qml):
                os.remove(tmp_qml)

    def _import_table(
        self,
        source_layer,
        data_type,
        host,
        port,
        dbname,
        user,
        password,
        schema,
        table_name,
        overwrite,
        copy_styles,
        load_source_default_style=True,
    ):
        src_uri = QgsDataSourceUri(source_layer.source())
        pk_col = "id"

        if data_type == "features" and source_layer.isSpatial():
            geom_col = "geom"
        else:
            geom_col = ""

        pg_uri = self._build_pg_uri(
            host,
            port,
            dbname,
            user,
            password,
            schema,
            table_name,
            geom_col,
            pk_col,
        )

        options = {}
        if overwrite:
            options["overwrite"] = True

        ret, err = QgsVectorLayerExporter.exportLayer(
            source_layer,
            pg_uri,
            "postgres",
            QgsCoordinateReferenceSystem(),
            False,
            options,
        )
        if ret != Qgis.VectorExportResult.Success:
            return False, f"{table_name}: {err or 'export failed'}", None

        style_warning = None
        if copy_styles and data_type == "features":
            style_warning = self._copy_style_to_postgis(
                source_layer,
                pg_uri,
                table_name,
                load_source_default_style=load_source_default_style,
            )
        return True, None, style_warning

    def _collect_project_layers(self, include_attributes):
        project_layers = []
        for layer in QgsProject.instance().layerTreeRoot().layerOrder():
            if layer.type() != QgsMapLayerType.VectorLayer:
                continue
            if not layer.isValid():
                continue
            data_type = "features" if layer.isSpatial() else "attributes"
            if data_type == "attributes" and not include_attributes:
                continue
            project_layers.append((layer.name(), layer, data_type))
        return project_layers

    def _run_import_job(self, sources, connection, source_label, use_current_project_style=False):
        host = connection["host"]
        port = connection["port"]
        dbname = connection["dbname"]
        schema = connection["schema"]
        username = connection["username"]
        password = connection["password"]
        overwrite = connection["overwrite"]
        copy_styles = connection["copy_styles"]

        imported = 0
        failed = []
        style_warnings = []
        invalid = []
        rename_notes = []
        used_target_names = set()

        for display_name, src_layer, data_type in sources:
            try:
                if not src_layer or not src_layer.isValid():
                    invalid.append(display_name)
                    continue

                target_name = self._sanitize_identifier(display_name)
                base_name = target_name
                suffix = 2
                while target_name in used_target_names:
                    candidate = f"{base_name}_{suffix}"
                    target_name = candidate[:63]
                    suffix += 1
                used_target_names.add(target_name)

                if target_name != display_name:
                    rename_notes.append(f"{display_name} -> {target_name}")

                ok, error_message, style_warning = self._import_table(
                    src_layer,
                    data_type,
                    host,
                    port,
                    dbname,
                    username,
                    password,
                    schema,
                    target_name,
                    overwrite,
                    copy_styles,
                    load_source_default_style=not use_current_project_style,
                )

                if not ok:
                    failed.append(error_message)
                    continue

                imported += 1
                if style_warning:
                    style_warnings.append(f"{target_name}: {style_warning}")
            except Exception as exc:
                failed.append(f"{display_name}: {exc}")

        if invalid:
            QgsMessageLog.logMessage(
                "\n".join([f"Invalid source layer: {n}" for n in invalid]),
                "GpkgToPostgisImporter",
                Qgis.Warning,
            )

        if failed:
            QgsMessageLog.logMessage(
                "\n".join(failed),
                "GpkgToPostgisImporter",
                Qgis.Warning,
            )

        if style_warnings:
            QgsMessageLog.logMessage(
                "\n".join(style_warnings),
                "GpkgToPostgisImporter",
                Qgis.Warning,
            )

        if rename_notes:
            QgsMessageLog.logMessage(
                "Renamed target tables for PostgreSQL compatibility:\n"
                + "\n".join(rename_notes[:50]),
                "GpkgToPostgisImporter",
                Qgis.Info,
            )

        level = Qgis.Success if imported > 0 else Qgis.Warning
        self._message(
            f"{source_label}: Imported {imported}/{len(sources)} table(s) to {dbname}.{schema}. "
            f"Failures: {len(failed)}. Style warnings: {len(style_warnings)}.",
            level=level,
            duration=12,
        )

    def run(self):
        gpkg_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            self.tr("Select Source GeoPackage"),
            self._read_setting("last_gpkg", str(Path.home())),
            self.tr("GeoPackage (*.gpkg)"),
        )
        if not gpkg_path:
            return
        self._write_setting("last_gpkg", gpkg_path)

        connection = self._prompt_connection()
        if connection is None:
            return

        ok_postgis, postgis_error = self._ensure_postgis_extension(
            connection["host"],
            connection["port"],
            connection["dbname"],
            connection["username"],
            connection["password"],
        )
        if not ok_postgis:
            self._message(
                "PostGIS is not enabled or cannot be created in this database. "
                "Run: CREATE EXTENSION IF NOT EXISTS postgis; "
                f"Details: {postgis_error}",
                level=Qgis.Critical,
                duration=14,
            )
            return

        try:
            tables = self._list_tables(gpkg_path, connection["include_attributes"])
        except Exception as exc:
            self._message(f"Could not read source GeoPackage: {exc}", level=Qgis.Critical, duration=12)
            return

        if not tables:
            self._message("No eligible tables found in source GeoPackage.", level=Qgis.Warning)
            return

        sources = []
        for table_name, data_type in tables:
            sources.append((table_name, self._source_layer(gpkg_path, table_name), data_type))

        self._run_import_job(
            sources,
            connection,
            "GeoPackage import",
            use_current_project_style=False,
        )

    def run_project_layers_import(self):
        connection = self._prompt_connection()
        if connection is None:
            return

        ok_postgis, postgis_error = self._ensure_postgis_extension(
            connection["host"],
            connection["port"],
            connection["dbname"],
            connection["username"],
            connection["password"],
        )
        if not ok_postgis:
            self._message(
                "PostGIS is not enabled or cannot be created in this database. "
                "Run: CREATE EXTENSION IF NOT EXISTS postgis; "
                f"Details: {postgis_error}",
                level=Qgis.Critical,
                duration=14,
            )
            return

        project_layers = self._collect_project_layers(connection["include_attributes"])
        if not project_layers:
            self._message(
                "No eligible vector layers found in the current project.",
                level=Qgis.Warning,
            )
            return

        self._run_import_job(
            project_layers,
            connection,
            "Current project import",
            use_current_project_style=True,
        )
