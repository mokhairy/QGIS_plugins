def classFactory(iface):
    """Load LayerDateFilter plugin."""
    from .plugin import LayerDateFilterPlugin

    return LayerDateFilterPlugin(iface)
