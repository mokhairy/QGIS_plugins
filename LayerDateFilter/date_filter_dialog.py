import os
import re
from datetime import date, datetime

from qgis.PyQt.QtCore import QDate, QDateTime, QEventLoop, QSettings, QTimer, Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QColorDialog,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject, QgsVectorLayer


class DateFilterDialog(QDialog):
    MAX_ROWS = 500
    SETTINGS_KEY_OUTPUT_DIR = "LayerDateFilter/output_dir"
    SETTINGS_KEY_SELECTION_COLOR = "LayerDateFilter/selection_color"
    SETTINGS_KEY_MOVIE_FPS = "LayerDateFilter/movie_fps"
    DATE_PATTERNS = [
        "yyyy-MM-dd",
        "yyyy/MM/dd",
        "dd/MM/yyyy",
        "MM/dd/yyyy",
        "dd-MM-yyyy",
        "MM-dd-yyyy",
        "yyyy-MM-dd HH:mm:ss",
        "yyyy/MM/dd HH:mm:ss",
        "dd/MM/yyyy HH:mm:ss",
        "MM/dd/yyyy HH:mm:ss",
    ]

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.settings = QSettings()
        self._last_layer = None
        self._last_feature_ids = []
        self._last_snapshot_paths = []
        self._last_run_layer_name = ""
        self._last_run_start = None
        self._last_run_end = None
        self._selection_color = QColor("#ff4d4f")
        self._canvas_date_label = None

        self.setWindowTitle("Layer Date Filter")
        self.resize(1040, 660)
        self._build_ui()
        self._connect_signals()
        self.output_dir_edit.setText(
            self.settings.value(self.SETTINGS_KEY_OUTPUT_DIR, "", type=str)
        )
        stored_color = self.settings.value(
            self.SETTINGS_KEY_SELECTION_COLOR,
            "#ff4d4f",
            type=str,
        )
        self._selection_color = QColor(stored_color)
        if not self._selection_color.isValid():
            self._selection_color = QColor("#ff4d4f")
        self._update_color_button()
        self.movie_fps_spin.setValue(
            self.settings.value(self.SETTINGS_KEY_MOVIE_FPS, 2, type=int)
        )
        self.refresh_layers()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        controls_layout = QGridLayout()
        layout.addLayout(controls_layout)

        controls_layout.addWidget(QLabel("Layer"), 0, 0)
        self.layer_combo = QComboBox()
        controls_layout.addWidget(self.layer_combo, 0, 1)
        self.refresh_button = QPushButton("Refresh Layers")
        controls_layout.addWidget(self.refresh_button, 0, 2)

        controls_layout.addWidget(QLabel("Date field"), 1, 0)
        self.date_field_combo = QComboBox()
        controls_layout.addWidget(self.date_field_combo, 1, 1, 1, 2)

        controls_layout.addWidget(QLabel("Filter mode"), 2, 0)
        self.filter_mode_combo = QComboBox()
        self.filter_mode_combo.addItems(["Single date", "Date range"])
        controls_layout.addWidget(self.filter_mode_combo, 2, 1, 1, 2)

        self.mode_stack = QStackedWidget()
        controls_layout.addWidget(self.mode_stack, 3, 0, 1, 3)

        single_page = QWidget()
        single_layout = QHBoxLayout(single_page)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.addWidget(QLabel("Date"))
        self.single_date_edit = QDateEdit(QDate.currentDate())
        self.single_date_edit.setCalendarPopup(True)
        self.single_date_edit.setDisplayFormat("yyyy-MM-dd")
        single_layout.addWidget(self.single_date_edit)
        single_layout.addStretch(1)
        self.mode_stack.addWidget(single_page)

        range_page = QWidget()
        range_layout = QHBoxLayout(range_page)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.addWidget(QLabel("Start date"))
        self.start_date_edit = QDateEdit(QDate.currentDate().addDays(-7))
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        range_layout.addWidget(self.start_date_edit)
        range_layout.addWidget(QLabel("End date"))
        self.end_date_edit = QDateEdit(QDate.currentDate())
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        range_layout.addWidget(self.end_date_edit)
        range_layout.addStretch(1)
        self.mode_stack.addWidget(range_page)

        controls_layout.addWidget(QLabel("PNG output folder"), 4, 0)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Choose folder for daily map PNG files")
        controls_layout.addWidget(self.output_dir_edit, 4, 1)
        self.browse_output_dir_button = QPushButton("Browse")
        controls_layout.addWidget(self.browse_output_dir_button, 4, 2)

        controls_layout.addWidget(QLabel("Filtered data color"), 5, 0)
        self.color_button = QPushButton()
        controls_layout.addWidget(self.color_button, 5, 1)

        controls_layout.addWidget(QLabel("Movie FPS"), 6, 0)
        self.movie_fps_spin = QSpinBox()
        self.movie_fps_spin.setRange(1, 30)
        self.movie_fps_spin.setValue(2)
        controls_layout.addWidget(self.movie_fps_spin, 6, 1)

        buttons_layout = QHBoxLayout()
        layout.addLayout(buttons_layout)
        self.apply_button = QPushButton("Apply Filter")
        self.select_button = QPushButton("Select In Layer")
        self.create_movie_button = QPushButton("Create Movie")
        self.clear_button = QPushButton("Clear Results")
        self.close_button = QPushButton("Close")
        buttons_layout.addWidget(self.apply_button)
        buttons_layout.addWidget(self.select_button)
        buttons_layout.addWidget(self.create_movie_button)
        buttons_layout.addWidget(self.clear_button)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.close_button)

        self.results_label = QLabel("No filter applied.")
        layout.addWidget(self.results_label)

        self.results_table = QTableWidget()
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.verticalHeader().setVisible(False)
        layout.addWidget(self.results_table)

        self.select_button.setEnabled(False)
        self.create_movie_button.setEnabled(False)

    def _connect_signals(self):
        self.refresh_button.clicked.connect(self.refresh_layers)
        self.layer_combo.currentIndexChanged.connect(self._populate_date_fields)
        self.filter_mode_combo.currentIndexChanged.connect(self.mode_stack.setCurrentIndex)
        self.browse_output_dir_button.clicked.connect(self.choose_output_directory)
        self.color_button.clicked.connect(self.choose_selection_color)
        self.apply_button.clicked.connect(self.apply_filter)
        self.select_button.clicked.connect(self.select_filtered_features)
        self.create_movie_button.clicked.connect(
            lambda _checked=False: self.create_movie_from_last_run()
        )
        self.clear_button.clicked.connect(self.clear_results)
        self.close_button.clicked.connect(self.close)
        self.movie_fps_spin.valueChanged.connect(self._store_movie_fps)

        project = QgsProject.instance()
        project.layersAdded.connect(self.refresh_layers)
        project.layersRemoved.connect(self.refresh_layers)
        project.cleared.connect(self.refresh_layers)

    def refresh_layers(self, *_args):
        current_layer_id = self.layer_combo.currentData()
        vector_layers = sorted(
            (
                lyr
                for lyr in QgsProject.instance().mapLayers().values()
                if isinstance(lyr, QgsVectorLayer)
            ),
            key=lambda lyr: lyr.name().lower(),
        )

        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for layer in vector_layers:
            self.layer_combo.addItem(layer.name(), layer.id())
        self.layer_combo.blockSignals(False)

        if not vector_layers:
            self.date_field_combo.clear()
            self.date_field_combo.setEnabled(False)
            return

        if current_layer_id:
            idx = self.layer_combo.findData(current_layer_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)

        self._populate_date_fields()

    def _current_layer(self):
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        if isinstance(layer, QgsVectorLayer):
            return layer
        return None

    def _populate_date_fields(self, *_args):
        layer = self._current_layer()
        self.date_field_combo.clear()

        if layer is None:
            self.date_field_combo.setEnabled(False)
            return

        candidate_fields = self._detect_date_fields(layer)
        for field_name in candidate_fields:
            self.date_field_combo.addItem(field_name)

        self.date_field_combo.setEnabled(bool(candidate_fields))
        if not candidate_fields:
            self._show_message("No date-like fields found in the selected layer.", warning=True)

    def _detect_date_fields(self, layer):
        fields = layer.fields()
        date_fields = []
        string_fields = []

        for field in fields:
            field_type = field.type()
            if field_type in (QVariant.Date, QVariant.DateTime):
                date_fields.append(field.name())
            elif field_type in (QVariant.String, QVariant.Char):
                string_fields.append(field.name())
            elif "date" in field.name().lower():
                date_fields.append(field.name())

        sample_values = {name: [] for name in string_fields}
        for i, feature in enumerate(layer.getFeatures()):
            if i >= 40:
                break
            for name in string_fields:
                value = feature[name]
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    sample_values[name].append(text)

        for name in string_fields:
            values = sample_values.get(name, [])
            if not values:
                continue
            valid_count = sum(1 for value in values if self._to_qdate(value))
            if valid_count / len(values) >= 0.6 and name not in date_fields:
                date_fields.append(name)

        return date_fields

    def apply_filter(self):
        layer = self._current_layer()
        if layer is None:
            self._show_message("Select a vector layer first.", warning=True)
            return

        field_name = self.date_field_combo.currentText()
        if not field_name:
            self._show_message("Select a date field first.", warning=True)
            return

        parsed_records = []
        max_available_date = None
        for feature in layer.getFeatures():
            parsed_date = self._to_qdate(feature[field_name])
            if not parsed_date:
                continue
            parsed_records.append((feature, parsed_date))
            if max_available_date is None or parsed_date > max_available_date:
                max_available_date = parsed_date

        if not parsed_records:
            self._show_message("No valid date values were found in this field.", warning=True)
            self.clear_results()
            return

        single_mode = self.filter_mode_combo.currentIndex() == 0
        if single_mode:
            start_date = self.single_date_edit.date()
            end_date = start_date
        else:
            start_date = self.start_date_edit.date()
            end_date = self.end_date_edit.date()
            if start_date > end_date:
                self._show_message("Start date must be before or equal to end date.", warning=True)
                return
            if max_available_date and end_date > max_available_date:
                end_date = max_available_date
                self._show_message(
                    "Range end adjusted to last available date in data: {0}.".format(
                        end_date.toString("yyyy-MM-dd")
                    ),
                    warning=True,
                )

        if start_date > end_date:
            self._show_message("No available data in the selected date range.", warning=True)
            self.clear_results()
            return

        day_to_features = self._group_features_by_day(parsed_records, start_date, end_date)
        matched_features = []
        for feature_list in day_to_features.values():
            matched_features.extend(feature_list)

        self._last_layer = layer
        self._last_run_layer_name = layer.name()
        self._last_run_start = start_date
        self._last_run_end = end_date
        self.select_button.setEnabled(True)

        snapshot_paths = self._run_single_date_cycle_for_range(
            layer=layer,
            day_to_features=day_to_features,
            start_date=start_date,
            end_date=end_date,
            update_table_each_step=single_mode,
        )
        self._last_snapshot_paths = snapshot_paths
        self.create_movie_button.setEnabled(len(snapshot_paths) >= 2)

        if not single_mode:
            # After the day-by-day run, show the full range result set.
            self._populate_table(layer, matched_features)

        end_key = end_date.toString(Qt.ISODate)
        self._last_feature_ids = [feature.id() for feature in day_to_features.get(end_key, [])]
        self.select_filtered_features(notify=False)

        if snapshot_paths:
            self.results_label.setText(
                "{0} Saved {1} daily map PNG file(s).".format(
                    self.results_label.text(), len(snapshot_paths)
                )
            )

        if not single_mode and len(snapshot_paths) >= 2:
            movie_path = self.create_movie_from_last_run(notify=False)
            if movie_path:
                self._show_message("Progress movie saved to: {0}".format(movie_path))

    def _populate_table(self, layer, features):
        headers = [field.name() for field in layer.fields()]
        display_count = min(len(features), self.MAX_ROWS)

        self.results_table.clear()
        self.results_table.setColumnCount(len(headers))
        self.results_table.setHorizontalHeaderLabels(headers)
        self.results_table.setRowCount(display_count)

        for row_idx, feature in enumerate(features[:display_count]):
            for col_idx, field_name in enumerate(headers):
                value = feature[field_name]
                text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.results_table.setItem(row_idx, col_idx, item)

        self.results_table.resizeColumnsToContents()

        if len(features) > self.MAX_ROWS:
            self.results_label.setText(
                "Matched {0} features (showing first {1}).".format(
                    len(features), self.MAX_ROWS
                )
            )
        else:
            self.results_label.setText("Matched {0} features.".format(len(features)))

    def select_filtered_features(self, notify=True):
        if not self._last_layer:
            if notify:
                self._show_message("No filtered layer is available.", warning=True)
            return

        self._last_layer.removeSelection()
        self._last_layer.selectByIds(self._last_feature_ids)
        self.iface.setActiveLayer(self._last_layer)
        self.iface.mapCanvas().refresh()

        if notify:
            if self._last_feature_ids:
                self._show_message(
                    "Selected {0} feature(s) in layer '{1}'.".format(
                        len(self._last_feature_ids), self._last_layer.name()
                    )
                )
            else:
                self._show_message(
                    "No matched features. Selection cleared in layer '{0}'.".format(
                        self._last_layer.name()
                    ),
                    warning=True,
                )

    def choose_output_directory(self):
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for map snapshots",
            self.output_dir_edit.text().strip() or os.path.expanduser("~"),
        )
        if not selected_dir:
            return

        self.output_dir_edit.setText(selected_dir)
        self.settings.setValue(self.SETTINGS_KEY_OUTPUT_DIR, selected_dir)

    def choose_selection_color(self):
        selected_color = QColorDialog.getColor(
            self._selection_color,
            self,
            "Choose filtered data color",
        )
        if not selected_color.isValid():
            return

        self._selection_color = selected_color
        self._update_color_button()
        self.settings.setValue(
            self.SETTINGS_KEY_SELECTION_COLOR,
            self._selection_color.name(),
        )
        self._apply_selection_color()

    def _update_color_button(self):
        self.color_button.setText(self._selection_color.name())
        self.color_button.setStyleSheet(
            "background-color: {0}; color: white; font-weight: 600;".format(
                self._selection_color.name()
            )
        )

    def _apply_selection_color(self):
        self.iface.mapCanvas().setSelectionColor(self._selection_color)

    def _resolve_output_directory(self):
        output_dir = self.output_dir_edit.text().strip()
        if output_dir and os.path.isdir(output_dir):
            self.settings.setValue(self.SETTINGS_KEY_OUTPUT_DIR, output_dir)
            return output_dir

        self.choose_output_directory()
        output_dir = self.output_dir_edit.text().strip()
        if output_dir and os.path.isdir(output_dir):
            self.settings.setValue(self.SETTINGS_KEY_OUTPUT_DIR, output_dir)
            return output_dir

        self._show_message("Map export skipped: choose a valid output folder.", warning=True)
        return None

    def _group_features_by_day(self, parsed_records, start_date, end_date):
        day_to_features = {}
        for feature, parsed_date in parsed_records:
            if start_date <= parsed_date <= end_date:
                key = parsed_date.toString(Qt.ISODate)
                day_to_features.setdefault(key, []).append(feature)
        return day_to_features

    def _run_single_date_cycle_for_range(
        self,
        layer,
        day_to_features,
        start_date,
        end_date,
        update_table_each_step=False,
    ):
        output_dir = self._resolve_output_directory()
        if not output_dir:
            return []

        saved_paths = []
        current = QDate(start_date)

        while current <= end_date:
            key = current.toString(Qt.ISODate)
            daily_features = day_to_features.get(key, [])
            daily_ids = [feature.id() for feature in daily_features]

            snapshot_path = self._apply_single_date_filter_and_save_png(
                layer=layer,
                target_date=current,
                feature_ids=daily_ids,
                output_dir=output_dir,
                features_for_table=daily_features if update_table_each_step else None,
            )
            if snapshot_path:
                saved_paths.append(snapshot_path)

            current = current.addDays(1)

        end_key = end_date.toString(Qt.ISODate)
        return saved_paths

    def _apply_single_date_filter_and_save_png(
        self,
        layer,
        target_date,
        feature_ids,
        output_dir,
        features_for_table=None,
    ):
        # This is the same routine for each day: clear, apply new day filter, render, save.
        layer.removeSelection()
        self._apply_selection_color()
        self._set_canvas_date_overlay(target_date)

        layer.selectByIds(feature_ids)
        self.iface.setActiveLayer(layer)
        layer.triggerRepaint()
        self._refresh_canvas_and_wait()

        self._last_feature_ids = list(feature_ids)
        if features_for_table is not None:
            self._populate_table(layer, features_for_table)

        current_date = target_date
        day_token = current_date.toString("yyyyMMdd")
        file_name = "daily_production_{0}.png".format(day_token)
        output_path = os.path.join(output_dir, file_name)

        canvas = self.iface.mapCanvas()
        pixmap = canvas.grab()
        if not pixmap.save(output_path, "PNG"):
            self._show_message("Failed to save map snapshot for {0}.".format(day_token), warning=True)
            return None
        return output_path

    def _set_canvas_date_overlay(self, target_date):
        self._ensure_canvas_date_label()
        self._canvas_date_label.setText("Date: {0}".format(target_date.toString("yyyy-MM-dd")))
        self._canvas_date_label.adjustSize()
        self._canvas_date_label.move(14, 14)
        self._canvas_date_label.show()
        self._canvas_date_label.raise_()
        QApplication.processEvents()

    def _ensure_canvas_date_label(self):
        if self._canvas_date_label is not None:
            return

        canvas = self.iface.mapCanvas()
        self._canvas_date_label = QLabel(canvas)
        self._canvas_date_label.setStyleSheet(
            "background-color: rgba(255, 255, 255, 220);"
            "border: 1px solid #222;"
            "border-radius: 4px;"
            "padding: 6px 10px;"
            "font-size: 11pt;"
            "font-weight: 600;"
            "color: #111;"
        )
        self._canvas_date_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._canvas_date_label.hide()

    def _hide_canvas_date_overlay(self):
        if self._canvas_date_label is not None:
            self._canvas_date_label.hide()

    def _refresh_canvas_and_wait(self, timeout_ms=5000):
        canvas = self.iface.mapCanvas()
        canvas.refresh()

        if hasattr(canvas, "waitWhileRendering"):
            canvas.waitWhileRendering()
            QApplication.processEvents()
            return

        loop = QEventLoop()
        timer = QTimer(self)
        timer.setSingleShot(True)

        def _done():
            loop.quit()

        timer.timeout.connect(_done)
        canvas.mapCanvasRefreshed.connect(_done)
        timer.start(timeout_ms)
        loop.exec_()

        try:
            canvas.mapCanvasRefreshed.disconnect(_done)
        except Exception:
            pass

        QApplication.processEvents()

    def create_movie_from_last_run(self, notify=True):
        if len(self._last_snapshot_paths) < 2:
            if notify:
                self._show_message("Need at least two PNG maps to build a movie.", warning=True)
            return None

        try:
            import cv2
        except ImportError:
            if notify:
                self._show_message(
                    "OpenCV (cv2) is not available in this QGIS Python environment.",
                    warning=True,
                )
            return None

        output_dir = self._resolve_output_directory()
        if not output_dir:
            return None

        image_paths = list(self._last_snapshot_paths)
        first_frame = cv2.imread(image_paths[0])
        if first_frame is None:
            if notify:
                self._show_message("Cannot read PNG frames for movie generation.", warning=True)
            return None

        height, width = first_frame.shape[:2]
        fps = float(max(1, self.movie_fps_spin.value()))
        layer_name = self._sanitize_name(self._last_run_layer_name or "layer")
        start_text = (
            self._last_run_start.toString("yyyyMMdd")
            if isinstance(self._last_run_start, QDate)
            else "start"
        )
        end_text = (
            self._last_run_end.toString("yyyyMMdd")
            if isinstance(self._last_run_end, QDate)
            else "end"
        )
        codec_candidates = [
            ("mp4v", "mp4"),
            ("avc1", "mp4"),
            ("MJPG", "avi"),
            ("XVID", "avi"),
        ]

        writer = None
        movie_path = None
        for codec, extension in codec_candidates:
            trial_name = "production_progress_{0}_to_{1}.{2}".format(
                start_text, end_text, extension
            )
            trial_path = os.path.join(output_dir, trial_name)
            trial_writer = cv2.VideoWriter(
                trial_path,
                cv2.VideoWriter_fourcc(*codec),
                fps,
                (width, height),
            )
            if trial_writer.isOpened():
                writer = trial_writer
                movie_path = trial_path
                break
            trial_writer.release()

        if writer is None or movie_path is None:
            if notify:
                self._show_message(
                    "Failed to initialize movie writer with available codecs.",
                    warning=True,
                )
            return None

        written_frames = 0
        for image_path in image_paths:
            frame = cv2.imread(image_path)
            if frame is None:
                continue
            if frame.shape[0] != height or frame.shape[1] != width:
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
            written_frames += 1

        writer.release()

        if written_frames < 2:
            if os.path.exists(movie_path):
                os.remove(movie_path)
            if notify:
                self._show_message("Movie creation failed: not enough valid frames.", warning=True)
            return None

        if notify:
            self._show_message("Progress movie saved to: {0}".format(movie_path))
        return movie_path

    def clear_results(self):
        self._clear_previous_filters()
        self._hide_canvas_date_overlay()

        self._last_layer = None
        self._last_feature_ids = []
        self._last_snapshot_paths = []
        self._last_run_layer_name = ""
        self._last_run_start = None
        self._last_run_end = None
        self.results_table.clear()
        self.results_table.setRowCount(0)
        self.results_table.setColumnCount(0)
        self.results_label.setText("No filter applied.")
        self.select_button.setEnabled(False)
        self.create_movie_button.setEnabled(False)

    def _store_movie_fps(self, *_args):
        self.settings.setValue(self.SETTINGS_KEY_MOVIE_FPS, self.movie_fps_spin.value())

    @staticmethod
    def _sanitize_name(text):
        sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
        return sanitized.strip("_") or "layer"

    @classmethod
    def _to_qdate(cls, value):
        if value is None:
            return None

        if isinstance(value, QDate):
            return value if value.isValid() else None

        if isinstance(value, QDateTime):
            date_value = value.date()
            return date_value if date_value.isValid() else None

        if isinstance(value, datetime):
            return QDate(value.year, value.month, value.day)

        if isinstance(value, date):
            return QDate(value.year, value.month, value.day)

        text = str(value).strip()
        if not text:
            return None

        as_qdate = QDate.fromString(text, Qt.ISODate)
        if as_qdate.isValid():
            return as_qdate

        as_qdatetime = QDateTime.fromString(text, Qt.ISODate)
        if as_qdatetime.isValid():
            return as_qdatetime.date()

        for pattern in cls.DATE_PATTERNS:
            parsed_date = QDate.fromString(text, pattern)
            if parsed_date.isValid():
                return parsed_date

            parsed_datetime = QDateTime.fromString(text, pattern)
            if parsed_datetime.isValid():
                return parsed_datetime.date()

        return None

    def closeEvent(self, event):
        self._hide_canvas_date_overlay()
        self.settings.setValue(
            self.SETTINGS_KEY_OUTPUT_DIR,
            self.output_dir_edit.text().strip(),
        )
        self.settings.setValue(
            self.SETTINGS_KEY_SELECTION_COLOR,
            self._selection_color.name(),
        )
        self.settings.setValue(
            self.SETTINGS_KEY_MOVIE_FPS,
            self.movie_fps_spin.value(),
        )
        super().closeEvent(event)

    def _clear_previous_filters(self):
        if self._last_layer is not None:
            self._last_layer.removeSelection()

        current_layer = self._current_layer()
        if current_layer is not None and current_layer is not self._last_layer:
            current_layer.removeSelection()

        self.iface.mapCanvas().refresh()

    def _show_message(self, text, warning=False):
        bar = self.iface.messageBar()
        if warning:
            bar.pushWarning("Layer Date Filter", text)
        else:
            bar.pushSuccess("Layer Date Filter", text)
