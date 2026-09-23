"""Quote matching, not semantic fact generation.

Only whitespace can vary. Returned quotes always contain the original source
characters. Disjoint passages must be explicitly separated by newlines, and
each passage is checked independently; no fuzzy or bag-of-words matching.
"""
from __future__ import annotations

import re


def compact(text: str) -> str:
    return " ".join(text.split())


def original_quote(quote: str, source: str, *, protect_negation: bool = False) -> str | None:
    if not isinstance(quote, str) or not quote.strip() or not isinstance(source, str):
        return None
    variants = [quote.strip()]
    for opening, closing in (("\"", "\""), ("«", "»"), ("“", "”"), ("'", "'")):
        if quote.startswith(opening) and quote.endswith(closing):
            variants.append(quote[1:-1].strip())
    for candidate in variants:
        pattern = r"\s+".join(re.escape(token) for token in candidate.split())
        if not pattern:
            continue
        for match in re.finditer(pattern, source):
            # Do not accept substrings inside words or numbers.
            if match.start() and source[match.start()-1].isalnum() and candidate[0].isalnum():
                continue
            if match.end() < len(source) and source[match.end()].isalnum() and candidate[-1].isalnum():
                continue
            if protect_negation:
                prefix = re.split(r"[.!?;]", source[:match.start()])[-1]
                suffix = re.split(r"[.!?;\n]", source[match.end():])[0]
                # A narrow safety guard, not a semantic classifier: request the
                # containing clause when an excerpt has cut off its negation.
                if re.search(r"\b(?:not|never|without|no|cannot|can['’]t|don['’]t|doesn['’]t|won['’]t|mustn['’]t|не|нельзя|без|запрещено)\b", prefix, re.I):
                    continue
                if re.match(r"\s+(?:емес|жоқ|қажет емес|запрещ[её]н[аоы]?)\b", suffix, re.I):
                    continue
            return match.group(0)
    return None


def resolve_spans(value: str, sources: dict[str, str], *, protect_negation: bool = True) -> list[dict[str, str]]:
    """Return verified original passages, or reject unsupported composition."""
    if not value:
        return []
    for name, source in sources.items():
        quote = original_quote(value, source, protect_negation=protect_negation)
        if quote is not None:
            return [{"source": name, "quote": quote}]
    parts = [part.strip() for part in value.splitlines() if part.strip()]
    if not 2 <= len(parts) <= 40:
        raise ValueError("use original source wording; separate disjoint full clauses with newlines")
    verified = []
    for part in parts:
        found = next(({"source": name, "quote": quote} for name, source in sources.items()
                      if (quote := original_quote(part, source, protect_negation=protect_negation)) is not None), None)
        if found is None:
            raise ValueError("a passage is unsupported or omits a negation; include its original full clause")
        if found not in verified:
            verified.append(found)
    return verified


def source_passages(sources: dict[str, str]) -> list[dict[str, str]]:
    """Number original sentence/line spans without rewriting their contents.

    Dense sources share a total budget of 64 passages. Adjacent grouping retains
    delimiters verbatim. A newline alone NEVER splits a clause: otherwise
    'do not\ncollect names' could become a misleading positive quotation.
    """
    result = []
    per_source = max(1, 64 // max(1, sum(bool(text) for text in sources.values())))
    for source, text in sources.items():
        if not text:
            continue
        boundaries = [0] + [match.end() for match in re.finditer(r"(?<=[.!?])\s+", text)] + [len(text)]
        spans = [(start, end) for start, end in zip(boundaries, boundaries[1:]) if text[start:end].strip()]
        group_size = max(1, (len(spans) + per_source - 1) // per_source)
        for offset in range(0, len(spans), group_size):
            group = spans[offset:offset+group_size]
            quote = text[group[0][0]:group[-1][1]].strip()
            result.append({"id": f"s{len(result)+1}", "source": source, "quote": quote})
    return result
