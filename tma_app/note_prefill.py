"""Nonblocking mass prefill; never overwrite a user's multiline edits."""
from PySide6.QtWidgets import QPlainTextEdit
from .mass_lookup import note_text_for_curve,format_note_text,configured_source
from .mass_jobs import MassLookupJob


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
        return None
    try:source=configured_source()
    except (ValueError,OSError):return None
    if not source:return None
    dialog.setLabelText('文字（支持多行；m 未就绪时先填 0.50 mg，可核对修改）')
    job=MassLookupJob([('note',curve.sample_name)],source,dialog)
    def ready(key,match):
        if dialog._note_edited or match.value is None:return
        from .mass_normalization import match_mass_mg
        mass=match_mass_mg(match)
        if mass is not None:
            dialog._note_setting=True
            try:dialog.setTextValue(format_note_text(mass))
            finally:dialog._note_setting=False
    job.row_ready.connect(ready);job.start()
    return job
