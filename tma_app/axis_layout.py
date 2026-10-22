"""Keep secondary Y-axis tick numbers and titles apart at their rendered sizes."""
from __future__ import annotations


def fit_y_gaps(owner,scale):
    axes=owner.axes
    owner.canvas.draw();renderer=owner.canvas.get_renderer();figure=owner.figure
    width=figure.bbox.width;left,right=figure.subplotpars.left,figure.subplotpars.right
    base=axes[0];base_x,base_width=base.bbox.x0,base.bbox.width;pad=16*scale
    left_delta=right_delta=0.;outer_left=outer_right=None
    def ticks(axis):return [t.get_window_extent(renderer) for t in axis.get_yticklabels() if t.get_visible() and t.get_text()]
    if 1 in axes and 2 not in axes and axes[1].yaxis.get_visible():
        boxes=ticks(axes[1])+[axes[1].yaxis.label.get_window_extent(renderer)]
        right_delta=max(0.,max(b.x1 for b in boxes)-(figure.bbox.x1-8*scale))
    if 3 not in axes and axes[0].yaxis.get_visible():
        boxes=ticks(axes[0])+[axes[0].yaxis.label.get_window_extent(renderer)]
        left_delta=max(0.,figure.bbox.x0+8*scale-min(b.x0 for b in boxes))
    if 1 in axes and 2 in axes and axes[1].yaxis.get_visible() and axes[2].yaxis.get_visible():
        inner=axes[1].yaxis.label.get_window_extent(renderer);labels=ticks(axes[2])
        outer=axes[2].yaxis.label.get_window_extent(renderer)
        if labels:
            overflow=max(0.,max([b.x1 for b in labels]+[outer.x1])-(figure.bbox.x1-8*scale))
            outer_right=base_x+base_width*axes[2].spines['right'].get_position()[1]-overflow
            right_delta=max(overflow,inner.x1+pad-outer_right)
    if 3 in axes and axes[0].yaxis.get_visible() and axes[3].yaxis.get_visible():
        inner=axes[0].yaxis.label.get_window_extent(renderer);labels=ticks(axes[3]);outer=axes[3].yaxis.label.get_window_extent(renderer)
        if labels:
            overflow=max(0.,figure.bbox.x0+8*scale-min([b.x0 for b in labels]+[outer.x0]))
            outer_left=base_x+base_width*axes[3].spines['left'].get_position()[1]+overflow
            left_delta=max(overflow,outer_left+pad-inner.x0)
    if not left_delta and not right_delta:return
    available=max(0.,(right-left-.28)*width)
    if left_delta+right_delta>available:
        ratio=available/(left_delta+right_delta);left_delta*=ratio;right_delta*=ratio
    figure.subplots_adjust(left=left+left_delta/width,right=right-right_delta/width)
    base_x,base_width=base.bbox.x0,base.bbox.width
    if outer_right is not None:axes[2].spines['right'].set_position(('axes',(outer_right-base_x)/base_width))
    if outer_left is not None:axes[3].spines['left'].set_position(('axes',(outer_left-base_x)/base_width))
    owner.canvas.draw()
