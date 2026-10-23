"""Exercise enlarged native Qt widgets, preview pixels and plot hit testing."""
from __future__ import annotations

import hashlib
import json
import traceback

from PySide6.QtCore import QEventLoop, QTimer, QPoint
from PySide6.QtWidgets import QApplication

from . import __version__, ui_size
from .reader import read_dataset
from .batch_qa import wait_until


def settle():
    loop=QEventLoop();QTimer.singleShot(180,loop.quit);loop.exec()


def verify(window,output,paths):
    output.parent.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','version':__version__,'preset':ui_size.active_size(),'checks':[]}
    try:
        before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        window.finish_import([read_dataset(path) for path in paths],[]);window.show_overlay()
        settle();window.redraw();window.canvas.draw();settle()
        ratio=window.devicePixelRatioF();canvas=window.canvas
        assert canvas.device_pixel_ratio==ratio
        image=window.grab();image.save(str(output.with_suffix('.main.png')))
        report.update(dpr=ratio,main_pixels=[image.width(),image.height()],
            button_pixels=[window.single_report_button.width()*ratio,window.single_report_button.height()*ratio],
            font_pixels=window.single_report_button.fontMetrics().height()*ratio,
            toolbar_icon_pixels=window.classic_toolbar.iconSize().width()*ratio,
            plot_tick_pixels=window.axes[0].get_xticklabels()[0].get_fontsize()*window.figure.dpi/72)
        assert window.single_report_button.isVisible() and window.share_button.isVisible()
        renderer=canvas.get_renderer();label=window.axes[0].xaxis.label.get_window_extent(renderer)
        assert label.y0>=0 and label.y1<=window.figure.bbox.height,(label,window.figure.bbox)
        selected=[];rescale=window.manual_rescale
        window.manual_rescale=lambda axis:selected.append(axis)
        try:
            x=(label.x0+label.x1)/2;y=(label.y0+label.y1)/2
            point=QPoint(round(x/ratio),round((window.figure.bbox.height-y)/ratio))
            window.show_plot_context_menu(window.active_document(),point)
            assert selected==['x'],selected
        finally:window.manual_rescale=rescale
        report['checks'].append('scaled_plot_text_inside_canvas_native_axis_right_click_correct')
        dialog=window.show_path_settings();settle()
        assert dialog.ui_size.currentData()==ui_size.active_size()
        dialog.grab().save(str(output.with_suffix('.settings.png')))
        if ui_size.factor()>1:
            assert dialog.frameGeometry().height()<=dialog.screen().availableGeometry().height()+6
        dialog.reject()
        batch=window.show_batch_analysis();settle();batch.grab().save(str(output.with_suffix('.batch.png')));batch.close()
        from .single_report_dialog import SingleReportDialog
        single=SingleReportDialog(window);single.show();settle()
        single.grab().save(str(output.with_suffix('.report.png')))
        if ui_size.factor()>1:
            available=single.screen().availableGeometry()
            assert single.frameGeometry().width()<=available.width()+8
            assert single.frameGeometry().height()<=available.height()+8
        single.close()
        share=window.show_share();wait_until(lambda:bool(share.png));settle()
        share.grab().save(str(output.with_suffix('.share.png')))
        assert share.preview.pixmap().devicePixelRatio()==ratio
        share.reject()
        report['checks']+=['settings_batch_report_and_share_readable_and_closeable',
                           'image_preview_rasterized_at_native_scaled_resolution']
        assert before=={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        report['status']='passed'
    except Exception:report['error']=traceback.format_exc()
    finally:
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.dirty=False;window.close()
    if report['status']!='passed':raise SystemExit(1)
