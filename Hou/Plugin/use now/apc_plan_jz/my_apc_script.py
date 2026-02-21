# my_apc_script.py
# -*- coding: utf-8 -*-
# Hussein Al Shibli  |  BGP Oman APC

from qgis.PyQt import QtWidgets, QtCore
from qgis.utils import iface
from qgis.core import QgsProject, QgsRectangle, QgsMessageLog, Qgis

import os
import sqlite3
import traceback

try:
    import psycopg2
except ImportError:
    psycopg2 = None

# ---------- Signature ----------
# Hussein Al Shibli | BGP Oman APC
SIGNATURE_TEXT = "Hussein Al Shibli | BGP Oman APC"

# ---------- Config ----------
# Legacy defaults (no longer used directly, kept only for reference)
SOURCE_LAYER_NAME   = "design_s_blockd"
RECV_NORMAL_NAME    = "design_r_blockd"

DEFAULT_LINE_FIELD  = "field_7"
DEFAULT_SQLITE_PATH = r"E:/26 JAZAL/01-DataBase/APC_Plan_Database_JZ.sqlite3"
APP_TITLE = "APC Swath Filter"

# Block list: (UI text, layer suffix, DB key)
#   - Layers: design_s_<suffix>, design_r_<suffix>
#   - DB tables: <db_key>_normal
BLOCK_OPTIONS = [
    ("Block A", "BlockA", "blocka"),
    ("Block B", "BlockB", "blockb"),
    ("Block C", "BlockC", "blockc"),
    ("Block D", "BlockD", "blockd"),
]

# ---------- Logging ----------
def _push(level, msg):
    try:
        QgsMessageLog.logMessage(str(msg), "APC", level=level)
        iface.messageBar().pushMessage(APP_TITLE, str(msg), level=level, duration=6)
    except Exception:
        pass

def info(m): _push(Qgis.Info, m)
def warn(m): _push(Qgis.Warning, m)
def crit(m): _push(Qgis.Critical, m)

def log_exc(prefix, e=None):
    tb = traceback.format_exc()
    crit(f"{prefix}: {e or ''}\n{tb}")

# ---------- DB ----------
def connect_sqlite(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQLite DB not found: {path}")
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=DELETE;")
    return con

def connect_postgres(host, dbname, user, password, port=5432):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed. Run: pip install psycopg2")
    return psycopg2.connect(host=host, database=dbname, user=user, password=password, port=port)

def table_exists(conn, dbtype: str, tab: str) -> bool:
    cur = conn.cursor()
    try:
        if dbtype == "sqlite":
            cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (tab,))
            return cur.fetchone() is not None
        else:
            try:
                cur.execute(f"SELECT 1 FROM {tab} LIMIT 1;")
                return True
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return False
    finally:
        cur.close()

def _num_clause(dbtype: str, col: str) -> str:
    # Treat a column as integer even if stored as text (SQLite/PG safe)
    if dbtype == "sqlite":
        return (
            f"CASE "
            f" WHEN typeof({col})='integer' THEN {col} "
            f" WHEN typeof({col})='text' AND {col}<>'' AND {col} NOT GLOB '*[^0-9]*' "
            f" THEN CAST({col} AS INTEGER) "
            f" ELSE NULL END"
        )
    else:
        return f"NULLIF(regexp_replace({col}::text, '[^0-9]', '', 'g'), '')::int"

def fetch_line_ranges_for_range(conn, dbtype: str, block: str, sw_from: int, sw_to: int):
    """
    Return (src_from, src_to, rcvN_from, rcvN_to) for the swath range.
      - Source range -> from <block>_normal (MIN(source_line_from), MAX(source_line_to))
      - Receiver Normal -> from <block>_normal (MIN(receiver_line_from), MAX(receiver_line_to))

    'block' is the DB key, e.g. 'blockc', 'blockd'.
    """
    tbl_normal = f"{block}_normal"

    sw_expr       = _num_clause(dbtype, "swath_number")
    src_from_expr = _num_clause(dbtype, "source_line_from")
    src_to_expr   = _num_clause(dbtype, "source_line_to")
    rcv_from_expr = _num_clause(dbtype, "receiver_line_from")
    rcv_to_expr   = _num_clause(dbtype, "receiver_line_to")

    cur = conn.cursor()

    def agg_src(tbl):
        sel = f"MIN({src_from_expr}), MAX({src_to_expr})"
        if dbtype == "sqlite":
            sql = f"SELECT {sel} FROM {tbl} WHERE {sw_expr} BETWEEN ? AND ?"
            cur.execute(sql, (sw_from, sw_to))
        else:
            sql = f"SELECT {sel} FROM {tbl} WHERE {sw_expr} BETWEEN %s AND %s"
            cur.execute(sql, (sw_from, sw_to))
        return cur.fetchone() or (None, None)

    def agg_rcv(tbl):
        sel = f"MIN({rcv_from_expr}), MAX({rcv_to_expr})"
        if dbtype == "sqlite":
            sql = f"SELECT {sel} FROM {tbl} WHERE {sw_expr} BETWEEN ? AND ?"
            cur.execute(sql, (sw_from, sw_to))
        else:
            sql = f"SELECT {sel} FROM {tbl} WHERE {sw_expr} BETWEEN %s AND %s"
            cur.execute(sql, (sw_from, sw_to))
        return cur.fetchone() or (None, None)

    try:
        has_normal = table_exists(conn, dbtype, tbl_normal)

        if not has_normal:
            raise RuntimeError(f"No table {tbl_normal} in DB.")

        # Source range from Normal
        src_from = src_to = None
        s_min, s_max = agg_src(tbl_normal)
        src_from = int(s_min) if s_min is not None else None
        src_to   = int(s_max) if s_max is not None else None

        # Receiver Normal min/max
        rcvN_from = rcvN_to = None
        r_min_n, r_max_n = agg_rcv(tbl_normal)
        rcvN_from = int(r_min_n) if r_min_n is not None else None
        rcvN_to   = int(r_max_n) if r_max_n is not None else None

        return src_from, src_to, rcvN_from, rcvN_to
    finally:
        cur.close()

def fetch_design_vps_sum(conn, dbtype: str, block: str, sw_from: int, sw_to: int):
    """Sum design_vps from <block>_normal across selected swaths. Returns int or None."""
    tbl_normal = f"{block}_normal"
    if not table_exists(conn, dbtype, tbl_normal):
        return None

    sw_expr = _num_clause(dbtype, "swath_number")
    dv_expr = _num_clause(dbtype, "design_vps")

    cur = conn.cursor()
    try:
        if dbtype == "sqlite":
            sql = f"SELECT SUM({dv_expr}) FROM {tbl_normal} WHERE {sw_expr} BETWEEN ? AND ?;"
            cur.execute(sql, (sw_from, sw_to))
        else:
            sql = f"SELECT SUM({dv_expr}) FROM {tbl_normal} WHERE {sw_expr} BETWEEN %s AND %s;"
            cur.execute(sql, (sw_from, sw_to))
        row = cur.fetchone()
        total = row[0] if row else None
        return int(total) if total is not None else None
    finally:
        cur.close()

# ---------- QGIS helpers ----------
def get_layer_by_name(name: str):
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.name() == name:
            return lyr
    return None

def safe_feature_count(layer):
    """
    Return a reliable feature count.
    If provider returns -1 or fails, fall back to manual counting.
    """
    if layer is None:
        return None
    try:
        cnt = layer.featureCount()
        if cnt is not None and cnt >= 0:
            return cnt
        return sum(1 for _ in layer.getFeatures())
    except Exception:
        return None

def set_line_filter(layer, line_field: str, a: int, b: int):
    if layer is None:
        return (False, 0)
    prov = layer.dataProvider()
    field_names = [f.name() for f in prov.fields()]
    if line_field not in field_names:
        return (False, 0)
    if a is None or b is None:
        layer.setSubsetString("")
        layer.triggerRepaint()
        return (False, 0)
    lo, hi = (a, b) if a <= b else (b, a)
    expr = f"\"{line_field}\" >= {lo} AND \"{line_field}\" <= {hi}"
    layer.setSubsetString(expr)
    layer.triggerRepaint()

    cnt = safe_feature_count(layer)
    if cnt is None:
        cnt = 0
    return (True, cnt)

def zoom_to_layers(layers):
    ext = None
    for lyr in layers:
        if lyr is None:
            continue
        r = lyr.extent()
        if not r or r.isEmpty():
            continue
        ext = QgsRectangle(r) if ext is None else ext.combineExtentWith(r) or ext
    if ext is not None and not ext.isEmpty():
        iface.mapCanvas().setExtent(ext)
        iface.mapCanvas().refresh()

def _count_by_step(lo, hi, step):
    """Return ((hi - lo) // step) + 1, guarding None and negatives."""
    if lo is None or hi is None or step <= 0:
        return None
    diff = hi - lo
    if diff < 0:
        return None
    return (diff // step) + 1

def _fmt_count(n):
    """Format counts for display: hide None/negative."""
    if n is None or n < 0:
        return ""
    return n

# ---------- Dock ----------
class SwathFilterDock(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__(APP_TITLE, parent)
        try:
            self.setObjectName("APC_Swath_Filter_Diag")
            w = QtWidgets.QWidget(self)
            self.setWidget(w)
            self.setMinimumWidth(360)
            self.setMinimumHeight(250)

            # DB select
            self.dbtype = QtWidgets.QComboBox()
            self.dbtype.addItems(["postgresql", "sqlite"])
            self.dbtype.setCurrentText("postgresql")

            # SQLite
            self.sqlitePath  = QtWidgets.QLineEdit(DEFAULT_SQLITE_PATH)
            self.sqliteBrowse= QtWidgets.QPushButton("...")
            self.sqliteBrowse.setFixedWidth(28)
            self.sqliteBrowse.clicked.connect(self._choose_sqlite)

            # PG
            self.pgHost = QtWidgets.QLineEdit("localhost")
            self.pgDb   = QtWidgets.QLineEdit("apc_plan")  # DB name
            self.pgUser = QtWidgets.QLineEdit("postgres")
            self.pgPass = QtWidgets.QLineEdit("hu8622")
            self.pgPass.setEchoMode(QtWidgets.QLineEdit.Password)
            self.pgPort = QtWidgets.QLineEdit("5433")

            # Block selection (combo)
            self.blockCombo = QtWidgets.QComboBox()
            for text, layer_suffix, db_key in BLOCK_OPTIONS:
                self.blockCombo.addItem(text, (layer_suffix, db_key))
            self.blockCombo.setCurrentIndex(self.blockCombo.count() - 1)

            # Swath range
            self.swFrom = QtWidgets.QSpinBox()
            self.swFrom.setRange(0, 999999)
            self.swFrom.setValue(101)

            self.swTo   = QtWidgets.QSpinBox()
            self.swTo.setRange(0, 999999)
            self.swTo.setValue(108)

            # Buttons (one line): Apply, Clear, Survey, SPS
            self.applyBtn = QtWidgets.QPushButton("Apply")
            self.clearBtn = QtWidgets.QPushButton("Clear")
            self.syncSurveyBtn = QtWidgets.QPushButton("Survey ↻")
            self.syncSpsBtn    = QtWidgets.QPushButton("SPS ↻")

            self.syncSurveyBtn.setToolTip("Sync Survey Shapefiles (update only if changes are detected)")
            self.syncSpsBtn.setToolTip("Sync SPS Tables (import new or update modified data)")

            self.applyBtn.setFixedWidth(70)
            self.clearBtn.setFixedWidth(70)
            self.syncSurveyBtn.setFixedWidth(90)
            self.syncSpsBtn.setFixedWidth(90)

            # Debug (hidden)
            self.testBtn  = QtWidgets.QPushButton("Test DB & Layers")
            self.pingBtn  = QtWidgets.QPushButton("Ping UI")
            self.testBtn.hide()
            self.pingBtn.hide()

            # Status
            self.status = QtWidgets.QLabel("Ready.")
            self.status.setStyleSheet("QLabel { color: #004080; }")

            # Layout
            form = QtWidgets.QFormLayout()
            form.setHorizontalSpacing(4)
            form.setVerticalSpacing(4)
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)

            form.addRow("DB Type", self.dbtype)

            h_sqlite = QtWidgets.QHBoxLayout()
            h_sqlite.setContentsMargins(0, 0, 0, 0)
            h_sqlite.setSpacing(4)
            h_sqlite.addWidget(self.sqlitePath)
            h_sqlite.addWidget(self.sqliteBrowse)
            self.sqliteRow = QtWidgets.QWidget()
            self.sqliteRow.setLayout(h_sqlite)
            self.sqliteLabel = QtWidgets.QLabel("SQLite")
            form.addRow(self.sqliteLabel, self.sqliteRow)

            grid_pg = QtWidgets.QGridLayout()
            grid_pg.setContentsMargins(0, 0, 0, 0)
            grid_pg.setHorizontalSpacing(4)
            grid_pg.setVerticalSpacing(2)
            grid_pg.addWidget(QtWidgets.QLabel("Host"), 0, 0)
            grid_pg.addWidget(self.pgHost,               0, 1)
            grid_pg.addWidget(QtWidgets.QLabel("DB"),   0, 2)
            grid_pg.addWidget(self.pgDb,                0, 3)
            grid_pg.addWidget(QtWidgets.QLabel("User"), 1, 0)
            grid_pg.addWidget(self.pgUser,              1, 1)
            grid_pg.addWidget(QtWidgets.QLabel("Pass"), 1, 2)
            grid_pg.addWidget(self.pgPass,              1, 3)
            grid_pg.addWidget(QtWidgets.QLabel("Port"), 2, 0)
            grid_pg.addWidget(self.pgPort,              2, 1)
            self.pgBox = QtWidgets.QGroupBox("PostgreSQL")
            self.pgBox.setLayout(grid_pg)
            form.addRow(self.pgBox)

            # Block + Swath row
            row_block = QtWidgets.QWidget()
            h1 = QtWidgets.QHBoxLayout()
            h1.setContentsMargins(0, 0, 0, 0)
            h1.setSpacing(4)

            self.blockCombo.setFixedWidth(90)
            self.swFrom.setFixedWidth(65)
            self.swTo.setFixedWidth(65)

            h1.addWidget(QtWidgets.QLabel("Block"))
            h1.addWidget(self.blockCombo)
            h1.addWidget(QtWidgets.QLabel("Swath From"))
            h1.addWidget(self.swFrom)
            h1.addWidget(QtWidgets.QLabel("To"))
            h1.addWidget(self.swTo)

            row_block.setLayout(h1)
            row_block.setSizePolicy(QtWidgets.QSizePolicy.Maximum,
                                    QtWidgets.QSizePolicy.Fixed)
            form.addRow(row_block)

            # Buttons row
            hb = QtWidgets.QHBoxLayout()
            hb.setContentsMargins(0, 0, 0, 0)
            hb.setSpacing(6)
            hb.addWidget(self.applyBtn)
            hb.addWidget(self.clearBtn)
            hb.addWidget(self.syncSurveyBtn)
            hb.addWidget(self.syncSpsBtn)
            hb.addWidget(self.testBtn)
            hb.addWidget(self.pingBtn)
            hb.addStretch(1)
            form.addRow(hb)

            # Status line
            form.addRow(self.status)

            # Signature
            form.addItem(
                QtWidgets.QSpacerItem(
                    0, 10,
                    QtWidgets.QSizePolicy.Minimum,
                    QtWidgets.QSizePolicy.Fixed
                )
            )
            self.signatureLbl = QtWidgets.QLabel(SIGNATURE_TEXT)
            self.signatureLbl.setStyleSheet("QLabel { color: #666666; font-size: 10pt; }")
            self.signatureLbl.setAlignment(QtCore.Qt.AlignLeft)
            form.addRow(self.signatureLbl)

            w.setLayout(form)

            # Wire
            self.applyBtn.clicked.connect(self.apply)
            self.clearBtn.clicked.connect(self.clear_filters)

            self.syncSurveyBtn.clicked.connect(self.update_survey)
            self.syncSpsBtn.clicked.connect(self.update_sps)

            self.testBtn.clicked.connect(self.test_everything)
            self.pingBtn.clicked.connect(lambda: self.status.setText("UI OK."))

            self.dbtype.currentIndexChanged.connect(self._toggle_db_frames)

            self._toggle_db_frames()
            QtCore.QTimer.singleShot(0, lambda: self._force_layout_refresh())

        except Exception as e:
            log_exc("Dock init failed", e)
            lbl = QtWidgets.QLabel(
                "APC panel failed to initialize. See Log Messages Panel (APC)."
            )
            self.setWidget(lbl)

    # ----------- NEW: Survey / SPS actions -----------
    def update_survey(self):
        """
        Survey ↻ button action
        Calls survey.py inside plugin folder.
        """
        try:
            self.status.setText("Survey ↻ : Starting...")
            info("Survey ↻ clicked.")

            # ✅ Load survey.py from the plugin folder (works even without package imports)
            import importlib.util

            plugin_dir = os.path.dirname(__file__)
            survey_path = os.path.join(plugin_dir, "survey.py")

            if not os.path.exists(survey_path):
                msg = f"survey.py not found in plugin folder: {survey_path}"
                warn(msg)
                self.status.setText(f"Survey ↻ : {msg}")
                return

            spec = importlib.util.spec_from_file_location("apc_survey", survey_path)
            survey = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(survey)

            ok, msg = survey.run(
                iface=iface,
                parent=self,
                status_callback=self.status.setText
            )

            if ok:
                self.status.setText(msg)
                info(msg)
            else:
                self.status.setText(msg)
                warn(msg)

        except Exception as e:
            log_exc("Update Survey failed", e)
            self.status.setText(f"Survey ↻ : Error: {e}")

    def update_sps(self):
        """
        SPS ↻ button action
        """
        try:
            self.status.setText("SPS ↻ : Starting...")
            info("SPS ↻ clicked.")
            # TODO: put your SPS update logic here
            self.status.setText("SPS ↻ : TODO (not added yet).")
            warn("SPS update is not implemented yet.")
        except Exception as e:
            log_exc("Update SPS failed", e)
            self.status.setText(f"SPS ↻ : Error: {e}")

    # ----------- Helpers inside dock -----------
    def _get_block_keys(self):
        data = self.blockCombo.currentData()
        if data:
            return data
        return ("BlockD", "blockd")

    def _get_layer_names_for_current_block(self):
        layer_suffix, _db_key = self._get_block_keys()
        layer_suffix = layer_suffix.lower()
        src_name  = f"design_s_{layer_suffix}"
        rcv_norm  = f"design_r_{layer_suffix}"
        return src_name, rcv_norm

    def _force_layout_refresh(self):
        try:
            self.widget().updateGeometry()
            self.widget().adjustSize()
            self.widget().update()
            self.resize(self.minimumWidth() + 1, self.minimumHeight() + 1)
        except Exception as e:
            log_exc("Layout refresh failed", e)

    def _toggle_db_frames(self, *args):
        try:
            if self.dbtype.currentText() == "postgresql":
                self.pgBox.show()
                self.sqliteRow.hide()
                self.sqliteLabel.hide()
            else:
                self.pgBox.hide()
                self.sqliteRow.show()
                self.sqliteLabel.show()
            self._force_layout_refresh()
        except Exception as e:
            log_exc("Toggle DB frames failed", e)

    def _choose_sqlite(self):
        try:
            p, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select SQLite DB",
                self.sqlitePath.text(),
                "SQLite DB (*.db *.sqlite *.sqlite3);;All files (*.*)"
            )
            if p:
                self.sqlitePath.setText(p)
        except Exception as e:
            log_exc("Choose SQLite failed", e)

    def _get_conn(self):
        if self.dbtype.currentText() == "sqlite":
            return connect_sqlite(self.sqlitePath.text()), "sqlite"
        return connect_postgres(
            self.pgHost.text(),
            self.pgDb.text(),
            self.pgUser.text(),
            self.pgPass.text(),
            int(self.pgPort.text() or 5432)
        ), "postgresql"

    # ----------- Actions -----------
    def test_everything(self):
        try:
            src_name, rcv_norm_name = self._get_layer_names_for_current_block()

            lyr_s  = get_layer_by_name(src_name)
            lyr_rn = get_layer_by_name(rcv_norm_name)

            missing = [
                n for n, l in [
                    (src_name,      lyr_s),
                    (rcv_norm_name, lyr_rn),
                ]
                if l is None
            ]
            if missing:
                warn(f"Missing layers: {', '.join(missing)}")
            else:
                info("All layers found.")

            conn, dbt = self._get_conn()
            _layer_suffix, blk_db = self._get_block_keys()

            ok1 = table_exists(conn, dbt, f"{blk_db}_normal")
            conn.close()

            if not ok1:
                warn(f"Table not found: {blk_db}_normal")
            else:
                info("Table present: normal")
            self.status.setText("Test finished.")
        except Exception as e:
            log_exc("Test DB & Layers failed", e)
            self.status.setText(f"Error: {e}")

    def apply(self):
        try:
            _layer_suffix, blk_db = self._get_block_keys()
            src_name, rcv_norm_name = self._get_layer_names_for_current_block()

            a = int(self.swFrom.value())
            b = int(self.swTo.value())
            lf = DEFAULT_LINE_FIELD

            sw_lo, sw_hi = (a, b) if a <= b else (b, a)

            conn, dbt = self._get_conn()

            src_from, src_to, rcvN_from, rcvN_to = fetch_line_ranges_for_range(
                conn, dbt, blk_db, sw_lo, sw_hi
            )

            design_vps_total = fetch_design_vps_sum(conn, dbt, blk_db, sw_lo, sw_hi)
            conn.close()

            lyr_s  = get_layer_by_name(src_name)
            lyr_rn = get_layer_by_name(rcv_norm_name)

            applied = []
            cnt_s = cnt_rn = None

            if src_from is not None and src_to is not None:
                ok, cnt_s = set_line_filter(lyr_s, lf, src_from, src_to)
                if ok:
                    applied.append(lyr_s)

            if rcvN_from is not None and rcvN_to is not None:
                ok, cnt_rn = set_line_filter(lyr_rn, lf, rcvN_from, rcvN_to)
                if ok:
                    applied.append(lyr_rn)

            if applied:
                zoom_to_layers(applied)

            normal_receiver_lines = _count_by_step(rcvN_from, rcvN_to, 8)
            normal_nodes_total = cnt_rn

            block_label = self.blockCombo.currentText()

            self.status.setText(
                f"\n"
                f"Block: {block_label}\n\n"
                f"Source Line Range: {src_from} → {src_to}\n\n"
                f"Normal Line Range: {rcvN_from} → {rcvN_to}\n\n"
                f"Number of Normal Receiver Lines: "
                f"{normal_receiver_lines if normal_receiver_lines is not None else ''}\n\n"
                f"Number of Normal Nodes: {_fmt_count(normal_nodes_total)}\n\n"
                f"Design VPs: {design_vps_total if design_vps_total is not None else ''}\n"
            )
            info(self.status.text())
        except Exception as e:
            log_exc("Apply failed", e)
            self.status.setText(f"Error: {e}")

    def clear_filters(self):
        try:
            src_name, rcv_norm_name = self._get_layer_names_for_current_block()
            for nm in (src_name, rcv_norm_name):
                lyr = get_layer_by_name(nm)
                if lyr:
                    lyr.setSubsetString("")
                    lyr.triggerRepaint()
            iface.mapCanvas().refresh()
            self.status.setText("Filters cleared.")
            info("Filters cleared.")
        except Exception as e:
            log_exc("Clear filters failed", e)
            self.status.setText(f"Error: {e}")

def show_apc_swath_filter():
    for d in iface.mainWindow().findChildren(QtWidgets.QDockWidget, "APC_Swath_Filter_Diag"):
        d.close()
    dock = SwathFilterDock(iface.mainWindow())
    iface.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    dock.raise_()
    info("APC Swath Filter opened. Use 'Test DB & Layers' if nothing happens.")

# ---------- Plugin-friendly entry point ----------
def main(qgis_iface=None):
    """
    Called by the plugin. Shows the dock and returns a short status string.
    """
    if qgis_iface is not None:
        pass
    show_apc_swath_filter()
    return f"APC Swath Filter loaded • {SIGNATURE_TEXT}"

# Hussein Al Shibli  |  BGP Oman APC
