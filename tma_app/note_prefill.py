"""Nonblocking mass prefill; never overwrite a user's multiline edits."""
from PySide6.QtWidgets import QPlainTextEdit
from .mass_lookup import note_text_for_curve,format_note_text
from .mass_jobs import MassLookupJob
from .path_settings import settings_revision


def prepare(dialog,curve):
    initial=note_text_for_curve(curve)
    dialog.setTextValue(initial)
    editor=dialog.findChild(QPlainTextEdit)
    dialog._note_edited=False;dialog._note_setting=False
    def edited():
        if not dialog._note_setting:dialog._note_edited=True
    if editor is not None:editor.textChanged.connect(edited)
    # Import already supplied a matched value. Opening an editor should reuse it.
    if curve.dataset.metadata.get('LookupMassSample')==[curve.sample_name] and curve.dataset.metadata.get('LookupMass'):
        if curve.dataset.metadata.get('LookupMassStatus'):
            dialog.setLabelText('文字（支持多行；m 来源暂不可用，已保留此前重量，请核对）')
        return None
    sample=curve.sample_name;revision=settings_revision()
    dialog.setLabelText('文字（支持多行；m 未就绪时先填 0.50 mg，可核对修改）')
    job=MassLookupJob([('note',sample)],None,dialog)
    def ready(key,match):
        if (dialog._note_edited or match.value is None or curve.sample_name!=sample
                or settings_revision()!=revision):return
        from .mass_normalization import match_mass_mg
        mass=match_mass_mg(match)
        if mass is not None:
            dialog._note_setting=True
            try:dialog.setTextValue(format_note_text(mass))
            finally:dialog._note_setting=False
    def finished():
        if settings_revision()!=revision:
            dialog.setLabelText('文字（m 数据源已变化，请核对称取质量）')
        elif job.error_message:
            dialog.setLabelText('文字（m 未读取，请核对称取质量）')
    job.row_ready.connect(ready);job.finished.connect(finished);job.start()
    return job
