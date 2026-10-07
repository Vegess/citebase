"""Pick the sources an answer actually used.

The model is shown sources numbered [1]..[k] and told to cite with those
markers. We return only the sources it cited, so a source chip always points
at a passage the answer relied on. Before this, every retrieved chunk was
returned, which is why a "the document isn't available" reply still showed
three resume citations.
"""
import re

_MARKER = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")

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
        {"filename": c["filename"], "chunk_index": c["chunk_index"], "n": i}
        for i, c in enumerate(chunks, start=1)
    ]
    used = cited_numbers(answer, len(chunks))
    if used:
        return [numbered[n - 1] for n in sorted(used)]
    if looks_like_abstention(answer):
        return []
    # The model answered but forgot markers: fall back to every source shown,
    # rather than presenting an answer with no way to verify it.
    return numbered
