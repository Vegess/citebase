"""Scored evaluation over the Northwind Freight demo workspace.

Used two ways:
* tests/test_eval.py runs it in CI with a deterministic word-hashing embedder,
  checking the pipeline (chunking, storage, org filter, routing) end to end.
* eval/run_eval.py runs it with the real embedding model (and optionally the
  real LLM) and prints the numbers for the README.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEMO_DIR = Path(__file__).resolve().parent / "demo_company"
QUESTIONS = Path(__file__).resolve().parent / "questions.yaml"


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]


def seed_demo_org(db, org_name: str = "Northwind Freight (demo)", email: str = "demo@northwind.example",
                  password_hash: str = "!disabled") -> tuple[str, str]:
    """Create an org + owner and ingest every demo document through the real
    queue and lifecycle. Returns (org_id, user_id)."""
    from app.models.models import Document, Org, User
    from app.services import ingestion, jobs, lifecycle

    org = Org(name=org_name)
    db.add(org)
    db.flush()
    user = User(email=email, hashed_password=password_hash, org_id=org.id, role="OWNER")
    db.add(user)
    db.flush()
    for path in sorted(DEMO_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        doc = Document(org_id=org.id, uploaded_by=user.id, filename=path.name,
                       status=lifecycle.QUEUED, char_count=len(text))
        db.add(doc)
        db.flush()
        lifecycle.record_created(db, doc, detail="demo seed")
        jobs.enqueue(db, ingestion.KIND, {"doc_id": doc.id, "org_id": org.id, "text": text})
    db.commit()
    jobs.drain()
    return org.id, user.id


@dataclass
class EvalResult:
    k: int
    retrieval_hits: int = 0
    retrieval_total: int = 0
    reciprocal_ranks: list[float] = field(default_factory=list)
    routing_correct: int = 0
    routing_total: int = 0
    answers_correct: int = 0
    answers_total: int = 0
    abstained: int = 0
    unanswerable_total: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def rate(self, hit: int, total: int) -> str:
        return f"{hit}/{total} ({100 * hit / total:.0f}%)" if total else "n/a"

    def table(self) -> str:
        mrr = sum(self.reciprocal_ranks) / len(self.reciprocal_ranks) if self.reciprocal_ranks else 0.0
        rows = [
            ("Retrieval hit@%d (answerable)" % self.k, self.rate(self.retrieval_hits, self.retrieval_total)),
            ("Retrieval MRR", f"{mrr:.2f}"),
            ("Routing (question vs whole-document task)", self.rate(self.routing_correct, self.routing_total)),
        ]
        if self.answers_total:
            rows.append(("Answer contains expected fact", self.rate(self.answers_correct, self.answers_total)))
        if self.unanswerable_total:
            rows.append(("Unanswerable → says so, no citations", self.rate(self.abstained, self.unanswerable_total)))
        if self.latencies_ms:
            ordered = sorted(self.latencies_ms)
            rows.append(("p95 answer latency", f"{ordered[int(0.95 * (len(ordered) - 1))]} ms"))
        lines = ["| Metric | Result |", "|---|---|"] + [f"| {name} | {value} |" for name, value in rows]
        if self.failures:
            lines += ["", "Misses:"] + [f"- {f}" for f in self.failures]
        return "\n".join(lines)


def run(db, org_id: str, *, k: int = 6, with_answers: bool = False) -> EvalResult:
    from app.services import rag
    from app.services.answer_plan import plan_answer
    from app.services.citations import looks_like_abstention, normalize_markers, select_citations
    from app.services.generation import generate_answer

    result = EvalResult(k=k)
    for q in load_questions():
        plan = plan_answer(db, org_id, q["question"])
        expected_mode = "document" if q["type"] == "document_task" else "question"
        result.routing_total += 1
        routed_ok = plan.mode == expected_mode and (
            q["type"] != "document_task" or plan.target_docs[:1] == [q["expect_doc"]]
        )
        result.routing_correct += routed_ok
        if not routed_ok:
            result.failures.append(f"{q['id']} routing: got {plan.mode} {plan.target_docs}")

        if q["type"] == "answerable":
            hits = rag.retrieve_chunks(org_id, q["question"], top_k=k, db=db)
            names = [h["filename"] for h in hits]
            result.retrieval_total += 1
            if q["expect_doc"] in names:
                result.retrieval_hits += 1
                result.reciprocal_ranks.append(1 / (names.index(q["expect_doc"]) + 1))
            else:
                result.reciprocal_ranks.append(0.0)
                result.failures.append(f"{q['id']} retrieval: {q['expect_doc']} not in top {k} {names}")

        if with_answers and q["type"] in ("answerable", "unanswerable"):
            start = time.perf_counter()
            answer = normalize_markers(generate_answer(q["question"], plan.chunks,
                                                       note=plan.note, context_limit=plan.context_limit))
            result.latencies_ms.append(int((time.perf_counter() - start) * 1000))
            if q["type"] == "answerable":
                result.answers_total += 1
                ok = any(s.lower() in answer.lower() for s in q["must_include"])
                result.answers_correct += ok
                if not ok:
                    result.failures.append(f"{q['id']} answer missing {q['must_include']}: {answer[:120]!r}")
            else:
                result.unanswerable_total += 1
                ok = looks_like_abstention(answer) and not select_citations(answer, plan.chunks)
                result.abstained += ok
                if not ok:
                    result.failures.append(f"{q['id']} did not abstain: {answer[:120]!r}")
    return result
