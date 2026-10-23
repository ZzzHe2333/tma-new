"""Plain Python batch worker: no QObject, Qt signal or widget crosses threads."""
from . import batch_analysis as backend
from .diagnostics import record_event


def run_batch_job(action, requests, source, directory, cancelled, events):
    def result(key, value):
        events.put(('row', key, value))
    record_event('batch.worker.start', action=action, files=len(requests))
    try:
        if action == 'plot' and directory:
            try:
                rows = [row for _, row in requests]
                paths = backend.plot_paths(rows, directory)
                requests = [(row['id'], (row, path)) for row, path in zip(rows, paths)]
            except Exception as exc:
                for key, _ in requests: result(key, {'export_error': str(exc)})
                return
        mass_requests = []
        for key, request in requests:
            if cancelled.is_set(): break
            try:
                if action == 'calculate':
                    record_event('batch.file.start', row=key, file=str(request))
                    value = backend.calculate_file(request)
                    result(key, value)
                    record_event('batch.file.result', row=key, file=str(request), error=value.get('error', ''))
                    if not value.get('error'): mass_requests.append((key, value))
                elif action == 'plot':
                    row, path = request
                    result(key, {'png': backend.write_plot(row, path), 'export_error': ''})
                elif action == 'xlsx':
                    rows, path = request
                    result(key, {'xlsx': backend.write_xlsx(rows, path)})
            except Exception as exc:
                result(key, {'error': str(exc), 'state': '读取失败'} if action == 'calculate' else {'export_error': str(exc)})
        for key, value in mass_requests:
            if cancelled.is_set(): break
            record_event('batch.mass.start', row=key)
            try:
                matched = backend.match_mass(value, source)
            except Exception as exc:
                matched = dict(M=None, warning=f'M 未匹配：{exc}', state='M 未匹配', mass_source='', mass_config=source)
            result(key, {k:v for k,v in matched.items() if k in ('M','warning','state','mass_source','mass_config')})
            record_event('batch.mass.result', row=key, matched=matched.get('M') is not None)
    except BaseException as exc:
        record_event('batch.worker.error', action=action, error=repr(exc))
        for key, _ in requests:
            result(key, {'error': str(exc), 'state': '读取失败'} if action == 'calculate' else {'export_error': str(exc)})
    finally:
        record_event('batch.worker.finished', action=action, cancelled=cancelled.is_set())
        events.put(('finished', None, None))
