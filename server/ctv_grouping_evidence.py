"""Bounded, process-local grouping facts that never enter public inspection data."""

from dataclasses import dataclass
import re
import unicodedata


_DUPLICATE_GROUP_ID = re.compile(r"duplicate-\d{4}\Z")


@dataclass(frozen=True)
class UnitTextKey:
    evidence_id: str
    unit_kind: str
    unit_index: int


def _normalized_private_text(private_text: str) -> str:
    normalized = unicodedata.normalize("NFKD", private_text)
    characters = []
    previous_was_space = True
    for character in normalized.upper():
        if unicodedata.combining(character):
            continue
        if character.isalnum():
            characters.append(character)
            previous_was_space = False
        elif not previous_was_space:
            characters.append(" ")
            previous_was_space = True
    return "".join(characters).strip()


def _text_key(evidence_id, unit_kind, unit_index) -> UnitTextKey:
    if type(evidence_id) is not str:
        raise TypeError("evidence id must be str")
    if type(unit_kind) is not str:
        raise TypeError("unit kind must be str")
    if type(unit_index) is not int:
        raise TypeError("unit index must be int")
    return UnitTextKey(evidence_id, unit_kind, unit_index)


class GroupingEvidence:
    def __init__(
        self,
        *,
        max_units: int = 10_000,
        max_chars_per_unit: int = 32 * 1024,
        max_total_chars: int = 16 * 1024 * 1024,
    ) -> None:
        for value in (max_units, max_chars_per_unit, max_total_chars):
            if type(value) is not int:
                raise TypeError("grouping evidence limits must be int")
            if value <= 0:
                raise ValueError("grouping evidence limits must be positive")
        self._limits = (max_units, max_chars_per_unit, max_total_chars)
        self._texts = {}
        self._seen_keys = set()
        self._complete_keys = set()
        self._duplicate_groups = {}
        self._used = 0
        self._sealed = False
        self.complete = True

    def capture(self, evidence_id, unit_kind, unit_index, private_text) -> None:
        key = _text_key(evidence_id, unit_kind, unit_index)
        if type(private_text) is not str:
            raise TypeError("private text must be str")
        if key in self._seen_keys:
            raise ValueError("grouping evidence unit text already captured")
        if self._sealed:
            self.complete = False
            return

        normalized = _normalized_private_text(private_text)
        max_units, max_chars_per_unit, max_total_chars = self._limits
        if len(self._seen_keys) >= max_units:
            self._sealed = True
            self.complete = False
            return
        self._seen_keys.add(key)
        if (
            len(normalized) > max_chars_per_unit
            or self._used + len(normalized) > max_total_chars
        ):
            self.complete = False
            return
        self._texts[key] = normalized
        self._complete_keys.add(key)
        self._used += len(normalized)

    def text_for(self, evidence_id, unit_kind, unit_index) -> str:
        return self._texts.get(_text_key(evidence_id, unit_kind, unit_index), "")

    def complete_for(self, evidence_id, unit_kind, unit_index) -> bool:
        return _text_key(evidence_id, unit_kind, unit_index) in self._complete_keys

    def capture_source_duplicate(self, evidence_id, duplicate_group_id) -> None:
        if type(evidence_id) is not str:
            raise TypeError("evidence id must be str")
        if type(duplicate_group_id) is not str:
            raise TypeError("duplicate group id must be str")
        if _DUPLICATE_GROUP_ID.fullmatch(duplicate_group_id) is None:
            raise ValueError("duplicate group id must be opaque")
        if evidence_id in self._duplicate_groups:
            raise ValueError("grouping evidence duplicate already captured")
        self._duplicate_groups[evidence_id] = duplicate_group_id

    def duplicate_group_for(self, evidence_id) -> str | None:
        if type(evidence_id) is not str:
            raise TypeError("evidence id must be str")
        return self._duplicate_groups.get(evidence_id)

    def clear(self) -> None:
        self._texts.clear()
        self._seen_keys.clear()
        self._complete_keys.clear()
        self._duplicate_groups.clear()
        self._used = 0
        self._sealed = False
        self.complete = False
