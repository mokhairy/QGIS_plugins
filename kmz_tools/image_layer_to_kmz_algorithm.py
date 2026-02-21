"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterString,
                       QgsProcessingParameterBoolean,
                       QgsWkbTypes,
                       QgsCoordinateTransform,
                       QgsCoordinateReferenceSystem,
                       QgsProject)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtCore import QDateTime
import os
import shutil
import zipfile
import tempfile
from xml.sax.saxutils import escape

class LayerToKmzWithPhotosAlgorithm(QgsProcessingAlgorithm):
    
    INPUT_LAYER = 'INPUT_LAYER'
    PHOTO_FIELD = 'PHOTO_FIELD'
    OUTPUT_KMZ = 'OUTPUT_KMZ'
    LAYER_NAME = 'LAYER_NAME'
    INCLUDE_ATTRIBUTES = 'INCLUDE_ATTRIBUTES'
    
    def tr(self, string):
        """
        Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate('Processing', string)
    
    def createInstance(self):
        return LayerToKmzWithPhotosAlgorithm()
    
    def name(self):
        return 'layer_to_kmz_with_photos'
    
    def displayName(self):
        return self.tr('Image Layer to KMZ with Photos')
    
    # def group(self):
    #     return self.tr('KMZ Tools')
    
    # def groupId(self):
    #     return 'kmz_tools'
    
    def shortHelpString(self):
        return self.tr("Converts a vector layer with photo attributes to a KMZ file with embedded images. "
                      "The layer must have a field containing file paths to images.")
    
    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr('Input layer'),
                [QgsProcessing.TypeVectorAnyGeometry]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.PHOTO_FIELD,
                self.tr('Photo field'),
                parentLayerParameterName=self.INPUT_LAYER,
                type=QgsProcessingParameterField.String
            )
        )
        
        self.addParameter(
            QgsProcessingParameterString(
                self.LAYER_NAME,
                self.tr('Layer name'),
                defaultValue='Layer with Photos'
            )
        )
        
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_ATTRIBUTES,
                self.tr('Include all attributes in description'),
                defaultValue=True
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_KMZ,
                self.tr('Output KMZ file'),
                fileFilter='KMZ files (*.kmz)'
            )
        )
    
    def get_filename_from_path(self, file_path):
        """Extract filename from file path"""
        if not file_path:
            return None
        # Handle both forward and backward slashes
        return os.path.basename(file_path.replace('\\', '/'))
    
    def geometry_to_kml_coordinates(self, geometry, transform=None):
        """Convert geometry to KML coordinates string"""
        if transform:
            geometry.transform(transform)
        
        geom_type = geometry.wkbType()
        
        if geom_type in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]:
            point = geometry.asPoint()
            return f"{point.x()},{point.y()},0"
        elif geom_type in [QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D]:
            coords = []
            for point in geometry.asPolyline():
                coords.append(f"{point.x()},{point.y()},0")
            return " ".join(coords)
        elif geom_type in [QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D]:
            polygon = geometry.asPolygon()
            if polygon:
                coords = []
                for point in polygon[0]:  # Outer ring
                    coords.append(f"{point.x()},{point.y()},0")
                return " ".join(coords)
        
        return ""
    
    def geometry_to_kml_element(self, geometry, transform=None):
        """Convert geometry to appropriate KML element"""
        if transform:
            geometry.transform(transform)
        
        geom_type = geometry.wkbType()
        coordinates = self.geometry_to_kml_coordinates(geometry)
        
        if geom_type in [QgsWkbTypes.Point, QgsWkbTypes.PointZ, QgsWkbTypes.Point25D]:
            return f"""      <Point>
        <coordinates>{coordinates}</coordinates>
      </Point>"""
        elif geom_type in [QgsWkbTypes.LineString, QgsWkbTypes.LineStringZ, QgsWkbTypes.LineString25D]:
            return f"""      <LineString>
        <coordinates>{coordinates}</coordinates>
      </LineString>"""
        elif geom_type in [QgsWkbTypes.Polygon, QgsWkbTypes.PolygonZ, QgsWkbTypes.Polygon25D]:
            return f"""      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{coordinates}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>"""
        
        return ""
    
    def create_feature_description(self, feature, photo_field, filename, include_attributes):
        description_parts = []
        
        # Add attributes table if requested
        if include_attributes:
            description_parts.append("<table border='1' style='border-collapse: collapse;'>")
            description_parts.append("<tr><th>Attribute</th><th>Value</th></tr>")
            
            for field_name in feature.fields().names():
                if field_name != photo_field:  # Don't include the full photo path
                    value = feature[field_name]
                    if isinstance(value, QDateTime):
                        value = value.toString("yyyy-MM-dd HH:mm:ss")
                    if value is not None:
                        description_parts.append(f"<tr><td>{escape(str(field_name))}</td><td>{escape(str(value))}</td></tr>")
            
            description_parts.append("</table>")
            description_parts.append("<br/>")
        
        # Add photo if available
        if filename:
            description_parts.append(f'<img src="Photos/{filename}" style="max-width:720px;" />')
        
        return "".join(description_parts)
    
    def create_kml_content(self, layer, photo_field, layer_name, include_attributes, transform, copied_photos):
        kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{escape(layer_name)}</name>
    <description>Layer exported with photos</description>
"""
        
        # Process features
        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if geometry.isEmpty():
                continue
            
            # Get photo path and filename
            photo_path = feature[photo_field] if photo_field in feature.fields().names() else None
            filename = None
            
            if photo_path and str(photo_path).strip():
                filename = self.get_filename_from_path(str(photo_path))
                if filename and filename in copied_photos:
                    # Photo was successfully copied
                    pass
                else:
                    # Photo wasn't copied, don't reference it
                    filename = None
            
            # Create feature name (use first non-photo field or feature ID)
            feature_name = f"Feature {feature.id()}"
            for field_name in feature.fields().names():
                if field_name != photo_field and feature[field_name] is not None:
                    feature_name = str(feature[field_name])
                    break
            
            # Create description
            description = self.create_feature_description(feature, photo_field, filename, include_attributes)
            
            # Get geometry element
            geometry_element = self.geometry_to_kml_element(geometry, transform)
            
            kml_content += f"""    <Placemark>
      <name>{escape(feature_name)}</name>
      <description><![CDATA[{description}]]></description>
{geometry_element}
    </Placemark>
"""
        
        kml_content += """  </Document>
</kml>"""
        return kml_content
    
    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        photo_field = self.parameterAsString(parameters, self.PHOTO_FIELD, context)
        output_kmz = self.parameterAsFileOutput(parameters, self.OUTPUT_KMZ, context)
        layer_name = self.parameterAsString(parameters, self.LAYER_NAME, context)
        include_attributes = self.parameterAsBool(parameters, self.INCLUDE_ATTRIBUTES, context)
        
        if not input_layer:
            raise QgsProcessingException('Invalid input layer')
        
        if not photo_field:
            raise QgsProcessingException('Photo field must be specified')
        
        # Check if photo field exists
        if photo_field not in input_layer.fields().names():
            raise QgsProcessingException(f'Photo field "{photo_field}" not found in layer')
        
        # Create coordinate transform to WGS84 (required for KML)
        source_crs = input_layer.crs()
        dest_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = None
        if source_crs != dest_crs:
            transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        
        # Create temporary directory for organizing files
        temp_dir = tempfile.mkdtemp()
        photos_dir = os.path.join(temp_dir, 'Photos')
        os.makedirs(photos_dir, exist_ok=True)
        
        copied_photos = set()
        total_features = input_layer.featureCount()
        processed_count = 0
        
        try:
            # First pass: copy photos
            feedback.pushInfo('Copying photos...')
            for feature in input_layer.getFeatures():
                if feedback.isCanceled():
                    break
                
                photo_path = feature[photo_field] if photo_field in feature.fields().names() else None
                
                if photo_path and str(photo_path).strip():
                    photo_path = str(photo_path).strip()
                    filename = self.get_filename_from_path(photo_path)
                    
                    if filename and os.path.exists(photo_path):
                        try:
                            dest_path = os.path.join(photos_dir, filename)
                            shutil.copy2(photo_path, dest_path)
                            copied_photos.add(filename)
                            feedback.pushInfo(f'Copied: {filename}')
                        except Exception as e:
                            feedback.pushInfo(f'Failed to copy {photo_path}: {str(e)}')
                    else:
                        if filename:
                            feedback.pushInfo(f'Photo not found: {photo_path}')
                
                processed_count += 1
                feedback.setProgress(int(processed_count * 50 / total_features))  # First 50% for copying
            
            feedback.pushInfo(f'Successfully copied {len(copied_photos)} photos')
            
            # Create KML content
            feedback.pushInfo('Creating KML content...')
            kml_content = self.create_kml_content(input_layer, photo_field, layer_name, 
                                                include_attributes, transform, copied_photos)
            
            # Write KML file to temp directory
            kml_path = os.path.join(temp_dir, 'doc.kml')
            with open(kml_path, 'w', encoding='utf-8') as kml_file:
                kml_file.write(kml_content)
            
            # Create KMZ file
            feedback.pushInfo('Creating KMZ file...')
            with zipfile.ZipFile(output_kmz, 'w', zipfile.ZIP_DEFLATED) as kmz:
                # Add KML file
                kmz.write(kml_path, 'doc.kml')
                
                # Add all photos
                for filename in copied_photos:
                    photo_path = os.path.join(photos_dir, filename)
                    if os.path.exists(photo_path):
                        kmz.write(photo_path, f'Photos/{filename}')
            
            feedback.setProgress(100)
            
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        feedback.pushInfo(f'Successfully processed {input_layer.featureCount()} features')
        feedback.pushInfo(f'Included {len(copied_photos)} photos in KMZ')
        feedback.pushInfo(f'KMZ file created: {output_kmz}')
        
        return {self.OUTPUT_KMZ: output_kmz}