"""Capture known weighing preferences without disk work on the GUI."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PendingMassSource:
    profile: str

    def resolve(self):
        from .path_settings import _read_settings
        data = _read_settings(primary=Path(self.profile))[1]
        paths = data.get('paths', {})
        if not isinstance(paths, dict) or not isinstance(paths.get('m', ''), str):
            raise ValueError('m 路径配置格式无效')
        return paths.get('m', '').strip()


def capture_mass_source():
    from .path_settings import cached_mass_source, config_path, refresh_in_background
    value = cached_mass_source()
    if value is not None:
        refresh_in_background(min_interval=30)
        return value
    return PendingMassSource(str(config_path()))
