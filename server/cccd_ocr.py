"""Local-only OCR helpers for CCCD images extracted from a workbook."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

import pytesseract
from PIL import Image, ImageOps

from cccd_workbook import EmbeddedDrawing
from ocr_extract import _upright_rotation, norm


Side = Literal["front", "back", "unknown"]


@dataclass(frozen=True)
class OcrWord:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float


@dataclass(frozen=True)
class CccdImageOcr:
    side: Side
    side_confidence: float
    cccd: str
    cccd_confidence: float
    name: str
    name_confidence: float
    number_bbox: dict[str, int] | None


def _group_words_into_lines(
    words: list[OcrWord],
    y_tolerance: int = 8,
) -> list[list[OcrWord]]:
    lines: list[list[OcrWord]] = []
    for word in sorted(words, key=lambda item: (item.y, item.x)):
        if not lines or abs(word.y - lines[-1][0].y) > y_tolerance:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda item: item.x) for line in lines]


def _clean_token(text: str) -> str:
    return norm(text).strip(" :;,.\t\n")


def _contains_phrase(words: list[OcrWord], phrase: str) -> tuple[bool, float]:
    tokens = [_clean_token(word.text) for word in words]
    wanted = phrase.split()
    for start in range(len(tokens) - len(wanted) + 1):
        if tokens[start:start + len(wanted)] == wanted:
            confidence = min(
                word.confidence for word in words[start:start + len(wanted)]
            )
            return True, confidence
    return False, 0.0


def _marker_groups(words: list[OcrWord], phrases: tuple[str, ...]) -> list[float]:
    groups = []
    for phrase in phrases:
        confidences = [
            confidence
            for line in _group_words_into_lines(words)
            if (found := _contains_phrase(line, phrase))[0]
            for confidence in [found[1]]
        ]
        if confidences:
            groups.append(max(confidences))
    return groups


_FRONT_MARKERS = ("can cuoc cong dan", "so", "ho va ten", "ngay sinh")
_BACK_MARKERS = ("dac diem nhan dang", "ngay cap", "co quan cap", "bo cong an")


def _has_cccd_mrz(words: list[OcrWord]) -> tuple[bool, float]:
    tokens = [
        re.sub(r"\s", "", word.text).upper()
        for word in words
        if word.confidence >= .5
    ]
    first = [
        word.confidence
        for word, token in zip(words, tokens)
        if token.startswith("IDVNM") and len(token) >= 20
    ]
    mrz_tokens = [
        word.confidence
        for word in words
        if len(re.sub(r"\s", "", word.text)) >= 20
        and ("<" in word.text or "VNM" in word.text.upper())
    ]
    if first and len(mrz_tokens) >= 2:
        return True, min(max(first), min(mrz_tokens))
    return False, 0.0


def _unique_twelve_digit_word(words: list[OcrWord]) -> OcrWord | None:
    candidates = [
        word
        for word in words
        if len(_digits(word)) == 12
        and word.width > 0
        and word.height > 0
        and word.confidence >= 0
    ]
    return candidates[0] if len(candidates) == 1 else None


def classify_side(words: list[OcrWord]) -> tuple[Side, float]:
    """Classify from strong marker groups or conservative structural signals."""
    front_markers = _marker_groups(words, _FRONT_MARKERS)
    back_markers = _marker_groups(words, _BACK_MARKERS)
    number_word = _unique_twelve_digit_word(words)
    mrz, mrz_confidence = _has_cccd_mrz(words)

    front_strong = len(front_markers) >= 2
    front_structural = number_word is not None and bool(front_markers)
    back_strong = len(back_markers) >= 2
    front = front_strong or front_structural
    back = back_strong or mrz

    if front and back:
        return "unknown", 0.0
    if front:
        marker_confidence = (
            min(front_markers)
            if front_strong
            else max(front_markers)
        )
        return "front", min(
            marker_confidence,
            number_word.confidence if front_structural else marker_confidence,
        )
    if back:
        confidence = min(back_markers) if back_strong else mrz_confidence
        return "back", confidence
    return "unknown", 0.0


def _number_label_span(line: list[OcrWord]) -> tuple[int, int] | None:
    tokens = [_clean_token(word.text) for word in line]
    for index, token in enumerate(tokens):
        if token == "so":
            return index, index + 1
        if tokens[index:index + 4] == ["so", "dinh", "danh", "ca"]:
            return index, index + 4
    return None


def _digits(word: OcrWord) -> str:
    return "".join(character for character in word.text if character.isdigit())


def _words_right_of(
    line: list[OcrWord],
    label: tuple[int, int],
    min_confidence: float,
) -> list[OcrWord]:
    label_right = max(word.x + word.width for word in line[label[0]:label[1]])
    return [
        word
        for word in line[label[1]:]
        if word.x >= label_right
        and word.confidence >= min_confidence
        and _digits(word)
    ]


def _next_line_digits(
    lines: list[list[OcrWord]],
    line_index: int,
) -> list[OcrWord]:
    if line_index + 1 >= len(lines):
        return []
    return [
        word
        for word in lines[line_index + 1]
        if word.confidence >= .5 and _digits(word)
    ]


def _padded_union(
    words: list[OcrWord],
    image_width: int,
    image_height: int,
    pad: int,
) -> dict[str, int]:
    x0 = max(0, min(word.x for word in words) - pad)
    y0 = max(0, min(word.y for word in words) - pad)
    x1 = min(
        image_width,
        max(word.x + word.width for word in words) + pad,
    )
    y1 = min(
        image_height,
        max(word.y + word.height for word in words) + pad,
    )
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def locate_number_region(
    words: list[OcrWord],
    image_width: int,
    image_height: int,
) -> dict[str, int] | None:
    """Prefer a printed label, then recover one unique 12-digit OCR word."""
    lines = _group_words_into_lines(words)
    for line_index, line in enumerate(lines):
        label = _number_label_span(line)
        if label is None:
            continue
        same_line = _words_right_of(line, label, min_confidence=.5)
        target = same_line or _next_line_digits(lines, line_index)
        if target:
            return _padded_union(target, image_width, image_height, pad=6)
    fallback = _unique_twelve_digit_word(words)
    if fallback is None:
        return None
    return _padded_union([fallback], image_width, image_height, pad=6)


def _upright_image(path: str) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    try:
        osd = pytesseract.image_to_osd(
            image,
            output_type=pytesseract.Output.DICT,
        )
        rotation = _upright_rotation(
            int(osd.get("rotate", 0)),
            float(osd.get("orientation_conf", 0.0)),
        )
    except Exception:
        rotation = 0
    return image.rotate(rotation, expand=True) if rotation else image


def _full_image_words(image: Image.Image) -> list[OcrWord]:
    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
    )
    words = []
    for index, text in enumerate(data["text"]):
        text = text.strip()
        confidence = _confidence(data["conf"][index])
        if text and confidence >= 0:
            words.append(OcrWord(
                text=text,
                x=int(data["left"][index]),
                y=int(data["top"][index]),
                width=int(data["width"][index]),
                height=int(data["height"][index]),
                confidence=confidence,
            ))
    return words


def _confidence(value: object) -> float:
    try:
        return float(value) / 100
    except (TypeError, ValueError):
        return -1.0


def _region_digits(
    image: Image.Image,
    bbox: dict[str, int],
) -> tuple[str, float]:
    crop = image.crop((
        bbox["x"],
        bbox["y"],
        bbox["x"] + bbox["width"],
        bbox["y"] + bbox["height"],
    ))
    data = pytesseract.image_to_data(
        crop,
        config="--psm 7 -c tessedit_char_whitelist=0123456789",
        output_type=pytesseract.Output.DICT,
    )
    readable = [
        (text.strip(), _confidence(data["conf"][index]))
        for index, text in enumerate(data["text"])
        if text.strip() and _confidence(data["conf"][index]) >= 0
    ]
    if not readable:
        return "", 0.0
    return (
        "".join(text for text, _ in readable),
        min(confidence for _, confidence in readable),
    )


def _name_from_words(words: list[OcrWord]) -> tuple[str, float]:
    lines = _group_words_into_lines(words)
    for line_index, line in enumerate(lines):
        found, _ = _contains_phrase(line, "ho va ten")
        if not found:
            continue
        label = _name_label_span(line)
        candidates = _name_value_words(line[label[1]:])
        if (
            not candidates
            and line_index + 1 < len(lines)
            and _next_line_is_name_value(line, label, lines[line_index + 1])
        ):
            candidates = _name_value_words(lines[line_index + 1])
        if candidates:
            return (
                " ".join(
                    word.text.strip(" :;,.\t\n") for word in candidates
                ),
                min(word.confidence for word in candidates),
            )
    return "", 0.0


def _name_value_words(words: list[OcrWord]) -> list[OcrWord]:
    return [
        word
        for word in words
        if word.confidence >= .5
        and not _digits(word)
        and _clean_token(word.text)
    ]


def _next_line_is_name_value(
    label_line: list[OcrWord],
    label: tuple[int, int],
    next_line: list[OcrWord],
) -> bool:
    label_words = label_line[label[0]:label[1]]
    label_left = min(word.x for word in label_words)
    label_right = max(word.x + word.width for word in label_words)
    label_width = label_right - label_left
    label_bottom = max(word.y + word.height for word in label_words)
    next_left = min(word.x for word in next_line)
    vertical_gap = min(word.y for word in next_line) - label_bottom
    return (
        -40 <= next_left - label_left <= label_width + 40
        and 0 <= vertical_gap
        <= max(40, 2 * max(word.height for word in label_words))
    )


def _name_label_span(line: list[OcrWord]) -> tuple[int, int]:
    tokens = [_clean_token(word.text) for word in line]
    wanted = ["ho", "va", "ten"]
    for index in range(len(tokens) - len(wanted) + 1):
        if tokens[index:index + len(wanted)] == wanted:
            return index, index + len(wanted)
    raise ValueError("name label was not found")


def analyze_drawing(drawing: EmbeddedDrawing) -> CccdImageOcr:
    """Analyze one drawing and re-OCR only a safely located number crop."""
    image = _upright_image(drawing.stored_path)
    words = _full_image_words(image)
    side, side_confidence = classify_side(words)
    number_bbox = locate_number_region(words, image.width, image.height)
    name, name_confidence = _name_from_words(words)
    cccd = ""
    cccd_confidence = 0.0
    if number_bbox is not None:
        region_text, confidence = _region_digits(image, number_bbox)
        candidate = re.sub(r"\D", "", region_text)
        if len(candidate) == 12:
            cccd = candidate
            cccd_confidence = confidence
    return CccdImageOcr(
        side=side,
        side_confidence=side_confidence,
        cccd=cccd,
        cccd_confidence=cccd_confidence,
        name=name,
        name_confidence=name_confidence,
        number_bbox=number_bbox,
    )
