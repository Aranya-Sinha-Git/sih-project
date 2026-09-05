"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isSupabaseConfigured, supabase } from "../lib/supabase";

type Candidate = {
  candidate_id: string;
  source: string;
  source_record_id: string;
  narrative: string;
  source_native_outcome: string;
  activity_if_known: string;
  queue_order: number;
};

type Label = "SIF_POTENTIAL" | "NON_SIF_POTENTIAL" | "UNCERTAIN" | "SKIP";

type Decision = {
  decision_id: string;
  candidate_id: string;
  reviewer_id: string;
  reviewer_name: string;
  sif_label: Label;
  confidence: number;
  hazard: string;
  exposure: string;
  barrier_failure: string;
  credible_consequence: string;
  reason: string;
  submitted_at: string;
};

const initialDetails = {
  hazard: "",
  exposure: "",
  barrierFailure: "",
  credibleConsequence: "",
  reason: "",
};

export default function LabelingWorkbench() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [completedIds, setCompletedIds] = useState<Set<string>>(new Set());
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [jumpNumber, setJumpNumber] = useState("1");
  const [reviewerId, setReviewerId] = useState("");
  const [reviewerName, setReviewerName] = useState("");
  const [label, setLabel] = useState<Label>("UNCERTAIN");
  const [confidence, setConfidence] = useState("0.70");
  const [details, setDetails] = useState(initialDetails);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const savingRef = useRef(false);

  const current = useMemo(() => {
    return candidates.find((candidate) => candidate.candidate_id === selectedCandidateId)
      ?? candidates.find((candidate) => !completedIds.has(candidate.candidate_id))
      ?? candidates[0];
  }, [candidates, completedIds, selectedCandidateId]);

  const currentIndex = current
    ? candidates.findIndex((candidate) => candidate.candidate_id === current.candidate_id)
    : -1;
  const currentDecisions = useMemo(
    () => decisions.filter((decision) => decision.candidate_id === current?.candidate_id),
    [current?.candidate_id, decisions],
  );
  const ownDecision = currentDecisions.find((decision) => decision.reviewer_id === reviewerId);

  const loadQueue = useCallback(async () => {
    if (!supabase) {
      setError("Supabase is not configured. Add the two NEXT_PUBLIC_SUPABASE environment variables.");
      setLoading(false);
      return;
    }

    try {
      const storedName = window.localStorage.getItem("sif-reviewer-name") ?? "";
      setReviewerName(storedName);

      const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
      if (sessionError) throw sessionError;

      let user = sessionData.session?.user;
      if (!user) {
        const { data, error: anonymousError } = await supabase.auth.signInAnonymously();
        if (anonymousError) throw anonymousError;
        user = data.user ?? undefined;
      }
      if (!user) throw new Error("Could not create an anonymous reviewer session.");
      setReviewerId(user.id);

      const [candidateResult, decisionResult] = await Promise.all([
        supabase
          .from("labeling_candidates")
          .select("candidate_id,source,source_record_id,narrative,source_native_outcome,activity_if_known,queue_order")
          .order("queue_order", { ascending: true }),
        supabase
          .from("labeling_decisions")
          .select("decision_id,candidate_id,reviewer_id,reviewer_name,sif_label,confidence,hazard,exposure,barrier_failure,credible_consequence,reason,submitted_at")
          .order("submitted_at", { ascending: true }),
      ]);

      if (candidateResult.error) throw candidateResult.error;
      if (decisionResult.error) throw decisionResult.error;

      const loadedCandidates = (candidateResult.data ?? []) as Candidate[];
      const loadedDecisions = (decisionResult.data ?? []) as Decision[];
      const ownCompleted = new Set(
        loadedDecisions
          .filter((decision) => decision.reviewer_id === user.id)
          .map((decision) => decision.candidate_id),
      );
      const firstOpen = loadedCandidates.find((candidate) => !ownCompleted.has(candidate.candidate_id));

      setCandidates(loadedCandidates);
      setDecisions(loadedDecisions);
      setCompletedIds(ownCompleted);
      setSelectedCandidateId(firstOpen?.candidate_id ?? loadedCandidates[0]?.candidate_id ?? "");
      setJumpNumber(String(Math.max(1, loadedCandidates.findIndex((candidate) => candidate.candidate_id === firstOpen?.candidate_id) + 1)));
    } catch (caught) {
      const text = caught instanceof Error ? caught.message : "Unable to connect to the labeling database.";
      setError(
        text.includes("Anonymous sign-ins")
          ? "Anonymous sign-in is disabled. Enable Anonymous Sign-Ins in Supabase Authentication settings."
          : text,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  useEffect(() => {
    const client = supabase;
    if (!client || !reviewerId) return;

    const channel = client
      .channel("public-labeling-decisions")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "labeling_decisions" },
        (payload) => {
          const incoming = payload.new as Decision;
          setDecisions((previous) =>
            previous.some((decision) => decision.decision_id === incoming.decision_id)
              ? previous
              : [...previous, incoming],
          );
          if (incoming.reviewer_id === reviewerId) {
            setCompletedIds((previous) => new Set(previous).add(incoming.candidate_id));
          }
        },
      )
      .subscribe();

    return () => {
      void client.removeChannel(channel);
    };
  }, [reviewerId]);

  function goToNumber(rawNumber: number) {
    if (savingRef.current || !candidates.length) return;
    const bounded = Math.min(candidates.length, Math.max(1, Math.round(rawNumber || 1)));
    setJumpNumber(String(bounded));
    setSelectedCandidateId(candidates[bounded - 1].candidate_id);
    setMessage("");
    setError("");
    setLabel("UNCERTAIN");
    setConfidence("0.70");
    setDetails(initialDetails);
  }

  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingRef.current || !supabase || !current || !reviewerId) return;
    if (reviewerName.trim().length < 2) {
      setError("Enter your reviewer name before saving.");
      return;
    }
    if (!details.reason.trim() && label !== "SKIP") {
      setError("Add a concise reason for the decision.");
      return;
    }

    const submittedCandidate = current;
    const submittedLabel = label;
    const submittedDetails = { ...details };
    const submittedReviewer = reviewerName.trim();
    const payload = {
      candidate_id: submittedCandidate.candidate_id,
      reviewer_id: reviewerId,
      reviewer_name: submittedReviewer,
      sif_label: submittedLabel,
      confidence: Number(confidence),
      hazard: submittedDetails.hazard.trim(),
      exposure: submittedDetails.exposure.trim(),
      barrier_failure: submittedDetails.barrierFailure.trim(),
      credible_consequence: submittedDetails.credibleConsequence.trim(),
      reason: submittedDetails.reason.trim(),
      client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    savingRef.current = true;
    setSaving(true);
    setError("");
    setMessage("");
    window.localStorage.setItem("sif-reviewer-name", reviewerName.trim());

    let saveError;
    let insertedDecision: Decision | null = null;
    try {
      const result = await supabase.from("labeling_decisions").insert(payload).select("decision_id,candidate_id,reviewer_id,reviewer_name,sif_label,confidence,hazard,exposure,barrier_failure,credible_consequence,reason,submitted_at").single();
      saveError = result.error;
      insertedDecision = (result.data as Decision | null) ?? null;
    } catch (caught) {
      saveError = caught instanceof Error ? caught : new Error("Unable to save decision.");
    }

    if (saveError) {
      setError(saveError.message);
      setSaving(false);
      savingRef.current = false;
      return;
    }

    setDecisions((previous) => insertedDecision && !previous.some((decision) => decision.decision_id === insertedDecision?.decision_id) ? [...previous, insertedDecision] : previous);
    setCompletedIds((previous) => new Set(previous).add(submittedCandidate.candidate_id));
    setLabel("UNCERTAIN");
    setConfidence("0.70");
    setDetails(initialDetails);
    setMessage("Decision saved permanently.");
    const nextCandidate = candidates
      .slice(currentIndex + 1)
      .concat(candidates.slice(0, currentIndex))
      .find((candidate) => !completedIds.has(candidate.candidate_id) && candidate.candidate_id !== submittedCandidate.candidate_id);
    if (nextCandidate) {
      const nextIndex = candidates.findIndex((candidate) => candidate.candidate_id === nextCandidate.candidate_id);
      setSelectedCandidateId(nextCandidate.candidate_id);
      setJumpNumber(String(nextIndex + 1));
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
    setSaving(false);
    savingRef.current = false;
  }

  function resetDraft(rawNumber: number) {
    if (!savingRef.current) goToNumber(rawNumber);
  }

  const completed = completedIds.size;
  const progress = candidates.length ? Math.round((completed / candidates.length) * 100) : 0;

  return (
    <main>
      <header className="masthead">
        <div>
          <p className="eyebrow">SIF v0.1 · Human review</p>
          <h1>Labeling workbench</h1>
          <p className="lede">Judge credible potential—not the actual outcome.</p>
        </div>
        <div className={`status ${error ? "offline" : ""}`} aria-label="Save status">
          <span className="status-dot" /> {loading ? "Connecting…" : error ? "Setup required" : "Supabase connected"}
        </div>
      </header>

      {!isSupabaseConfigured && <div className="notice error">Supabase environment variables are missing.</div>}
      {error && <div className="notice error" role="alert">{error}</div>}
      {message && <div className="notice success" role="status">{message}</div>}

      {loading ? (
        <section className="card loading">Preparing your private reviewer session…</section>
      ) : candidates.length === 0 && !error ? (
        <section className="card empty">
          <h2>No candidates found</h2>
          <p>Run the supplied Supabase setup and import the candidate CSV.</p>
        </section>
      ) : current ? (
        <>
          <section className="progress-card" aria-label="Review progress">
            <div className="progress-copy">
              <span>{completed} of {candidates.length} saved</span>
              <strong>{progress}%</strong>
            </div>
            <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
          </section>

          <nav className="record-nav card" aria-label="Incident number navigation">
            <button type="button" className="nav-button" onClick={() => goToNumber(currentIndex)} disabled={saving || currentIndex <= 0}>← Previous</button>
            <form className="jump-form" onSubmit={(event) => { event.preventDefault(); goToNumber(Number(jumpNumber)); }}>
              <label htmlFor="record-number">Go to incident</label>
              <input id="record-number" type="number" min="1" max={candidates.length} value={jumpNumber} disabled={saving} onChange={(event) => setJumpNumber(event.target.value)} />
              <span>of {candidates.length}</span>
              <button type="submit" className="go-button" disabled={saving}>Go</button>
            </form>
            <button type="button" className="nav-button" onClick={() => goToNumber(currentIndex + 2)} disabled={saving || currentIndex >= candidates.length - 1}>Next →</button>
          </nav>

          <form onSubmit={submitDecision}>
            <div className="workspace">
              <section className="card incident-card">
                <div className="record-head">
                  <div>
                    <p className="eyebrow">Current incident</p>
                    <h2>{current.source} · {current.source_record_id}</h2>
                  </div>
                  <span className="record-number">Incident {currentIndex + 1} of {candidates.length}</span>
                </div>
                <div className="narrative">{current.narrative}</div>
                <dl className="context-grid">
                  <div><dt>Activity</dt><dd>{current.activity_if_known || "Not recorded"}</dd></div>
                  <div><dt>Native outcome</dt><dd>{current.source_native_outcome || "Not recorded"}</dd></div>
                </dl>
                <div className="outcome-warning">
                  The native outcome is context only. Do not infer SIF potential from injury severity, fatality, or no-injury status alone.
                </div>
              </section>

              <aside className="card guide-card">
                <p className="eyebrow">Decision test</p>
                <ol>
                  <li>Was there a meaningful hazard or hazardous energy?</li>
                  <li>Was a person credibly exposed?</li>
                  <li>Did a barrier or critical control fail?</li>
                  <li>Could the event credibly cause death or life-altering harm?</li>
                </ol>
                <p className="guide-note">Use UNCERTAIN when the narrative does not support a defensible judgment.</p>
              </aside>
            </div>

            <section className="card peer-card" aria-live="polite">
              <div className="peer-head">
                <div>
                  <p className="eyebrow">Live peer review</p>
                  <h2>Labels from other reviewers</h2>
                </div>
                <span className="live-badge"><i /> Live · {currentDecisions.length}</span>
              </div>
              {currentDecisions.length === 0 ? (
                <p className="peer-empty">No one has labeled this incident yet.</p>
              ) : (
                <div className="peer-list">
                  {currentDecisions.map((decision) => (
                    <article className="peer-decision" key={decision.decision_id}>
                      <div className="peer-summary">
                        <div>
                          <strong>{decision.reviewer_name}{decision.reviewer_id === reviewerId ? " · You" : ""}</strong>
                          <span>{new Date(decision.submitted_at).toLocaleString()}</span>
                        </div>
                        <div className="peer-label-wrap">
                          <span className={`peer-label ${decision.sif_label.toLowerCase()}`}>{decision.sif_label.replaceAll("_", " ")}</span>
                          <small>{Math.round(Number(decision.confidence) * 100)}% confidence</small>
                        </div>
                      </div>
                      {decision.reason && <p className="peer-reason">{decision.reason}</p>}
                      {(decision.hazard || decision.exposure || decision.barrier_failure || decision.credible_consequence) && (
                        <details>
                          <summary>View evidence details</summary>
                          <dl className="peer-evidence">
                            <div><dt>Hazard</dt><dd>{decision.hazard || "Not stated"}</dd></div>
                            <div><dt>Exposure</dt><dd>{decision.exposure || "Not stated"}</dd></div>
                            <div><dt>Barrier failure</dt><dd>{decision.barrier_failure || "Not stated"}</dd></div>
                            <div><dt>Credible consequence</dt><dd>{decision.credible_consequence || "Not stated"}</dd></div>
                          </dl>
                        </details>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>

            <section className="card decision-card">
              <div className="section-title">
                <div><p className="eyebrow">Your assessment</p><h2>Record the evidence chain</h2></div>
                <label className="reviewer-field">
                  <span>Reviewer name</span>
                  <input value={reviewerName} disabled={saving} onChange={(event) => setReviewerName(event.target.value)} maxLength={100} required placeholder="Your name or reviewer ID" />
                </label>
              </div>

              {ownDecision && <div className="notice own-decision">You already labeled incident {currentIndex + 1}. Choose another number to continue; your saved label appears above.</div>}

              <div className="evidence-grid">
                <label><span>Hazard / hazardous energy</span><textarea disabled={saving} value={details.hazard} onChange={(event) => setDetails({ ...details, hazard: event.target.value })} rows={3} /></label>
                <label><span>Personnel exposure</span><textarea disabled={saving} value={details.exposure} onChange={(event) => setDetails({ ...details, exposure: event.target.value })} rows={3} /></label>
                <label><span>Barrier / control failure</span><textarea disabled={saving} value={details.barrierFailure} onChange={(event) => setDetails({ ...details, barrierFailure: event.target.value })} rows={3} /></label>
                <label><span>Credible consequence</span><textarea disabled={saving} value={details.credibleConsequence} onChange={(event) => setDetails({ ...details, credibleConsequence: event.target.value })} rows={3} /></label>
              </div>

              <fieldset>
                <legend>Final label</legend>
                <div className="label-options">
                  {(["SIF_POTENTIAL", "NON_SIF_POTENTIAL", "UNCERTAIN", "SKIP"] as Label[]).map((option) => (
                    <label className={`label-option ${label === option ? "selected" : ""}`} key={option}>
                      <input type="radio" name="label" value={option} disabled={saving} checked={label === option} onChange={() => setLabel(option)} />
                      <span>{option.replaceAll("_", " ")}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="final-row">
                <label className="confidence"><span>Confidence</span><select disabled={saving} value={confidence} onChange={(event) => setConfidence(event.target.value)}><option value="0.50">Low · 0.50</option><option value="0.70">Medium · 0.70</option><option value="0.90">High · 0.90</option></select></label>
                <label className="reason"><span>Concise reason</span><textarea disabled={saving} value={details.reason} onChange={(event) => setDetails({ ...details, reason: event.target.value })} rows={2} maxLength={600} placeholder="Why does the evidence support this label?" /></label>
              </div>

              <div className="save-row">
                <p>Saved to the central database with timestamp and reviewer identity.</p>
                <button type="submit" disabled={saving || Boolean(ownDecision)}>{saving ? "Saving…" : ownDecision ? "Already saved" : "Save and continue"}</button>
              </div>
            </section>
          </form>
        </>
      ) : null}
    </main>
  );
}
