"""Legend composition and normalized positioning; source paths stay immutable.

The manufacturer documents normalized 0..1 handles but does not establish the
exact original reference rectangle. This implementation explicitly uses the
inner plotting axes, with lower-left origin, independent of data-axis units.
"""
from matplotlib.lines import Line2D
from matplotlib.legend import Legend
from types import MethodType
from .graph_options import render_style


def _draw_cached(legend,renderer):
    previous=legend._tma_draw_positions
    legend._tma_draw_positions={}
    try:return Legend.draw(legend,renderer)
    finally:legend._tma_draw_positions=previous


def _find_cached(legend,width,height,renderer,*args,**kwargs):
    cache=legend._tma_draw_positions
    # This cache exists only inside one Legend.draw call. Both layout queries
    # there use the same unchanged axes, paths and renderer. Calls outside draw
    # (including manual dragging/export layout) always perform a fresh search.
    if cache is None or args or kwargs:return Legend._find_best_position(legend,width,height,renderer,*args,**kwargs)
    key=(width,height,id(renderer))
    if key not in cache:cache[key]=Legend._find_best_position(legend,width,height,renderer)
    return cache[key]


def cache_draw_positions(legend):
    """Avoid repeated full-curve scans inside our own standard legends only."""
    if type(legend) is Legend and not hasattr(legend,'_tma_draw_positions'):
        legend._tma_draw_positions=None
        legend.draw=MethodType(_draw_cached,legend)
        legend._find_best_position=MethodType(_find_cached,legend)
    return legend


def location(anchor):
    horizontal, vertical = anchor["horizontal"], anchor["vertical"]
    if vertical == "center": return "center" if horizontal == "center" else "center " + horizontal
    return ("upper" if vertical == "top" else "lower") + " " + horizontal


def apply_anchor(legend, axis, anchor):
    legend.set_loc(location(anchor))
    legend.borderaxespad = 0
    legend.set_bbox_to_anchor((anchor["x"], anchor["y"]), transform=axis.transAxes)


def render_legend(owner, base, options, fonts, scale):
    previous = base.get_legend()
    if previous is not None: previous.remove()
    captions, handles = [], []
    for curve, *_ in owner._plot_artists:
        # The legacy whole-row visibility field remains for older sessions.
        # New Curves-page checkboxes only affect custom text.
        if not curve.show_legend: continue
        line = next((line for line in owner.axes[curve.axis].lines if getattr(line, "_tma_curve_uid", None) == curve.uid), None)
        if line is None: continue
        pieces = []
        if options["legend_file"] and curve.display_filename: pieces.append(curve.display_filename)
        if options["legend_text"] and curve.show_legend_text and curve.legend_text: pieces.append(curve.legend_text)
        captions.append("\n".join(pieces))
        handles.append(Line2D([], [], color=line.get_color() if options["legend_color"] else "black",
                              lw=line.get_linewidth(), ls=render_style(curve.style) if options["legend_line"] else "None",
                              marker=line.get_marker() if options["legend_symbol"] else "", ms=line.get_markersize()))
    if not handles: return None
    anchor = options["legend_anchor"]
    legend = base.legend(handles, captions, loc=location(anchor) if anchor else options["legend_location"],
                         frameon=options["legend_border"], prop={"family": fonts, "size": max(8, 14*scale)})
    cache_draw_positions(legend)
    if anchor: apply_anchor(legend, base, anchor)
    legend.set_visible(len(owner._plot_artists) > 1 if options["legend"] is None else options["legend"])
    legend.set_gid("tma-legend")
    return legend


def moved_anchor(axis, bounds, original, dx, dy):
    horizontal, vertical = original["horizontal"], original["vertical"]
    x = {"left": bounds.x0, "center": (bounds.x0+bounds.x1)/2, "right": bounds.x1}[horizontal] + dx
    y = {"bottom": bounds.y0, "center": (bounds.y0+bounds.y1)/2, "top": bounds.y1}[vertical] + dy
    nx, ny = axis.transAxes.inverted().transform((x, y))
    return dict(original, x=float(max(0, min(1, nx))), y=float(max(0, min(1, ny))))
