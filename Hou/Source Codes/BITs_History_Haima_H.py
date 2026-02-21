import sqlite3
import logging
import threading
import pytz
import time
import os
from datetime import datetime
from pyproj import Transformer
from tkinter import Tk, Label, Button, filedialog, messagebox, Entry, Frame, Toplevel
from tkinter import ttk
from tkcalendar import Calendar
from tkinter.font import Font
from datetime import datetime
from tkinter import PhotoImage, Label
from tkinter import Checkbutton, IntVar

# Set up logging
logging.basicConfig(level=logging.INFO)

class SQLiteCopyApp:
    def __init__(self, master):
        root.geometry("800x550")  # Set the window size as needed
        self.master = master
        master.title("BITs History Database Copier")

        self.database_path = "C:/Users/DELL/Desktop/Hussein's Program Hub/02-Haima H/00-QGIS/Bits_Database_HimaH.sqlite3"

        # Frame for Database selection
        db_frame = Frame(master)
        db_frame.pack(pady=20)  # Add padding to the frame for more spacing

        # Define a bold font for the date entry
        bold_font = Font(weight="bold")

        # Label for Target Database (.sqlite3), centered above the entry and button
        self.label_db = Label(db_frame, text="Target Database (.sqlite3):")
        self.label_db.grid(row=0, column=0, columnspan=2, pady=10)  # Center label across two columns with padding

        # Entry widget for the Target Database path
        self.database_entry = Entry(db_frame, width=30, font=bold_font)
        self.database_entry.grid(row=1, column=0, padx=10, pady=5)
        # Display only the database name
        self.database_entry.insert(0, os.path.basename(self.database_path))

        # Button to the right of the Entry widget
        self.select_db_button = Button(db_frame, text="Select Database", command=self.select_database)
        self.select_db_button.grid(row=1, column=1, padx=10, pady=5)

        # Frame for File selection
        file_frame = Frame(master)
        file_frame.pack(pady=20)

        # Label for File selection
        self.label_file = Label(file_frame, text="Select BITs CSV files to import:")
        self.label_file.grid(row=0, column=0, columnspan=2, pady=10)  # Centered above entry and button

        # Entry widget for the file path
        self.file_entry = Entry(file_frame, width=47)
        self.file_entry.grid(row=1, column=0, padx=10, pady=5)

        # Button to the right of the Entry widget for file selection
        self.select_file_button = Button(file_frame, text="Select Files", command=self.select_file)
        self.select_file_button.grid(row=1, column=1, padx=10, pady=5)  # Add padding between widgets

        # Button to initiate copying process
        self.copy_button = Button(master, text="Copy to Database", command=self.copy_to_database)
        self.copy_button.pack(pady=10)

        # Label for animation (blue text)
        self.animation_label = Label(master, text="", fg="blue")  # Set text color to blue for animation
        self.animation_label.pack(pady=10)

        # Store animation thread and flag
        self.animating = False
        self.animation_thread = None

        # Label for Line Range and Date Selection
        bold_font = ("Helvetica", 10, "bold")
        Label(self.master, text="Select Date and Line Range to Export:", font=bold_font).pack(pady=10)

        # Frame for Date Picker and Line Range Input
        line_date_frame = Frame(self.master)
        line_date_frame.pack(pady=5)

        # Button to open the calendar
        ttk.Button(line_date_frame, text="Choose Date", command=self.pick_date).pack(side='left', padx=5)
        # Date Entry to store selected date

        # Set today's date as default and display it in bold
        today_date = datetime.now().strftime("%Y-%m-%d")
        self.date_entry = Entry(line_date_frame, width=10, font=bold_font)
        self.date_entry.pack(side='left', padx=5)
        self.date_entry.insert(0, today_date)  # Insert today's date by default

        # Frame for Line Range Entry
        line_range_frame = Frame(self.master)
        line_range_frame.pack(pady=5)

        # Line Range Start Entry
        Label(line_range_frame, text="Start Line:").grid(row=0, column=0, padx=5)
        self.start_line_entry = Entry(line_range_frame, width=10)
        self.start_line_entry.grid(row=0, column=1, padx=5)

        # Line Range End Entry
        Label(line_range_frame, text="End Line:").grid(row=0, column=2, padx=5)
        self.end_line_entry = Entry(line_range_frame, width=10)
        self.end_line_entry.grid(row=0, column=3, padx=5)

        # Frame for Date Picker
        date_frame = Frame(self.master)
        date_frame.pack(pady=5)

        # EPSG transformation to convert Longitude and Latitude to PSD93
        self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:3440", always_xy=True)

        # Checkbox frame
        checkbox_frame = Frame(master)
        checkbox_frame.pack(pady=10)

        # Define IntVars to store checkbox states
        self.check_serial = IntVar()
        self.check_tilt = IntVar()
        self.check_resistance = IntVar()
        self.check_gps = IntVar()
        self.check_thd = IntVar()

        # Add checkboxes to frame
        Checkbutton(checkbox_frame, text="Serial", variable=self.check_serial).grid(row=0, column=0, padx=5)
        Checkbutton(checkbox_frame, text="Tilt", variable=self.check_tilt).grid(row=0, column=1, padx=5)
        Checkbutton(checkbox_frame, text="Resistance", variable=self.check_resistance).grid(row=0, column=2, padx=5)
        Checkbutton(checkbox_frame, text="GPS_Status", variable=self.check_gps).grid(row=0, column=3, padx=5)
        Checkbutton(checkbox_frame, text="THD", variable=self.check_thd).grid(row=0, column=4, padx=5)

        # Button to export data to CSV
        self.export_csv_button = Button(master, text="Export As CSV", command=self.export_to_csv)
        self.export_csv_button.pack(pady=10)

    def pick_date(self):
        def print_sel():
            selected_date = cal.selection_get()
            formatted_date = selected_date.strftime("%Y-%m-%d")  # For display purposes
            self.date_entry.delete(0, 'end')  # Clear any existing text
            self.date_entry.insert(0, formatted_date)
            top.destroy()

        top = Toplevel(self.master)
        cal = Calendar(top, selectmode='day')
        cal.grid(row=0, column=0, padx=10, pady=10)

        ttk.Button(top, text="Ok", command=print_sel).grid(row=1, column=0, pady=20)

    def select_database(self):
        db_file = filedialog.askopenfilename(title="Select Target Database", filetypes=[("SQLite files", "*.sqlite3")])
        if db_file:
            self.database_entry.delete(0, 'end')
            # Display only the database name of the selected file
            self.database_entry.insert(0, os.path.basename(db_file))
            self.database_path = db_file  # Update self.database_path with the selected file path

    def select_file(self):
        files = filedialog.askopenfilenames(title="Select SQLite files", filetypes=[("SQLite files", "*.csv")])
        if files:
            self.file_entry.delete(0, 'end')
            self.file_entry.insert(0, ', '.join(files))  # Display selected files as a comma-separated string
            self.selected_files = list(files)  # Store the selected files in a list

    def start_animation(self):
        """Start the waiting animation."""
        self.animating = True
        self.animation_thread = threading.Thread(target=self.animate)
        self.animation_thread.start()

    def stop_animation(self):
        """Stop the waiting animation and clear the animation label."""
        self.animating = False
        if self.animation_thread:
            self.animation_thread.join()
        self.animation_label.config(text="")  # Clear the animation label after stopping

    def animate(self):
        """Perform the animation while waiting."""
        chars = ['|', '/', '-', '\\']  # A rotating animation effect
        idx = 0
        while self.animating:
            time.sleep(0.2)
            self.animation_label.config(text=f"Importing... {chars[idx % len(chars)]}")
            idx += 1
            self.master.update_idletasks()

    def convert_unix_to_oman_time(self, unix_timestamp):
        oman_tz = pytz.timezone('Asia/Muscat')
        dt = datetime.fromtimestamp(unix_timestamp, pytz.utc).astimezone(oman_tz)
        return dt.date(), dt.time()  # Returns (date, time)

    def format_line_station(self, value):
        # Convert value by dividing by 100
        return str(value // 100)

    def copy_to_database(self):
        # Use the existing self.database_path or get the path from the entry if manually changed
        if not self.database_path:
            self.database_path = self.database_entry.get()

        # Check if the database path is set
        if not self.database_path:
            messagebox.showwarning("No Database", "Please select or set a target database.")
            return

        # Ensure there are selected files to import
        if not hasattr(self, 'selected_files') or not self.selected_files:
            messagebox.showwarning("No Selection", "Please select one or more .sqlite files to import.")
            return

        # Start the animation in a new thread
        self.start_animation()

        # Run the import process in a separate thread to keep the GUI responsive
        threading.Thread(target=self._run_import_process).start()

    def _run_import_process(self):
        """The actual process of importing data (runs in a separate thread)."""
        try:
            for file in self.selected_files:
                self.copy_database(file)
            self.stop_animation()
            messagebox.showinfo("Success", "Data copied successfully!")
        except Exception as e:
            self.stop_animation()
            messagebox.showerror("Error", f"An error occurred: {e}")

    def copy_database(self, source_file):
        with sqlite3.connect(self.database_path) as target_conn, sqlite3.connect(source_file) as source_conn:
            target_cursor = target_conn.cursor()
            source_cursor = source_conn.cursor()

            try:
                # Process QuantumQCBT data
                source_cursor.execute("""
                    SELECT PullTime, AssumedBITsTime, Serial, BatteryRemaining, MemoryAvailable, Resistance, GeophoneNoise,
                           Tilt, GPSStatus, AcquisitionStatus, Latitude, Longitude, NearestLine, NearestFlag, 
                           THDResponseFail, DeviceType 
                    FROM QuantumQCBT
                """)
                rows_bt = source_cursor.fetchall()

                for row in rows_bt:
                    # Prepare data fields with appropriate mappings and default handling for None values
                    pull_time_value = row[0] if row[0] is not None else 0
                    bits_time_value = row[1] if row[1] is not None else 0
                    serial_value = row[2] if row[2] is not None else "Unknown"
                    battery_remaining = row[3] if row[3] is not None else 0
                    memory_available = row[4] if row[4] is not None else 0
                    resistance_status = "PASS" if row[5] < 198800.75 else "FAIL" if row[5] is not None else "Unknown"
                    geophone_noise = row[6] if row[6] is not None else "Unknown"
                    tilt_status = "PASS" if row[7] < 30 else "FAIL" if row[7] is not None else "Unknown"
                    gps_status = "PASS" if row[8] < 4 else "FAIL" if row[8] is not None else "Unknown"
                    thd_status = "PASS" if row[14] == 0 else "FAIL" if row[14] is not None else "Unknown"
                    latitude_formatted = row[10] / 10000000 if row[10] is not None else None
                    longitude_formatted = row[11] / 10000000 if row[11] is not None else None
                    line_formatted = self.format_line_station(row[12]) if row[12] is not None else "Unknown"
                    station_formatted = self.format_line_station(row[13]) if row[13] is not None else "Unknown"
                    device_type = row[15] if row[15] is not None else "Unknown"

                    # Convert timestamps
                    pull_date, pull_time = self.convert_unix_to_oman_time(pull_time_value)
                    bits_date, bits_time = self.convert_unix_to_oman_time(bits_time_value)

                    pull_date_str = pull_date.strftime("%Y-%m-%d")
                    pull_time_str = pull_time.strftime("%H:%M:%S")
                    bits_date_str = bits_date.strftime("%Y-%m-%d")
                    bits_time_str = bits_time.strftime("%H:%M:%S")

                    # Only transform coordinates if both latitude and longitude are valid
                    if latitude_formatted is not None and longitude_formatted is not None:
                        easting, northing = self.transformer.transform(longitude_formatted, latitude_formatted)
                    else:
                        easting = None
                        northing = None

                    # Insert into HyperQ_Node_Data
                    target_cursor.execute(
                        "INSERT INTO HyperQ_Node_Data (Serial_Number, Pull_Date, Pull_Time, BITs_Date, BITs_Time, Line, "
                        "Station, Longitude, Latitude, Easting, Northing, Device_Type, Tilt, Resistance, GPS_Status, THD, "
                        "Geophone_Noise, Battery_Remaining, Memory_Available) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            serial_value, pull_date_str, pull_time_str, bits_date_str, bits_time_str, line_formatted,
                            station_formatted, longitude_formatted, latitude_formatted, easting, northing, device_type,
                            tilt_status, resistance_status, gps_status, thd_status, geophone_noise, battery_remaining,
                            memory_available
                        )
                    )

                # Process QuantumQCHyperQ data
                source_cursor.execute("""
                    SELECT PullTime, AssumedBITsTime, Serial, BatteryRemaining, MemoryAvailable, TiltFail, ResistanceFail, 
                           GPSStatus, GeophoneNoise, Latitude, Longitude, NearestLine, NearestFlag, THDResponseFail, 
                           DeviceType 
                    FROM QuantumQCHyperQ
                """)
                rows_hyperq = source_cursor.fetchall()

                for row in rows_hyperq:
                    # Prepare data fields
                    pull_time_value = row[0] if row[0] is not None else 0
                    bits_time_value = row[1] if row[1] is not None else 0
                    serial_value = row[2] if row[2] is not None else "Unknown"
                    battery_remaining = row[3] if row[3] is not None else 0
                    memory_available = row[4] if row[4] is not None else 0
                    tilt_status = "PASS" if row[5] == 0 else "FAIL" if row[5] is not None else "Unknown"
                    resistance_status = "PASS" if row[6] == 0 else "FAIL" if row[6] is not None else "Unknown"
                    gps_status = "PASS" if row[7] == 0 else "FAIL" if row[7] is not None else "Unknown"
                    geophone_noise = row[8] if row[8] is not None else "Unknown"
                    latitude_formatted = row[9] / 10000000 if row[9] is not None else None
                    longitude_formatted = row[10] / 10000000 if row[10] is not None else None
                    line_formatted = self.format_line_station(row[11]) if row[11] is not None else "Unknown"
                    station_formatted = self.format_line_station(row[12]) if row[12] is not None else "Unknown"
                    thd_status = "PASS" if row[13] == 0 else "FAIL" if row[13] is not None else "Unknown"
                    device_type = row[14] if row[14] is not None else "Unknown"

                    # Convert timestamps
                    pull_date, pull_time = self.convert_unix_to_oman_time(pull_time_value)
                    bits_date, bits_time = self.convert_unix_to_oman_time(bits_time_value)

                    pull_date_str = pull_date.strftime("%Y-%m-%d")
                    pull_time_str = pull_time.strftime("%H:%M:%S")
                    bits_date_str = bits_date.strftime("%Y-%m-%d")
                    bits_time_str = bits_time.strftime("%H:%M:%S")

                    # Only transform coordinates if both latitude and longitude are valid
                    if latitude_formatted is not None and longitude_formatted is not None:
                        easting, northing = self.transformer.transform(longitude_formatted, latitude_formatted)
                    else:
                        easting = None
                        northing = None

                    # Insert into HyperQ_Node_Data
                    target_cursor.execute(
                        "INSERT INTO HyperQ_Node_Data (Serial_Number, Pull_Date, Pull_Time, BITs_Date, BITs_Time, Line, "
                        "Station, Longitude, Latitude, Easting, Northing, Device_Type, Tilt, Resistance, GPS_Status, THD, "
                        "Geophone_Noise, Battery_Remaining, Memory_Available) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            serial_value, pull_date_str, pull_time_str, bits_date_str, bits_time_str, line_formatted,
                            station_formatted, longitude_formatted, latitude_formatted, easting, northing, device_type,
                            tilt_status, resistance_status, gps_status, thd_status, geophone_noise, battery_remaining,
                            memory_available
                        )
                    )

                target_conn.commit()  # Commit all inserts at once

                # Remove duplicate Serial Numbers in HyperQ_Node_Data, keeping the latest by Pull_Time
                target_cursor.execute("""
                    DELETE FROM HyperQ_Node_Data
                    WHERE rowid NOT IN (
                        SELECT MAX(rowid)
                        FROM HyperQ_Node_Data
                        GROUP BY Serial_Number, Pull_Date, Pull_Time
                    )
                """)

                target_conn.commit()  # Final commit after duplicate removal

            except sqlite3.Error as e:
                target_conn.rollback()  # Rollback in case of error
                logging.error(f"Database error: {e}")
                raise  # Raise the exception for the messagebox

    def export_to_csv(self):
        if not hasattr(self, 'database_path') or not self.database_path:
            messagebox.showwarning("No Database", "Please select a target database.")
            return

        selected_date = self.date_entry.get()
        if not selected_date:
            messagebox.showwarning("No Date Selected", "Please select a date.")
            return

        start_line = self.start_line_entry.get()
        end_line = self.end_line_entry.get()

        from datetime import datetime
        try:
            selected_date = datetime.strptime(selected_date, '%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:
            messagebox.showerror("Date Format Error", "Please enter a date in YYYY-MM-DD format.")
            return

        # Define columns to be exported based on user selection
        columns = ["Line", "Station", "Easting", "Northing"]
        if self.check_serial.get():
            columns.append("Serial_Number")
        if self.check_tilt.get():
            columns.append("Tilt")
        if self.check_resistance.get():
            columns.append("Resistance")
        if self.check_gps.get():
            columns.append("GPS_Status")
        if self.check_thd.get():
            columns.append("THD")

        columns_sql = ", ".join(columns)

        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()

            if not start_line or not end_line:
                query = f"""
                WITH RankedData AS (
                    SELECT {columns_sql}, 
                           ROW_NUMBER() OVER(PARTITION BY Line, Station ORDER BY Pull_Time DESC) AS row_num
                    FROM HyperQ_Node_Data
                    WHERE Pull_Date = ?
                )
                SELECT {columns_sql}
                FROM RankedData
                WHERE row_num = 1
                """
                params = (selected_date,)
                csv_filename = f"{selected_date}_All_Lines.csv"
            else:
                query = f"""
                WITH RankedData AS (
                    SELECT {columns_sql}, 
                           ROW_NUMBER() OVER(PARTITION BY Line, Station ORDER BY Pull_Time DESC) AS row_num
                    FROM HyperQ_Node_Data
                    WHERE Line BETWEEN ? AND ? AND Pull_Date = ?
                )
                SELECT {columns_sql}
                FROM RankedData
                WHERE row_num = 1
                """
                params = (start_line, end_line, selected_date)
                csv_filename = f"{selected_date}_Lines_{start_line}_To_{end_line}.csv"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            if rows:
                csv_path = os.path.join(os.path.dirname(self.database_path), csv_filename)

                with open(csv_path, 'w') as csv_file:
                    csv_file.write(",".join(columns) + "\n")
                    for row in rows:
                        csv_file.write(",".join(map(str, row)) + "\n")
                messagebox.showinfo("Export Success", f"Data exported to {csv_path}")
            else:
                messagebox.showinfo("No Data", "No data found for the specified criteria.")

        except sqlite3.Error as e:
            messagebox.showerror("Database Error", f"Error occurred: {e}")
        finally:
            if 'conn' in locals():
                conn.close()


if __name__ == "__main__":
    root = Tk()
    app = SQLiteCopyApp(root)
    root.mainloop()
