import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox
import os

# Default path for the database
default_db_path = "C:/Users/DELL/Desktop/QC_Pro_Hub/25ZAZ/SPS_Database_ZAZ.sqlite3"

# To store the full paths of the folders (not shown in the listbox)
full_folder_paths = []

def insert_data_from_txt(cursor, filepath, table_name):
    try:
        with open(filepath, 'r') as file:
            next(file)  # Skip header

            for line in file:
                record_identification = line[0:1].strip()
                line_name = line[1:11].strip()
                point_number = line[11:21].strip()
                point_index_point_code = line[24:26].strip()
                map_grid_easting = line[46:55].strip()
                map_grid_northing = line[55:65].strip()
                surface_elevation = line[65:71].strip()

                cursor.execute(f'''INSERT INTO {table_name} ("Record_identification", "Line_name", "Point_number", "Point_index_Point_code",
                                  "Map_grid_easting", "Map_grid_northing", "Surface_elevation")
                                  VALUES (?, ?, ?, ?, ?, ?, ?)''', (record_identification, line_name, point_number,
                                  point_index_point_code, map_grid_easting, map_grid_northing, surface_elevation))

    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while importing data: {str(e)}")
        raise e

def select_main_folder():
    folder_path = filedialog.askdirectory()
    if folder_path:
        sub_folders_list.delete(0, tk.END)  # Clear the current list
        full_folder_paths.clear()  # Clear full paths list

        for entry in os.listdir(folder_path):
            full_path = os.path.join(folder_path, entry)
            if os.path.isdir(full_path):
                full_folder_paths.append(full_path)  # Store full paths internally
                sub_folders_list.insert(tk.END, os.path.basename(full_path))  # Show only the last folder name

def browse_database():
    file_path = filedialog.askopenfilename(
        filetypes=[("SQLite Database", "*.db"), ("SQLite Database", "*.sqlite3")],
        initialdir=os.path.expanduser("~")
    )
    if file_path:
        database_entry.delete(0, tk.END)  # Clear the current entry
        database_entry.insert(0, file_path)  # Insert the selected file path

def import_data():
    db_path = database_entry.get()
    selected_folders = sub_folders_list.curselection()  # Get selected indices
    selected_folders_paths = [full_folder_paths[i] for i in selected_folders]  # Retrieve full folder paths
    selected_block = block_name.get()

    if not db_path or not selected_folders_paths:
        messagebox.showerror("Error", "Please select a database and at least one folder.")
        return

    conn = None
    cursor = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        total_files = 0
        # Count all .r, .s, .x files in the selected folders
        for folder_path in selected_folders_paths:
            total_files += len([filename for filename in os.listdir(folder_path) if filename.endswith(('.r', '.s'))])
            # To re-enable .x files in the future, include '.x' again above

        imported_files = 0
        progress_label.config(text=f"Importing files: 0/{total_files}")

        for folder_path in selected_folders_paths:
            for filename in os.listdir(folder_path):
                if filename.endswith(('.r', '.s')):
                    file_path = os.path.join(folder_path, filename)
                    table_name = f"To_VCU_{'R' if filename.endswith('.r') else 'S'}_Block_{selected_block}"
                    insert_data_from_txt(cursor, file_path, table_name)

                    imported_files += 1
                    progress_label.config(text=f"Importing files: {imported_files}/{total_files}")
                    root.update()  # Update the GUI

        conn.commit()  # Commit all changes after processing all files
        conn.close()

        messagebox.showinfo("Success", "Data imported successfully.")
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred while importing data: {str(e)}")
        if conn:
            conn.rollback()
            conn.close()

root = tk.Tk()
root.title("To VCU SPS Data Importer")

database_label = tk.Label(root, text="Select SQLite Database:")
database_label.grid(row=0, column=0, padx=5, pady=5)
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
block_label.grid(row=2, column=0, padx=5, pady=5)
block_name = tk.StringVar(root, value="D")
block_dropdown = tk.OptionMenu(root, block_name, "D", "C", "D_Infill", "C_Infill")
block_dropdown.grid(row=2, column=1, padx=5, pady=5)

progress_label = tk.Label(root, text="")
progress_label.grid(row=3, columnspan=3, padx=5, pady=5)

import_button = tk.Button(root, text="Import Data", command=import_data)
import_button.grid(row=4, column=1, padx=5, pady=5)

root.mainloop()
