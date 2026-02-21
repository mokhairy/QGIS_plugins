def classFactory(iface):
    """Load SeismicForecastPlanner plugin."""
    from .plugin import SeismicForecastPlannerPlugin

    return SeismicForecastPlannerPlugin(iface)
