# APC_Importer_SQL_or_PostgreSQL_Final_Hussein.py
# Excel → (SQLite | PostgreSQL) importer with clean UI and signature footer.

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
DEFAULT_SQLITE = "E:/25 BIRBA/01-DataBase/Production_APC_Database_BB.sqlite3"

TARGET_COLUMNS = [
    "Swath_Number",
    "Source_Line_From",
    "Source_Line_To",
    "Source_Point_From",
    "Source_Point_To",
    "Design_VPs",
    "Receiver_Line_From",
    "Receiver_Line_To",
    "Receiver_Station_From",
    "Receiver_Station_To",
    "Receiver_Lines_Per_Swath",
    "Traces_Per_Swath",
]

# ---------- Connections ----------
def connect_sqlite(path: str):
    con = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    con.execute("PRAGMA journal_mode=WAL;")
    return con

def connect_postgres(host, dbname, user, password, port=5432):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed. Run: pip install psycopg2")
    return psycopg2.connect(host=host, database=dbname, user=user, password=password, port=port)

# ---------- Identifier quoting ----------
def q_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""').strip() + '"'

def q_table(name: str) -> str:
    return q_ident(name)

def q_cols(cols) -> str:
    return ",".join(q_ident(c) for c in cols)

# ---------- DB helpers ----------
def ensure_table(conn, table_name: str, dbtype: str):
    serial = "SERIAL" if dbtype == "postgresql" else "INTEGER"
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {q_table(table_name)} (
          {q_ident("id")} {serial} PRIMARY KEY,
          {q_ident("Swath_Number")} INTEGER NOT NULL,
          {q_ident("Source_Line_From")} INTEGER,
          {q_ident("Source_Line_To")} INTEGER,
          {q_ident("Source_Point_From")} INTEGER,
          {q_ident("Source_Point_To")} INTEGER,
          {q_ident("Design_VPs")} INTEGER,
          {q_ident("Receiver_Line_From")} INTEGER,
          {q_ident("Receiver_Line_To")} INTEGER,
          {q_ident("Receiver_Station_From")} INTEGER,
          {q_ident("Receiver_Station_To")} INTEGER,
          {q_ident("Receiver_Lines_Per_Swath")} INTEGER,
          {q_ident("Traces_Per_Swath")} INTEGER
        );
    """)
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
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
    else:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;")
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    return rows

# ---------- Data shaping ----------
def build_df_from_sequence(df_src: pd.DataFrame) -> pd.DataFrame:
    cols = list(df_src.columns)
    n = len(cols)

    def safe_iloc(idx):
        if idx < n:
            return df_src.iloc[:, idx]
        return pd.Series([None] * len(df_src))

    has_dup_design = n >= 13
    design_left = safe_iloc(5)
    if has_dup_design:
        design_right = safe_iloc(6)
        design_final = design_left.where(
            design_left.notna() & (design_left.astype(str).str.strip() != ""),
            design_right
        )
        idx_rl_first, idx_rl_last, idx_rs_first, idx_rs_last, idx_rl_sw, idx_tr_sw = 7,8,9,10,11,12
    else:
        design_final = design_left
        idx_rl_first, idx_rl_last, idx_rs_first, idx_rs_last, idx_rl_sw, idx_tr_sw = 6,7,8,9,10,11

    out = pd.DataFrame({
        "Swath_Number":             safe_iloc(0),
        "Source_Line_From":         safe_iloc(1),
        "Source_Line_To":           safe_iloc(2),
        "Source_Point_From":        safe_iloc(3),
        "Source_Point_To":          safe_iloc(4),
        "Design_VPs":               design_final,
        "Receiver_Line_From":       safe_iloc(idx_rl_first),
        "Receiver_Line_To":         safe_iloc(idx_rl_last),
        "Receiver_Station_From":    safe_iloc(idx_rs_first),
        "Receiver_Station_To":      safe_iloc(idx_rs_last),
        "Receiver_Lines_Per_Swath": safe_iloc(idx_rl_sw),
        "Traces_Per_Swath":         safe_iloc(idx_tr_sw),
    })

    for c in out.columns:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.fillna(0)
    out = out[out["Swath_Number"] > 0].copy()
    out.reset_index(drop=True, inplace=True)
    return out

def df_to_python_ints(df: pd.DataFrame) -> list[tuple]:
    rows = []
    for row in df.itertuples(index=False, name=None):
        rows.append(tuple(int(v) for v in row))
    return rows

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("920x480")

        self.dbtype      = tk.StringVar(value="postgresql")
        self.sqlite_path = tk.StringVar(value=DEFAULT_SQLITE)
        self.table_name  = tk.StringVar(value="BlockD_Normal")
        self.xlsx_path   = tk.StringVar(value="")
        self.sheet_name  = tk.StringVar(value="BlockD")
        self.header_idx  = tk.IntVar(value=2)
        self.mode        = tk.StringVar(value="replace")

        # PostgreSQL
        self.pg_host = tk.StringVar(value="localhost")
        self.pg_db   = tk.StringVar(value="Production_APC")
        self.pg_user = tk.StringVar(value="postgres")
        self.pg_pass = tk.StringVar(value="hu8622")
        self.pg_port = tk.StringVar(value="5432")

        self._build_ui()
        self.toggle_db_frames()
        self.refresh_tables(silent=True)

    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        # DB type
        ttk.Label(root, text="DB Type").grid(row=0, column=0, sticky="w")
        dbtype_combo = ttk.Combobox(root, textvariable=self.dbtype, values=["sqlite", "postgresql"], width=12, state="readonly")
        dbtype_combo.grid(row=0, column=1, sticky="w")
        dbtype_combo.bind("<<ComboboxSelected>>", lambda e: (self.toggle_db_frames(), self.refresh_tables(silent=False)))

        # SQLite
        self.sqlite_frame = ttk.LabelFrame(root, text="SQLite", padding=6)
        self.sqlite_frame.grid(row=1, column=0, columnspan=4, sticky="we", pady=(6,0))
        ttk.Label(self.sqlite_frame, text="DB File").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.sqlite_frame, textvariable=self.sqlite_path, width=52).grid(row=0, column=1, padx=6, sticky="we")
        ttk.Button(self.sqlite_frame, text="Browse", command=self.choose_sqlite).grid(row=0, column=2, padx=2)
        ttk.Button(self.sqlite_frame, text="Load Tables", command=self.refresh_tables).grid(row=0, column=3, padx=2)

        # PostgreSQL
        self.pg_frame = ttk.LabelFrame(root, text="PostgreSQL Connection", padding=6)
        self.pg_frame.grid(row=2, column=0, columnspan=4, sticky="we", pady=6)
        ttk.Label(self.pg_frame, text="Host").grid(row=0, column=0)
        ttk.Entry(self.pg_frame, textvariable=self.pg_host, width=14).grid(row=0, column=1)
        ttk.Label(self.pg_frame, text="DB").grid(row=0, column=2)
        ttk.Entry(self.pg_frame, textvariable=self.pg_db, width=16).grid(row=0, column=3)
        ttk.Label(self.pg_frame, text="User").grid(row=0, column=4)
        ttk.Entry(self.pg_frame, textvariable=self.pg_user, width=14).grid(row=0, column=5)
        ttk.Label(self.pg_frame, text="Pass").grid(row=0, column=6)
        ttk.Entry(self.pg_frame, textvariable=self.pg_pass, width=14, show="*").grid(row=0, column=7)
        ttk.Label(self.pg_frame, text="Port").grid(row=0, column=8)
        ttk.Entry(self.pg_frame, textvariable=self.pg_port, width=8).grid(row=0, column=9)
        ttk.Button(self.pg_frame, text="Load Tables", command=self.refresh_tables).grid(row=0, column=10, padx=8)

        # Table section
        ttk.Label(root, text="Table").grid(row=3, column=0, sticky="w", pady=(6,0))
        self.table_combo = ttk.Combobox(root, textvariable=self.table_name, width=32)
        self.table_combo.grid(row=3, column=1, sticky="w", pady=(6,0))
        ttk.Button(root, text="Ensure Table", command=self.ensure_selected_table).grid(row=3, column=2, padx=2)
        ttk.Button(root, text="Recreate Table", command=self.recreate_selected_table).grid(row=3, column=3, padx=2)

        # Excel section
        self.excel_frame = ttk.LabelFrame(root, text="Excel Source", padding=6)
        self.excel_frame.grid(row=4, column=0, columnspan=4, sticky="we", pady=(6,0))
        ttk.Label(self.excel_frame, text="Excel").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.excel_frame, textvariable=self.xlsx_path, width=52).grid(row=0, column=1, padx=6, sticky="we")
        ttk.Button(self.excel_frame, text="Browse", command=self.choose_excel).grid(row=0, column=2, padx=2)
        ttk.Button(self.excel_frame, text="Sheets", command=self.load_sheets).grid(row=0, column=3, padx=2)

        ttk.Label(self.excel_frame, text="Sheet").grid(row=1, column=0, sticky="w")
        self.sheet_combo = ttk.Combobox(self.excel_frame, textvariable=self.sheet_name, width=32)
        self.sheet_combo.grid(row=1, column=1, sticky="w")
        ttk.Label(self.excel_frame, text="Header idx").grid(row=1, column=2, sticky="e")
        ttk.Spinbox(self.excel_frame, from_=0, to=100, textvariable=self.header_idx, width=6).grid(row=1, column=3, sticky="w")

        # Mode + Import
        ttk.Label(root, text="Mode").grid(row=5, column=0, sticky="e", pady=(6,0))
        mode_fr = ttk.Frame(root)
        mode_fr.grid(row=5, column=1, sticky="w", pady=(6,0))
        ttk.Radiobutton(mode_fr, text="Replace", value="replace", variable=self.mode).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_fr, text="Append", value="append", variable=self.mode).pack(side=tk.LEFT)
        ttk.Button(root, text="Import", command=self.import_to_db).grid(row=5, column=3, padx=2, pady=(6,0))

        # Bottom status + signature
        footer = ttk.Frame(self)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(footer, textvariable=self.status, anchor="w", relief="groove").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            footer,
            text="Hussein Al Shibli  |  Production APC  |  BGP Oman Crew 8622",
            anchor="e",
            foreground="#004080",
            font=("Segoe UI", 9, "italic")
        ).pack(side=tk.RIGHT, padx=10, pady=3)

    def toggle_db_frames(self):
        if self.dbtype.get() == "postgresql":
            self.sqlite_frame.grid_remove()
            self.pg_frame.grid()
        else:
            self.pg_frame.grid_remove()
            self.sqlite_frame.grid()

    def choose_sqlite(self):
        p = filedialog.askopenfilename(title="Select SQLite DB",
                                       filetypes=[("SQLite DB","*.db *.sqlite *.sqlite3"), ("All files","*.*")])
        if p:
            self.sqlite_path.set(p)
            self.refresh_tables()

    def refresh_tables(self, silent=False):
        try:
            conn = self.get_connection()
            tables = list_tables(conn, self.dbtype.get())
            conn.close()
            self.table_combo["values"] = tables
            if tables and (self.table_name.get() == "" or self.table_name.get() not in tables):
                self.table_combo.current(0)
                self.table_name.set(tables[0])
            if not silent:
                self.status.set(f"{len(tables)} table(s) found.")
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Load tables failed:\n{e}")

    def ensure_selected_table(self):
        try:
            conn = self.get_connection()
            ensure_table(conn, self.table_name.get().strip(), self.dbtype.get())
            conn.close()
            self.status.set(f"Ensured '{self.table_name.get().strip()}'.")
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Ensure failed:\n{e}")

    def recreate_selected_table(self):
        try:
            tbl = self.table_name.get().strip()
            if not tbl:
                messagebox.showwarning(APP_TITLE, "Enter a table name.")
                return
            conn = self.get_connection()
            drop_table(conn, tbl)
            ensure_table(conn, tbl, self.dbtype.get())
            conn.close()
            self.status.set(f"Recreated '{tbl}'.")
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Recreate failed:\n{e}")

    def choose_excel(self):
        p = filedialog.askopenfilename(title="Select Excel",
                                       filetypes=[("Excel","*.xlsx *.xlsm *.xlsb *.xls")])
        if p:
            self.xlsx_path.set(p)

    def load_sheets(self):
        try:
            if not self.xlsx_path.get():
                return
            xls = pd.ExcelFile(self.xlsx_path.get())
            self.sheet_combo["values"] = xls.sheet_names
            if xls.sheet_names and (self.sheet_name.get() == "" or self.sheet_name.get() not in xls.sheet_names):
                self.sheet_combo.current(0)
                self.sheet_name.set(xls.sheet_names[0])
            self.status.set(f"{len(xls.sheet_names)} sheet(s) loaded.")
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Load sheets failed:\n{e}")

    def import_to_db(self):
        try:
            if not self.xlsx_path.get() or not self.sheet_name.get():
                return

            df = pd.read_excel(self.xlsx_path.get(),
                               sheet_name=self.sheet_name.get(),
                               header=int(self.header_idx.get()))
            df_db = build_df_from_sequence(df)
            if df_db.empty:
                self.status.set("No valid rows to import.")
                return

            values = df_to_python_ints(df_db)
            cols = list(df_db.columns)

            conn = self.get_connection()
            dbt = self.dbtype.get()
            table = self.table_name.get().strip()
            ensure_table(conn, table, dbt)
            cur = conn.cursor()

            if self.mode.get() == "replace":
                cur.execute(f"DELETE FROM {q_table(table)}")

            placeholders = ",".join(["%s" if dbt == "postgresql" else "?"] * len(cols))
            insert_sql = f"INSERT INTO {q_table(table)} ({q_cols(cols)}) VALUES ({placeholders})"
            cur.executemany(insert_sql, values)
            conn.commit()
            cur.close()
            conn.close()

            self.status.set(f"Imported {len(values)} rows into {table}.")
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Import failed:\n{e}")

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
