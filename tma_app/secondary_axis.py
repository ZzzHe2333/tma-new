"""Additional time/temperature tick labels without inventing inverse branches."""
import numpy as np


def corresponding_values(x, y, targets,rows=None):
    x, y = np.asarray(x), np.asarray(y)
    output = []
    for target in targets:
        values = list(y[x == target])
        for i in np.flatnonzero(((x[:-1] < target) & (x[1:] > target)) | ((x[:-1] > target) & (x[1:] < target))):
            if rows is not None and rows[i+1]!=rows[i]+1:continue
            values.append(y[i] + (y[i+1]-y[i])*(target-x[i])/(x[i+1]-x[i]))
        # A hold or repeated branch must not be collapsed to a made-up time.
        output.append(float(values[0]) if values and np.allclose(values, values[0], rtol=1e-9, atol=1e-9) else None)
    return output


def add_secondary_axis(base,curve,domain,fonts,scale,display_x_offset=0.):
    other = "time" if domain == "temperature" else "temperature"
    try: x, y = curve.x_values(domain)+curve.display_x_shift(domain)+display_x_offset, curve.x_values(other)
    except ValueError: return None
    axis = base.twiny(); axis.set_xlim(base.get_xlim())
    def update(_=None):
        ticks = base.get_xticks(); values = corresponding_values(x, y, ticks,curve.active_rows)
        axis.set_xticks(ticks, labels=["" if value is None else f"{value:.6g}" for value in values])
        axis.set_xlim(base.get_xlim())
    update(); base.callbacks.connect("xlim_changed", update)
    label=curve.x_label(other).replace("Time", "时间").replace("Temperature", "温度")
    axis.set_xlabel(label, fontfamily=fonts, fontsize=15*scale, labelpad=3)
    axis.tick_params(direction="out", labelsize=14*scale, width=.55, length=5*scale)
    for label in axis.get_xticklabels(): label.set_fontfamily(fonts)
    for name, spine in axis.spines.items(): spine.set_visible(name == "top"); spine.set_linewidth(.55)
    axis.patch.set_visible(False); axis.set_gid("tma-secondary-x")
    return axis
