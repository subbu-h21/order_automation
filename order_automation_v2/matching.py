import re
from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.70
RESCUE_THRESHOLD = 0.50

_DOSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(MG|MCG)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _dose(name: str):
    """First (value, unit) dosage found, e.g. (75.0, 'mg'). None if no
    explicit MG/MCG strength is present in the name."""
    match = _DOSE_RE.search(name)
    if not match:
        return None
    return float(match.group(1)), match.group(2).lower()


def _numbers(name: str) -> set:
    return {float(n) for n in _NUMBER_RE.findall(name)}


def _first_word(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name)
    return words[0].upper() if words else ""


def _shares_first_word(a: str, b: str) -> bool:
    first = _first_word(a)
    if not first:
        return False
    return re.search(rf"\b{re.escape(first)}\b", b, re.IGNORECASE) is not None


def is_confident_match(crm_name: str, matched_name: str) -> bool:
    dose_a = _dose(crm_name)
    dose_b = _dose(matched_name)
    if dose_a and dose_b and dose_a[1] == dose_b[1] and dose_a[0] != dose_b[0]:
        return False  # explicit strength conflict (e.g. 75MG vs 25MG) - hard veto

    score = similarity(crm_name, matched_name)
    if score >= SIMILARITY_THRESHOLD:
        return True

    # Rescue path: same brand word, no conflicting numbers anywhere in the
    # name, and at least a moderate similarity - catches legitimate matches
    # that differ mainly in pack-size phrasing ("TAB" vs "Tablet 10 NO'S").
    if score < RESCUE_THRESHOLD:
        return False
    if not _shares_first_word(crm_name, matched_name):
        return False
    nums_a, nums_b = _numbers(crm_name), _numbers(matched_name)
    if nums_a and nums_b and nums_a.isdisjoint(nums_b):
        return False
    return True
