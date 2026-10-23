from copy import deepcopy
import json

import fitz
import pytest
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QColor, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrintPreviewWidget
from PySide6.QtWidgets import QApplication, QDialog

from test_feature_ui import ui, imported
from tma_app import printing, path_settings


def test_print_menu_defaults_and_empty_preview(ui):
    for key in ('Print1', 'PrintSetup1', 'PrintPreview1'):
        assert ui.classic_actions[key].isEnabled()
        assert 'A4' in ui.classic_actions[key].toolTip()
    assert printing.settings()==printing.DEFAULTS
    assert ui.show_print_preview() is None
    assert '请先打开' in ui.statusBar().currentMessage()
    printer=printing.make_printer(printing.DEFAULTS, QSize(1600,900))
    assert printer.pageLayout().pageSize().id()==QPageSize.PageSizeId.A4
    assert printer.pageLayout().orientation()==QPageLayout.Orientation.Landscape


def test_settings_save_cancel_and_restart_keep_other_preferences(ui):
    path_settings._save_data({'paths':{'m':'weights.xlsx'},'sharing':{'fixture':'preserved'}})
    dialog=ui.show_print_settings(); dialog.paper.setCurrentIndex(dialog.paper.findData('A3'));dialog.reject()
    assert printing.settings()['paper']=='A4'
    dialog=ui.show_print_settings();dialog.orientation.setCurrentIndex(dialog.orientation.findData('portrait'))
    dialog.margins[0].setValue(15);dialog.accept()
    assert dialog.result()==QDialog.DialogCode.Accepted
    assert printing.controller(ui).options==printing.settings()
    assert printing.settings()['margins_mm']==[15,10,10,10]
    assert path_settings.load_paths()['m']=='weights.xlsx'
    assert path_settings._settings_data()['sharing']=={'fixture':'preserved'}
    # A fresh controller reads the persisted values, rather than printer defaults.
    del ui._print_controller
    assert printing.controller(ui).options['orientation']=='portrait'


@pytest.mark.parametrize('size,orientation,page_landscape', [
    (QSize(1600,900),'auto',True),(QSize(900,1600),'auto',False),
    (QSize(1600,900),'portrait',False),(QSize(900,1600),'landscape',True)])
def test_a4_pdf_fits_complete_image_and_preserves_aspect(ui,tmp_path,size,orientation,page_landscape):
    path=tmp_path/'printed.pdf'
    options={**printing.DEFAULTS,'orientation':orientation,'margins_mm':[12,14,16,18]}
    image=QImage(size,QImage.Format.Format_RGB32); image.fill(QColor('#d62839'))
    printer=printing.make_printer(options,size,output_pdf=path)
    target=printing.paint_page(printer,image)
    assert target.width()/target.height()==pytest.approx(size.width()/size.height())
    with fitz.open(path) as pdf:
        assert len(pdf)==1 and pdf.metadata['creator']=='Power By ZzzHe'
        page=pdf[0];assert (page.rect.width>page.rect.height)==page_landscape
        expected=(297,210) if page_landscape else (210,297)
        assert (page.rect.width*25.4/72,page.rect.height*25.4/72)==pytest.approx(expected,abs=.1)
        placed=page.get_image_rects(page.get_images()[0][0])[0]
        assert placed.width/placed.height==pytest.approx(size.width()/size.height(),rel=1e-5)
        assert placed.x0>=12*72/25.4-1 and placed.y0>=14*72/25.4-1
        assert page.rect.width-placed.x1>=16*72/25.4-1
        assert page.rect.height-placed.y1>=18*72/25.4-1
        # Check that the rasterized output contains the image, not an empty PDF.
        pixels=page.get_pixmap(matrix=fitz.Matrix(.4,.4))
        assert min(pixels.samples)<100


def test_preview_and_print_use_same_renderer_current_overlay_and_single_snapshot(ui,tmp_path,monkeypatch):
    imported(ui,tmp_path,2);ui.show_overlay();document=ui.active_document()
    before_options=deepcopy(ui.plot_options)
    snapshots=[];rendered=[]
    original=ui.output_pixmap
    def snapshot(**kwargs): snapshots.append(kwargs);return original(**kwargs)
    monkeypatch.setattr(ui,'output_pixmap',snapshot)
    monkeypatch.setattr(printing,'paint_page',lambda p,image: rendered.append((p,image.size())))
    dialog=ui.show_print_preview();QApplication.processEvents()
    assert dialog is not None and dialog._print_error is None
    assert ui.show_print_preview() is dialog and len(snapshots)==1
    preview=dialog.findChild(QPrintPreviewWidget)
    preview.updatePreview();QApplication.processEvents()
    assert len(snapshots)==1 and snapshots[0]=={'dpi':300} and len(rendered)>=2
    assert all(p is dialog._plot_printer for p,_ in rendered)
    assert dialog._plot_printer.pageLayout().orientation()==QPageLayout.Orientation.Landscape
    dialog.reject()
    assert 'print_preview' not in ui.dialogs
    monkeypatch.setattr(printing.QPrintDialog,'exec',lambda dialog:QDialog.DialogCode.Rejected)
    rendered.clear();ui.print_plot();assert not rendered
    monkeypatch.setattr(printing.QPrintDialog,'exec',lambda dialog:QDialog.DialogCode.Accepted)
    ui.print_plot();assert len(rendered)==1
    assert ui.active_document() is document and ui.plot_options==before_options


def test_print_settings_failure_keeps_dialog_open(ui,monkeypatch):
    def denied(*args): raise PermissionError('fixture write denied')
    monkeypatch.setattr(printing,'_save_data',denied)
    dialog=ui.show_print_settings();dialog.paper.setCurrentIndex(dialog.paper.findData('A3'));dialog.accept()
    assert dialog.result()!=QDialog.DialogCode.Accepted and dialog.isVisible()
    assert 'fixture write denied' in dialog.feedback.text()
    assert printing.controller(ui).options['paper']=='A4';dialog.reject()


def test_fit_offsets_and_invalid_options():
    rect=printing.fitted_rect(QRectF(30,40,200,100),QSize(100,100))
    assert (rect.x(),rect.y(),rect.width(),rect.height())==(80,40,100,100)
    for invalid in ({'paper':'invalid'},{'orientation':'invalid'},{'margins_mm':[float('nan')]*4}):
        with pytest.raises(ValueError):printing.validate(invalid)
