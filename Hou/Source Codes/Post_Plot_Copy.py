import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox

def insert_data_from_txt(cursor, filepath, table_name):
    try:
        with open(filepath, 'r') as file:
            for line in file:
                record_identification = line[0:1].strip()
                line_name = line[1:11].strip()
                point_number = line[11:21].strip()
                point_index = line[23:24].strip()
                point_code = line[24:26].strip()
                map_grid_easting = line[46:55].strip()
                map_grid_northing = line[55:65].strip()
                surface_elevation = line[65:71].strip()

                cursor.execute(f'''INSERT INTO {table_name} ("Record_identification", "Line_name", "Point_number", "Point_index", "Point_code",
                                  "Map_grid_easting", "Map_grid_northing", "Surface_elevation")
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (record_identification, line_name, point_number, point_index,
                                  point_code, map_grid_easting, map_grid_northing, surface_elevation))
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while importing data from {filepath}: {str(e)}")
        raise e

def select_database():
    database_path = filedialog.askopenfilename(filetypes=[("SQLite Database", "*.sqlite3")])
    database_entry.delete(0, tk.END)
    database_entry.insert(0, database_path)

def select_files():
    file_paths = filedialog.askopenfilenames(filetypes=[("REC Files", "*.REC"), ("Text Files", "*.txt"), ("R Files", "*.R")])
    file_entry.delete(0, tk.END)
    file_entry.insert(0, ', '.join(file_paths))

def import_data():
    db_path = database_entry.get()
    file_paths = file_entry.get().split(', ')

    selected_block = block_name.get()

    if not db_path or not file_paths:
        messagebox.showerror("Error", "Please select both a database and at least one file.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        table_name = f"Postplot_Block_{selected_block}"

        for file_path in file_paths:
            insert_data_from_txt(cursor, file_path.strip(), table_name)

        conn.commit()
        messagebox.showinfo("Success", "Data imported successfully.")
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while importing data: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

root = tk.Tk()
root.title("Post Plot Importer")

database_label = tk.Label(root, text="Select SQLite Database:")
database_label.grid(row=0, column=0, padx=5, pady=5)
database_entry = tk.Entry(root, width=50)
database_entry.grid(row=0, column=1, padx=5, pady=5)
database_button = tk.Button(root, text="Browse", command=select_database)
database_button.grid(row=0, column=2, padx=5, pady=5)

file_label = tk.Label(root, text="Select Data Files:")
file_label.grid(row=1, column=0, padx=5, pady=5)
file_entry = tk.Entry(root, width=50)
file_entry.grid(row=1, column=1, padx=5, pady=5)
file_button = tk.Button(root, text="Browse", command=select_files)
file_button.grid(row=1, column=2, padx=5, pady=5)

block_label = tk.Label(root, text="Select Block Name:")
block_label.grid(row=2, column=0, padx=5, pady=5)
block_name = tk.StringVar(root, value="A")
block_dropdown = tk.OptionMenu(root, block_name, "A", "B", "C", "D")
block_dropdown.grid(row=2, column=1, padx=5, pady=5)

import_button = tk.Button(root, text="Import Data", command=import_data)
import_button.grid(row=3, column=1, padx=5, pady=5)

root.mainloop()
