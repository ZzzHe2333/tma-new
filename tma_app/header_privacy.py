"""Reversible display-only header masking (never changes source metadata)."""
import ntpath
from matplotlib.artist import Artist
from matplotlib.patches import Rectangle
from matplotlib.transforms import Bbox, IdentityTransform

BARCODE_VALUE = 'ZZZTMA POWERBYZZZHE.'
# Code 39: b/s = narrow bar/space, B/S = wide bar/space; * is start/stop.
_PATTERNS = {'M':'BsBsbsbSb', 'T':'bsbsBsBSb', 'W':'BSBsbsbsb',
             'Y':'BSbsBsbsb', ' ':'bSBsbsBsb', 'E':'BsbsBSbsb',
             '*':'bSbsBsBsb', 'A':'BsbsbSbsB', 'O':'BsbsBsbSb',
             'P':'bsBsBsbSb', 'Z':'bSBsBsbsb', 'R':'BsbsbsBSb',
             '.':'BSbsbsBsb', 'B':'bsBsbSbsB', 'H':'BsbsbSBsb'}


def barcode_runs():
    """Code39 with ten narrow-module quiet zones and no optional checksum."""
    runs = [(False, 10)]
    for i, char in enumerate('*' + BARCODE_VALUE + '*'):
        if i:
            runs.append((False, 1))
        runs.extend((c.lower() == 'b', 3 if c.isupper() else 1) for c in _PATTERNS[char])
    return runs + [(False, 10)]


class HeaderBarcode(Artist):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.set_zorder(100)

    def get_window_extent(self, renderer=None):
        label = self.text.get_window_extent(renderer)
        unit = renderer.points_to_pixels(.65)
        width = sum(n for _, n in barcode_runs()) * unit
        height = renderer.points_to_pixels(16)
        left = label.x1 if self.text.get_ha() != 'right' else label.x0 - width
        return Bbox.from_bounds(left, label.y1 - height, width, height)

    def draw(self, renderer):
        if not self.get_visible() or not self.text.get_visible():
            return
        bounds = self.get_window_extent(renderer)
        unit = renderer.points_to_pixels(.65)
        x = bounds.x0
        background = Rectangle((x, bounds.y0), bounds.width, bounds.height,
                               facecolor='white', edgecolor='none', transform=IdentityTransform())
        background.set_figure(self.figure)
        background.draw(renderer)
        for bar, count in barcode_runs():
            if bar:
                patch = Rectangle((x, bounds.y0), count * unit, bounds.height,
                                  facecolor='black', edgecolor='none', antialiased=False,
                                  transform=IdentityTransform())
                patch.set_figure(self.figure)
                patch.draw(renderer)
            x += count * unit


def privacy_bounds(text, renderer):
    bounds = text.get_window_extent(renderer)
    barcode = getattr(text, '_privacy_barcode', None)
    return Bbox.union([bounds, barcode.get_window_extent(renderer)]) if barcode else bounds


def masked_header(text, *, sample=False, mode=0):
    if not mode:
        return text
    if sample:
        return "样品: "
    prefix, separator, path = text.partition(": ")
    if mode == 1:
        return f" {ntpath.basename(path)}" if separator else text
    return " "


def apply_header_privacy(figure, sample_hidden, source_mode):
    for text in figure.texts:
        gid = text.get_gid()
        if gid not in ('tma-header', 'tma-source'):
            continue
        original = getattr(text, '_privacy_original', text.get_text())
        text._privacy_original = original
        text.set_text(masked_header(original, sample=gid == 'tma-header',
                                    mode=int(sample_hidden) if gid == 'tma-header' else source_mode))
        barcode = getattr(text, '_privacy_barcode', None)
        if barcode is not None:
            barcode.remove()
            text._privacy_barcode = None
        enabled = sample_hidden if gid == 'tma-header' else source_mode
        if enabled:
            barcode = HeaderBarcode(text)
            figure.add_artist(barcode)
            text._privacy_barcode = barcode
