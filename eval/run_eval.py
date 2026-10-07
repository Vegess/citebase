"""Run the scored eval against the demo company with the real models.

    python -m eval.run_eval              # retrieval + routing (real embeddings, no LLM key needed)
    python -m eval.run_eval --answers    # also asks the LLM (uses LLM_PROVIDER + key from .env)

Uses a throwaway SQLite database, never your real one. Prints a Markdown
table; in GitHub Actions it is also written to the job summary.
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", action="store_true", help="also generate answers with the configured LLM")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--min-hit-rate", type=float, default=0.0,
                        help="exit non-zero if retrieval hit@k falls below this (0-1)")
    args = parser.parse_args()

    workdir = tempfile.mkdtemp(prefix="documind-eval-")
    os.environ["DATABASE_URL"] = f"sqlite:///{workdir}/eval.db"
    os.environ.setdefault("JWT_SECRET_KEY", "eval-only")
    os.environ["WORKER_MODE"] = "off"
    os.environ["LOG_JSON"] = "false"

    from app.core.database import Base, SessionLocal, engine
    import app.models.models  # noqa: F401
    from eval.harness import run, seed_demo_org

    from app.core.config import get_settings
    settings = get_settings()
    key = {"groq": settings.groq_api_key, "gemini": settings.google_api_key,
           "anthropic": settings.anthropic_api_key}.get(settings.llm_provider)
    if args.answers and not key:
        print(f"WARNING: no API key for LLM_PROVIDER={settings.llm_provider}; answers will be the degraded "
              "fallback and score poorly. Set the key in .env to measure real answers.\n")

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        org_id, _ = seed_demo_org(db)
        result = run(db, org_id, k=args.k, with_answers=args.answers)

    report = "## DocuMind eval — Northwind Freight demo\n\n" + result.table()
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(report + "\n", encoding="utf-8")

    hit_rate = result.retrieval_hits / result.retrieval_total if result.retrieval_total else 0
    return 1 if hit_rate < args.min_hit_rate else 0


if __name__ == "__main__":
    sys.exit(main())
