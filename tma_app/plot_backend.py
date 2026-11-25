"""Qt plotting backend loaded when the first canvas is requested."""
import matplotlib

matplotlib.use("QtAgg")
matplotlib.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
                          "axes.unicode_minus": False, "font.size": 9, "svg.fonttype": "none"})
from shiboken6 import isValid
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT


class PlotCanvas(FigureCanvasQTAgg):
    """Do not allocate an Agg image for a not-yet-plotted MDI document."""
    def __init__(self,figure):
        self.plot_ready=False
        super().__init__(figure)

    def draw_idle(self):
        if self.plot_ready and isValid(self):
            super().draw_idle()

    def _draw_idle(self):
        # Matplotlib schedules this callback without a Qt receiver. It may run
        # after the MDI document has destroyed the canvas's native widget.
        if not isValid(self):
            self._draw_pending = False
            return
        super()._draw_idle()
