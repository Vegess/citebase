import os
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.models.models import Document, Org, User
from app.services.rag import ingest_document


def _doc_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _ensure_demo_org_and_user() -> tuple[Org, User]:
    email = os.getenv("DEMO_EMAIL", "demo@documind.local")
    password = os.getenv("DEMO_PASSWORD", "demo-password")

    with SessionLocal() as db:
        org = db.scalar(select(Org).where(Org.name == "Demo Org"))
        if org is None:
            org = Org(name="Demo Org")
            db.add(org)
            db.flush()

        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, hashed_password=hash_password(password), org_id=org.id, role="OWNER")
            db.add(user)
            db.flush()
        elif user.org_id != org.id:
            user.org_id = org.id

        db.commit()
        db.refresh(org)
        db.refresh(user)
        return org, user


def _ingest_demo_docs(org_id: str, uploader_id: str) -> None:
    doc_dir = Path(__file__).resolve().parent.parent / "demo_docs"
    if not doc_dir.exists():
        return

    with SessionLocal() as db:
        for path in sorted(doc_dir.glob("*.pdf")):
            filename = path.name
            existing = db.scalar(select(Document).where(Document.org_id == org_id, Document.filename == filename))
            if existing is not None:
                continue

            doc = Document(org_id=org_id, uploaded_by=uploader_id, filename=filename, status="processing")
            db.add(doc)
            db.commit()
            db.refresh(doc)

            try:
                text = _doc_text_from_pdf(path)
                doc.num_chunks = ingest_document(doc.id, org_id, filename, text)
                doc.status = "ready" if doc.num_chunks > 0 else "failed"
                db.commit()
            except Exception:
                doc.status = "failed"
                db.commit()


def main() -> None:
    from app.core.database import Base

    Base.metadata.create_all(bind=engine)
    org, user = _ensure_demo_org_and_user()
    _ingest_demo_docs(org.id, user.id)


if __name__ == "__main__":
    main()
