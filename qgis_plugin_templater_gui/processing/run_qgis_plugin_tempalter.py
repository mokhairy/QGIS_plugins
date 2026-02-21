"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
)

from qgis_plugin_templater_gui.toolbelt.preferences import PlgOptionsManager


class RunQgisPluginTemplater(QgsProcessingAlgorithm):
    """
    Algorithm to generate QGIS plugin configuration based on cookiecutter template.
    """

    PLUGIN_NAME = "PLUGIN_NAME"
    PLUGIN_CATEGORY = "PLUGIN_CATEGORY"
    PLUGIN_PROCESSING = "PLUGIN_PROCESSING"
    PLUGIN_DESCRIPTION_SHORT = "PLUGIN_DESCRIPTION_SHORT"
    PLUGIN_DESCRIPTION_LONG = "PLUGIN_DESCRIPTION_LONG"
    PLUGIN_TAGS = "PLUGIN_TAGS"
    PLUGIN_ICON = "PLUGIN_ICON"
    AUTHOR_NAME = "AUTHOR_NAME"
    AUTHOR_ORG = "AUTHOR_ORG"
    AUTHOR_EMAIL = "AUTHOR_EMAIL"
    QGIS_VERSION_MIN = "QGIS_VERSION_MIN"
    QGIS_VERSION_MAX = "QGIS_VERSION_MAX"
    SUPPORT_QT6 = "SUPPORT_QT6"
    REPOSITORY_URL_BASE = "REPOSITORY_URL_BASE"
    REPOSITORY_DEFAULT_BRANCH = "REPOSITORY_DEFAULT_BRANCH"
    OPEN_SOURCE_LICENSE = "OPEN_SOURCE_LICENSE"
    LINTER_PY = "LINTER_PY"
    CI_CD_TOOL = "CI_CD_TOOL"
    CI_GITLAB_JOBS_TAGS = "CI_GITLAB_JOBS_TAGS"
    IDE = "IDE"
    PUBLISH_OFFICIAL_REPOSITORY = "PUBLISH_OFFICIAL_REPOSITORY"
    DEBUG = "DEBUG"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    # Options lists
    CATEGORY_OPTIONS = ["Database", "Filter", "Raster", "Vector", "Web", "None"]
    LICENSE_OPTIONS = ["GPLv2+", "GPLv3", "MIT", "None"]
    LINTER_OPTIONS = ["Flake8", "PyLint", "both", "None"]
    CI_CD_OPTIONS = ["GitHub", "GitLab", "None"]
    IDE_OPTIONS = ["VSCode", "None"]

    def name(self) -> str:
        """Returns the algorithm name."""
        return "run_qgis_plugin_templater"

    def displayName(self) -> str:
        """Returns the translated algorithm name."""
        return "Create plugin template"

    def shortHelpString(self) -> str:
        """Returns a localised short helper string for the algorithm."""
        return "Generate a QGIS plugin structure based on cookiecutter template configuration"

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """Define the inputs and output of the algorithm."""

        # Plugin Name
        self.addParameter(
            QgsProcessingParameterString(
                self.PLUGIN_NAME, "Plugin Name", defaultValue="My Awesome Plugin"
            )
        )

        # Plugin Category
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PLUGIN_CATEGORY,
                "Plugin Category",
                options=self.CATEGORY_OPTIONS,
                defaultValue=3,  # Vector
            )
        )

        # Plugin Processing
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.PLUGIN_PROCESSING, "Add Processing Provider", defaultValue=False
            )
        )

        # Plugin Description Short
        self.addParameter(
            QgsProcessingParameterString(
                self.PLUGIN_DESCRIPTION_SHORT,
                "Short Description",
                defaultValue="This plugin is a revolution!",
                multiLine=False,
            )
        )

        # Plugin Description Long
        self.addParameter(
            QgsProcessingParameterString(
                self.PLUGIN_DESCRIPTION_LONG,
                "Long Description",
                defaultValue="Extends QGIS with revolutionary features!",
                multiLine=True,
            )
        )

        # Plugin Tags
        self.addParameter(
            QgsProcessingParameterString(
                self.PLUGIN_TAGS, "Tags (comma separated)", defaultValue="topic1,topic2"
            )
        )

        # Plugin Icon
        self.addParameter(
            QgsProcessingParameterString(
                self.PLUGIN_ICON,
                "Plugin Icon Path (leave blank for default)",
                defaultValue="",
                optional=True,
            )
        )

        # Author Name
        self.addParameter(
            QgsProcessingParameterString(
                self.AUTHOR_NAME, "Author Name", defaultValue="Firstname LASTNAME"
            )
        )

        # Author Organization
        self.addParameter(
            QgsProcessingParameterString(
                self.AUTHOR_ORG, "Author Organization", defaultValue="Company"
            )
        )

        # Author Email
        self.addParameter(
            QgsProcessingParameterString(
                self.AUTHOR_EMAIL, "Author Email", defaultValue="qgis@company.com"
            )
        )

        # QGIS Version Min
        self.addParameter(
            QgsProcessingParameterString(
                self.QGIS_VERSION_MIN, "QGIS Minimum Version", defaultValue="3.40"
            )
        )

        # QGIS Version Max
        self.addParameter(
            QgsProcessingParameterString(
                self.QGIS_VERSION_MAX, "QGIS Maximum Version", defaultValue="3.99"
            )
        )

        # Support Qt6
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SUPPORT_QT6, "Support Qt6", defaultValue=True
            )
        )

        # Repository URL Base
        self.addParameter(
            QgsProcessingParameterString(
                self.REPOSITORY_URL_BASE,
                "Repository URL Base",
                defaultValue="https://gitlab.com/company/plugin_name/",
            )
        )

        # Repository Default Branch
        self.addParameter(
            QgsProcessingParameterString(
                self.REPOSITORY_DEFAULT_BRANCH,
                "Default Branch Name",
                defaultValue="main",
            )
        )

        # Open Source License
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OPEN_SOURCE_LICENSE,
                "Open Source License",
                options=self.LICENSE_OPTIONS,
                defaultValue=0,  # GPLv2+
            )
        )

        # Linter Python
        self.addParameter(
            QgsProcessingParameterEnum(
                self.LINTER_PY,
                "Python Linter",
                options=self.LINTER_OPTIONS,
                defaultValue=0,  # Flake8
            )
        )

        # CI/CD Tool
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CI_CD_TOOL,
                "CI/CD Tool",
                options=self.CI_CD_OPTIONS,
                defaultValue=1,  # GitLab
            )
        )

        # CI GitLab Jobs Tags
        self.addParameter(
            QgsProcessingParameterString(
                self.CI_GITLAB_JOBS_TAGS,
                "GitLab CI Jobs Tags",
                defaultValue="gitlab-org",
                optional=True,
            )
        )

        # IDE
        self.addParameter(
            QgsProcessingParameterEnum(
                self.IDE,
                "IDE",
                options=self.IDE_OPTIONS,
                defaultValue=0,  # VSCode
            )
        )

        # Publish to Official Repository
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.PUBLISH_OFFICIAL_REPOSITORY,
                "Publish to Official QGIS Repository",
                defaultValue=True,
            )
        )

        # Debug Mode
        self.addParameter(
            QgsProcessingParameterBoolean(self.DEBUG, "Debug Mode", defaultValue=False)
        )

        # Output Folder
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                "Path to the output directory of the generated project",
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        """Process the algorithm."""

        # Get all parameters
        plugin_name = self.parameterAsString(parameters, self.PLUGIN_NAME, context)

        plugin_category = self.CATEGORY_OPTIONS[
            self.parameterAsEnum(parameters, self.PLUGIN_CATEGORY, context)
        ]

        plugin_processing = self.parameterAsBoolean(
            parameters, self.PLUGIN_PROCESSING, context
        )
        plugin_description_short = self.parameterAsString(
            parameters, self.PLUGIN_DESCRIPTION_SHORT, context
        )
        plugin_description_long = self.parameterAsString(
            parameters, self.PLUGIN_DESCRIPTION_LONG, context
        )
        plugin_tags = self.parameterAsString(parameters, self.PLUGIN_TAGS, context)
        plugin_icon = self.parameterAsString(parameters, self.PLUGIN_ICON, context)

        author_name = self.parameterAsString(parameters, self.AUTHOR_NAME, context)
        author_org = self.parameterAsString(parameters, self.AUTHOR_ORG, context)
        author_email = self.parameterAsString(parameters, self.AUTHOR_EMAIL, context)

        qgis_version_min = self.parameterAsString(
            parameters, self.QGIS_VERSION_MIN, context
        )
        qgis_version_max = self.parameterAsString(
            parameters, self.QGIS_VERSION_MAX, context
        )
        support_qt6 = self.parameterAsBoolean(parameters, self.SUPPORT_QT6, context)

        repository_url_base = self.parameterAsString(
            parameters, self.REPOSITORY_URL_BASE, context
        )
        repository_default_branch = self.parameterAsString(
            parameters, self.REPOSITORY_DEFAULT_BRANCH, context
        )

        open_source_license = self.LICENSE_OPTIONS[
            self.parameterAsEnum(parameters, self.OPEN_SOURCE_LICENSE, context)
        ]

        linter_py = self.LINTER_OPTIONS[
            self.parameterAsEnum(parameters, self.LINTER_PY, context)
        ]

        ci_cd_tool = self.CI_CD_OPTIONS[
            self.parameterAsEnum(parameters, self.CI_CD_TOOL, context)
        ]

        ci_gitlab_jobs_tags = self.parameterAsString(
            parameters, self.CI_GITLAB_JOBS_TAGS, context
        )

        ide = self.IDE_OPTIONS[self.parameterAsEnum(parameters, self.IDE, context)]

        publish_official_repository = self.parameterAsBoolean(
            parameters, self.PUBLISH_OFFICIAL_REPOSITORY, context
        )
        debug = self.parameterAsBoolean(parameters, self.DEBUG, context)

        output_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)

        self.plg_settings = PlgOptionsManager()
        settings = self.plg_settings.get_plg_settings()

        # If output_folder not exists, create it
        output_path = Path(output_folder)
        output_path.mkdir(exist_ok=True)

        feedback.pushInfo("Plugin configuration created:")
        feedback.pushInfo(f"Name: {plugin_name}")
        feedback.pushInfo(f"Category: {plugin_category}")
        feedback.pushInfo(f"Output folder: {output_folder}")

        # Slugify plugin name for slug and class name
        plugin_name_slug = plugin_name.lower().replace(" ", "_").replace("-", "_")
        plugin_name_class = "".join(
            word.capitalize() for word in plugin_name_slug.split("_")
        )

        context_data = {
            "author_name": author_name,
            "author_org": author_org,
            "author_email": author_email,
            "plugin_name": plugin_name,
            "plugin_name_slug": plugin_name_slug,
            "plugin_name_class": plugin_name_class,
            "plugin_category": plugin_category,
            "plugin_processing": plugin_processing,
            "plugin_description_short": plugin_description_short,
            "plugin_description_long": plugin_description_long,
            "plugin_tags": plugin_tags,
            "plugin_icon": plugin_icon,
            "qgis_version_min": qgis_version_min,
            "qgis_version_max": qgis_version_max,
            "support_qt6": support_qt6,
            "repository_url_base": repository_url_base,
            "repository_default_branch": repository_default_branch,
            "open_source_license": open_source_license,
            "linter_py": linter_py,
            "ci_cd_tool": ci_cd_tool,
            "ci_gitlab_jobs_tags": ci_gitlab_jobs_tags,
            "ide": ide,
            "publish_official_repository": publish_official_repository,
            "debug": debug,
        }

        # Temporary json config
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(context_data, tmp, indent=2)
            tmp_path = tmp.name

        feedback.pushInfo(f"Configuration JSON écrite dans : {tmp_path}")

        cmd = [
            "cookiecutter",
            "--no-input",
            "--overwrite-if-exists",
            "--config-file",
            tmp_path,
            "--output-dir",
            output_folder,
            settings.template_url,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            feedback.pushInfo("Plugin template generated successfully!")
            feedback.pushInfo(f"Output: {result.stdout}")

            if result.stderr:
                feedback.pushInfo(f"Warnings: {result.stderr}")

        except subprocess.CalledProcessError as e:
            feedback.reportError(f"Error executing cookiecutter: {e}")
            feedback.reportError(f"stdout: {e.stdout}")
            feedback.reportError(f"stderr: {e.stderr}")
            raise QgsProcessingException(f"Failed to generate plugin: {e}")
        except FileNotFoundError:
            raise QgsProcessingException(
                "Cookiecutter not found. Please install it: pip install cookiecutter"
            )

        return {self.OUTPUT_FOLDER: output_folder}

    def createInstance(self):
        return self.__class__()
