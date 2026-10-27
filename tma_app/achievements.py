"""Local achievement rules and disk worker. No Qt, network or sample paths."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import queue


@dataclass(frozen=True)
class Tier:
    key: str
    name: str
    threshold: int
    base: str
    light: str
    dark: str


TIERS = (
    Tier('wood', '木', 1, '#a87b47', '#dfb779', '#54371f'),
    Tier('stone', '石', 10, '#939693', '#dadbd3', '#454b49'),
    Tier('copper', '铜', 100, '#c0784e', '#f2bc83', '#713f31'),
    Tier('iron', '铁', 300, '#b9c6c6', '#f0f4ef', '#65777c'),
    Tier('gold', '金', 1000, '#e9bd38', '#fff1a1', '#94601e'),
    Tier('diamond', '钻石', 3000, '#52cfc7', '#bcfff0', '#267e91'),
    Tier('netherite', '下界合金', 10000, '#675761', '#bd9da1', '#29232e'),
)


@dataclass(frozen=True)
class Achievement:
    key: str
    name: str
    description: str
    unit: str
    glyph: str


CATALOG = (
    Achievement('images', '把曲线装进口袋', '成功导出单图、叠图或批量图片', '张', 'picture'),
    Achievement('imports', '样品收藏家', '成功导入 TMA 数据文件，重复打开也计数', '个文件', 'folder'),
    Achievement('analysis', '曲线侦探', '新增并确定一个分析结果；编辑已有结果不重复计数', '个结果', 'lens'),
    Achievement('overlays', '曲线开派对', '成功创建含至少两条曲线的新叠图，包括复制叠图', '张叠图', 'curves'),
    Achievement('batch', '流水线小能手', '批量处理成功提取一份样品的 T1、T2、H，M 可为空', '份样品', 'blocks'),
    Achievement('tables', '表格整理师', '成功导出 CSV / XLSX，或复制批量结果表', '次', 'table'),
    Achievement('reports', '报告交付员', '成功生成单样品 PDF 或导出分析 HTML 报告', '份报告', 'page'),
    Achievement('shares', '分享小邮差', '一次分享至少有一个渠道发送成功；预览不计数', '次分享', 'mail'),
    Achievement('normalize', '公平的天平', '成功将叠图质量统一为 0.50 mg', '次', 'balance'),
)
BY_KEY = {a.key: a for a in CATALOG}


def empty():
    return {'version': 1, 'counts': {a.key: 0 for a in CATALOG}, 'earned': {}}


def validate(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('成就文件版本或格式无效')
    counts, earned = data.get('counts'), data.get('earned', {})
    if not isinstance(counts, dict) or not isinstance(earned, dict):
        raise ValueError('成就统计格式无效')
    result = empty()
    for a in CATALOG:
        n = counts.get(a.key, 0)
        if type(n) is not int or not 0 <= n <= 10**12:
            raise ValueError('成就计数无效')
        result['counts'][a.key] = n
        for t in TIERS:
            key = a.key + ':' + t.key
            if n >= t.threshold:
                stamp = earned.get(key, '')
                result['earned'][key] = stamp if isinstance(stamp, str) and len(stamp) < 80 else ''
    return result


def advance(data, key, amount=1):
    if key not in BY_KEY or type(amount) is not int or not 1 <= amount <= 10**9:
        raise ValueError('未知成就或计数增量无效')
    before = data['counts'][key]
    after = min(10**12, before + amount)
    data['counts'][key] = after
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    unlocked = []
    for tier in TIERS:
        if before < tier.threshold <= after:
            data['earned'][key + ':' + tier.key] = stamp
            unlocked.append(tier.key)
    return unlocked


def load(paths):
    """Read a small local JSON; a damaged file is never silently overwritten."""
    existing = []
    for path in paths:
        try: existing.append((path.stat().st_mtime_ns, path))
        except FileNotFoundError: pass
    if not existing: return empty(), paths[0]
    path = max(existing, key=lambda entry: entry[0])[1]
    if path.stat().st_size > 128 * 1024: raise ValueError('成就文件过大')
    return validate(json.loads(path.read_text(encoding='utf-8-sig'))), path


def disk_worker(paths, fallback, commands, events):
    """A single daemon owns all state and serial writes; never touches Qt."""
    writable = True
    try: state, location = load(paths)
    except (OSError, ValueError, TypeError) as exc:
        state, location, writable = empty(), paths[0], False
        events.put(('error', '成就统计未载入，原文件已保留；可清除统计后重新开始。' + str(exc)))
    epoch = 0
    events.put(('state', json.loads(json.dumps(state)), [], str(location), epoch))
    while True:
        command = commands.get()
        unlocked = []
        stopping = False
        try:
            # Coalesce a burst of batch rows into one small disk transaction.
            pending = [command]
            for _ in range(255):
                try: pending.append(commands.get_nowait())
                except queue.Empty: break
            changed = False
            for item in pending:
                if item[0] == 'stop': stopping = True; continue
                if item[0] == 'reset':
                    epoch = item[1]
                    state, writable, unlocked = empty(), True, []
                    changed = True
                elif item[0] == 'record':
                    tiers = advance(state, item[1], item[2]); changed = True
                    if tiers: unlocked.append((item[1], tiers[-1]))
            if changed and writable:
                from .atomic_files import write_json
                try:
                    write_json(paths[0], state); location = paths[0]
                except OSError:
                    if fallback is None: raise
                    write_json(fallback, state); location = fallback
            if changed:
                events.put(('state', json.loads(json.dumps(state)), unlocked, str(location), epoch))
        except (OSError, ValueError, TypeError) as exc:
            from .diagnostics import record_event
            record_event('achievements.storage.error',error=str(exc))
            events.put(('error', '成就统计暂未保存：' + str(exc)))
            events.put(('state', json.loads(json.dumps(state)), unlocked, str(location), epoch))
        finally:
            for _ in pending: commands.task_done()
        if stopping: return
