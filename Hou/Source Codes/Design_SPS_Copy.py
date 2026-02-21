# ============================================================
# Design SPS Data Importer (Normal vs Infill aware)
# Author: Hussein Al Shibli | BGP Oman APC
# ============================================================

import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sqlite3

# ---------- Signature ----------
SIGNATURE_TEXT = "Hussein Al Shibli | BGP Oman APC"

# Default path for the database
default_db_path = "E:/25 BIRBA/01-DataBase/SPS_Database_BB.sqlite3"

def is_infill(block_value: str) -> bool:
    """Return True if selected block is an Infill block."""
    return "_Infill" in (block_value or "")

def allowed_extensions_for_block(block_value: str):
    """Infill → only .r files | Normal → .r and .s files"""
    if is_infill(block_value):
        return {".r"}
    return {".r", ".s"}

def insert_data_from_txt(cursor, filepath, table_name):
    try:
        with open(filepath, 'r') as file:
            pos = file.tell()
            first = file.readline()
            if not first or (len(first) > 0 and first[0] not in ("R", "S")):
                pass
            else:
                file.seek(pos)

            cursor.execute("BEGIN TRANSACTION;")

            for line in file:
                if not line.strip():
                    continue

                record_identification   = line[0:1].strip()
                line_name               = line[1:11].strip()
                point_number            = line[11:21].strip()
                point_index_point_code  = line[24:26].strip()
                map_grid_easting        = line[46:55].strip()
                map_grid_northing       = line[55:65].strip()
                surface_elevation       = line[65:71].strip()

                cursor.execute(f'''
                    INSERT OR REPLACE INTO {table_name} (
                        "Record_identification",
                        "Line_name",
                        "Point_number",
                        "Point_index_Point_code",
                        "Map_grid_easting",
                        "Map_grid_northing",
                        "Surface_elevation"
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record_identification,
                    line_name,
                    point_number,
                    point_index_point_code,
                    map_grid_easting,
                    map_grid_northing,
                    surface_elevation
                ))

            cursor.execute("COMMIT;")

    except Exception as e:
        try:
            cursor.execute("ROLLBACK;")
        except Exception:
            pass
        messagebox.showerror("Error", f"An error occurred while importing data:\n{str(e)}")
        raise

def select_main_folder():
    folder_path = filedialog.askdirectory()
    if folder_path:
        sub_folders_list.delete(0, tk.END)
        for entry in os.listdir(folder_path):
            full_path = os.path.join(folder_path, entry)
            if os.path.isdir(full_path):
                sub_folders_list.insert(tk.END, full_path)

def import_data():
    db_path = database_entry.get()
    selected_folders = sub_folders_list.curselection()
    selected_folders_paths = [sub_folders_list.get(i) for i in selected_folders]
    selected_block = block_name.get()

    if not db_path or not selected_folders_paths:
        messagebox.showerror("Error", "Please select a database and at least one folder.")
        return

    allowed_exts = allowed_extensions_for_block(selected_block)

    def _is_allowed(filename: str) -> bool:
        ext = os.path.splitext(filename)[1].lower()
        return ext in allowed_exts

    conn = None
    cursor = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        total_files = 0
        for folder_path in selected_folders_paths:
            total_files += len([
                filename for filename in os.listdir(folder_path)
                if _is_allowed(filename)
            ])

        if total_files == 0:
            messagebox.showinfo("No files", "No matching SPS files found for the selected block.")
            return

        imported_files = 0
        progress_label.config(text=f"Importing files: 0/{total_files}")

        for folder_path in selected_folders_paths:
            for filename in os.listdir(folder_path):
                if not _is_allowed(filename):
                    continue

                file_path = os.path.join(folder_path, filename)
                ext = os.path.splitext(filename)[1].lower()
                table_suffix = "R" if ext == ".r" else "S"
                table_name = f'Design_{table_suffix}_Block_{selected_block}'
                insert_data_from_txt(cursor, file_path, table_name)

                imported_files += 1
                progress_label.config(text=f"Importing files: {imported_files}/{total_files}")
                root.update()

        conn.commit()
        messagebox.showinfo("Success", "Data imported successfully.")
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        messagebox.showerror("Error", f"An error occurred while importing data:\n{str(e)}")
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def browse_database():
    file_path = filedialog.askopenfilename(
        filetypes=[("SQLite Database", "*.db *.sqlite *.sqlite3"), ("All Files", "*.*")],
        initialdir=os.path.expanduser("~")
    )
    if file_path:
        database_entry.delete(0, tk.END)
        database_entry.insert(0, file_path)

# ---------------- UI ----------------
root = tk.Tk()
root.title("Design SPS Data Importer")

database_label = tk.Label(root, text="Select SQLite Database:")
database_label.grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
database_entry = tk.Entry(root, width=50)
database_entry.grid(row=0, column=1, padx=5, pady=5)
database_entry.insert(0, default_db_path)
database_button = tk.Button(root, text="Browse", command=browse_database)
database_button.grid(row=0, column=2, padx=5, pady=5)

folder_label = tk.Label(root, text="Select Main Folder:")
folder_label.grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
folder_button = tk.Button(root, text="Browse", command=select_main_folder)
folder_button.grid(row=1, column=2, padx=5, pady=5)

sub_folders_list = tk.Listbox(root, selectmode=tk.MULTIPLE, width=70, height=10)
sub_folders_list.grid(row=1, column=1, padx=5, pady=5)

block_label = tk.Label(root, text="Select Block Name:")
block_label.grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
block_name = tk.StringVar(root, value="A")
block_dropdown = tk.OptionMenu(
    root, block_name,
    "A", "A_Infill",
    "B", "B_Infill",
    "C", "C_Infill",
    "D", "D_Infill"
)
block_dropdown.grid(row=3, column=1, padx=5, pady=5, sticky=tk.W)

progress_label = tk.Label(root, text="")
progress_label.grid(row=4, columnspan=3, padx=5, pady=5)

import_button = tk.Button(root, text="Import Data", command=import_data)
import_button.grid(row=5, column=1, padx=5, pady=5)

# Signature footer (aligned left)
signature_label = tk.Label(root, text=SIGNATURE_TEXT, fg="gray", font=("Arial", 8, "italic"), anchor="w", justify="left")
signature_label.grid(row=6, column=0, columnspan=3, sticky="w", padx=10, pady=(15, 5))

root.mainloop()
