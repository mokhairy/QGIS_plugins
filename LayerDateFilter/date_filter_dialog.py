from datetime import date, datetime

from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject, QgsVectorLayer


class DateFilterDialog(QDialog):
    MAX_ROWS = 500
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
        self._last_layer = None
        self._last_feature_ids = []

        self.setWindowTitle("Layer Date Filter")
        self.resize(1000, 620)
        self._build_ui()
        self._connect_signals()
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

        buttons_layout = QHBoxLayout()
        layout.addLayout(buttons_layout)
        self.apply_button = QPushButton("Apply Filter")
        self.select_button = QPushButton("Select In Layer")
        self.clear_button = QPushButton("Clear Results")
        self.close_button = QPushButton("Close")
        buttons_layout.addWidget(self.apply_button)
        buttons_layout.addWidget(self.select_button)
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

    def _connect_signals(self):
        self.refresh_button.clicked.connect(self.refresh_layers)
        self.layer_combo.currentIndexChanged.connect(self._populate_date_fields)
        self.filter_mode_combo.currentIndexChanged.connect(self.mode_stack.setCurrentIndex)
        self.apply_button.clicked.connect(self.apply_filter)
        self.select_button.clicked.connect(self.select_filtered_features)
        self.clear_button.clicked.connect(self.clear_results)
        self.close_button.clicked.connect(self.close)

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

        single_mode = self.filter_mode_combo.currentIndex() == 0
        if single_mode:
            target_date = self.single_date_edit.date()
            start_date = target_date
            end_date = target_date
        else:
            start_date = self.start_date_edit.date()
            end_date = self.end_date_edit.date()
            if start_date > end_date:
                self._show_message("Start date must be before or equal to end date.", warning=True)
                return

        matched_features = []
        matched_ids = []
        for feature in layer.getFeatures():
            parsed_date = self._to_qdate(feature[field_name])
            if not parsed_date:
                continue
            if start_date <= parsed_date <= end_date:
                matched_features.append(feature)
                matched_ids.append(feature.id())

        self._last_layer = layer
        self._last_feature_ids = matched_ids
        self._populate_table(layer, matched_features)
        self.select_button.setEnabled(bool(self._last_feature_ids))

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

    def select_filtered_features(self):
        if not self._last_layer or not self._last_feature_ids:
            self._show_message("No filtered features available to select.", warning=True)
            return

        self._last_layer.selectByIds(self._last_feature_ids)
        self.iface.setActiveLayer(self._last_layer)
        self.iface.mapCanvas().refresh()
        self._show_message(
            "Selected {0} feature(s) in layer '{1}'.".format(
                len(self._last_feature_ids), self._last_layer.name()
            )
        )

    def clear_results(self):
        self._last_layer = None
        self._last_feature_ids = []
        self.results_table.clear()
        self.results_table.setRowCount(0)
        self.results_table.setColumnCount(0)
        self.results_label.setText("No filter applied.")
        self.select_button.setEnabled(False)

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

    def _show_message(self, text, warning=False):
        bar = self.iface.messageBar()
        if warning:
            bar.pushWarning("Layer Date Filter", text)
        else:
            bar.pushSuccess("Layer Date Filter", text)
