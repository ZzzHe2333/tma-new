"""Temporary pastel frames in the existing export margin."""
from contextlib import contextmanager

from .sample_identity import recognize_sample

COLORS = {"experiment": "#F6DCE6", "production_a": "#F9E2CB",
          "production_b": "#F9E2CB", "external": "#DDEEDC"}
FALLBACK = "#E7E7EA"


def frame_color(identities):
    colors = [COLORS.get(item.kind, FALLBACK) if item else FALLBACK for item in identities]
    # Mixed/unknown overlays must not suggest a single known sample category.
    return colors[0] if colors and len(set(colors)) == 1 else FALLBACK


def dataset_frame_color(datasets):
    identities = []
    for ds in datasets:
        sample = recognize_sample(ds.name)
        filename = recognize_sample(ds.path.stem)
        if sample and filename and COLORS.get(sample.kind) != COLORS.get(filename.kind):
            identities.append(None)
        else:
            identities.append(sample or filename)
    return frame_color(identities)


@contextmanager
def export_frame(figure, color):
    from matplotlib.patches import Rectangle
    width, height = figure.get_size_inches()
    margin = .13
    patch = Rectangle((-margin / width, -margin / height),
                      1 + 2 * margin / width, 1 + 2 * margin / height,
                      transform=figure.transFigure, fill=False, edgecolor=color,
                      linewidth=7, clip_on=False, zorder=10000)
    figure.add_artist(patch)
    try:
        yield
    finally:
        patch.remove()
