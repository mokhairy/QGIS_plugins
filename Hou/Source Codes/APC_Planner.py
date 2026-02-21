import os
import json
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- Third-party ---
import pandas as pd

APP_TITLE = "APC Production Planner"
SETTINGS_JSON = "apc_planner_settings.json"

# -----------------------
# Utility + Core Planning
# -----------------------

def safe_parse_date(s):
    if isinstance(s, (datetime, date)):
        return pd.to_datetime(s).date()
    try:
        return pd.to_datetime(str(s)).date()
    except Exception:
        return None

def interleave_pattern(list_a, list_b, a_count=4, b_count=1):
    """
    Return a new list that alternates items from A then B using
    a_count : b_count pattern (default 4:1). Stops when both run out.
    """
    out = []
    i = j = 0
    n_a, n_b = len(list_a), len(list_b)
    while i < n_a or j < n_b:
        # Pull from A
        take_a = min(a_count, n_a - i)
        if take_a > 0:
            out.extend(list_a[i:i+take_a])
            i += take_a
        # Pull from B
        take_b = min(b_count, n_b - j)
        if take_b > 0:
            out.extend(list_b[j:j+take_b])
            j += take_b
    return out

def read_inputs_from_workbook(xlsx_path):
    """
    Load all the required sheets. Return dict.
    Expected sheets (by your screenshots):
      - Params: optional; we also take GUI inputs
      - Swaths_Normal, Swaths_Infill : need column 'Sw No'
      - ReceiverLines_Normal, ReceiverLines_Infill : need column 'Line'
      - Actuals: columns Date | LinesDone | SwathsDone (optional)
    """
    xls = pd.ExcelFile(xlsx_path)

    def load_sheet(name, required_cols=None, optional=False):
        if name not in xls.sheet_names:
            if optional:
                return pd.DataFrame()
            raise ValueError(f"Sheet '{name}' not found.")
        df = pd.read_excel(xlsx_path, sheet_name=name)
        if required_cols:
            miss = [c for c in required_cols if c not in df.columns]
            if miss:
                raise ValueError(f"Sheet '{name}' missing columns: {miss}")
        return df

    sw_norm = load_sheet("Swaths_Normal", ["Sw No"])
    sw_infl = load_sheet("Swaths_Infill", ["Sw No"])
    rl_norm = load_sheet("ReceiverLines_Normal", ["Line"])
    rl_infl = load_sheet("ReceiverLines_Infill", ["Line"])
    actuals = load_sheet("Actuals", ["Date","LinesDone","SwathsDone"], optional=True)
    if not actuals.empty:
        actuals["Date"] = pd.to_datetime(actuals["Date"]).dt.date

    return {
        "Swaths_Normal": sw_norm,
        "Swaths_Infill": sw_infl,
        "ReceiverLines_Normal": rl_norm,
        "ReceiverLines_Infill": rl_infl,
        "Actuals": actuals
    }

def build_queues(data, policy="NORMAL_FIRST"):
    """
    policy: NORMAL_FIRST | INFILL_FIRST | ALT_4_1
    Returns sw_queue, line_queue (lists of ints/strings).
    """
    sw_norm = data["Swaths_Normal"][["Sw No"]].dropna()
    sw_infl = data["Swaths_Infill"][["Sw No"]].dropna()
    ln_norm = data["ReceiverLines_Normal"][["Line"]].dropna()
    ln_infl = data["ReceiverLines_Infill"][["Line"]].dropna()

    sw_norm_list = sw_norm["Sw No"].tolist()
    sw_infl_list = sw_infl["Sw No"].tolist()
    ln_norm_list = ln_norm["Line"].tolist()
    ln_infl_list = ln_infl["Line"].tolist()

    if policy == "NORMAL_FIRST":
        sw_queue = sw_norm_list + sw_infl_list
        ln_queue = ln_norm_list + ln_infl_list
    elif policy == "INFILL_FIRST":
        sw_queue = sw_infl_list + sw_norm_list
        ln_queue = ln_infl_list + ln_norm_list
    elif policy == "ALT_4_1":
        sw_queue = interleave_pattern(sw_norm_list, sw_infl_list, 4, 1)
        ln_queue = interleave_pattern(ln_norm_list, ln_infl_list, 4, 1)
    else:
        sw_queue = sw_norm_list + sw_infl_list
        ln_queue = ln_norm_list + ln_infl_list

    return sw_queue, ln_queue

def plan_schedule(
    sw_queue,
    ln_queue,
    target_lines,
    target_swaths,
    start_date,
    horizon_days,
    friday_line_buffer=0,
    friday_swath_buffer=0,
    actuals_df=None
):
    """
    Returns a DataFrame with plan rows.
    - target reductions on Friday (weekday=4 in Python's Mon=0..Sun=6)
    - If actuals exist for a day, we advance by actuals; otherwise by plan.
    """
    if actuals_df is None:
        actuals_df = pd.DataFrame(columns=["Date","LinesDone","SwathsDone"])

    actuals = actuals_df.copy()
    if not actuals.empty:
        actuals["Date"] = pd.to_datetime(actuals["Date"]).dt.date

    plan_rows = []
    offset_sw = int(actuals["SwathsDone"].sum()) if not actuals.empty else 0
    offset_ln = int(actuals["LinesDone"].sum()) if not actuals.empty else 0

    for d in range(horizon_days):
        day = start_date + timedelta(days=d)

        # Apply Friday buffer (weekday 4 = Friday if week starts Monday)
        day_tgt_ln  = max(0, target_lines  - (friday_line_buffer  if day.weekday()==4 else 0))
        day_tgt_sw  = max(0, target_swaths - (friday_swath_buffer if day.weekday()==4 else 0))

        next_lines  = ln_queue[offset_ln : offset_ln + day_tgt_ln]
        next_swaths = sw_queue[offset_sw : offset_sw + day_tgt_sw]

        # Actuals for that day?
        act = actuals[actuals["Date"] == day]
        if not act.empty:
            lines_done  = int(act["LinesDone"].iloc[0]  or 0)
            swaths_done = int(act["SwathsDone"].iloc[0] or 0)
        else:
            lines_done  = len(next_lines)
            swaths_done = len(next_swaths)

        plan_rows.append({
            "Date": day,
            "PlanLines": len(next_lines),
            "PlanSwaths": len(next_swaths),
            "NextLinesList": ",".join(map(str, next_lines)),
            "NextSwathsList": ",".join(map(str, next_swaths)),
            "ActualLines": lines_done if not act.empty else "",
            "ActualSwaths": swaths_done if not act.empty else "",
            "LineVariance": (lines_done - len(next_lines)) if not act.empty else "",
            "SwathVariance": (swaths_done - len(next_swaths)) if not act.empty else "",
        })

        # Advance offsets
        offset_ln += lines_done if not act.empty else len(next_lines)
        offset_sw += swaths_done if not act.empty else len(next_swaths)

        # Stop if both queues exhausted
        if offset_ln >= len(ln_queue) and offset_sw >= len(sw_queue):
            break

    df = pd.DataFrame(plan_rows)
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    return df

def save_actuals_row(xlsx_path, day, lines_done, swaths_done):
    """
    Append/update the Actuals sheet. If day exists, overwrite that row.
    """
    # Read all sheets first
    with pd.ExcelWriter(xlsx_path, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
        try:
            # Load
            xls = pd.ExcelFile(xlsx_path)
            if "Actuals" in xls.sheet_names:
                df = pd.read_excel(xlsx_path, sheet_name="Actuals")
            else:
                df = pd.DataFrame(columns=["Date","LinesDone","SwathsDone"])
        except Exception:
            df = pd.DataFrame(columns=["Date","LinesDone","SwathsDone"])

    # Update in memory
    if not df.empty:
        df["Date"] = pd.to_datetime(df["Date"]).dt.date

    day = pd.to_datetime(day).date()
    mask = (df["Date"] == day) if not df.empty else pd.Series(dtype=bool)

    new_row = {"Date": day, "LinesDone": int(lines_done), "SwathsDone": int(swaths_done)}
    if not df.empty and mask.any():
        df.loc[mask, ["LinesDone","SwathsDone"]] = new_row["LinesDone"], new_row["SwathsDone"]
    else:
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    # Write back (overwrite sheet cleanly)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        # Preserve other sheets by reading all, then writing back—simplify:
        # We'll reload all and re-write; safest for integrity.
        book = pd.ExcelFile(xlsx_path)
        existing = {name: pd.read_excel(xlsx_path, sheet_name=name) for name in book.sheet_names if name!="Actuals"}
        for name, frame in existing.items():
            frame.to_excel(writer, sheet_name=name, index=False)
        df.to_excel(writer, sheet_name="Actuals", index=False)

# -----------
# GUI Layer
# -----------

class APCPlannerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x720")
        self.minsize(1100, 650)

        self.xlsx_path = tk.StringVar()
        self.start_date = tk.StringVar()
        self.horizon = tk.IntVar(value=60)
        self.target_lines = tk.IntVar(value=8)
        self.target_swaths = tk.IntVar(value=10)
        self.friday_line_buffer = tk.IntVar(value=0)
        self.friday_swath_buffer = tk.IntVar(value=0)
        self.lock_time = tk.StringVar(value="10:00")
        self.policy = tk.StringVar(value="NORMAL_FIRST")
        self.today_lines_done = tk.IntVar(value=0)
        self.today_swaths_done = tk.IntVar(value=0)

        self.data_cache = None
        self.plan_df = pd.DataFrame()

        self._load_settings()
        self._build_ui()

    # --- UI ---

    def _build_ui(self):
        # Top file + params frame
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        # File chooser
        ttk.Label(top, text="Workbook (.xlsx):").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.xlsx_path, width=70).grid(row=0, column=1, padx=6, sticky="we")
        ttk.Button(top, text="Browse…", command=self.on_browse).grid(row=0, column=2, padx=3)
        ttk.Button(top, text="Load", command=self.on_load).grid(row=0, column=3, padx=3)

        # Parameters
        ttk.Label(top, text="Start Date (YYYY-MM-DD):").grid(row=1, column=0, sticky="w", pady=(6,0))
        ttk.Entry(top, textvariable=self.start_date, width=20).grid(row=1, column=1, sticky="w", pady=(6,0))

        ttk.Label(top, text="Horizon (days):").grid(row=1, column=2, sticky="e", pady=(6,0))
        ttk.Entry(top, textvariable=self.horizon, width=8).grid(row=1, column=3, sticky="w", pady=(6,0))

        ttk.Label(top, text="Target Lines/Day:").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.target_lines, width=8).grid(row=2, column=1, sticky="w")

        ttk.Label(top, text="Target Swaths/Day:").grid(row=2, column=2, sticky="e")
        ttk.Entry(top, textvariable=self.target_swaths, width=8).grid(row=2, column=3, sticky="w")

        ttk.Label(top, text="Friday Line Buffer (-):").grid(row=3, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.friday_line_buffer, width=8).grid(row=3, column=1, sticky="w")

        ttk.Label(top, text="Friday Swath Buffer (-):").grid(row=3, column=2, sticky="e")
        ttk.Entry(top, textvariable=self.friday_swath_buffer, width=8).grid(row=3, column=3, sticky="w")

        ttk.Label(top, text="Lock Time (HH:MM):").grid(row=4, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.lock_time, width=8).grid(row=4, column=1, sticky="w")

        # Policy radios
        pol = ttk.Frame(top)
        pol.grid(row=5, column=0, columnspan=4, pady=(6,3), sticky="w")
        ttk.Label(pol, text="Queue Policy:").pack(side=tk.LEFT)
        ttk.Radiobutton(pol, text="Normal → Infill", variable=self.policy, value="NORMAL_FIRST").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(pol, text="Infill → Normal", variable=self.policy, value="INFILL_FIRST").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(pol, text="Alternate 4:1", variable=self.policy, value="ALT_4_1").pack(side=tk.LEFT, padx=10)

        # Buttons
        btns = ttk.Frame(top)
        btns.grid(row=6, column=0, columnspan=4, pady=(6,6), sticky="w")
        ttk.Button(btns, text="Generate Plan", command=self.on_generate).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Export Plan CSV", command=self.on_export_csv).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Export Plan Excel", command=self.on_export_excel).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Export Today’s Locked Plan", command=self.on_export_today_locked).pack(side=tk.LEFT, padx=8)

        # Divider
        ttk.Separator(self, orient="horizontal").pack(fill=tk.X, pady=6)

        # Center: table + right panel
        mid = ttk.Frame(self, padding=8)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Plan tree
        self.tree = ttk.Treeview(mid, columns=("Date","PlanLines","PlanSwaths","NextLinesList","NextSwathsList","ActualLines","ActualSwaths","LineVariance","SwathVariance"), show="headings", height=18)
        for col, w in [
            ("Date",110),("PlanLines",90),("PlanSwaths",95),
            ("NextLinesList",260),("NextSwathsList",260),
            ("ActualLines",90),("ActualSwaths",95),
            ("LineVariance",95),("SwathVariance",100),
        ]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbars
        yscroll = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        yscroll.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=yscroll.set)

        # Right panel: Today Actuals
        right = ttk.Frame(mid, padding=(10,0))
        right.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(right, text="Today’s Actuals", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(2,6))
        self.today_label = ttk.Label(right, text=f"Date: {date.today().isoformat()}")
        self.today_label.pack(anchor="w")

        row_fr = ttk.Frame(right)
        row_fr.pack(anchor="w", pady=(6,0))
        ttk.Label(row_fr, text="Lines Done:").grid(row=0, column=0, sticky="w")
        ttk.Entry(row_fr, textvariable=self.today_lines_done, width=8).grid(row=0, column=1, padx=6)
        ttk.Label(row_fr, text="Swaths Done:").grid(row=1, column=0, sticky="w", pady=(6,0))
        ttk.Entry(row_fr, textvariable=self.today_swaths_done, width=8).grid(row=1, column=1, padx=6, pady=(6,0))

        ttk.Button(right, text="Save Today to Actuals", command=self.on_save_today_actuals).pack(anchor="w", pady=(10,0))

        ttk.Separator(right, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(right, text="Tips:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tips = (
            "• Keep targets (8 lines / 10 swaths). Enter actuals at end of day.\n"
            "• Plan auto-shifts; no manual editing.\n"
            "• Use Alternate 4:1 when CSR wants steady infill progress.\n"
            "• Add Friday buffers to reduce targets before weekend logistics."
        )
        ttk.Label(right, text=tips, wraplength=260, justify="left").pack(anchor="w")

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        sb = ttk.Label(self, textvariable=self.status, anchor="w", relief="groove")
        sb.pack(side=tk.BOTTOM, fill=tk.X)

    # --- Actions ---

    def on_browse(self):
        path = filedialog.askopenfilename(
            title="Select planning workbook",
            filetypes=[("Excel files","*.xlsx")]
        )
        if path:
            self.xlsx_path.set(path)

    def on_load(self):
        try:
            if not self.xlsx_path.get():
                messagebox.showwarning(APP_TITLE, "Choose a workbook first.")
                return
            data = read_inputs_from_workbook(self.xlsx_path.get())
            self.data_cache = data
            self.status.set("Workbook loaded.")
            # If Params sheet exists, you can auto-fill here (optional)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Failed to load workbook:\n{e}")

    def on_generate(self):
        try:
            if not self.data_cache:
                self.on_load()
                if not self.data_cache:
                    return

            start = safe_parse_date(self.start_date.get())
            if not start:
                messagebox.showwarning(APP_TITLE, "Invalid Start Date. Use YYYY-MM-DD.")
                return

            policy = self.policy.get()
            sw_q, ln_q = build_queues(self.data_cache, policy=policy)

            # Friday buffers
            fb_ln = max(0, int(self.friday_line_buffer.get()))
            fb_sw = max(0, int(self.friday_swath_buffer.get()))

            df = plan_schedule(
                sw_queue=sw_q,
                ln_queue=ln_q,
                target_lines=int(self.target_lines.get()),
                target_swaths=int(self.target_swaths.get()),
                start_date=start,
                horizon_days=int(self.horizon.get()),
                friday_line_buffer=fb_ln,
                friday_swath_buffer=fb_sw,
                actuals_df=self.data_cache.get("Actuals")
            )
            self.plan_df = df
            self._fill_tree(df)
            self.status.set(f"Plan generated: {len(df)} days.")
            self._save_settings()
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Error generating plan:\n{e}")

    def _fill_tree(self, df):
        for i in self.tree.get_children():
            self.tree.delete(i)
        if df is None or df.empty:
            return
        for _, r in df.iterrows():
            self.tree.insert("", "end", values=[
                r["Date"],
                r["PlanLines"], r["PlanSwaths"],
                r["NextLinesList"], r["NextSwathsList"],
                r["ActualLines"], r["ActualSwaths"],
                r["LineVariance"], r["SwathVariance"]
            ])

    def on_export_csv(self):
        if self.plan_df is None or self.plan_df.empty:
            messagebox.showinfo(APP_TITLE, "Generate a plan first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV","*.csv")],
            initialfile=f"DailyPlan_{date.today().isoformat()}.csv"
        )
        if not path:
            return
        self.plan_df.to_csv(path, index=False)
        self.status.set(f"Exported CSV: {path}")

    def on_export_excel(self):
        if self.plan_df is None or self.plan_df.empty:
            messagebox.showinfo(APP_TITLE, "Generate a plan first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel","*.xlsx")],
            initialfile=f"DailyPlan_{date.today().isoformat()}.xlsx"
        )
        if not path:
            return
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            self.plan_df.to_excel(w, sheet_name="Plan", index=False)
        self.status.set(f"Exported Excel: {path}")

    def on_export_today_locked(self):
        """
        Creates a 1-row CSV/Excel for ONLY today's plan (useful for WhatsApp/WeChat).
        Lock time is informational here; if you want to enforce it strictly,
        you can compare current time vs lock_time and block edits.
        """
        if self.plan_df is None or self.plan_df.empty:
            messagebox.showinfo(APP_TITLE, "Generate a plan first.")
            return

        today = date.today()
        today_row = self.plan_df[self.plan_df["Date"] == today]
        if today_row.empty:
            # Fall back to the first row as "today's plan" if start_date > today
            today_row = self.plan_df.iloc[[0]]

        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel","*.xlsx"), ("CSV","*.csv")],
            initialfile=f"APC_Today_{today.isoformat()}.xlsx"
        )
        if not path:
            return

        if path.lower().endswith(".csv"):
            today_row.to_csv(path, index=False)
        else:
            with pd.ExcelWriter(path, engine="openpyxl") as w:
                today_row.to_excel(w, sheet_name="Today", index=False)

        self.status.set(f"Exported today’s locked plan: {path}")

    def on_save_today_actuals(self):
        try:
            if not self.xlsx_path.get():
                messagebox.showwarning(APP_TITLE, "Choose a workbook first.")
                return
            # Save to Actuals sheet
            day = date.today()
            ln = int(self.today_lines_done.get())
            sw = int(self.today_swaths_done.get())
            save_actuals_row(self.xlsx_path.get(), day, ln, sw)
            # Reload data + regenerate plan to reflow
            self.on_load()
            self.on_generate()
            messagebox.showinfo(APP_TITLE, f"Saved actuals for {day} (Lines={ln}, Swaths={sw}).")
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(APP_TITLE, f"Failed to save actuals:\n{e}")

    # --- Settings persistence ---

    def _load_settings(self):
        try:
            if not os.path.exists(SETTINGS_JSON):
                # Defaults
                self.start_date.set(date.today().isoformat())
                return
            with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
                s = json.load(f)
            self.xlsx_path.set(s.get("xlsx_path",""))
            self.start_date.set(s.get("start_date", date.today().isoformat()))
            self.horizon.set(s.get("horizon",60))
            self.target_lines.set(s.get("target_lines",8))
            self.target_swaths.set(s.get("target_swaths",10))
            self.friday_line_buffer.set(s.get("friday_line_buffer",0))
            self.friday_swath_buffer.set(s.get("friday_swath_buffer",0))
            self.lock_time.set(s.get("lock_time","10:00"))
            self.policy.set(s.get("policy","NORMAL_FIRST"))
        except Exception:
            self.start_date.set(date.today().isoformat())

    def _save_settings(self):
        try:
            s = {
                "xlsx_path": self.xlsx_path.get(),
                "start_date": self.start_date.get(),
                "horizon": int(self.horizon.get()),
                "target_lines": int(self.target_lines.get()),
                "target_swaths": int(self.target_swaths.get()),
                "friday_line_buffer": int(self.friday_line_buffer.get()),
                "friday_swath_buffer": int(self.friday_swath_buffer.get()),
                "lock_time": self.lock_time.get(),
                "policy": self.policy.get(),
            }
            with open(SETTINGS_JSON, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2, default=str)
        except Exception:
            pass


if __name__ == "__main__":
    app = APCPlannerGUI()
    app.mainloop()
