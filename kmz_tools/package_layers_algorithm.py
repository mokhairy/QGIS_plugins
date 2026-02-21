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
from qgis.core import (QgsProcessing, QgsProcessingException,
                       QgsProcessingAlgorithm, QgsProcessingParameterMultipleLayers,
                       QgsProcessingParameterCrs, QgsProcessingParameterBoolean,
                       QgsProcessingParameterFileDestination, QgsProject,
                       QgsVectorFileWriter, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsVectorLayer, QgsRasterLayer)
import processing
import os
import tempfile
import zipfile
import shutil
import re


class MultipleLayersToKmzAlgorithm(QgsProcessingAlgorithm):
    
    INPUT_LAYERS = 'INPUT_LAYERS'
    TARGET_CRS = 'TARGET_CRS'
    SAVE_STYLES = 'SAVE_STYLES'
    OUTPUT_KMZ = 'OUTPUT_KMZ'
    
    def tr(self, string):
        """Returns a translatable string with the self.tr() function."""
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        """Creates a new instance of the algorithm class."""
        return MultipleLayersToKmzAlgorithm()

    def name(self):
        """Returns the algorithm name."""
        return 'multilayerstokmz'

    def displayName(self):
        """Returns the translated algorithm name."""
        return self.tr('Package Layers to KMZ')

    # def group(self):
    #     return self.tr('KMZ Tools')

    # def groupId(self):
    #     return 'kmz_tools'

    def shortHelpString(self):
        """Returns a localised short helper string for the algorithm."""
        return self.tr("""
        This algorithm packages multiple QGIS layers into a single KMZ file.
        
        Features:
        • Select multiple vector and raster layers
        • Choose target CRS (defaults to project CRS)
        • Option to preserve layer styles in KMZ
        • Specify output location and filename
        
        The KMZ file will contain all selected layers with proper styling 
        if the option is enabled.
        """)

    def initAlgorithm(self, config=None):
        """Define the inputs and outputs of the algorithm."""
        
        # Input layers parameter
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.INPUT_LAYERS,
                self.tr('Input Layers'),
                optional=False
            )
        )
        
        # Target CRS parameter (optional, defaults to project CRS)
        self.addParameter(
            QgsProcessingParameterCrs(
                self.TARGET_CRS,
                self.tr('Target CRS (optional)'),
                defaultValue=None,
                optional=True
            )
        )
        
        # Save styles option
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SAVE_STYLES,
                self.tr('Save layer styles to KMZ'),
                defaultValue=False,
                optional=True
            )
        )
        
        # Output KMZ file
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_KMZ,
                self.tr('Output KMZ file'),
                fileFilter='KMZ files (*.kmz)'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Main processing function."""
        
        # Get parameters
        input_layers = self.parameterAsLayerList(parameters, self.INPUT_LAYERS, context)
        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)
        save_styles = self.parameterAsBool(parameters, self.SAVE_STYLES, context)
        output_kmz = self.parameterAsFileOutput(parameters, self.OUTPUT_KMZ, context)
        
        if not input_layers:
            raise QgsProcessingException(self.tr('No input layers selected'))
        
        # Use project CRS if no target CRS specified
        if not target_crs.isValid():
            target_crs = QgsProject.instance().crs()
            
        feedback.pushInfo(f'Target CRS: {target_crs.authid()}')
        feedback.pushInfo(f'Processing {len(input_layers)} layers')
        feedback.pushInfo(f'Save styles: {save_styles}')
        
        # Create temporary directory for processing
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Process each layer
            processed_files = []
            total_layers = len(input_layers)
            
            feedback.pushInfo(f'Starting to process {total_layers} layers...')
            
            for i, layer in enumerate(input_layers):
                if feedback.isCanceled():
                    break
                    
                feedback.setProgress(int((i / total_layers) * 90))
                feedback.pushInfo(f'Processing layer {i+1}/{total_layers}: {layer.name()}')
                
                kml_file = None
                
                # Process vector layers
                if isinstance(layer, QgsVectorLayer):
                    feedback.pushInfo(f'  -> Vector layer detected: {layer.name()}')
                    kml_file = self._process_vector_layer(
                        layer, target_crs, temp_dir, save_styles, feedback
                    )
                        
                # Process raster layers
                elif isinstance(layer, QgsRasterLayer):
                    feedback.pushInfo(f'  -> Raster layer detected: {layer.name()}')
                    kml_file = self._process_raster_layer(
                        layer, target_crs, temp_dir, save_styles, feedback
                    )
                else:
                    feedback.pushInfo(f'  -> Unsupported layer type: {type(layer).__name__}')
                    continue
                
                # Add to processed files if successful
                if kml_file and os.path.exists(kml_file):
                    processed_files.append(kml_file)
                    feedback.pushInfo(f'  -> Successfully processed: {layer.name()}')
                else:
                    feedback.reportError(f'  -> Failed to process: {layer.name()}')
            
            feedback.pushInfo(f'Processing complete. {len(processed_files)} layers successfully processed.')
            
            if not processed_files:
                raise QgsProcessingException(self.tr('No layers could be processed successfully'))
            
            # Create KMZ file
            feedback.pushInfo('Creating KMZ file...')
            self._create_kmz_file(processed_files, output_kmz, feedback)
            
            feedback.setProgress(100)
            feedback.pushInfo(f'KMZ file created successfully: {output_kmz}')
            feedback.pushInfo(f'Total layers included: {len(processed_files)}')
            
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        return {self.OUTPUT_KMZ: output_kmz}

    def _process_vector_layer(self, layer, target_crs, temp_dir, save_styles, feedback):
        """Process a vector layer and convert to KML."""
        
        layer_name = self._sanitize_filename(layer.name())
        # Add unique identifier to avoid filename conflicts
        kml_file = os.path.join(temp_dir, f'{layer_name}_{id(layer)}.kml')
        
        feedback.pushInfo(f'Processing vector layer: {layer.name()} -> {kml_file}')
        
        try:
            # Set up coordinate transform if needed
            source_crs = layer.crs()
            transform = None
            if source_crs != target_crs:
                transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            
            # Export to KML using QGIS vector file writer
            writer_options = QgsVectorFileWriter.SaveVectorOptions()
            writer_options.driverName = 'KML'
            writer_options.fileEncoding = 'UTF-8'
            
            if transform:
                writer_options.ct = transform
            
            # Handle styles if requested
            if save_styles:
                writer_options.symbologyExport = QgsVectorFileWriter.SymbolLayerSymbology
            
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                kml_file,
                QgsProject.instance().transformContext(),
                writer_options
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                feedback.reportError(f'Error exporting layer {layer.name()}: {error[1]}')
                return None
            
            # Verify KML file was created and has content
            if os.path.exists(kml_file) and os.path.getsize(kml_file) > 0:
                feedback.pushInfo(f'Successfully created KML for vector: {layer.name()}')
                return kml_file
            else:
                feedback.reportError(f'KML file not created or empty for layer: {layer.name()}')
                return None
                
        except Exception as e:
            feedback.reportError(f'Error processing vector layer {layer.name()}: {str(e)}')
            return None

    def _process_raster_layer(self, layer, target_crs, temp_dir, save_styles, feedback):
        """Process a raster layer and convert to KML with ground overlay."""
        
        layer_name = self._sanitize_filename(layer.name())
        
        try:
            # Create unique filenames to avoid conflicts
            temp_tiff = os.path.join(temp_dir, f'{layer_name}_{id(layer)}_temp.tif')
            kml_file = os.path.join(temp_dir, f'{layer_name}_{id(layer)}.kml')
            
            feedback.pushInfo(f'Processing raster layer: {layer.name()} -> {kml_file}')
            
            # First, reproject raster if needed
            if layer.crs() != target_crs:
                gdal_params = {
                    'INPUT': layer,
                    'TARGET_CRS': target_crs,
                    'OUTPUT': temp_tiff
                }
                
                result = processing.run('gdal:warpreproject', gdal_params, 
                                      context=None, feedback=feedback)
                input_for_kml = temp_tiff
            else:
                input_for_kml = layer
            
            # Convert to KML using GDAL translate
            translate_params = {
                'INPUT': input_for_kml,
                'OPTIONS': '-of KMLSUPEROVERLAY',
                'OUTPUT': kml_file
            }
            
            result = processing.run('gdal:translate', translate_params, 
                                  context=None, feedback=feedback)
            
            # Clean up temporary tiff
            if os.path.exists(temp_tiff):
                os.remove(temp_tiff)
            
            # Verify KML file was created
            if os.path.exists(kml_file) and os.path.getsize(kml_file) > 0:
                feedback.pushInfo(f'Successfully created KML for raster: {layer.name()}')
                return kml_file
            else:
                feedback.reportError(f'KML file not created or empty for layer: {layer.name()}')
                return None
                
        except Exception as e:
            feedback.reportError(f'Error processing raster layer {layer.name()}: {str(e)}')
            return None

    def _create_kmz_file(self, kml_files, output_kmz, feedback):
        """Create KMZ file from multiple KML files."""
        
        try:
            # Create KMZ archive
            with zipfile.ZipFile(output_kmz, 'w', zipfile.ZIP_DEFLATED) as kmz:
                
                # Create simple master KML as string
                master_kml = '<?xml version="1.0" encoding="UTF-8"?>\n'
                master_kml += '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
                master_kml += '  <Document>\n'
                master_kml += f'    <name>{os.path.splitext(os.path.basename(output_kmz))[0]}</name>\n'
                
                # Add each KML file
                for kml_file in kml_files:
                    if os.path.exists(kml_file):
                        with open(kml_file, 'r', encoding='utf-8') as f:
                            kml_content = f.read()
                        folder_match = re.search(r'<Folder>.*?</Folder>', kml_content, re.DOTALL).group(0)

                        master_kml += folder_match
                
                master_kml += '  </Document>\n'
                master_kml += '</kml>'
                
                kmz.writestr('doc.kml', master_kml.encode('utf-8'))
                
            feedback.pushInfo(f'KMZ archive created with {len(kml_files)} layers')
            
        except Exception as e:
            raise QgsProcessingException(f'Error creating KMZ file: {str(e)}')

    def _sanitize_filename(self, filename):
        """Sanitize filename for use in file system."""
        
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove leading/trailing spaces and dots
        filename = filename.strip(' .')
        # Limit length
        if len(filename) > 50:
            filename = filename[:50]
        
        return filename if filename else 'layer'