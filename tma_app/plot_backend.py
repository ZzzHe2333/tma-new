"""Qt plotting backend loaded when the first canvas is requested."""
import matplotlib

matplotlib.use("QtAgg")
matplotlib.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
                          "axes.unicode_minus": False, "font.size": 9, "svg.fonttype": "none"})
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT


class PlotCanvas(FigureCanvasQTAgg):
    """Do not allocate an Agg image for a not-yet-plotted MDI document."""
    def __init__(self,figure):
        self.plot_ready=False
        super().__init__(figure)

    def draw_idle(self):
        if self.plot_ready:super().draw_idle()
