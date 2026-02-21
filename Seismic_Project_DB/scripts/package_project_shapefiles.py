"""
Package current-project shapefiles into one GeoPackage, including styles.

Run from the QGIS Python console:
    from Seismic_Project_DB.package_project_shapefiles import package_current_project_shapefiles
    gpkg_path, layer_names, _ = package_current_project_shapefiles(
        "/absolute/path/project_layers.gpkg",
        overwrite=True,
    )
    print(gpkg_path)
    print(layer_names)
"""

import os
import sqlite3
import tempfile
from pathlib import Path

from qgis.core import (
    QgsMapLayerType,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorFileWriter,
    QgsVectorLayer,
)


def _get_layer_source_path(layer):
    """Return the underlying data source path for a layer."""
    source = layer.source()
    if layer.providerType() == "ogr":
        decoded = QgsProviderRegistry.instance().decodeUri("ogr", source)
        if isinstance(decoded, dict) and decoded.get("path"):
            return decoded["path"]
    return source.split("|", 1)[0]


def _is_shapefile_layer(layer):
    """True if layer is a vector layer sourced from a .shp file."""
    if layer.type() != QgsMapLayerType.VectorLayer:
        return False
    source_path = _get_layer_source_path(layer)
    return Path(source_path).suffix.lower() == ".shp"


def _unique_layer_name(name, used_names):
    """Generate a unique layer name for the output GeoPackage."""
    base_name = (name or "layer").strip() or "layer"
    candidate = base_name
    index = 2
    while candidate in used_names:
        candidate = f"{base_name}_{index}"
        index += 1
    used_names.add(candidate)
    return candidate


def _save_style_to_gpkg(source_layer, gpkg_path, gpkg_layer_name):
    """Copy source style to the GeoPackage layer and persist it in layer_styles."""
    output_layer = QgsVectorLayer(
        f"{gpkg_path}|layername={gpkg_layer_name}", gpkg_layer_name, "ogr"
    )
    if not output_layer.isValid():
        raise RuntimeError("Could not open exported layer to save style.")

    tmp_qml = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".qml", delete=False) as tmp_file:
            tmp_qml = tmp_file.name

        _, saved_ok = source_layer.saveNamedStyle(tmp_qml)
        if not saved_ok:
            raise RuntimeError("Could not serialize source layer style.")

        _, loaded_ok = output_layer.loadNamedStyle(tmp_qml)
        if not loaded_ok:
            raise RuntimeError("Could not load style into exported GeoPackage layer.")

        # Empty string usually means success. Non-empty may contain an id or warning message.
        output_layer.saveStyleToDatabase(
            source_layer.name(),
            "Saved by Seismic Project DB plugin",
            True,
            "",
        )
    finally:
        if tmp_qml and os.path.exists(tmp_qml):
            os.remove(tmp_qml)


def _read_template_styles(template_gpkg_path):
    """Read default styles from template GeoPackage layer_styles table."""
    template_path = Path(template_gpkg_path).expanduser()
    if not template_path.exists():
        raise RuntimeError(f"Style template GeoPackage not found: {template_path}")

    with sqlite3.connect(str(template_path)) as conn:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='layer_styles' LIMIT 1"
        ).fetchone()
        if not has_table:
            raise RuntimeError("Template GeoPackage does not contain a layer_styles table.")

        rows = conn.execute(
            """
            SELECT f_table_name, styleQML, COALESCE(useAsDefault, 0) AS is_default, id
            FROM layer_styles
            WHERE styleQML IS NOT NULL AND styleQML <> ''
            ORDER BY is_default DESC, id DESC
            """
        ).fetchall()

    by_layer_name = {}
    for layer_name, style_qml, _, _ in rows:
        if layer_name and layer_name not in by_layer_name:
            by_layer_name[layer_name] = style_qml
    return by_layer_name


def _apply_template_styles_to_gpkg(target_gpkg_path, target_layer_names, template_gpkg_path):
    """Apply template styles to matching target GeoPackage layers and save as default."""
    style_map = _read_template_styles(template_gpkg_path)
    if not style_map:
        return 0, list(target_layer_names), []

    applied = 0
    missing = []
    errors = []

    for layer_name in target_layer_names:
        style_qml = style_map.get(layer_name)
        if not style_qml:
            missing.append(layer_name)
            continue

        output_layer = QgsVectorLayer(
            f"{target_gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr",
        )
        if not output_layer.isValid():
            errors.append(f"{layer_name}: could not open target layer for template style.")
            continue

        tmp_qml = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".qml", delete=False, mode="w", encoding="utf-8") as tmp_file:
                tmp_qml = tmp_file.name
                tmp_file.write(style_qml)

            _, loaded_ok = output_layer.loadNamedStyle(tmp_qml)
            if not loaded_ok:
                errors.append(f"{layer_name}: could not load template style QML.")
                continue

            output_layer.saveStyleToDatabase(
                layer_name,
                f"Default style from template {Path(template_gpkg_path).name}",
                True,
                "",
            )
            applied += 1
        except Exception as exc:
            errors.append(f"{layer_name}: {exc}")
        finally:
            if tmp_qml and os.path.exists(tmp_qml):
                os.remove(tmp_qml)

    return applied, missing, errors


def package_current_project_shapefiles(output_gpkg_path, overwrite=True, style_template_gpkg=None):
    """
    Export all shapefiles in the current QGIS project into one GeoPackage.

    Styles are saved into the GeoPackage (layer_styles table) when supported.
    Returns: (output_path, exported_layer_names, processing_result)
    """
    output_path = Path(output_gpkg_path).expanduser()
    if output_path.suffix.lower() != ".gpkg":
        output_path = output_path.with_suffix(".gpkg")
    output_path_str = str(output_path)

    if output_path.exists():
        if overwrite:
            output_path.unlink()
        else:
            raise RuntimeError(f"Output file already exists: {output_path_str}")

    project = QgsProject.instance()
    shapefile_layers = [
        layer for layer in project.mapLayers().values() if _is_shapefile_layer(layer)
    ]
    if not shapefile_layers:
        raise RuntimeError(
            "No shapefile layers found in the current project. "
            "Only layers with .shp sources are exported."
        )

    exported_names = []
    style_errors = []
    used_names = set()

    for i, layer in enumerate(shapefile_layers):
        gpkg_layer_name = _unique_layer_name(layer.name(), used_names)

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        options.layerName = gpkg_layer_name
        options.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteFile
            if i == 0
            else QgsVectorFileWriter.CreateOrOverwriteLayer
        )

        error_code, error_message, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            output_path_str,
            project.transformContext(),
            options,
        )
        if error_code != QgsVectorFileWriter.NoError:
            raise RuntimeError(
                f"Failed to write layer '{layer.name()}' to GeoPackage: {error_message}"
            )

        exported_names.append(gpkg_layer_name)

        try:
            _save_style_to_gpkg(layer, output_path_str, gpkg_layer_name)
        except Exception as exc:
            style_errors.append(f"{gpkg_layer_name}: {exc}")

    template_applied = 0
    template_missing = []
    template_errors = []
    if style_template_gpkg:
        template_applied, template_missing, template_errors = _apply_template_styles_to_gpkg(
            output_path_str,
            exported_names,
            style_template_gpkg,
        )

    result = {
        "style_errors": style_errors,
        "template_styles_applied": template_applied,
        "template_styles_missing": template_missing,
        "template_style_errors": template_errors,
    }
    return output_path_str, exported_names, result
