import { Link } from "react-router-dom";
import { Wordmark } from "../components/Chrome";

const SECTIONS = [
  {
    title: "What we store",
    body: [
      "Your account: email address, a hashed password (or nothing usable, if you sign in with Google or GitHub), your workspace and role.",
      "Documents your workspace uploads, the text extracted from them, and the search index built from that text.",
      "Questions, answers and the sources cited, so your history and the Insights page work.",
      "An audit log of security-relevant actions (invites, role changes, uploads, deletions).",
    ],
  },
  {
    title: "Google and GitHub sign-in",
    body: [
      "We ask only for your basic profile and email address. We use the email to find or create your account and never request access to your files, repositories or contacts.",
      "Only verified email addresses are accepted.",
    ],
  },
  {
    title: "Who can see your documents",
    body: [
      "Only members of your workspace. Every query is filtered by workspace, and this is covered by automated tests.",
      "To write answers, the relevant passages and your question are sent to the language-model provider configured for this deployment (currently Groq). They are not used by DocuMind for anything else.",
    ],
  },
  {
    title: "Deleting your data",
    body: [
      "Admins can delete any document; it is removed with its search index.",
      "The workspace owner can delete the whole workspace from the Team page. This permanently removes its members, documents, conversations and audit log.",
    ],
  },
  {
    title: "This is a beta",
    body: [
      "DocuMind is an early product run by an individual developer. Please don't upload documents you are not allowed to share with a third-party AI provider, or highly sensitive personal data.",
    ],
  },
];

export default function PrivacyPage() {
  return (
    <div className="min-h-dvh bg-paper">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-5">
          <Link to="/">
            <Wordmark />
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-5 py-12">
        <h1 className="font-display text-4xl text-ink">Privacy notice</h1>
        <p className="mt-3 text-ink-soft">In plain words: what DocuMind keeps, who can see it, and how to remove it.</p>
        {SECTIONS.map((s) => (
          <section key={s.title} className="mt-10">
            <h2 className="text-lg font-semibold text-ink">{s.title}</h2>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-ink-soft">
              {s.body.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
        ))}
        <p className="mt-12 text-sm text-muted">
          <Link to="/" className="text-signal">
            ← Back to DocuMind
          </Link>
        </p>
      </main>
    </div>
  );
}
