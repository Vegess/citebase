from app.services.rag import chunk_text


def test_chunk_text_splits_on_paragraphs_and_sentences():
    text = (
        "First paragraph sentence one. Second sentence here.\n\n"
        "Second paragraph only one sentence."
    )

    chunks = chunk_text(text, target_size=80, overlap_sentences=1)

    assert any("First paragraph sentence one." in chunk for chunk in chunks)
    assert any("Second sentence here." in chunk for chunk in chunks)
    assert any("Second paragraph only one sentence." in chunk for chunk in chunks)
    assert len(chunks) >= 2


def test_chunk_text_overlaps_sentences():
    text = (
        "Sentence one. Sentence two. Sentence three. Sentence four.\n\n"
        "Another paragraph sentence five."
    )

    chunks = chunk_text(text, target_size=60, overlap_sentences=1)
    assert len(chunks) >= 2
    overlapped = any(
        sentence in chunks[i] and sentence in chunks[i + 1]
        for i in range(len(chunks) - 1)
        for sentence in [
            "Sentence one.",
            "Sentence two.",
            "Sentence three.",
            "Sentence four.",
            "Another paragraph sentence five.",
        ]
    )
    assert overlapped
