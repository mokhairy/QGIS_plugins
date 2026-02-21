"""QGIS plugin entry point for RCM Production Progress."""

from __future__ import annotations

from .rcm_progress import RCMProgressPlugin


def classFactory(iface):  # type: ignore[override]
    """Entry point required by QGIS."""
    return RCMProgressPlugin(iface)
