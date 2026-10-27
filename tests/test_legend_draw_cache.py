"""Deduplicate work within one legend draw without caching across frames."""
import io
import numpy as np
import pytest
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.legend import Legend
from tma_app.legend import cache_draw_positions


def figure():
    fig=Figure(figsize=(6,4),dpi=100);FigureCanvasAgg(fig);axis=fig.add_subplot()
    x=np.linspace(0,10,5000)
    for i in range(5):axis.plot(x,np.sin(x+i)+i,label=f'sample {i}')
    legend=axis.legend(loc='best')
    return fig,axis,legend


@pytest.mark.parametrize('dpi',[80,100,170])
def test_best_position_scans_once_per_draw_and_pixels_match_uncached(monkeypatch,dpi):
    fig,axis,legend=figure();fig.set_dpi(dpi);calls=[];original=Legend._find_best_position
    def counted(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(Legend,'_find_best_position',counted)
    fig.canvas.draw();expected=np.asarray(fig.canvas.buffer_rgba()).copy();plain=len(calls)
    cache_draw_positions(legend);calls.clear();fig.canvas.draw()
    np.testing.assert_array_equal(np.asarray(fig.canvas.buffer_rgba()),expected)
    assert len(calls)==1 and plain>=len(calls) and legend._tma_draw_positions is None
    # get_window_extent outside draw never reuses a previous frame's result.
    before=len(calls);legend.get_window_extent(fig.canvas.get_renderer())
    assert len(calls)>before and legend._tma_draw_positions is None


@pytest.mark.parametrize('change',['limits','data','size','font','location','anchor'])
def test_frame_changes_and_manual_positions_never_reuse_old_position(change):
    fig,axis,legend=figure();cache_draw_positions(legend);fig.canvas.draw()
    if change=='limits':axis.set_xlim(2,6);axis.set_ylim(-1,9)
    elif change=='data':axis.lines[0].set_ydata(axis.lines[0].get_ydata()+5)
    elif change=='size':fig.set_size_inches(4,6)
    elif change=='font':
        for text in legend.get_texts():text.set_fontsize(17)
    elif change=='location':legend.set_loc('lower left')
    else:legend.set_loc('center');legend.set_bbox_to_anchor((.4,.7))
    fig.canvas.draw();cached=np.asarray(fig.canvas.buffer_rgba()).copy()
    # Remove only our instance methods; compare the exact same changed artist.
    del legend.draw;del legend._find_best_position
    fig.canvas.draw();np.testing.assert_array_equal(np.asarray(fig.canvas.buffer_rgba()),cached)


def test_cache_clears_on_draw_error_and_has_no_renderer_reference(monkeypatch):
    fig,axis,legend=figure();cache_draw_positions(legend)
    def broken(legend,renderer):
        legend._find_best_position(20,30,renderer)
        raise ValueError('draw error')
    monkeypatch.setattr(Legend,'draw',broken)
    with pytest.raises(ValueError,match='draw error'):legend.draw(fig.canvas.get_renderer())
    assert legend._tma_draw_positions is None


@pytest.mark.parametrize('format',['png','pdf','svg'])
def test_export_renderer_finishes_with_empty_cache(format):
    fig,axis,legend=figure();cache_draw_positions(legend);fig.canvas.draw()
    stream=io.BytesIO();fig.savefig(stream,format=format,dpi=140)
    assert len(stream.getvalue())>1000 and legend._tma_draw_positions is None
