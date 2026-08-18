import { Link } from "react-router-dom";
import { Wordmark } from "../components/Chrome";
import { Button } from "../components/ui";

/* The hero is a specimen of the actual output: an answer with its sources
   attached. That is the whole argument for the product, so it leads. */
function AnswerSpecimen() {
  return (
    <figure className="rounded-lg border border-rule bg-surface p-6">
      <figcaption className="font-mono text-[11px] text-muted">
        “How much notice do I need to give?”
      </figcaption>

      <div className="ruled-margin mt-4">
        <p className="text-[15px] leading-relaxed text-ink">
          Employees on a permanent contract give 30 days' written notice. During
          probation the period is 7 days.
        </p>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {[
            { n: 1, file: "employee-handbook.pdf", chunk: 42 },
            { n: 2, file: "probation-policy.pdf", chunk: 8 },
          ].map((s) => (
            <span
              key={s.n}
              className="inline-flex items-center gap-1.5 rounded-sm border border-source/20 bg-source-soft px-2 py-1 font-mono text-[11px] text-source"
            >
              <span className="opacity-60">{s.n}</span>
              {s.file}
              <span className="opacity-60">#{s.chunk}</span>
            </span>
          ))}
        </div>
      </div>
    </figure>
  );
}

const capabilities = [
  {
    title: "Every answer names its source",
    body: "Responses cite the file and passage they came from, so anyone can check the original before acting on it.",
  },
  {
    title: "One organisation cannot read another's files",
    body: "Documents are scoped to the organisation that uploaded them at every query, and that boundary is covered by automated tests.",
  },
  {
    title: "Upload and keep working",
    body: "Files are indexed in the background. Large PDFs process while you carry on; the status updates when they're searchable.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex h-14 max-w-5xl items-center px-5">
          <Wordmark />
          <div className="ml-auto flex items-center gap-2">
            <Link to="/login">
              <Button variant="ghost">Sign in</Button>
            </Link>
            <Link to="/signup">
              <Button>Get started</Button>
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5">
        <section className="grid gap-10 py-16 md:grid-cols-2 md:items-center md:py-24">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-widest text-source">
              Document intelligence
            </p>
            <h1 className="mt-3 font-display text-4xl leading-[1.15] text-ink md:text-5xl">
              Your company's documents, ready to answer questions.
            </h1>
            <p className="mt-4 max-w-md text-[15px] leading-relaxed text-ink-soft">
              Upload handbooks, policies, and contracts. Ask in plain language. Get an
              answer with the passage it came from, so you can verify it in one click.
            </p>
            <div className="mt-7 flex gap-3">
              <Link to="/signup">
                <Button>Create an account</Button>
              </Link>
              <Link to="/login">
                <Button variant="secondary">Sign in</Button>
              </Link>
            </div>
          </div>

          <AnswerSpecimen />
        </section>

        <section className="grid gap-px overflow-hidden rounded-lg border border-rule bg-rule md:grid-cols-3">
          {capabilities.map((c) => (
            <div key={c.title} className="bg-surface p-6">
              <h2 className="font-display text-lg leading-snug text-ink">{c.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">{c.body}</p>
            </div>
          ))}
        </section>

        <footer className="border-t border-rule py-8 text-center">
          <p className="font-mono text-[11px] text-muted">
            Built with FastAPI, ChromaDB, and the Claude API.
          </p>
        </footer>
      </main>
    </div>
  );
}
