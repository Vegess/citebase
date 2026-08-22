import sys
from types import SimpleNamespace

import pytest
import numpy as np
from fastapi.testclient import TestClient


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    chroma_dir = tmp_path / "chroma"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)

    import app.core.database as database_module
    import app.main as main_module
    import app.routes.documents as documents_module
    import app.services.generation as generation_module
    import app.services.rag as rag_module

    class FakeEmbeddingResult(list):
        def tolist(self):
            return [list(item) for item in self]

    class FakeEmbedder:
        """Mock embedder matching fastembed interface.
        
        Key differences from old sentence-transformers version:
        - .embed(texts) instead of .encode(texts, show_progress_bar=False)
        - .embed() returns a generator of individual 1-D numpy arrays
        - Text-dependent vectors: hash of text content seeds the RNG to produce
          consistent, unique vectors per text (ensures retrieval tests work correctly)
        """
        def embed(self, texts):
            """Generate embeddings as a generator of 1-D numpy arrays.
            
            Each text produces a deterministic embedding based on its hash:
            - Same text always produces the same vector
            - Different texts produce different vectors
            This preserves the org isolation tests that rely on real retrieval behavior.
            """
            for text in texts:
                # Hash the text to get a seed (deterministic and different per text)
                seed = hash(text) % (2**31)
                # Create a pseudo-random but stable vector
                rng = np.random.RandomState(seed)
                # Generate a 384-dim vector (typical for all-MiniLM-L6-v2)
                vector = rng.randn(384).astype(np.float32)
                # Normalize to unit length (like real embeddings)
                vector = vector / np.linalg.norm(vector)
                yield vector

    class FakeCollection:
        def __init__(self):
            self.items = []

        def add(self, ids, embeddings, documents, metadatas):
            for doc_id, doc, meta in zip(ids, documents, metadatas):
                self.items.append({"id": doc_id, "document": doc, "metadata": meta})

        def query(self, query_embeddings, n_results, where):
            filtered = [item for item in self.items if item["metadata"]["org_id"] == where["org_id"]]
            return {
                "documents": [[item["document"] for item in filtered[:n_results]]],
                "metadatas": [[item["metadata"] for item in filtered[:n_results]]],
                "distances": [[0.0 for _ in filtered[:n_results]]],
            }

        def delete(self, where):
            self.items = [item for item in self.items if item["metadata"]["doc_id"] != where["$and"][0]["doc_id"]]

    fake_collection = FakeCollection()

    def fake_get_embedder():
        return FakeEmbedder()

    generation_module.last_request_messages = None

    class FakeStream:
        def __init__(self, chunks):
            self.text_stream = chunks

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeMessages:
        def create(self, *args, **kwargs):
            generation_module.last_request_messages = kwargs.get("messages")
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="stubbed answer")])

        def stream(self, *args, **kwargs):
            generation_module.last_request_messages = kwargs.get("messages")
            return FakeStream(["stub", "bed", " answer"])

    class FakeAnthropicClient:
        def __init__(self, *args, **kwargs):
            self.messages = FakeMessages()

    class FakeGroqClient:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda *args, **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="stubbed answer"))]
                    )
                )
            )

    def fake_get_client():
        if generation_module.settings.llm_provider == "groq":
            return FakeGroqClient()
        return FakeAnthropicClient()

    monkeypatch.setattr(rag_module, "get_embedder", fake_get_embedder)
    monkeypatch.setattr(rag_module, "get_collection", lambda: fake_collection)
    monkeypatch.setattr(documents_module, "delete_document_chunks", lambda doc_id, org_id: None)
    monkeypatch.setattr(generation_module, "get_client", fake_get_client)

    database_module.Base.metadata.drop_all(bind=database_module.engine)
    database_module.Base.metadata.create_all(bind=database_module.engine)

    with TestClient(main_module.app) as client:
        yield client
