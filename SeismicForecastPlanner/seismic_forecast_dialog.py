from datetime import date, datetime

from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
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
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)


class SeismicForecastDialog(QDialog):
    FORECAST_FIELD = "forecasted_production_date"
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

        self.setWindowTitle("Seismic Forecast Planner")
        self.resize(1020, 680)
        self._build_ui()
        self._connect_signals()
        self.refresh_layers()

    def _build_ui(self):
        root = QVBoxLayout(self)

        controls = QGridLayout()
        root.addLayout(controls)

        controls.addWidget(QLabel("Point layer"), 0, 0)
        self.layer_combo = QComboBox()
        controls.addWidget(self.layer_combo, 0, 1)
        self.refresh_button = QPushButton("Refresh Layers")
        controls.addWidget(self.refresh_button, 0, 2)

        controls.addWidget(QLabel("Date field"), 1, 0)
        self.date_field_combo = QComboBox()
        controls.addWidget(self.date_field_combo, 1, 1, 1, 2)

        controls.addWidget(QLabel("Filter mode"), 2, 0)
        self.filter_mode_combo = QComboBox()
        self.filter_mode_combo.addItems(["Single date", "Date range"])
        controls.addWidget(self.filter_mode_combo, 2, 1, 1, 2)

        self.mode_stack = QStackedWidget()
        controls.addWidget(self.mode_stack, 3, 0, 1, 3)

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

        filter_buttons = QHBoxLayout()
        root.addLayout(filter_buttons)
        self.apply_filter_button = QPushButton("Display Selected Date(s)")
        self.clear_filter_button = QPushButton("Clear Selection")
        filter_buttons.addWidget(self.apply_filter_button)
        filter_buttons.addWidget(self.clear_filter_button)
        filter_buttons.addStretch(1)

        self.results_label = QLabel("No date filter applied.")
        root.addWidget(self.results_label)

        self.results_table = QTableWidget()
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.verticalHeader().setVisible(False)
        root.addWidget(self.results_table)

        forecast_controls = QGridLayout()
        root.addLayout(forecast_controls)

        forecast_controls.addWidget(QLabel("Forecast start date"), 0, 0)
        self.forecast_start_edit = QDateEdit(QDate.currentDate())
        self.forecast_start_edit.setCalendarPopup(True)
        self.forecast_start_edit.setDisplayFormat("yyyy-MM-dd")
        forecast_controls.addWidget(self.forecast_start_edit, 0, 1)

        forecast_controls.addWidget(QLabel("Average daily production"), 1, 0)
        self.daily_prod_spin = QDoubleSpinBox()
        self.daily_prod_spin.setDecimals(2)
        self.daily_prod_spin.setRange(0.01, 1000000.00)
        self.daily_prod_spin.setValue(150.0)
        self.daily_prod_spin.setSuffix(" points/day")
        forecast_controls.addWidget(self.daily_prod_spin, 1, 1)

        forecast_controls.addWidget(
            QLabel("Forecast sequence uses SPS table order (feature ID ascending)."),
            2,
            0,
            1,
            2,
        )

        self.create_forecast_button = QPushButton("Create Forecast Layer")
        forecast_controls.addWidget(self.create_forecast_button, 3, 0, 1, 2)

    def _connect_signals(self):
        self.refresh_button.clicked.connect(self.refresh_layers)
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        self.filter_mode_combo.currentIndexChanged.connect(self.mode_stack.setCurrentIndex)
        self.apply_filter_button.clicked.connect(self.apply_date_filter)
        self.clear_filter_button.clicked.connect(self.clear_filter)
        self.create_forecast_button.clicked.connect(self.create_forecast_layer)

        project = QgsProject.instance()
        project.layersAdded.connect(self.refresh_layers)
        project.layersRemoved.connect(self.refresh_layers)
        project.cleared.connect(self.refresh_layers)

    def refresh_layers(self, *_args):
        current_id = self.layer_combo.currentData()
        layers = sorted(
            self._point_layers(),
            key=lambda lyr: lyr.name().lower(),
        )

        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for layer in layers:
            self.layer_combo.addItem(layer.name(), layer.id())
        self.layer_combo.blockSignals(False)

        if not layers:
            self.date_field_combo.clear()
            self.date_field_combo.setEnabled(False)
            self.results_label.setText("No point layers found in the current project.")
            return

        if current_id:
            idx = self.layer_combo.findData(current_id)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)

        self._on_layer_changed()

    def _point_layers(self):
        return [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
            and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PointGeometry
        ]

    def _current_layer(self):
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        if (
            isinstance(layer, QgsVectorLayer)
            and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PointGeometry
        ):
            return layer
        return None

    def _on_layer_changed(self, *_args):
        layer = self._current_layer()
        self.date_field_combo.clear()

        if layer is None:
            self.date_field_combo.setEnabled(False)
            return

        date_fields = self._detect_date_fields(layer)
        for name in date_fields:
            self.date_field_combo.addItem(name)

        self.date_field_combo.setEnabled(bool(date_fields))
        if not date_fields:
            self._show_message(
                "No date-like fields found in selected layer.",
                warning=True,
            )

    def _detect_date_fields(self, layer):
        date_fields = []
        string_fields = []

        for field in layer.fields():
            field_type = field.type()
            if field_type in (QVariant.Date, QVariant.DateTime):
                date_fields.append(field.name())
            elif field_type in (QVariant.String, QVariant.Char):
                string_fields.append(field.name())
            elif "date" in field.name().lower() and field.name() not in date_fields:
                date_fields.append(field.name())

        samples = {name: [] for name in string_fields}
        for i, feature in enumerate(layer.getFeatures()):
            if i >= 40:
                break
            for name in string_fields:
                value = feature[name]
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    samples[name].append(text)

        for name in string_fields:
            values = samples.get(name, [])
            if not values:
                continue
            valid_count = sum(1 for value in values if self._to_qdate(value))
            if valid_count / len(values) >= 0.6 and name not in date_fields:
                date_fields.append(name)

        return date_fields

    def apply_date_filter(self):
        layer = self._current_layer()
        if layer is None:
            self._show_message("Select a point layer first.", warning=True)
            return

        field_name = self.date_field_combo.currentText()
        if not field_name:
            self._show_message("Select a date field first.", warning=True)
            return

        if self.filter_mode_combo.currentIndex() == 0:
            start_date = self.single_date_edit.date()
            end_date = start_date
        else:
            start_date = self.start_date_edit.date()
            end_date = self.end_date_edit.date()
            if start_date > end_date:
                self._show_message(
                    "Start date must be before or equal to end date.",
                    warning=True,
                )
                return

        matched_features = []
        matched_ids = []
        for feature in layer.getFeatures():
            parsed_date = self._to_qdate(feature[field_name])
            if parsed_date and start_date <= parsed_date <= end_date:
                matched_features.append(feature)
                matched_ids.append(feature.id())

        layer.removeSelection()
        layer.selectByIds(matched_ids)
        self.iface.setActiveLayer(layer)
        self.iface.mapCanvas().refresh()
        self._populate_table(layer, matched_features)

        self.results_label.setText(
            "Matched {0} source point(s) in selected date window.".format(
                len(matched_features)
            )
        )

    def clear_filter(self):
        layer = self._current_layer()
        if layer is not None:
            layer.removeSelection()
            self.iface.mapCanvas().refresh()

        self.results_table.clear()
        self.results_table.setRowCount(0)
        self.results_table.setColumnCount(0)
        self.results_label.setText("No date filter applied.")

    def _populate_table(self, layer, features):
        headers = [field.name() for field in layer.fields()]
        row_count = min(len(features), self.MAX_ROWS)

        self.results_table.clear()
        self.results_table.setColumnCount(len(headers))
        self.results_table.setHorizontalHeaderLabels(headers)
        self.results_table.setRowCount(row_count)

        for row_idx, feature in enumerate(features[:row_count]):
            for col_idx, field_name in enumerate(headers):
                value = feature[field_name]
                text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.results_table.setItem(row_idx, col_idx, item)

        self.results_table.resizeColumnsToContents()
        if len(features) > self.MAX_ROWS:
            self.results_label.setText(
                "{0} Showing first {1} rows.".format(
                    self.results_label.text(),
                    self.MAX_ROWS,
                )
            )

    def create_forecast_layer(self):
        layer = self._current_layer()
        if layer is None:
            self._show_message("Select a point layer first.", warning=True)
            return

        daily_production = self.daily_prod_spin.value()
        if daily_production <= 0:
            self._show_message(
                "Average daily production must be greater than zero.",
                warning=True,
            )
            return

        input_features = sorted(
            list(layer.getFeatures()),
            key=lambda feat: feat.id(),
        )
        if not input_features:
            self._show_message("Selected layer has no features.", warning=True)
            return

        crs_authid = layer.crs().authid() or "EPSG:4326"
        geom_type = QgsWkbTypes.displayString(layer.wkbType()) or "Point"
        out_name = "{0}_forecast".format(layer.name())
        out_layer = QgsVectorLayer(
            "{0}?crs={1}".format(geom_type, crs_authid),
            out_name,
            "memory",
        )
        if not out_layer.isValid():
            self._show_message("Failed to create output forecast layer.", warning=True)
            return

        provider = out_layer.dataProvider()
        out_fields = [field for field in layer.fields()]
        forecast_field_name = self._unique_forecast_field_name(layer)
        out_fields.append(QgsField(forecast_field_name, QVariant.Date))
        provider.addAttributes(out_fields)
        out_layer.updateFields()

        start_date = self.forecast_start_edit.date()
        out_features = []
        for idx, feature in enumerate(input_features):
            day_index = int(idx / daily_production)
            forecast_date = start_date.addDays(day_index)

            out_feature = QgsFeature(out_layer.fields())
            out_feature.setGeometry(feature.geometry())
            attrs = list(feature.attributes())
            attrs.append(forecast_date)
            out_feature.setAttributes(attrs)
            out_features.append(out_feature)

        provider.addFeatures(out_features)
        out_layer.updateExtents()
        QgsProject.instance().addMapLayer(out_layer)

        self._show_message(
            "Created forecast layer '{0}' with field '{1}'.".format(
                out_name,
                forecast_field_name,
            )
        )

    def _unique_forecast_field_name(self, layer):
        existing = {field.name().lower() for field in layer.fields()}
        if self.FORECAST_FIELD.lower() not in existing:
            return self.FORECAST_FIELD

        suffix = 1
        while True:
            candidate = "{0}_{1}".format(self.FORECAST_FIELD, suffix)
            if candidate.lower() not in existing:
                return candidate
            suffix += 1

    @classmethod
    def _to_qdate(cls, value):
        if value is None:
            return None

        if isinstance(value, QDate):
            return value if value.isValid() else None

        if isinstance(value, QDateTime):
            out_date = value.date()
            return out_date if out_date.isValid() else None

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
            parsed = QDate.fromString(text, pattern)
            if parsed.isValid():
                return parsed

            parsed_dt = QDateTime.fromString(text, pattern)
            if parsed_dt.isValid():
                return parsed_dt.date()

        return None

    def _show_message(self, text, warning=False):
        bar = self.iface.messageBar()
        if warning:
            bar.pushWarning("Seismic Forecast Planner", text)
        else:
            bar.pushSuccess("Seismic Forecast Planner", text)
