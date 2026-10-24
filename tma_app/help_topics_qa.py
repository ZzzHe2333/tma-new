"""Exercise offline teaching and the existing file-info/export menu workflows."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import traceback

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFileDialog

from . import __version__
from .batch_qa import wait_until
from .help_topics import TOPICS
from .workspace import save_session, load_session


def verify(window, output, paths):
    output.parent.mkdir(parents=True, exist_ok=True)
    report={'status':'failed','version':__version__,'checks':[]}
    original_picker=QFileDialog.getSaveFileName
    try:
        assert len(paths)==2
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        window.classic_actions['FileInformation1'].trigger()
        guide=window.dialogs['help_topics']
        assert guide.current_key()=='file_information' and guide.isVisible()
        guide.close();window.classic_actions['HelpTopics1'].trigger()
        assert guide is window.dialogs['help_topics'] and guide.current_key()=='start'
        assert window.classic_actions['HelpTopics1'].shortcut().toString()=='F1'
        for key in ('start','right_click','changes','file_information','export'):
            guide.open_topic(key);QApplication.processEvents()
            assert guide.current_key()==key
            assert guide.grab().save(str(output.with_suffix('.'+key+'.png')))
        guide.search.setText('T1 T2 H');assert guide.topics.count()>0
        guide.search.setText('no_such_help_123');assert guide.topics.count()==0
        guide.follow_link(QUrl('help:export'));assert guide.current_key()=='export'
        guide.follow_link(QUrl('file:///C:/Windows/win.ini'));assert guide.current_key()=='export'
        assert not guide.isModal() and not guide.browser.openLinks() and not guide.browser.openExternalLinks()
        guide.close_button.click();assert not guide.isVisible()
        assert not window.curves and not window.results and not window.dirty
        report['checks'].append('empty_workspace_help_menus_F1_search_internal_links_and_close')

        window.import_files(paths);wait_until(lambda:window.worker is None)
        assert len(window.curves)==2
        window.show_normal();curve=window.selected();document=window.active_document()
        window.start_point_measurement('dimension_change');window.confirm_measurement()
        before=deepcopy(window.results);plots=deepcopy(window.plot_options);dirty=window.dirty
        window.classic_actions['HowTo1'].trigger();assert guide.current_key()=='right_click'
        for topic in TOPICS:guide.open_topic(topic.key)
        guide.close()
        assert window.results==before and window.plot_options==plots and window.dirty==dirty
        assert window.selected() is curve and window.active_document() is document
        report['checks'].append('reading_all_topics_preserves_curves_results_and_current_document')

        window.classic_actions['FileInformation1'].trigger();editor=window.dialogs['file_information']
        old=deepcopy(curve.file_info);editor.fields['Comment'].setText('teaching QA draft')
        editor.help();QApplication.processEvents()
        assert guide.current_key()=='file_information' and guide.parentWidget() is editor
        assert curve.file_info==old and editor.isVisible()
        guide.close();editor.reject();assert curve.file_info==old
        editor=window.show_file_information();editor.fields['Comment'].setText('teaching QA verified');editor.accept()
        assert curve.file_info['Comment']=='teaching QA verified' and window.results==before
        session=output.with_suffix('.tmas');save_session(session,window.curves,window.domain,window.results,window.plot_options)
        assert load_session(session)[0][-1].file_info['Comment']=='teaching QA verified'
        report['checks'].append('existing_file_information_draft_cancel_help_edit_and_session_save')

        image=output.with_suffix('.export.png')
        QFileDialog.getSaveFileName=lambda *args:(str(image),'PNG (*.png)')
        window.classic_actions['ExportPlot1'].trigger()
        rendered=QImage(str(image));assert not rendered.isNull()
        assert rendered.pixelColor(0,0).name()=='#ffffff'
        assert window.selected() is curve and window.active_document() is document
        report['checks'].append('existing_export_plot_menu_saves_current_graph_with_white_border')
        report.update(status='passed',topics=len(TOPICS),source_sha256=hashes,
                      exported_image=str(image),export_pixels=[rendered.width(),rendered.height()])
        assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    except Exception:report['error']=traceback.format_exc()
    finally:
        QFileDialog.getSaveFileName=original_picker
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        for dialog in window.dialogs.values():
            if dialog is not None:dialog.hide()
        window.dirty=False;window.close()
    if report['status']!='passed':raise SystemExit(1)
