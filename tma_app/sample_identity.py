"""Internal sample-number recognition; no UI or public feature switch yet.

Recognition is descriptive only: never rewrite sample names or source files.
Two-digit production years are interpreted as 2000--2099.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
import unicodedata


@dataclass(frozen=True)
class SampleIdentity:
    kind: str  # experiment, production_a, production_b, external
    matched: str
    canonical: str
    model: str | None = None
    date: date | None = None
    year: int | None = None
    month: int | None = None
    reactor: int | None = None
    sequence: int | None = None
    repeat: int | None = None
    suffix: str = ""

    @property
    def repeated_test(self) -> bool:
        return self.repeat is not None


_EXPERIMENT = re.compile(
    r"(?<![A-Za-z0-9])(?P<day>20\d{6})(?:-(?P<reactor>[1-9]\d?)#?|(?P<compact>\d{2}))"
    r"(?P<repeat>-\d+)?(?![A-Za-z0-9#])"
)
_PRODUCTION = re.compile(
    r"(?<![A-Za-z0-9])(?P<model>[A-Za-z][A-Za-z0-9]*)-(?P<number>\d+)(?![A-Za-z0-9])"
)
_EXTERNAL = re.compile(r"(?<![A-Za-z0-9])W456[A-Za-z0-9]*(?:-[A-Za-z0-9#-]+)?", re.I)


def recognize_sample(text: str) -> SampleIdentity | None:
    """Recognize a sample name or filename, retaining trailing descriptive text.

    Unknown or invalid dates/serials return None. W456 models take priority.
    Compact experiment numbers use a two-digit reactor (01--99).
    """
    text = unicodedata.normalize("NFKC", str(text)).strip()
    external = _EXTERNAL.search(text)
    if external:
        matched = external.group()
        return SampleIdentity("external", matched, matched.upper(),
                              model=matched.split("-", 1)[0].upper(),
                              suffix=text[external.end():])
    for match in _EXPERIMENT.finditer(text):
        try:
            day = date.fromisoformat(match["day"][:4] + "-" + match["day"][4:6] + "-" + match["day"][6:])
        except ValueError:
            continue
        reactor = int(match["reactor"] or match["compact"])
        repeat = int(match["repeat"][1:]) if match["repeat"] else None
        if reactor == 0 or repeat == 0:
            continue
        return SampleIdentity("experiment", match.group(), f"{match['day']}-{reactor}",
                              date=day, year=day.year, month=day.month,
                              reactor=reactor, repeat=repeat, suffix=text[match.end():])
    for match in _PRODUCTION.finditer(text):
        number = match["number"]
        model = match["model"].upper()
        if len(number) == 7:
            year, month, serial = 2000 + int(number[:2]), int(number[2:4]), int(number[4:])
            if not 1 <= month <= 12 or not 1 <= serial <= 999:
                continue
            return SampleIdentity("production_a", match.group(), f"{model}-{number}",
                                  model=model, year=year, month=month, sequence=serial,
                                  suffix=text[match.end():])
        digits = number[2:] if len(number) == 10 and number.startswith("11") else number
        if len(digits) != 8:
            continue
        try:
            day = date(2000 + int(digits[:2]), int(digits[2:4]), int(digits[4:6]))
        except ValueError:
            continue
        serial = int(digits[6:])
        if serial == 0:
            continue
        return SampleIdentity("production_b", match.group(), f"{model}-{number}",
                              model=model, date=day, year=day.year, month=day.month,
                              sequence=serial, suffix=text[match.end():])
    return None
