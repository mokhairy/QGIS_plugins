import os
import sqlite3
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None

APP_TITLE = "APC_Plan Importer"
DEFAULT_SQLITE = r"E:/26 JAZAL/01-DataBase/APC_Plan_Database_JZ.sqlite3"

# ---------- Swath DB column names (match table definition) ----------
SWATH_COLS = [
    "swath_number",
    "source_line_from",
    "source_line_to",
    "source_point_from",
    "source_point_to",
    "design_vps",
    "receiver_line_from",
    "receiver_line_to",
    "receiver_station_from",
    "receiver_station_to",
    "receiver_lines_per_swath",
    "traces_per_swath",
]

# ---------- DB connections ----------
def connect_sqlite(path: str):
    # Do NOT create DB if missing
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQLite DB not found: {path}")
    con = sqlite3.connect(
        path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    # Avoid extra -wal/-shm files
    con.execute("PRAGMA journal_mode=DELETE;")
    return con


def connect_postgres(host, dbname, user, password, port=5432):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed. Run: pip install psycopg2")
    return psycopg2.connect(
        host=host, database=dbname, user=user, password=password, port=port
    )


# ---------- SQL helpers ----------
def q_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""').strip() + '"'


def q_table(name: str) -> str:
    return q_ident(name)


def q_cols(cols) -> str:
    return ",".join(q_ident(c) for c in cols)


def ensure_table_swath(conn, table_name: str, dbtype: str):
    serial = "SERIAL" if dbtype == "postgresql" else "INTEGER"
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_table(table_name)} (
          {q_ident("id")} {serial} PRIMARY KEY,
          {q_ident("swath_number")} INTEGER NOT NULL,
          {q_ident("source_line_from")} INTEGER,
          {q_ident("source_line_to")} INTEGER,
          {q_ident("source_point_from")} INTEGER,
          {q_ident("source_point_to")} INTEGER,
          {q_ident("design_vps")} INTEGER,
          {q_ident("receiver_line_from")} INTEGER,
          {q_ident("receiver_line_to")} INTEGER,
          {q_ident("receiver_station_from")} INTEGER,
          {q_ident("receiver_station_to")} INTEGER,
          {q_ident("receiver_lines_per_swath")} INTEGER,
          {q_ident("traces_per_swath")} INTEGER
        );
    """
    )
    conn.commit()
    cur.close()


def ensure_table_rline_normal(conn, table_name: str):
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {q_table(table_name)} (
          {q_ident("normal_line")} INTEGER,
          {q_ident("normal_station_start")} INTEGER,
          {q_ident("normal_station_end")} INTEGER,
          {q_ident("normal_traces")} INTEGER
        );
    """
    )
    conn.commit()
    cur.close()


def drop_table(conn, table_name: str):
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {q_table(table_name)};")
    conn.commit()
    cur.close()


def list_tables(conn, dbtype: str):
    cur = conn.cursor()
    if dbtype == "sqlite":
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
    else:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name;"
        )
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows


# ---------- Data shaping ----------
def build_df_swath(df_src: pd.DataFrame) -> pd.DataFrame:
    cols = list(df_src.columns)
    n = len(cols)

    def s(i):
        return df_src.iloc[:, i] if i < n else pd.Series([None] * len(df_src))

    has_dup_design = n >= 13
    design_left = s(5)
    if has_dup_design:
        design_right = s(6)
        design_final = design_left.where(
            design_left.notna() & (design_left.astype(str).str.strip() != ""),
            design_right,
        )
        a, b, c, d, e, f = 7, 8, 9, 10, 11, 12
    else:
        design_final = design_left
        a, b, c, d, e, f = 6, 7, 8, 9, 10, 11

    out = pd.DataFrame(
        {
            "swath_number": s(0),
            "source_line_from": s(1),
            "source_line_to": s(2),
            "source_point_from": s(3),
            "source_point_to": s(4),
            "design_vps": design_final,
            "receiver_line_from": s(a),
            "receiver_line_to": s(b),
            "receiver_station_from": s(c),
            "receiver_station_to": s(d),
            "receiver_lines_per_swath": s(e),
            "traces_per_swath": s(f),
        }
    )
    for c in out.columns:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.fillna(0)
    out = out[out["swath_number"] > 0].copy()
    out.reset_index(drop=True, inplace=True)
    return out


def _norm(h):
    s = str(h).strip().lower()
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _find_rline_blocks(df_header1: pd.DataFrame):
    # Drop fully empty columns (skip spacers)
    df = df_header1.dropna(axis=1, how="all").copy()
    cols = list(df.columns)
    norm = [_norm(c) for c in cols]
    n = len(norm)
    starts = []
    for i in range(0, n - 3):
        if norm[i + 1] == "start" and norm[i + 2] == "end" and norm[i + 3] == "traces":
            starts.append(i)
    return df, starts


def build_df_rline_normal_only(df_src_header1: pd.DataFrame) -> pd.DataFrame:
    df, starts = _find_rline_blocks(df_src_header1)

    labels = ["normal_line", "normal_station_start", "normal_station_end", "normal_traces"]

    if not starts:
        return pd.DataFrame(columns=labels)

    i = starts[0]
    n = df.shape[1]
    if i + 3 >= n:
        return pd.DataFrame(columns=labels)

    block = df.iloc[:, [i, i + 1, i + 2, i + 3]].copy()
    block.columns = labels
    for c in block.columns:
        block[c] = pd.to_numeric(block[c], errors="coerce")
    block = block.fillna(0)
    block = block[block["normal_line"] > 0].copy()
    block.reset_index(drop=True, inplace=True)
    return block


def df_to_python_ints(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for row in df.itertuples(index=False, name=None):
        rows.append(tuple(0 if pd.isna(v) else int(v) for v in row))
    return rows


# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x480")

        # DB type / paths
        self.dbtype = tk.StringVar(value="postgresql")
        self.sqlite_path = tk.StringVar(value=DEFAULT_SQLITE)

        # Block selector (A/B/C/D)
        self.block = tk.StringVar(value="D")

        # Excel
        self.xlsx_path = tk.StringVar(value="")
        self.mode = tk.StringVar(value="replace")

        # PostgreSQL settings
        self.pg_host = tk.StringVar(value="localhost")
        self.pg_db = tk.StringVar(value="apc_plan_jz")
        self.pg_user = tk.StringVar(value="postgres")
        self.pg_pass = tk.StringVar(value="hu8622")
        self.pg_port = tk.StringVar(value="5433")

        self._build_ui()
        self.toggle_db_frames()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # React on block change
        self.block.trace_add("write", self._on_block_change)

    # ----- UI -----
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        # DB type
        ttk.Label(root, text="DB Type").grid(row=0, column=0, sticky="w")
        dbtype_combo = ttk.Combobox(
            root,
            textvariable=self.dbtype,
            values=["sqlite", "postgresql"],
            width=12,
            state="readonly",
        )
        dbtype_combo.grid(row=0, column=1, sticky="w")
        dbtype_combo.bind("<<ComboboxSelected>>", lambda e: self.toggle_db_frames())

        # Block selector A/B/C/D
        ttk.Label(root, text="Block").grid(row=0, column=2, sticky="e", padx=(20, 0))
        block_combo = ttk.Combobox(
            root,
            textvariable=self.block,
            values=["A", "B", "C", "D"],
            width=4,
            state="readonly",
        )
        block_combo.grid(row=0, column=3, sticky="w")

        # SQLite frame
        self.sqlite_frame = ttk.LabelFrame(root, text="SQLite", padding=6)
        self.sqlite_frame.grid(row=1, column=0, columnspan=4, sticky="we", pady=(6, 0))
        ttk.Label(self.sqlite_frame, text="DB File").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.sqlite_frame, textvariable=self.sqlite_path, width=52).grid(
            row=0, column=1, padx=6, sticky="we"
        )
        ttk.Button(self.sqlite_frame, text="Browse", command=self.choose_sqlite).grid(
            row=0, column=2, padx=2
        )

        # Postgres frame
        self.pg_frame = ttk.LabelFrame(root, text="PostgreSQL Connection", padding=6)
        self.pg_frame.grid(row=2, column=0, columnspan=4, sticky="we", pady=6)
        ttk.Label(self.pg_frame, text="Host").grid(row=0, column=0)
        ttk.Entry(self.pg_frame, textvariable=self.pg_host, width=14).grid(
            row=0, column=1
        )
        ttk.Label(self.pg_frame, text="DB").grid(row=0, column=2)
        ttk.Entry(self.pg_frame, textvariable=self.pg_db, width=16).grid(
            row=0, column=3
        )
        ttk.Label(self.pg_frame, text="User").grid(row=0, column=4)
        ttk.Entry(self.pg_frame, textvariable=self.pg_user, width=14).grid(
            row=0, column=5
        )
        ttk.Label(self.pg_frame, text="Pass").grid(row=0, column=6)
        ttk.Entry(self.pg_frame, textvariable=self.pg_pass, width=14, show="*").grid(
            row=0, column=7
        )
        ttk.Label(self.pg_frame, text="Port").grid(row=0, column=8)
        ttk.Entry(self.pg_frame, textvariable=self.pg_port, width=8).grid(
            row=0, column=9
        )

        # Excel source
        self.excel_frame = ttk.LabelFrame(root, text="Excel Source", padding=6)
        self.excel_frame.grid(row=3, column=0, columnspan=4, sticky="we", pady=(6, 0))
        ttk.Label(self.excel_frame, text="Excel").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.excel_frame, textvariable=self.xlsx_path, width=52).grid(
            row=0, column=1, padx=6, sticky="we"
        )
        ttk.Button(self.excel_frame, text="Browse", command=self.choose_excel).grid(
            row=0, column=2, padx=2
        )
        ttk.Label(
            self.excel_frame,
            text="Sheets used per block: BlockX, Receiver Lines BlockX",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # Mode & import button
        ttk.Label(root, text="Mode").grid(row=4, column=0, sticky="e", pady=(6, 0))
        mode_fr = ttk.Frame(root)
        mode_fr.grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Radiobutton(mode_fr, text="Replace", value="replace", variable=self.mode).pack(
            side=tk.LEFT
        )
        ttk.Radiobutton(mode_fr, text="Append", value="append", variable=self.mode).pack(
            side=tk.LEFT
        )
        ttk.Button(root, text="Import ALL for Block", command=self.import_to_db).grid(
            row=4, column=3, padx=2, pady=(6, 0)
        )

        # Footer
        footer = ttk.Frame(self)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(
            footer,
            textvariable=self.status,
            anchor="w",
            relief="groove",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            footer,
            text="Hussein Al Shibli  |  BGP Oman APC",
            anchor="e",
            foreground="#004080",
            font=("Segoe UI", 9, "italic"),
        ).pack(side=tk.RIGHT, padx=10, pady=3)

    # ----- block handling -----
    def _on_block_change(self, *_):
        blk = (self.block.get() or "").upper()
        if blk in {"A", "B", "C", "D"}:
            self.status.set(f"Block {blk} selected. Import will load Normal tables only.")

    # ----- UI toggles -----
    def toggle_db_frames(self):
        if self.dbtype.get() == "postgresql":
            self.sqlite_frame.grid_remove()
            self.pg_frame.grid()
        else:
            self.pg_frame.grid_remove()
            self.sqlite_frame.grid()

    # ----- table list / excel helpers -----
    def choose_sqlite(self):
        p = filedialog.askopenfilename(
            title="Select SQLite DB",
            filetypes=[
                ("SQLite DB", "*.db *.sqlite *.sqlite3"),
                ("All files", "*.*"),
            ],
        )
        if p:
            self.sqlite_path.set(p)

    def choose_excel(self):
        p = filedialog.askopenfilename(
            title="Select Excel",
            filetypes=[
                ("Excel", "*.xlsx *.xlsm *.xlsb *.xls"),
            ],
        )
        if p:
            self.xlsx_path.set(p)

    # ----- import NORMAL tables for selected block -----
    def import_to_db(self):
        try:
            if not self.xlsx_path.get():
                messagebox.showwarning(APP_TITLE, "Excel file required.")
                return

            blk = (self.block.get() or "").upper()
            if blk not in {"A", "B", "C", "D"}:
                messagebox.showwarning(APP_TITLE, "Select Block A/B/C/D.")
                return

            # Sheet names in Excel
            sheet_swath_normal = f"Block{blk}"                # e.g. BlockC
            sheet_r_lines      = f"Receiver Lines Block{blk}" # e.g. Receiver Lines BlockC

            # Table names in DB (lowercase)
            blk_lower = blk.lower()
            tbl_swath_normal = f"block{blk_lower}_normal"
            tbl_r_normal     = f"receiver_lines_block{blk_lower}_normal"

            xls = pd.ExcelFile(self.xlsx_path.get())
            sheets = set(xls.sheet_names)

            conn = self.get_connection()
            cur = conn.cursor()

            ph_swath = ",".join(
                ["%s" if self.dbtype.get() == "postgresql" else "?"]
                * len(SWATH_COLS)
            )

            summary = []

            # --- Swath (NORMAL) ---
            if sheet_swath_normal not in sheets:
                summary.append(f"Swath NORMAL: sheet '{sheet_swath_normal}' not found, skipped.")
            else:
                df_raw = pd.read_excel(
                    self.xlsx_path.get(),
                    sheet_name=sheet_swath_normal,
                    header=2,  # Swath header row index
                )
                df_db = build_df_swath(df_raw)
                if df_db.empty:
                    summary.append("Swath NORMAL: no valid rows.")
                else:
                    ensure_table_swath(conn, tbl_swath_normal, self.dbtype.get())
                    if self.mode.get() == "replace":
                        cur.execute(f"DELETE FROM {q_table(tbl_swath_normal)}")
                    values = df_to_python_ints(df_db[SWATH_COLS])
                    cur.executemany(
                        f"INSERT INTO {q_table(tbl_swath_normal)} ({q_cols(SWATH_COLS)}) VALUES ({ph_swath})",
                        values,
                    )
                    summary.append(f"Swath NORMAL: {len(values)} row(s) → {tbl_swath_normal}")

            # --- Receiver Lines (NORMAL only) ---
            if sheet_r_lines not in sheets:
                summary.append(f"Receiver NORMAL: sheet '{sheet_r_lines}' not found, skipped.")
            else:
                df_raw = pd.read_excel(
                    self.xlsx_path.get(),
                    sheet_name=sheet_r_lines,
                    header=1,  # Receiver header row index
                )
                df_normal = build_df_rline_normal_only(df_raw)

                ensure_table_rline_normal(conn, tbl_r_normal)
                if self.mode.get() == "replace":
                    cur.execute(f"DELETE FROM {q_table(tbl_r_normal)}")

                if not df_normal.empty:
                    cols_n = [
                        "normal_line",
                        "normal_station_start",
                        "normal_station_end",
                        "normal_traces",
                    ]
                    vals_n = df_to_python_ints(df_normal[cols_n])
                    ph_n = ",".join(
                        ["%s" if self.dbtype.get() == "postgresql" else "?"]
                        * len(cols_n)
                    )
                    cur.executemany(
                        f"INSERT INTO {q_table(tbl_r_normal)} ({q_cols(cols_n)}) VALUES ({ph_n})",
                        vals_n,
                    )
                    summary.append(f"Receiver NORMAL: {len(vals_n)} row(s) → {tbl_r_normal}")
                else:
                    summary.append("Receiver NORMAL: no valid rows.")

            conn.commit()
            cur.close()
            conn.close()

            self.status.set(" | ".join(summary))
            messagebox.showinfo(APP_TITLE, "Import finished:\n" + "\n".join(summary))

        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Import failed:\n{e}")

    # ----- connection factory -----
    def get_connection(self):
        if self.dbtype.get() == "sqlite":
            return connect_sqlite(self.sqlite_path.get())
        return connect_postgres(
            host=self.pg_host.get(),
            dbname=self.pg_db.get(),
            user=self.pg_user.get(),
            password=self.pg_pass.get(),
            port=int(self.pg_port.get() or 5432),
        )


if __name__ == "__main__":
    app = App()
    app.mainloop()

# Hussein Al Shibli | BGP Oman APC
