import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Wordmark } from "../components/Chrome";
import { AuthModal } from "../components/AuthPanel";
import { Icon } from "../components/icons";

/* ------------------------------------------------------------------ */
/* Content                                                             */
/* ------------------------------------------------------------------ */

const AUDIENCES = {
  hr: {
    tab: "For HR",
    headline: "Answer every policy question once. Then never again.",
    sub: "Employees ask DocuMind about leave, notice periods and benefits, and get the answer with the exact handbook passage, instead of waiting for HR to reply.",
    demo: {
      q: "How much notice do I give after probation?",
      steps: ["Searched “notice period” in employee_handbook.pdf", "Read probation_policy.pdf"],
      a: "After confirmation, permanent employees give **30 days'** written notice [1]. During probation it is **7 days** [2].",
      sources: ["employee_handbook.pdf", "probation_policy.pdf"],
    },
  },
  legal: {
    tab: "For Legal",
    headline: "Know what every contract says, and where they disagree.",
    sub: "Ask across your agreements in plain language. DocuMind cites the clause, and its agents flag contradictions between documents before they become disputes.",
    demo: {
      q: "Do the vendor MSA and the 2026 SOW agree on payment terms?",
      steps: ["Searched “payment terms” in vendor_msa.pdf", "Searched “payment terms” in sow_2026.pdf"],
      a: "No. The MSA sets **net 45** payment [1], while the 2026 SOW says **net 30** [2]. The SOW doesn't state that it overrides the MSA.",
      sources: ["vendor_msa.pdf", "sow_2026.pdf"],
    },
  },
  it: {
    tab: "For IT & Security",
    headline: "Security policy answers people actually follow.",
    sub: "Passwords, MFA, devices, incident reporting: the rules live in your policy, and DocuMind makes them answerable in seconds, with the source to prove it.",
    demo: {
      q: "How fast must I report a lost laptop, and to whom?",
      steps: ["Searched “lost laptop report” across all policies"],
      a: "Report a lost or stolen laptop to the **IT helpdesk within 24 hours** [1]. Don't try to investigate it yourself [1].",
      sources: ["it_security_policy.pdf"],
    },
  },
  ops: {
    tab: "For Operations",
    headline: "Your SOPs, finally searchable by the people who use them.",
    sub: "Shift rules, travel limits, approvals and claims: new joiners ask DocuMind instead of digging through shared drives, and every answer shows where it came from.",
    demo: {
      q: "What's the hotel limit in Mumbai and when do claims close?",
      steps: ["Searched “hotel limit metro” in travel_policy.pdf", "Searched “claim deadline”"],
      a: "Up to **Rs 6,000 per night** in metro cities [1]. Submit claims within **30 days** of the trip; after 60 days they aren't reimbursed [1].",
      sources: ["travel_policy.pdf"],
    },
  },
};

const CAPABILITIES = [
  { icon: Icon.Cite, title: "Cited answers", body: "Every claim links to the file and passage it came from. Answers it can't support say so instead of guessing." },
  { icon: Icon.Search, title: "Hybrid search", body: "Meaning-based and exact-keyword search combined, so policy codes, amounts and IDs are found as reliably as concepts." },
  { icon: Icon.Agent, title: "Research agent", body: "For harder questions, an agent plans several searches across documents and shows each step it took." },
  { icon: Icon.Alert, title: "Conflict detection", body: "When a new document contradicts an existing one, DocuMind flags it the moment it's uploaded." },
  { icon: Icon.Chart, title: "Knowledge-gap insights", body: "See what your team asks, and which questions your documents can't answer yet." },
  { icon: Icon.Shield, title: "Workspace isolation", body: "Every query is filtered to your workspace in the database itself. Roles control who can upload and manage." },
];

const USE_CASES = {
  HR: [
    { q: "How many leave days can I carry forward?", get: "The rule, the limit, and the handbook clause." },
    { q: "Summarise the new maternity policy.", get: "A structured summary of the whole document." },
    { q: "Does the 2026 handbook change the notice period?", get: "A side-by-side comparison with sources." },
  ],
  Legal: [
    { q: "Which contracts auto-renew?", get: "A research pass across every agreement." },
    { q: "Review this NDA and flag unusual clauses.", get: "A clause-by-clause review of the full file." },
    { q: "What's our liability cap with Vendor X?", get: "The figure and the exact clause." },
  ],
  IT: [
    { q: "Is SMS allowed for MFA?", get: "A clear yes/no with the policy line." },
    { q: "What software can I install?", get: "The rule and the approval path." },
    { q: "Which data is classified Restricted?", get: "The classification table, cited." },
  ],
  Operations: [
    { q: "What's the daily allowance abroad?", get: "The amount and the conditions." },
    { q: "Who approves international travel?", get: "The approvers, in order." },
    { q: "Walk me through the onboarding SOP.", get: "A step-by-step walkthrough of the SOP." },
  ],
  Finance: [
    { q: "What receipts do I need for a claim?", get: "The threshold and requirements." },
    { q: "When are reimbursements paid?", get: "The payment cycle, cited." },
    { q: "Do the expense and travel policies conflict?", get: "Contradictions found by the agent." },
  ],
};

const STEPS = [
  { icon: Icon.Upload, title: "Upload your documents", body: "Handbooks, policies, contracts, SOPs as PDF or text. Each is read, indexed and summarised in the background, with suggested questions." },
  { icon: Icon.Chat, title: "Ask in plain language", body: "Ask quick questions, or tick Deep research for comparisons and 'do these conflict?' questions. Follow-ups keep the context." },
  { icon: Icon.Cite, title: "Verify and act", body: "Each answer carries numbered sources. Rate answers, and see knowledge gaps in Insights so you know what to document next." },
];

const SECURITY = [
  "Separate workspace per company, enforced in every database query",
  "Join a workspace only by single-use invite, never by typing its name",
  "Roles: owner, admin, member, viewer, checked on every request",
  "Passwords hashed with bcrypt; sign in with Google or GitHub",
  "Document text is treated as data, never as instructions to the AI",
  "Activity log of invites, role changes, uploads and deletions",
];

const FAQ = [
  ["What kinds of documents work best?", "Text-based PDFs and .txt files: policies, handbooks, contracts, SOPs, reports. Scanned PDFs (photos of pages) aren't supported yet."],
  ["Does DocuMind make things up?", "It is instructed to answer only from your documents and to cite them. When your documents don't cover a question it says so, shows no sources, and the question appears as a knowledge gap in Insights."],
  ["What is Deep research?", "An agent that plans up to four steps (searching specific files or reading whole documents) before answering. Use it for comparisons and questions that span several documents. Each step is shown."],
  ["Who can see my documents?", "Only people in your workspace. Viewers can ask questions; members can upload; admins manage people and any document. Owners can delete the whole workspace and all its data."],
  ["Is it free?", "Yes, while DocuMind is in beta, with daily question limits per person and per workspace. Paid team plans are planned."],
];

/* ------------------------------------------------------------------ */
/* Pieces                                                              */
/* ------------------------------------------------------------------ */

function renderBold(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong> : part,
  );
}

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** The product, demonstrated: question → research steps → cited answer. */
function LiveDemo({ demo }) {
  const [phase, setPhase] = useState(prefersReducedMotion() ? 99 : 0);

  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    setPhase(0);
    const timers = [400, 1300, 2200, 3200].map((ms, i) => setTimeout(() => setPhase(i + 1), ms));
    return () => timers.forEach(clearTimeout);
  }, [demo]);

  return (
    <figure className="rounded-xl bg-surface p-5 text-left shadow-2xl ring-1 ring-black/5 sm:p-6" aria-label="Example answer">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-lg rounded-br-sm bg-ink px-3.5 py-2 text-sm text-paper">{demo.q}</p>
      </div>
      <div className="mt-4 rounded-md border border-rule px-3 py-2 text-xs">
        <p className="font-medium text-ink-soft">{phase >= 3 ? `Researched in ${demo.steps.length} step${demo.steps.length > 1 ? "s" : ""}` : "Researching across your documents…"}</p>
        <ol className="mt-1.5 space-y-1">
          {demo.steps.map((s, i) => (
            <li key={s} className={`flex gap-2 transition-opacity duration-500 ${phase > i ? "opacity-100" : "opacity-0"}`}>
              <span className="font-mono text-muted">{i + 1}.</span>
              <span className="text-ink">{s}</span>
            </li>
          ))}
        </ol>
      </div>
      <div className={`ruled-margin mt-4 transition-opacity duration-700 ${phase >= 3 ? "opacity-100" : "opacity-0"}`}>
        <p className="text-[15px] leading-relaxed text-ink">{renderBold(demo.a)}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {demo.sources.map((file, i) => (
            <span key={file} className="inline-flex items-center gap-1.5 rounded-sm border border-source/20 bg-source-soft px-2 py-1 font-mono text-[11px] text-source">
              <span className="opacity-60">{i + 1}</span>
              {file}
            </span>
          ))}
        </div>
      </div>
    </figure>
  );
}

function SectionHeading({ eyebrow, title, sub, id }) {
  return (
    <div id={id} className="mx-auto max-w-2xl scroll-mt-24 text-center">
      {eyebrow && <p className="font-mono text-[11px] uppercase tracking-widest text-source">{eyebrow}</p>}
      <h2 className="mt-2 font-display text-3xl leading-tight text-ink md:text-4xl">{title}</h2>
      {sub && <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">{sub}</p>}
    </div>
  );
}

function Faq() {
  const [open, setOpen] = useState(0);
  return (
    <div className="mx-auto mt-10 max-w-3xl divide-y divide-rule rounded-xl border border-rule bg-surface">
      {FAQ.map(([q, a], i) => (
        <div key={q}>
          <button
            type="button"
            onClick={() => setOpen(open === i ? -1 : i)}
            aria-expanded={open === i}
            className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-[15px] font-medium text-ink"
          >
            {q}
            <Icon.Chevron className={`shrink-0 text-muted transition-transform ${open === i ? "rotate-180" : ""}`} />
          </button>
          {open === i && <p className="px-5 pb-5 text-sm leading-relaxed text-ink-soft">{a}</p>}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

const NAV = [
  ["Product", "#product"],
  ["Use cases", "#use-cases"],
  ["Agents", "#agents"],
  ["Security", "#security"],
  ["Pricing", "#pricing"],
  ["FAQ", "#faq"],
];

export default function LandingPage() {
  const [audience, setAudience] = useState("hr");
  const [useCase, setUseCase] = useState("HR");
  const [auth, setAuth] = useState(null); // null | "signin" | "signup"
  const [menuOpen, setMenuOpen] = useState(false);
  const a = AUDIENCES[audience];

  return (
    <div className="min-h-screen bg-paper">
      {/* Audience bar */}
      <div className="bg-ink text-paper">
        <div className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-5 text-sm" role="tablist" aria-label="Who is it for">
          {Object.entries(AUDIENCES).map(([key, value]) => (
            <button
              key={key}
              role="tab"
              aria-selected={audience === key}
              onClick={() => setAudience(key)}
              className={`shrink-0 border-b-2 px-3 py-2.5 transition-colors ${
                audience === key ? "border-paper font-medium text-paper" : "border-transparent text-paper/70 hover:text-paper"
              }`}
            >
              {value.tab}
            </button>
          ))}
        </div>
      </div>

      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-rule bg-surface/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-5">
          <Wordmark className="text-2xl" />
          <nav className="hidden items-center gap-5 text-sm text-ink-soft lg:flex">
            {NAV.map(([label, href]) => (
              <a key={href} href={href} className="hover:text-ink">{label}</a>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-2 sm:flex">
            <button type="button" onClick={() => setAuth("signin")} className="rounded-md px-3 py-2 text-sm font-medium text-signal hover:bg-signal-soft">
              Log in
            </button>
            <button type="button" onClick={() => setAuth("signup")} className="rounded-md border border-signal px-4 py-2 text-sm font-semibold text-signal hover:bg-signal-soft">
              Join for free
            </button>
          </div>
          <button
            type="button"
            className="ml-auto rounded-md p-2 text-ink sm:ml-0 lg:hidden"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            {menuOpen ? <Icon.Close /> : <Icon.Menu />}
          </button>
        </div>
        {menuOpen && (
          <div className="border-t border-rule bg-surface px-5 py-3 lg:hidden">
            {NAV.map(([label, href]) => (
              <a key={href} href={href} onClick={() => setMenuOpen(false)} className="block py-2 text-[15px] text-ink">
                {label}
              </a>
            ))}
            <div className="mt-3 flex gap-2 sm:hidden">
              <button type="button" onClick={() => { setMenuOpen(false); setAuth("signin"); }} className="flex-1 rounded-md border border-rule py-2 text-sm font-medium">
                Log in
              </button>
              <button type="button" onClick={() => { setMenuOpen(false); setAuth("signup"); }} className="flex-1 rounded-md bg-signal py-2 text-sm font-semibold text-white">
                Join for free
              </button>
            </div>
          </div>
        )}
      </header>

      {/* Hero */}
      <section id="product" className="relative overflow-hidden bg-signal text-white">
        <div className="pointer-events-none absolute -top-40 -right-40 h-[32rem] w-[32rem] rounded-full bg-white/10" />
        <div className="pointer-events-none absolute -bottom-48 left-1/3 h-[28rem] w-[28rem] rounded-full bg-white/5" />
        <div className="relative mx-auto grid max-w-6xl items-center gap-10 px-5 py-14 md:grid-cols-[1.05fr_1fr] md:py-20">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 font-mono text-[11px] uppercase tracking-widest">
              <span className="h-1.5 w-1.5 rounded-full bg-white" /> AI knowledge assistant for teams
            </p>
            <h1 className="mt-5 text-4xl leading-[1.08] font-semibold tracking-tight md:text-[3.4rem]">{a.headline}</h1>
            <p className="mt-5 max-w-xl text-[17px] leading-relaxed text-white/90">{a.sub}</p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <button type="button" onClick={() => setAuth("signup")} className="rounded-md bg-white px-6 py-3 text-[15px] font-semibold text-signal shadow-sm hover:bg-white/90">
                Start free
              </button>
              <a href="#how" className="inline-flex items-center gap-2 px-2 py-3 text-[15px] font-medium text-white hover:underline">
                See how it works <Icon.Arrow />
              </a>
            </div>
            <p className="mt-4 text-sm text-white/75">Free during beta · Sign in with Google or GitHub · No card needed</p>
          </div>
          <LiveDemo demo={a.demo} />
        </div>
      </section>

      {/* Capability strip */}
      <section className="border-b border-rule bg-surface">
        <div className="mx-auto grid max-w-6xl gap-px bg-rule sm:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map(({ icon: I, title, body }) => (
            <div key={title} className="bg-surface p-6">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-signal-soft text-signal">
                <I />
              </span>
              <h3 className="mt-4 text-[15px] font-semibold text-ink">{title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <main>
        {/* Why */}
        <section className="mx-auto max-w-6xl px-5 py-20">
          <SectionHeading
            eyebrow="Why DocuMind"
            title="Your answers already exist. They're just buried."
            sub="Policies live in PDFs nobody finds, so the same questions land on HR, legal and IT every week. General-purpose chatbots don't know your rules, and they sound confident even when they're wrong. Teams need answers grounded in their own documents, with the receipts."
          />
          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {[
              ["Without DocuMind", ["Search five shared drives for the right version", "Wait a day for HR or legal to reply", "Two policies say different things; nobody notices"], "bg-surface"],
              ["With a generic chatbot", ["Fluent answers with no source", "Doesn't know your company's rules", "Your documents leave your control"], "bg-surface"],
              ["With DocuMind", ["Answers from your own files, cited", "Agents research across documents and flag contradictions", "Workspace-isolated, role-controlled, measurable"], "bg-signal-soft ring-1 ring-signal/30"],
            ].map(([title, points, style]) => (
              <div key={title} className={`rounded-xl border border-rule p-6 ${style}`}>
                <h3 className="font-semibold text-ink">{title}</h3>
                <ul className="mt-3 space-y-2 text-sm text-ink-soft">
                  {points.map((p) => (
                    <li key={p} className="flex gap-2">
                      <span className="mt-0.5 shrink-0 text-source"><Icon.Check width={16} height={16} /></span>
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        {/* Use cases */}
        <section id="use-cases" className="scroll-mt-20 bg-rule-soft/60 py-20">
          <div className="mx-auto max-w-6xl px-5">
            <div className="grid gap-8 lg:grid-cols-[18rem_1fr]">
              <div>
                <h2 className="font-display text-3xl leading-tight text-ink">Ask the questions your team really asks</h2>
                <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">
                  Pick a team to see the kinds of questions DocuMind answers, and what you get back.
                </p>
                <button type="button" onClick={() => setAuth("signup")} className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-signal">
                  Try it with your documents <Icon.Arrow />
                </button>
              </div>
              <div>
                <div className="flex flex-wrap gap-2" role="tablist" aria-label="Use cases">
                  {Object.keys(USE_CASES).map((k) => (
                    <button
                      key={k}
                      role="tab"
                      aria-selected={useCase === k}
                      onClick={() => setUseCase(k)}
                      className={`rounded-full border px-4 py-1.5 text-sm transition-colors ${
                        useCase === k ? "border-ink bg-ink text-paper" : "border-rule bg-surface text-ink hover:border-ink-soft"
                      }`}
                    >
                      {k}
                    </button>
                  ))}
                </div>
                <div className="mt-5 grid gap-4 md:grid-cols-3">
                  {USE_CASES[useCase].map((c) => (
                    <div key={c.q} className="flex flex-col rounded-xl border border-rule bg-surface p-5 transition-shadow hover:shadow-md">
                      <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-source-soft px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-source">
                        <Icon.Chat width={12} height={12} /> {useCase}
                      </span>
                      <p className="mt-3 text-[15px] font-semibold leading-snug text-ink">“{c.q}”</p>
                      <p className="mt-auto pt-4 text-sm text-muted">{c.get}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="mx-auto max-w-6xl px-5 py-20">
          <SectionHeading id="how" eyebrow="How it works" title="From PDF to verified answer in three steps" />
          <ol className="mt-12 grid gap-6 md:grid-cols-3">
            {STEPS.map(({ icon: I, title, body }, i) => (
              <li key={title} className="relative rounded-xl border border-rule bg-surface p-6">
                <span className="absolute -top-3 left-6 rounded-full bg-ink px-2.5 py-0.5 font-mono text-[11px] text-paper">0{i + 1}</span>
                <I className="text-signal" />
                <h3 className="mt-3 font-semibold text-ink">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* Agents */}
        <section id="agents" className="scroll-mt-20 bg-ink py-20 text-paper">
          <div className="mx-auto max-w-6xl px-5">
            <div className="mx-auto max-w-2xl text-center">
              <p className="font-mono text-[11px] uppercase tracking-widest text-paper/60">Agentic workflows</p>
              <h2 className="mt-2 font-display text-3xl leading-tight md:text-4xl">Agents that do the reading for you</h2>
              <p className="mt-3 text-[15px] leading-relaxed text-paper/75">
                DocuMind doesn't stop at one search. Agents plan, read across files and work in the background, and they always show their work.
              </p>
            </div>
            <div className="mt-12 grid gap-5 md:grid-cols-3">
              <div className="rounded-xl bg-paper/5 p-6 ring-1 ring-paper/10">
                <Icon.Agent />
                <h3 className="mt-3 font-semibold">Research agent</h3>
                <p className="mt-1.5 text-sm text-paper/70">Plans up to four searches or full-document reads, then answers with every source. You watch each step live.</p>
                <ol className="mt-4 space-y-1.5 rounded-md bg-ink/60 p-3 font-mono text-[11px] text-paper/80 ring-1 ring-paper/10">
                  <li>1. search “notice period” · handbook</li>
                  <li>2. search “notice period” · 2026 policy</li>
                  <li>3. finish → answer with [1, 2]</li>
                </ol>
              </div>
              <div className="rounded-xl bg-paper/5 p-6 ring-1 ring-paper/10">
                <Icon.Alert />
                <h3 className="mt-3 font-semibold">Conflict checker</h3>
                <p className="mt-1.5 text-sm text-paper/70">Every new upload is compared with what's already there. Contradictions are flagged before an employee gets two different answers.</p>
                <p className="mt-4 rounded-md bg-warn-soft p-3 text-xs text-warn">
                  ⚠ <strong>Notice period:</strong> this file says 60 days, but leave_policy_2025.txt says 30 days.
                </p>
              </div>
              <div className="rounded-xl bg-paper/5 p-6 ring-1 ring-paper/10">
                <Icon.Chart />
                <h3 className="mt-3 font-semibold">Upload automation</h3>
                <p className="mt-1.5 text-sm text-paper/70">Each document is indexed, summarised and given starter questions automatically, and unanswered questions surface as knowledge gaps.</p>
                <div className="mt-4 space-y-1.5 text-xs">
                  {["queued", "reading", "indexing", "ready · summary · 3 questions"].map((s, i) => (
                    <div key={s} className="flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 rounded-full ${i === 3 ? "bg-source" : "bg-paper/40"}`} />
                      <span className="text-paper/80">{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Proof */}
        <section className="mx-auto max-w-6xl px-5 py-20">
          <SectionHeading
            eyebrow="Measured, not claimed"
            title="Quality checked automatically on every change"
            sub="A benchmark company with 24 scored questions runs on every code change, so retrieval and routing can't silently get worse."
          />
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {[
              ["18 / 18", "benchmark questions with the right document in the top results"],
              ["24 / 24", "questions routed correctly between quick answers and whole-document tasks"],
              ["125+", "automated tests, including workspace isolation and concurrency"],
            ].map(([n, label]) => (
              <div key={label} className="rounded-xl border border-rule bg-surface p-6 text-center">
                <p className="font-display text-4xl text-ink">{n}</p>
                <p className="mt-2 text-sm text-muted">{label}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Security */}
        <section id="security" className="scroll-mt-20 bg-surface py-20">
          <div className="mx-auto grid max-w-6xl gap-10 px-5 md:grid-cols-[1fr_1.3fr] md:items-center">
            <div>
              <Icon.Lock className="text-source" width={28} height={28} />
              <h2 className="mt-3 font-display text-3xl leading-tight text-ink">Built for company data from day one</h2>
              <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">
                Isolation and access control aren't add-ons. They're checked on every request and covered by automated tests.
              </p>
              <Link to="/privacy" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-signal">
                Read the privacy notice <Icon.Arrow />
              </Link>
            </div>
            <ul className="grid gap-3 sm:grid-cols-2">
              {SECURITY.map((s) => (
                <li key={s} className="flex gap-3 rounded-lg border border-rule bg-paper p-4 text-sm text-ink">
                  <Icon.Shield className="shrink-0 text-source" width={18} height={18} />
                  {s}
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Expectations */}
        <section className="mx-auto max-w-6xl px-5 py-20">
          <SectionHeading eyebrow="What to expect" title="Honest about what it does today" />
          <div className="mt-10 grid gap-5 md:grid-cols-2">
            <div className="rounded-xl border border-rule bg-surface p-6">
              <h3 className="font-semibold text-ink">Available now</h3>
              <ul className="mt-3 space-y-2 text-sm text-ink-soft">
                {[
                  "PDF and text uploads with automatic summaries",
                  "Cited answers, whole-document review, comparisons",
                  "Research agent and conflict detection",
                  "Teams with roles and single-use invites",
                  "Insights: top questions and knowledge gaps",
                ].map((x) => (
                  <li key={x} className="flex gap-2"><Icon.Check className="shrink-0 text-source" width={16} height={16} />{x}</li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-dashed border-rule bg-surface p-6">
              <h3 className="font-semibold text-ink">Coming next</h3>
              <ul className="mt-3 space-y-2 text-sm text-ink-soft">
                {[
                  "Word documents and scanned PDFs (OCR)",
                  "Google Drive and Notion sync",
                  "Slack and Teams answers",
                  "Team plans with higher limits",
                ].map((x) => (
                  <li key={x} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-muted" />{x}</li>
                ))}
              </ul>
              <p className="mt-4 text-xs text-muted">Beta limits apply: daily questions per person and per workspace.</p>
            </div>
          </div>
        </section>

        {/* Pricing */}
        <section id="pricing" className="scroll-mt-20 bg-rule-soft/60 py-20">
          <div className="mx-auto max-w-6xl px-5">
            <SectionHeading eyebrow="Pricing" title="Free while in beta" />
            <div className="mt-10 grid gap-5 md:grid-cols-3">
              {[
                { name: "Beta", price: "Free", note: "Available now", points: ["All features, including agents", "Unlimited documents up to 20 MB each", "Daily question limits"], cta: "Start free", primary: true },
                { name: "Team", price: "Coming soon", note: "For growing teams", points: ["Higher daily limits", "Drive & Notion sync", "Priority support"], cta: "Join the beta", primary: false },
                { name: "Enterprise", price: "Talk to us", note: "Custom deployment", points: ["Single sign-on", "Dedicated infrastructure", "Custom retention"], cta: "Join the beta", primary: false },
              ].map((p) => (
                <div key={p.name} className={`flex flex-col rounded-xl bg-surface p-6 ${p.primary ? "ring-2 ring-signal" : "border border-rule"}`}>
                  <p className="text-sm font-medium text-muted">{p.name}</p>
                  <p className="mt-1 font-display text-3xl text-ink">{p.price}</p>
                  <p className="mt-1 text-xs text-muted">{p.note}</p>
                  <ul className="mt-5 space-y-2 text-sm text-ink-soft">
                    {p.points.map((x) => (
                      <li key={x} className="flex gap-2"><Icon.Check className="shrink-0 text-source" width={16} height={16} />{x}</li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    onClick={() => setAuth("signup")}
                    className={`mt-6 rounded-md py-2.5 text-sm font-semibold ${p.primary ? "bg-signal text-white" : "border border-rule text-ink hover:border-ink-soft"}`}
                  >
                    {p.cta}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section className="mx-auto max-w-6xl px-5 py-20">
          <SectionHeading id="faq" eyebrow="FAQ" title="Questions, answered" />
          <Faq />
        </section>

        {/* Final CTA */}
        <section className="bg-signal">
          <div className="mx-auto flex max-w-6xl flex-col items-start gap-5 px-5 py-14 text-white md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-2xl font-semibold md:text-3xl">Upload one policy. Ask it anything.</h2>
              <p className="mt-2 text-white/85">It takes about a minute to see your first cited answer.</p>
            </div>
            <button type="button" onClick={() => setAuth("signup")} className="rounded-md bg-white px-6 py-3 font-semibold text-signal hover:bg-white/90">
              Start free
            </button>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="bg-ink text-paper/80">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-12 sm:grid-cols-2 md:grid-cols-4">
          <div>
            <Wordmark className="text-2xl" light />
            <p className="mt-3 text-sm text-paper/60">Answers you can trust, from the documents you already have.</p>
          </div>
          {[
            ["Product", [["Features", "#product"], ["Agents", "#agents"], ["Pricing", "#pricing"]]],
            ["Resources", [["How it works", "#how"], ["Security", "#security"], ["FAQ", "#faq"]]],
            ["Legal", [["Privacy notice", "/privacy"]]],
          ].map(([title, links]) => (
            <div key={title}>
              <p className="text-sm font-semibold text-paper">{title}</p>
              <ul className="mt-3 space-y-2 text-sm">
                {links.map(([label, href]) => (
                  <li key={label}><a href={href} className="hover:text-paper">{label}</a></li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="border-t border-paper/10">
          <p className="mx-auto max-w-6xl px-5 py-5 text-xs text-paper/50">
            © {new Date().getFullYear()} DocuMind · Built by K Anirudh · Beta software: don't upload confidential documents to the public demo.
          </p>
        </div>
      </footer>

      <AuthModal open={Boolean(auth)} mode={auth || "signin"} onClose={() => setAuth(null)} />
    </div>
  );
}
