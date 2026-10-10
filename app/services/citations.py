"""Pick the sources an answer actually used.

The model is shown sources numbered [1]..[k] and told to cite with those
markers. We return only the sources it cited, so a source chip always points
at a passage the answer relied on. Before this, every retrieved chunk was
returned, which is why a "the document isn't available" reply still showed
three resume citations.
"""
import re

_MARKER = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")

# Models don't always use plain [1]. Seen in production: 【1】 (gpt-oss), and
# other common variants: ［1］, 〔1〕, [^1], [source 1], 【1†L4-L9】, [1，2].
_VARIANT = re.compile(
    r"[\[【［〔]\s*(?:\^|source\s*)?"
    r"(\d{1,2}(?:\s*[,，、]\s*\d{1,2})*)"
    r"(?:\s*†[^\]】］〕]*)?\s*[\]】］〕]",
    re.IGNORECASE,
)


def normalize_markers(answer: str) -> str:
    """Rewrite every citation-marker variant to the canonical [1] / [1, 2] form."""
    def canonical(match: re.Match) -> str:
        numbers = re.split(r"\s*[,，、]\s*", match.group(1).strip())
        return "[" + ", ".join(numbers) + "]"

    return _merge_runs(_VARIANT.sub(canonical, answer or ""))


# Two or more canonical markers in a row: "[3][3]", "[1] [2]", "[3], [4]".
_RUN = re.compile(r"\[\d{1,2}(?:, \d{1,2})*\](?:(?:\s*,\s*|\s*)\[\d{1,2}(?:, \d{1,2})*\])+(?!\()")


def _merge_runs(text: str) -> str:
    """Collapse adjacent markers into one, without duplicates: [3][3] -> [3], [1][2] -> [1, 2]."""
    def merge(match: re.Match) -> str:
        numbers = sorted({int(n) for n in re.findall(r"\d{1,2}", match.group(0))})
        return "[" + ", ".join(str(n) for n in numbers) + "]"

    return _RUN.sub(merge, text)

# A reply that says the answer is not in the documents must not carry sources.
_ABSTAIN = re.compile(
    r"\b(couldn'?t|could not|can'?t|cannot|unable to) "
    r"(find|locate|answer|review|rate|assess|summari[sz]e|see|access)"
    r"|\b(not|n't|never)( been)? (mentioned|provided|uploaded|available|included|covered|specified|found)"
    r"|\bno (relevant )?information"
    r"|\b(doesn'?t|does not|do not|don'?t) (mention|contain|include|cover|say|specify)",
    re.IGNORECASE,
)


def cited_numbers(answer: str, available: int) -> list[int]:
    seen: list[int] = []
    for group in _MARKER.findall(answer or ""):
        for part in group.split(","):
            n = int(part.strip())
            if 1 <= n <= available and n not in seen:
                seen.append(n)
    return seen


def looks_like_abstention(answer: str) -> bool:
    return bool(_ABSTAIN.search(answer or ""))


def select_citations(answer: str, chunks: list[dict]) -> list[dict]:
    """Return [{n, filename, chunk_index}] for the sources the answer used."""
    numbered = [
        {"filename": c["filename"], "chunk_index": c["chunk_index"], "n": i, **({"doc_id": c["doc_id"]} if c.get("doc_id") else {})}
        for i, c in enumerate(chunks, start=1)
    ]
    used = cited_numbers(normalize_markers(answer), len(chunks))
    if used:
        return [numbered[n - 1] for n in sorted(used)]
    if looks_like_abstention(answer):
        return []
    # The model answered but forgot markers: fall back to every source shown,
    # rather than presenting an answer with no way to verify it.
    return numbered
