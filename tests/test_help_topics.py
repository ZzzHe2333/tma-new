"""Teaching is reachable without data and never mutates the user's analysis."""
from copy import deepcopy

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication

from test_feature_ui import ui, imported
from tma_app.help_topics import TOPICS, BY_KEY, HelpTopicsDialog


def test_menu_help_is_offline_searchable_and_available_without_data(ui):
    ui.classic_actions['HelpTopics1'].trigger()
    dialog=ui.dialogs['help_topics']
    assert isinstance(dialog,HelpTopicsDialog) and dialog.isVisible()
    assert dialog.current_key()=='start' and not dialog.isModal()
    assert ui.classic_actions['HelpTopics1'].shortcut().toString()=='F1'
    assert not dialog.browser.openExternalLinks() and not dialog.browser.openLinks()
    dialog.search.setText('T1 T2 H')
    assert dialog.topics.count() and any(dialog.topics.item(i).data(Qt.ItemDataRole.UserRole)=='changes' for i in range(dialog.topics.count()))
    dialog.search.setText('无此主题abcdef')
    assert dialog.topics.count()==0 and '未找到主题' in dialog.browser.toPlainText()
    assert not dialog.next.isEnabled() and not dialog.previous.isEnabled()
    dialog.home.click();assert dialog.current_key()=='start'
    dialog.follow_link(QUrl('help:export'));assert dialog.current_key()=='export'
    assert '300 dpi' in dialog.browser.toPlainText() and 'Power By ZzzHe' in dialog.browser.toPlainText()
    dialog.follow_link(QUrl('file:///C:/Windows/win.ini'));assert dialog.current_key()=='export'
    dialog.follow_link(QUrl('https://example.com'));assert dialog.current_key()=='export'
    dialog.close_button.click();assert not dialog.isVisible()
    ui.classic_actions['HowTo1'].trigger()
    assert ui.dialogs['help_topics'] is dialog and dialog.current_key()=='right_click'
    ui.classic_actions['GettingStartedGuide1'].trigger();assert dialog.current_key()=='start'
    dialog.close();assert ui.curves==[] and ui.results==[] and not ui.dirty


def test_file_information_empty_opens_teaching_and_real_editor_still_works(ui,tmp_path):
    ui.classic_actions['FileInformation1'].trigger()
    guide=ui.dialogs['help_topics'];assert guide.current_key()=='file_information'
    assert '.tmas' in guide.browser.toPlainText()
    guide.close();imported(ui,tmp_path,1);ui.show_normal()
    editor=ui.show_file_information();assert editor.objectName()=='FileInfoForm'
    editor.fields['Comment'].setText('unsaved draft')
    editor.help();QApplication.processEvents()
    assert guide.isVisible() and guide.parentWidget() is editor
    assert guide.current_key()=='file_information' and ui.selected().file_info=={}
    guide.close();editor.reject();ui.classic_actions['HelpTopics1'].trigger()
    assert guide.parentWidget() is ui and guide.current_key()=='start'


def test_reading_all_topics_preserves_active_curve_results_and_plot(ui,tmp_path):
    imported(ui,tmp_path,2)
    entry=ui.start_point_measurement('dimension_change');ui.confirm_measurement()
    selected=ui.selected();active=ui.active_document();before=deepcopy(ui.results);plots=deepcopy(ui.plot_options)
    dirty=ui.dirty;guide=ui.show_help_topics('changes')
    for topic in TOPICS:
        guide.open_topic(topic.key)
        assert topic.title in guide.browser.toPlainText()
        assert guide.current_key()==topic.key
    guide.next.click();guide.previous.click();guide.close()
    assert ui.selected() is selected and ui.active_document() is active
    assert ui.results==before and ui.plot_options==plots and ui.dirty==dirty
    assert entry['interactive']['confirmed']


def test_every_internal_help_link_has_a_real_topic():
    import re
    for topic in TOPICS:
        for target in re.findall(r'href="help:([^"]+)"',topic.body):
            assert target in BY_KEY
    assert BY_KEY['export'].matches('导出 图片')
    assert BY_KEY['file_information'].matches('文件信息')
