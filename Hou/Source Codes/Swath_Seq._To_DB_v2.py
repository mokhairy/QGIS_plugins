# Swath_Seq_To_DB_NoCfg_NoCreateDB.py
# - No config file saved/loaded
# - Does NOT auto-create SQLite DB (raises error if path missing)
# - Fixed header rows: Swath=2, Receiver=1
# - Swath table Combobox with Ensure/Recreate
# - Receiver lines split into Normal & Infill tables

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
DEFAULT_SQLITE = "E:/25 BIRBA/01-DataBase/Production_APC_Database_BB.sqlite3"

SWATH_COLS = [
    "Swath_Number","Source_Line_From","Source_Line_To","Source_Point_From","Source_Point_To",
    "Design_VPs","Receiver_Line_From","Receiver_Line_To","Receiver_Station_From","Receiver_Station_To",
    "Receiver_Lines_Per_Swath","Traces_Per_Swath",
]

# ---------- DB connections ----------
def connect_sqlite(path: str):
    # Do NOT create DB if missing
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQLite DB not found: {path}")
    con = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    # Avoid extra -wal/-shm files per your request
    con.execute("PRAGMA journal_mode=DELETE;")
    return con

def connect_postgres(host, dbname, user, password, port=5432):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed. Run: pip install psycopg2")
    return psycopg2.connect(host=host, database=dbname, user=user, password=password, port=port)

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
    conn.commit(); cur.close()

def ensure_table_rline_normal(conn, table_name: str):
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {q_table(table_name)} (
          {q_ident("Normal_Line")} INTEGER,
          {q_ident("Normal_Station_Start")} INTEGER,
          {q_ident("Normal_Station_End")} INTEGER,
          {q_ident("Normal_Traces")} INTEGER
        );
    """)
    conn.commit(); cur.close()

def ensure_table_rline_infill(conn, table_name: str):
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {q_table(table_name)} (
          {q_ident("Infill_Line")} INTEGER,
          {q_ident("Infill_Station_Start")} INTEGER,
          {q_ident("Infill_Station_End")} INTEGER,
          {q_ident("Infill_Traces")} INTEGER
        );
    """)
    conn.commit(); cur.close()

def drop_table(conn, table_name: str):
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {q_table(table_name)};")
    conn.commit(); cur.close()

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
def build_df_swath(df_src: pd.DataFrame) -> pd.DataFrame:
    cols = list(df_src.columns); n = len(cols)
    def s(i): return df_src.iloc[:, i] if i < n else pd.Series([None]*len(df_src))

    has_dup_design = n >= 13
    design_left = s(5)
    if has_dup_design:
        design_right = s(6)
        design_final = design_left.where(
            design_left.notna() & (design_left.astype(str).str.strip() != ""),
            design_right
        )
        a,b,c,d,e,f = 7,8,9,10,11,12
    else:
        design_final = design_left
        a,b,c,d,e,f = 6,7,8,9,10,11

    out = pd.DataFrame({
        "Swath_Number": s(0),
        "Source_Line_From": s(1),
        "Source_Line_To": s(2),
        "Source_Point_From": s(3),
        "Source_Point_To": s(4),
        "Design_VPs": design_final,
        "Receiver_Line_From": s(a),
        "Receiver_Line_To": s(b),
        "Receiver_Station_From": s(c),
        "Receiver_Station_To": s(d),
        "Receiver_Lines_Per_Swath": s(e),
        "Traces_Per_Swath": s(f),
    })
    for c in out.columns: out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.fillna(0)
    out = out[out["Swath_Number"] > 0].copy()
    out.reset_index(drop=True, inplace=True)
    return out

def _norm(h):
    s = str(h).strip().lower()
    if "." in s: s = s.split(".", 1)[0]
    return s

def _find_rline_blocks(df_header1: pd.DataFrame):
    # Drop fully empty columns (skip spacers)
    df = df_header1.dropna(axis=1, how="all").copy()
    cols = list(df.columns)
    norm = [_norm(c) for c in cols]
    n = len(norm)
    starts = []
    for i in range(0, n-3):
        if norm[i+1] == "start" and norm[i+2] == "end" and norm[i+3] == "traces":
            starts.append(i)
    return df, starts

def build_df_rline_split(df_src_header1: pd.DataFrame):
    df, starts = _find_rline_blocks(df_src_header1)

    def as_block(i, labels):
        if i is None: return pd.DataFrame(columns=labels)
        n = df.shape[1]
        if i+3 >= n: return pd.DataFrame(columns=labels)
        block = df.iloc[:, [i, i+1, i+2, i+3]].copy()
        block.columns = labels
        for c in block.columns: block[c] = pd.to_numeric(block[c], errors="coerce")
        block = block.fillna(0)
        key = labels[0]
        block = block[block[key] > 0].copy()
        block.reset_index(drop=True, inplace=True)
        return block

    normal = as_block(starts[0] if len(starts)>=1 else None,
                      ["Normal_Line","Normal_Station_Start","Normal_Station_End","Normal_Traces"])
    infill  = as_block(starts[1] if len(starts)>=2 else None,
                      ["Infill_Line","Infill_Station_Start","Infill_Station_End","Infill_Traces"])
    return normal, infill

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
        self.geometry("1040x560")

        self.dbtype      = tk.StringVar(value="postgresql")
        self.sqlite_path = tk.StringVar(value=DEFAULT_SQLITE)

        self.import_type = tk.StringVar(value="Swath sequence")  # Swath sequence | Receiver lines (split)
        self.swath_table = tk.StringVar(value="BlockD_Normal")
        self.r_normal_table = tk.StringVar(value="Receiver_Lines_BlockD_Normal")
        self.r_infill_table = tk.StringVar(value="Receiver_Lines_BlockD_Infill")

        self.xlsx_path   = tk.StringVar(value="")
        self.sheet_name  = tk.StringVar(value="BlockD")
        self.mode        = tk.StringVar(value="replace")

        self.pg_host = tk.StringVar(value="localhost")
        self.pg_db   = tk.StringVar(value="Production_APC")
        self.pg_user = tk.StringVar(value="postgres")
        self.pg_pass = tk.StringVar(value="hu8622")
        self.pg_port = tk.StringVar(value="5432")

        self._build_ui()
        self.toggle_db_frames()
        self.refresh_tables(silent=True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ----- UI -----
    def _build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text="DB Type").grid(row=0, column=0, sticky="w")
        dbtype_combo = ttk.Combobox(root, textvariable=self.dbtype, values=["sqlite","postgresql"], width=12, state="readonly")
        dbtype_combo.grid(row=0, column=1, sticky="w")
        dbtype_combo.bind("<<ComboboxSelected>>", lambda e: (self.toggle_db_frames(), self.refresh_tables(False)))

        # SQLite frame
        self.sqlite_frame = ttk.LabelFrame(root, text="SQLite", padding=6)
        self.sqlite_frame.grid(row=1, column=0, columnspan=4, sticky="we", pady=(6,0))
        ttk.Label(self.sqlite_frame, text="DB File").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.sqlite_frame, textvariable=self.sqlite_path, width=52).grid(row=0, column=1, padx=6, sticky="we")
        ttk.Button(self.sqlite_frame, text="Browse", command=self.choose_sqlite).grid(row=0, column=2, padx=2)

        # Postgres frame
        self.pg_frame = ttk.LabelFrame(root, text="PostgreSQL Connection", padding=6)
        self.pg_frame.grid(row=2, column=0, columnspan=4, sticky="we", pady=6)
        ttk.Label(self.pg_frame, text="Host").grid(row=0, column=0); ttk.Entry(self.pg_frame, textvariable=self.pg_host, width=14).grid(row=0, column=1)
        ttk.Label(self.pg_frame, text="DB").grid(row=0, column=2); ttk.Entry(self.pg_frame, textvariable=self.pg_db, width=16).grid(row=0, column=3)
        ttk.Label(self.pg_frame, text="User").grid(row=0, column=4); ttk.Entry(self.pg_frame, textvariable=self.pg_user, width=14).grid(row=0, column=5)
        ttk.Label(self.pg_frame, text="Pass").grid(row=0, column=6); ttk.Entry(self.pg_frame, textvariable=self.pg_pass, width=14, show="*").grid(row=0, column=7)
        ttk.Label(self.pg_frame, text="Port").grid(row=0, column=8); ttk.Entry(self.pg_frame, textvariable=self.pg_port, width=8).grid(row=0, column=9)

        ttk.Label(root, text="Import Type").grid(row=3, column=0, sticky="w", pady=(6,0))
        ttk.Combobox(root, textvariable=self.import_type,
                     values=["Swath sequence","Receiver lines (split)"],
                     width=24, state="readonly").grid(row=3, column=1, sticky="w", pady=(6,0))
        self.import_type.trace_add("write", lambda *_: self._toggle_table_rows())

        # Swath table row
        self.swath_row = ttk.Frame(root)
        self.swath_row.grid(row=4, column=0, columnspan=4, sticky="we", pady=(4,0))
        ttk.Label(self.swath_row, text="Swath table").pack(side=tk.LEFT)
        self.swath_table_combo = ttk.Combobox(self.swath_row, textvariable=self.swath_table, width=34, state="normal")
        self.swath_table_combo.pack(side=tk.LEFT, padx=6)
        ttk.Button(self.swath_row, text="Ensure", command=self.ensure_swath).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.swath_row, text="Recreate", command=self.recreate_swath).pack(side=tk.LEFT, padx=2)

        # Receiver lines row (Normal/Infill)
        self.rline_row = ttk.Frame(root)
        self.rline_row.grid(row=5, column=0, columnspan=4, sticky="we", pady=(4,0))
        ttk.Label(self.rline_row, text="Normal table").pack(side=tk.LEFT)
        ttk.Entry(self.rline_row, textvariable=self.r_normal_table, width=28).pack(side=tk.LEFT, padx=6)
        ttk.Label(self.rline_row, text="Infill table").pack(side=tk.LEFT)
        ttk.Entry(self.rline_row, textvariable=self.r_infill_table, width=28).pack(side=tk.LEFT, padx=6)
        ttk.Button(self.rline_row, text="Ensure both", command=self.ensure_both_rline).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.rline_row, text="Recreate both", command=self.recreate_both_rline).pack(side=tk.LEFT, padx=2)

        # Excel source
        self.excel_frame = ttk.LabelFrame(root, text="Excel Source", padding=6)
        self.excel_frame.grid(row=6, column=0, columnspan=4, sticky="we", pady=(6,0))
        ttk.Label(self.excel_frame, text="Excel").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.excel_frame, textvariable=self.xlsx_path, width=52).grid(row=0, column=1, padx=6, sticky="we")
        ttk.Button(self.excel_frame, text="Browse", command=self.choose_excel).grid(row=0, column=2, padx=2)
        ttk.Button(self.excel_frame, text="Sheets", command=self.load_sheets).grid(row=0, column=3, padx=2)
        ttk.Label(self.excel_frame, text="Sheet").grid(row=1, column=0, sticky="w")
        self.sheet_combo = ttk.Combobox(self.excel_frame, textvariable=self.sheet_name, width=32)
        self.sheet_combo.grid(row=1, column=1, sticky="w")

        ttk.Label(root, text="Mode").grid(row=7, column=0, sticky="e", pady=(6,0))
        mode_fr = ttk.Frame(root); mode_fr.grid(row=7, column=1, sticky="w", pady=(6,0))
        ttk.Radiobutton(mode_fr, text="Replace", value="replace", variable=self.mode).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_fr, text="Append",  value="append",  variable=self.mode).pack(side=tk.LEFT)
        ttk.Button(root, text="Import", command=self.import_to_db).grid(row=7, column=3, padx=2, pady=(6,0))

        footer = ttk.Frame(self); footer.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(footer, textvariable=self.status, anchor="w", relief="groove").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(footer,
                  text="Hussein Al Shibli  |  Production APC  |  BGP Oman Crew 8622",
                  anchor="e", foreground="#004080", font=("Segoe UI", 9, "italic")
                 ).pack(side=tk.RIGHT, padx=10, pady=3)

        self._toggle_table_rows()

    # ----- UI toggles -----
    def _toggle_table_rows(self):
        if self.import_type.get().startswith("Receiver"):
            self.swath_row.grid_remove()
            self.rline_row.grid()
        else:
            self.rline_row.grid_remove()
            self.swath_row.grid()

    def toggle_db_frames(self):
        if self.dbtype.get() == "postgresql":
            self.sqlite_frame.grid_remove(); self.pg_frame.grid()
        else:
            self.pg_frame.grid_remove(); self.sqlite_frame.grid()

    # ----- table list / excel helpers -----
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
            self.swath_table_combo["values"] = tables
            if not silent:
                self.status.set(f"{len(tables)} table(s) found.")
        except Exception as e:
            if not silent:
                traceback.print_exc()
                messagebox.showerror(APP_TITLE, f"Load tables failed:\n{e}")

    def choose_excel(self):
        p = filedialog.askopenfilename(title="Select Excel",
                                       filetypes=[("Excel","*.xlsx *.xlsm *.xlsb *.xls")])
        if p:
            self.xlsx_path.set(p)

    def load_sheets(self):
        try:
            if not self.xlsx_path.get():
                messagebox.showwarning(APP_TITLE, "Select an Excel file.")
                return
            xls = pd.ExcelFile(self.xlsx_path.get())
            self.sheet_combo["values"] = xls.sheet_names
            if xls.sheet_names and (self.sheet_name.get()=="" or self.sheet_name.get() not in xls.sheet_names):
                self.sheet_combo.current(0); self.sheet_name.set(xls.sheet_names[0])
            self.status.set(f"{len(xls.sheet_names)} sheet(s) loaded.")
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(APP_TITLE, f"Load sheets failed:\n{e}")

    # ----- handlers -----
    def ensure_swath(self):
        try:
            conn = self.get_connection()
            ensure_table_swath(conn, self.swath_table.get().strip(), self.dbtype.get())
            conn.close(); self.status.set("Swath table ensured.")
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(APP_TITLE, f"Ensure failed:\n{e}")

    def recreate_swath(self):
        try:
            tbl = self.swath_table.get().strip()
            conn = self.get_connection()
            drop_table(conn, tbl); ensure_table_swath(conn, tbl, self.dbtype.get())
            conn.close(); self.status.set("Swath table recreated.")
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(APP_TITLE, f"Recreate failed:\n{e}")

    def ensure_both_rline(self):
        try:
            conn = self.get_connection()
            ensure_table_rline_normal(conn, self.r_normal_table.get().strip())
            ensure_table_rline_infill(conn, self.r_infill_table.get().strip())
            conn.close(); self.status.set("Normal & Infill tables ensured.")
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(APP_TITLE, f"Ensure failed:\n{e}")

    def recreate_both_rline(self):
        try:
            conn = self.get_connection()
            drop_table(conn, self.r_normal_table.get().strip())
            drop_table(conn, self.r_infill_table.get().strip())
            ensure_table_rline_normal(conn, self.r_normal_table.get().strip())
            ensure_table_rline_infill(conn, self.r_infill_table.get().strip())
            conn.close(); self.status.set("Normal & Infill tables recreated.")
        except Exception as e:
            traceback.print_exc(); messagebox.showerror(APP_TITLE, f"Recreate failed:\n{e}")

    # ----- import -----
    def import_to_db(self):
        try:
            if not self.xlsx_path.get() or not self.sheet_name.get():
                messagebox.showwarning(APP_TITLE, "Excel & Sheet required.")
                return

            # Fixed header rows per your requirement
            header_row = 1 if self.import_type.get().startswith("Receiver") else 2
            df = pd.read_excel(self.xlsx_path.get(), sheet_name=self.sheet_name.get(), header=header_row)

            conn = self.get_connection()
            cur = conn.cursor()

            if self.import_type.get().startswith("Receiver"):
                df_normal, df_infill = build_df_rline_split(df)

                normal_tbl = self.r_normal_table.get().strip()
                infill_tbl = self.r_infill_table.get().strip()

                ensure_table_rline_normal(conn, normal_tbl)
                ensure_table_rline_infill(conn, infill_tbl)

                if self.mode.get() == "replace":
                    cur.execute(f"DELETE FROM {q_table(normal_tbl)}")
                    cur.execute(f"DELETE FROM {q_table(infill_tbl)}")

                if not df_normal.empty:
                    cols_n = ["Normal_Line","Normal_Station_Start","Normal_Station_End","Normal_Traces"]
                    vals_n = df_to_python_ints(df_normal[cols_n])
                    ph_n = ",".join(["%s" if self.dbtype.get()=="postgresql" else "?"] * len(cols_n))
                    cur.executemany(f"INSERT INTO {q_table(normal_tbl)} ({q_cols(cols_n)}) VALUES ({ph_n})", vals_n)

                if not df_infill.empty:
                    cols_i = ["Infill_Line","Infill_Station_Start","Infill_Station_End","Infill_Traces"]
                    vals_i = df_to_python_ints(df_infill[cols_i])
                    ph_i = ",".join(["%s" if self.dbtype.get()=="postgresql" else "?"] * len(cols_i))
                    cur.executemany(f"INSERT INTO {q_table(infill_tbl)} ({q_cols(cols_i)}) VALUES ({ph_i})", vals_i)

                conn.commit()
                self.status.set(f"Imported Normal={len(df_normal)}  Infill={len(df_infill)} row(s).")

            else:
                df_db = build_df_swath(df)
                if df_db.empty:
                    self.status.set("No valid rows to import.")
                    cur.close(); conn.close()
                    return

                table = self.swath_table.get().strip()
                ensure_table_swath(conn, table, self.dbtype.get())

                if self.mode.get() == "replace":
                    cur.execute(f"DELETE FROM {q_table(table)}")

                values = df_to_python_ints(df_db[SWATH_COLS])
                ph = ",".join(["%s" if self.dbtype.get()=="postgresql" else "?"] * len(SWATH_COLS))
                cur.executemany(f"INSERT INTO {q_table(table)} ({q_cols(SWATH_COLS)}) VALUES ({ph})", values)

                conn.commit()
                self.status.set(f"Imported {len(values)} rows into {table}.")

            cur.close(); conn.close()

        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Import failed:\n{e}")

    # ----- connection factory -----
    def get_connection(self):
        if self.dbtype.get() == "sqlite":
            return connect_sqlite(self.sqlite_path.get())
        return connect_postgres(
            host=self.pg_host.get(), dbname=self.pg_db.get(), user=self.pg_user.get(),
            password=self.pg_pass.get(), port=int(self.pg_port.get() or 5432),
        )

if __name__ == "__main__":
    app = App()
    app.mainloop()
