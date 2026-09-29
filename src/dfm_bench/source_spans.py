"""Opt-in verbatim source-span selection for future evidence packets.

This does not alter existing card extraction, active pilots or frozen outputs.
A future packet policy can show span IDs and ask a judge to select IDs instead of
copying prose. Offsets count Python Unicode characters, not UTF-8 bytes. Hashes
use the exact UTF-8 source, with no newline or whitespace normalization. Paragraph
and whitespace boundaries are preferred, but long tokens/code may be split.
"""
import hashlib

FIELDS = ("claim", "increment", "evidence", "decisive_test", "alternatives", "limitations")
MAX_CHARS = 1200


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _span_id(source_hash, start, end, text_hash):
    return f"span-{start:08d}-{end:08d}-{source_hash[:16]}-{text_hash[:16]}"


def split_source(text, max_chars=MAX_CHARS):
    """Partition exact source into stable, nonempty, bounded spans without loss."""
    if not isinstance(text, str):
        raise ValueError("Source must be a string")
    if type(max_chars) is not int or not 1 <= max_chars <= MAX_CHARS:
        raise ValueError("max_chars must be an integer from 1 through 1200")
    source_hash = _sha(text)
    spans, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Avoid pathological short chunks; never remove boundary whitespace.
            floor = start + max(1, max_chars // 2)
            newline = text.rfind("\n", floor, end)
            if newline >= floor:
                end = newline + 1
            else:
                boundary = next((i for i in range(end - 1, floor - 1, -1) if text[i].isspace()), None)
                if boundary is not None:
                    end = boundary + 1
        exact = text[start:end]
        text_hash = _sha(exact)
        spans.append({"id": _span_id(source_hash, start, end, text_hash),
                      "start": start, "end": end, "text": exact,
                      "source_sha256": source_hash, "span_sha256": text_hash})
        start = end
    return spans


def selection_to_card(source, spans, selection):
    """Validate source/span integrity and six-field ID selection; return quotes.

    The complete span bank must partition this exact source. Selecting a span
    twice within a field is invalid; reuse across different fields is permitted.
    Missing fields are invalid: explicitly use null for absent evidence.
    """
    if not isinstance(source, str) or not isinstance(spans, list):
        raise ValueError("Source must be text and spans a list")
    if not isinstance(selection, dict) or set(selection) != set(FIELDS):
        raise ValueError("Selection must contain exactly the six card fields")
    source_hash, bank, intervals = _sha(source), {}, []
    required = {"id", "start", "end", "text", "source_sha256", "span_sha256"}
    for span in spans:
        if not isinstance(span, dict) or set(span) != required:
            raise ValueError("Invalid span record fields")
        start, end, text = span["start"], span["end"], span["text"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source):
            raise ValueError("Invalid source offsets")
        if not isinstance(text, str) or len(text) > MAX_CHARS or text != source[start:end]:
            raise ValueError("Span text does not match exact bounded source slice")
        text_hash = _sha(text)
        expected_id = _span_id(source_hash, start, end, text_hash)
        if span["source_sha256"] != source_hash or span["span_sha256"] != text_hash or span["id"] != expected_id:
            raise ValueError("Source hash, span hash or span ID was mutated")
        if expected_id in bank:
            raise ValueError("Duplicate span ID")
        bank[expected_id] = text
        intervals.append((start, end))
    cursor = 0
    for start, end in sorted(intervals):
        if start != cursor:
            raise ValueError("Span bank has a gap or overlap")
        cursor = end
    if cursor != len(source):
        raise ValueError("Span bank does not cover the source")
    card = {}
    for field in FIELDS:
        ids = selection[field]
        if ids is None:
            if field == "claim":
                raise ValueError("Claim requires at least one span")
            card[field] = None
            continue
        if not isinstance(ids, list) or not 1 <= len(ids) <= 2 or any(not isinstance(i, str) for i in ids):
            raise ValueError("Fields require null or one to two span IDs")
        if len(set(ids)) != len(ids) or any(i not in bank for i in ids):
            raise ValueError("Unknown or repeated span ID")
        card[field] = [bank[i] for i in ids]
    return card
