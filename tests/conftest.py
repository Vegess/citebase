import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    chroma_dir = tmp_path / "chroma"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
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
        def encode(self, texts, show_progress_bar=False):
            return FakeEmbeddingResult([[0.0, 0.0, 0.0] for _ in texts])

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

    class FakeMessages:
        def create(self, *args, **kwargs):
            generation_module.last_request_messages = kwargs.get("messages")
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="stubbed answer")])

        def stream(self, *args, **kwargs):
            generation_module.last_request_messages = kwargs.get("messages")
            for chunk in ["stub", "bed", " answer"]:
                yield SimpleNamespace(type="response.output_text.delta", delta=chunk)
            yield SimpleNamespace(type="response.completed")

    class FakeAnthropicClient:
        def __init__(self, *args, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(rag_module, "get_embedder", fake_get_embedder)
    monkeypatch.setattr(rag_module, "get_collection", lambda: fake_collection)
    monkeypatch.setattr(documents_module, "delete_document_chunks", lambda doc_id, org_id: None)
    monkeypatch.setattr(generation_module, "get_client", lambda: FakeAnthropicClient())

    database_module.Base.metadata.drop_all(bind=database_module.engine)
    database_module.Base.metadata.create_all(bind=database_module.engine)

    with TestClient(main_module.app) as client:
        yield client
