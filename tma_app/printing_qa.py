"""Frozen preview checks and PDF jobs; never submit a physical print job."""
from copy import deepcopy
import hashlib
import json
import traceback

from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrintPreviewWidget
from PySide6.QtWidgets import QApplication, QDialog

from . import __version__, printing
from .reader import read_dataset


def verify(window, output, paths, *, restart=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    try:
        if restart:
            assert printing.settings()=={'paper':'A4','orientation':'portrait','margins_mm':[12.,10.,10.,10.]}
            dialog=window.show_print_settings()
            assert dialog.orientation.currentData()=='portrait' and dialog.margins[0].value()==12
            QApplication.processEvents();dialog.grab().save(str(output.with_suffix('.png')));dialog.reject()
            report['checks'].append('print_settings_restored_after_exe_restart')
        else:
            hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
            window.finish_import([read_dataset(p) for p in paths],[])
            assert printing.settings()==printing.DEFAULTS
            dialog=window.show_print_settings();QApplication.processEvents()
            assert dialog.paper.currentData()=='A4' and dialog.orientation.currentData()=='auto'
            dialog.grab().save(str(output.with_suffix('.settings.png')));dialog.reject()
            window.start_point_measurement('dimension_change');window.confirm_measurement()
            assert window.results and window._result_annotations
            images=[]
            for overlay in (False,True):
                if overlay: window.show_overlay()
                document=window.active_document();before=deepcopy(window.plot_options)
                preview=window.show_print_preview();QApplication.processEvents()
                widget=preview.findChild(QPrintPreviewWidget)
                assert widget is not None and widget.pageCount()==1 and preview._print_error is None
                assert preview._plot_printer.pageLayout().pageSize().id()==QPageSize.PageSizeId.A4
                assert preview._plot_printer.pageLayout().orientation()==QPageLayout.Orientation.Landscape
                label='overlay' if overlay else 'single'
                preview.grab().save(str(output.with_suffix('.'+label+'-preview.png')))
                widget.setPortraitOrientation();widget.updatePreview();QApplication.processEvents()
                assert preview._plot_printer.pageLayout().orientation()==QPageLayout.Orientation.Portrait
                assert widget.pageCount()==1 and preview._print_error is None
                if overlay: preview.grab().save(str(output.with_suffix('.portrait-preview.png')))
                image=preview._plot_image.copy();preview.reject();QApplication.processEvents()
                assert window.active_document() is document and window.plot_options==before
                assert 'print_preview' not in window.dialogs
                destination=output.with_suffix('.'+label+'.pdf')
                printer=printing.make_printer(printing.DEFAULTS,image.size(),title=label,output_pdf=destination)
                printing.paint_page(printer,image)
                images.append({'file':str(destination),'size':[image.width(),image.height()]})
            destination=output.with_suffix('.portrait.pdf')
            printer=printing.make_printer({**printing.DEFAULTS,'orientation':'portrait'},image.size(),output_pdf=destination)
            printing.paint_page(printer,image)
            images.append({'file':str(destination),'size':[image.width(),image.height()]})
            dialog=window.show_print_settings()
            dialog.orientation.setCurrentIndex(dialog.orientation.findData('portrait'));dialog.margins[0].setValue(12)
            dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
            assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
            report.update(pdfs=images,source_sha256=hashes)
            report['checks'].extend(['native_preview_single_and_overlay_A4_landscape_one_page',
                'preview_orientation_controls_work_without_changing_active_plot',
                'same_renderer_prints_single_overlay_and_portrait_PDF_with_labels',
                'print_settings_save_paper_orientation_margins','physical_print_jobs_not_submitted'])
        report['status']='passed'
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.dirty=False;window.close()
    if report['status']!='passed': raise SystemExit(1)
