import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as tmp:
    os.environ['DATABASE_URL'] = f"sqlite:///{Path(tmp) / 'test.db'}"
    os.environ['CHROMA_PERSIST_DIR'] = str(Path(tmp) / 'chroma')
    os.environ['ANTHROPIC_API_KEY'] = 'test-key'
    os.environ['JWT_SECRET_KEY'] = 'test-secret'
    os.environ['JWT_ALGORITHM'] = 'HS256'
    for name in list(sys.modules):
        if name == 'app' or name.startswith('app.'):
            sys.modules.pop(name, None)

    import app.core.database as database_module
    import app.main as main_module
    import app.services.generation as generation_module
    import app.services.rag as rag_module

    class FakeEmbedder:
        def encode(self, texts, show_progress_bar=False):
            return [[0.0, 0.0, 0.0] for _ in texts]

    def fake_get_embedder():
        return FakeEmbedder()

    class FakeMessages:
        def create(self, *args, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type='text', text='stubbed answer')])

    class FakeAnthropicClient:
        def __init__(self, *args, **kwargs):
            self.messages = FakeMessages()

    rag_module.get_embedder = fake_get_embedder
    generation_module.get_client = lambda: FakeAnthropicClient()
    database_module.Base.metadata.drop_all(bind=database_module.engine)
    database_module.Base.metadata.create_all(bind=database_module.engine)

    with TestClient(main_module.app) as client:
        signup = client.post('/auth/signup', json={'email':'usera@example.com','password':'password123','org_name':'OrgA'})
        print('signup', signup.status_code, signup.text)
        login = client.post('/auth/login', data={'username':'usera@example.com','password':'password123'}, headers={'content-type':'application/x-www-form-urlencoded'})
        print('login', login.status_code, login.text)
        token = login.json()['access_token']
        resp = client.post('/documents', files={'file': ('alpha.txt', b'Alpha doc contents for tenant A.', 'text/plain')}, headers={'Authorization': f'Bearer {token}'})
        print('upload', resp.status_code, resp.text)
