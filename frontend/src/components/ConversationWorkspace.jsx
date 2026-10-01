import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createConversation, getConversation, listConversations, submitConversationTurn } from "../api.js";
import ConversationHistory from "./ConversationHistory.jsx";
import ConversationList from "./ConversationList.jsx";
import ResearchComposer from "./ResearchComposer.jsx";
import { ConversationEvidenceDetails } from "./ConversationMessage.jsx";

function errorText(error) { return error instanceof Error ? error.message : "An unexpected error occurred."; }

export default function ConversationWorkspace({ conversationId, isAdmin, navigate, evidenceWorkspace }) {
  const [conversations, setConversations] = useState([]);
  const [turns, setTurns] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [listState, setListState] = useState({ loading: true, error: "" });
  const [detailState, setDetailState] = useState({ loading: !!conversationId, error: "" });
  const [submittingIds, setSubmittingIds] = useState(() => new Set());
  const [submissionError, setSubmissionError] = useState("");
  const [pending, setPending] = useState(null);
  const [showList, setShowList] = useState(false);
  const [draft, setDraft] = useState("");
  const loadGeneration = useRef(0);
  const skipLoadId = useRef(null);
  const activeConversationIdRef = useRef(conversationId);
  const inFlightRef = useRef(new Map());
  activeConversationIdRef.current = conversationId;
  const responseRef = useRef(null);
  const focusAfterResponse = useRef(false);

  useEffect(() => {
    let active = true;
    listConversations().then(result => { if (active) { setConversations(result.items || []); setListState({ loading: false, error: "" }); } }).catch(error => { if (active) setListState({ loading: false, error: errorText(error) }); });
    return () => { active = false; };
  }, [conversationId]);

  useEffect(() => {
    if (skipLoadId.current === conversationId) { skipLoadId.current = null; return undefined; }
    setPending(null);
    setSubmissionError("");
    if (!conversationId) { setTurns([]); setActiveConversation(null); setDetailState({ loading: false, error: "" }); return undefined; }
    const generation = ++loadGeneration.current;
    let active = true;
    setDetailState({ loading: true, error: "" });
    async function loadAllTurns() {
      try {
        let result = await getConversation(conversationId);
        const allTurns = [...(result.turns || [])];
        while (result.next_cursor) {
          result = await getConversation(conversationId, { offset: Number(result.next_cursor) });
          allTurns.push(...(result.turns || []));
        }
        if (!active || generation !== loadGeneration.current) return;
        setActiveConversation(result.conversation);
        setTurns(allTurns.sort((left, right) => left.sequence - right.sequence).map(turn => {
          const result = turn.result || turn.public_response || null;
          return { ...turn, result: isAdmin && result && turn.request_id ? { ...result, request_id: turn.request_id } : result };
        }));
        setDetailState({ loading: false, error: "" });
      } catch (error) { if (active && generation === loadGeneration.current) setDetailState({ loading: false, error: errorText(error) }); }
    }
    loadAllTurns();
    return () => { active = false; };
  }, [conversationId]);

  const activeLockKey = conversationId || "__new__";
  const activePmids = useMemo(() => evidenceWorkspace.activeTabId?.startsWith("pmid:") ? [evidenceWorkspace.activeTabId.slice(5)] : [], [evidenceWorkspace.activeTabId]);
  const submitting = submittingIds.has(activeLockKey);
  useEffect(() => { if (focusAfterResponse.current && !submitting) { responseRef.current?.focus(); focusAfterResponse.current = false; } }, [turns, submitting]);

  function startNew() { activeConversationIdRef.current = null; setActiveConversation(null); setTurns([]); setPending(null); setDraft(""); setSubmissionError(""); setShowList(false); navigate(isAdmin ? "/admin/research" : "/research"); }
  function selectConversation(id) { activeConversationIdRef.current = id; setPending(null); setDraft(""); setSubmissionError(""); setShowList(false); navigate(`${isAdmin ? "/admin" : ""}/research/${encodeURIComponent(id)}`); }
  const openEvidence = useCallback((pmid, target = {}) => {
    const matchingTurn = turns.find(turn => turn.turn_id === target.turnId);
    const paper = target.paper || matchingTurn?.result?.retrieved_papers?.find(item => String(item.pmid) === String(pmid)) || turns.flatMap(turn => turn.result?.retrieved_papers || []).find(item => String(item.pmid) === String(pmid)) || { pmid, title: `PMID ${pmid}` };
    const evidenceRecords = turns.flatMap(turn => turn.result?.evidence_table || []).filter(row => String(row.pmid) === String(pmid));
    evidenceWorkspace.openPaper({ paper: { ...paper, pmid, evidenceRecords }, turnId: target.turnId, evidenceId: target.evidenceId, spanText: target.spanText });
  }, [turns, evidenceWorkspace.openPaper]);
  const openRankedPaper = useCallback((paper, target = {}) => openEvidence(paper.pmid, { ...target, paper }), [openEvidence]);
  async function submit(message, controls = {}) {
    const initialKey = conversationId || "__new__";
    if (inFlightRef.current.has(initialKey)) return false;
    const requestToken = Symbol("conversation-turn");
    inFlightRef.current.set(initialKey, requestToken);
    setSubmittingIds(current => new Set(current).add(initialKey));
    const shouldFocusResponse = document.activeElement?.id !== "conversation-message";
    setSubmissionError("");
    setDetailState({ loading: false, error: "" });
    let id = conversationId;
    let lockKey = initialKey;
    let localTurn = null;
    const canUpdateActive = () => activeConversationIdRef.current === id && inFlightRef.current.get(lockKey) === requestToken;
    try {
      if (!id) {
        const created = await createConversation();
        id = created.conversation_id;
        inFlightRef.current.delete(initialKey);
        inFlightRef.current.set(id, requestToken);
        lockKey = id;
        setSubmittingIds(current => { const next = new Set(current); next.delete(initialKey); next.add(id); return next; });
        setActiveConversation(created);
        skipLoadId.current = id;
        activeConversationIdRef.current = id;
        navigate(`${isAdmin ? "/admin" : ""}/research/${encodeURIComponent(id)}`);
      }
      localTurn = { turn_id: `pending-${Date.now()}`, user_message: message, action: null, answer_status: null, assistant_message: null };
      setTurns(current => [...current, localTurn]);
      setPending({ message });
      const response = await submitConversationTurn(id, { message, ...controls });
      const completedTurn = { ...localTurn, turn_id: response.turn_id, action: response.action, answer_status: response.answer_status, assistant_message: response.assistant_message, result: response };
      const responseIsActive = canUpdateActive();
      if (responseIsActive) {
        setTurns(current => [...current.filter(turn => turn.turn_id !== localTurn.turn_id && turn.turn_id !== response.turn_id), completedTurn]);
        setPending(null);
        focusAfterResponse.current = shouldFocusResponse;
        setActiveConversation(current => current && ["New conversation", "New research"].includes(current.title) ? { ...current, title: message.slice(0, 80) } : current);
      }
      setConversations(current => {
        const existing = current.find(item => item.conversation_id === id);
        const defaultTitle = !existing || ["New conversation", "New research"].includes(existing.title);
        return [{ conversation_id: id, title: defaultTitle ? message.slice(0, 80) : existing.title, updated_at: new Date().toISOString() }, ...current.filter(item => item.conversation_id !== id)];
      });
      return responseIsActive;
    } catch (error) {
      if (canUpdateActive()) {
        if (localTurn) setTurns(current => current.map(turn => turn.turn_id === localTurn.turn_id ? { ...turn, answer_status: "FAILED", action: "RESEARCH", assistant_message: "A technical failure prevented this turn from completing. Please try again." } : turn));
        setSubmissionError(`${errorText(error)} Your message is still here; retry when ready.`);
        setPending(null);
      }
      return false;
    } finally {
      if (inFlightRef.current.get(lockKey) === requestToken) inFlightRef.current.delete(lockKey);
      setSubmittingIds(current => { const next = new Set(current); next.delete(lockKey); return next; });
    }
  }

  const firstQuestion = turns.find(turn => typeof turn.user_message === "string" && turn.user_message)?.user_message;
  const latestCompleted = [...turns].reverse().find(turn => turn.assistant_message);
  const persistedTitle = activeConversation?.title;
  const title = firstQuestion && persistedTitle === firstQuestion.slice(0, 80)
    ? firstQuestion
    : persistedTitle || "Research conversations";
  function usePrompt(question) { setDraft(question); requestAnimationFrame(() => document.getElementById("conversation-message")?.focus()); }
  const examples = [
    { topic: "Care delivery", title: "Telehealth & blood pressure", question: "Does telehealth improve blood pressure control in nondialysis CKD?" },
    { topic: "Long-term risk", title: "Kidney stones & later CKD", question: "Is nephrolithiasis associated with later CKD or end-stage kidney disease?" },
    { topic: "Prognosis", title: "Kidney involvement in amyloidosis", question: "What renal outcomes and survival predictors occur in AA amyloidosis with kidney involvement?" },
  ];
  return <main className={`app-main conversation-workspace ${isAdmin ? "admin-research" : "user-research"}`}>
    <header className={`conversation-header ${!conversationId ? "research-welcome" : ""}`}><div><span className="eyebrow">THE RESEARCH DESK <span aria-hidden="true">/</span> PUBMED ABSTRACTS</span><h1>{title}</h1><p>{conversationId ? "Explore the findings, check the sources, and ask what comes next." : "Ask a focused question. See what the studies report, where they agree, and what remains uncertain."}</p></div><div className="conversation-header-actions"><button type="button" onClick={() => setShowList(value => !value)} aria-expanded={showList}>Conversations <span className="history-count">{conversations.length}</span></button><button className="new-research-button" type="button" onClick={startNew}><span aria-hidden="true">＋</span> New conversation</button></div></header>
    {showList && <ConversationList conversations={conversations} activeId={conversationId} loading={listState.loading} error={listState.error} onNew={startNew} onSelect={selectConversation} />}
    {detailState.loading && <p role="status">Loading conversation…</p>}
    {detailState.error && <p className="conversation-error" role="alert">{detailState.error}</p>}
    {!detailState.loading && !detailState.error && <>
      {conversationId && <ConversationHistory turns={turns} pending={pending} responseRef={responseRef} onEvidence={openEvidence} onPaper={openRankedPaper} isAdmin={isAdmin} navigate={navigate} activePmids={activePmids} />}
      <ResearchComposer draft={draft} onDraftChange={setDraft} onSubmit={submit} submitting={submitting} isAdmin={isAdmin} hasConversation={Boolean(conversationId)} />
      {submissionError && <p className="conversation-error" role="alert">{submissionError}</p>}
      {!conversationId && <section className="research-start" aria-label="Research starting points"><div className="starting-heading"><h2>A few questions to start with</h2><span>Choose one to edit before searching</span></div><div className="research-examples">{examples.map((example, index) => <button type="button" key={example.topic} onClick={() => usePrompt(example.question)}><span className="example-index">0{index + 1}</span><span className="example-copy"><small>{example.topic}</small><strong>{example.title}</strong><span>{example.question}</span></span><span className="example-arrow" aria-hidden="true">↗</span></button>)}</div><div className="research-method"><div><span className="method-mark" aria-hidden="true">↳</span><h2>Every answer has a paper trail.</h2></div><p>Search the local PubMed collection, read source-linked findings, and open the original abstracts alongside your conversation. Limited evidence stays visible, so you can decide what to explore next.</p><details><summary>How to read an answer</summary><p><strong>Source-backed findings</strong> are checked against retrieved abstracts. They are not a measure of study quality or clinical certainty. <strong>Partial answers</strong> leave part of the question unresolved. <strong>Limited evidence</strong> means this search could not establish an answer; it does not mean no research exists.</p></details></div></section>}
      {conversationId && turns.some(turn => turn.result?.cited_pmids?.length) && !submitting && <nav className="followup-prompts" aria-label="Suggested follow-up questions"><span>Continue exploring</span>{["What are the limitations of these studies?", "Which findings are consistent across the studies?"].map(question => <button type="button" key={question} onClick={() => usePrompt(question)}>{question}</button>)}</nav>}
      {conversationId && latestCompleted?.assistant_message && latestCompleted.action !== "CLARIFY" && latestCompleted.action !== "ABSTAIN" && <ConversationEvidenceDetails key={latestCompleted.turn_id} content={latestCompleted.assistant_message} result={latestCompleted.result} turnId={latestCompleted.turn_id} onEvidence={openEvidence} onPaper={openRankedPaper} isAdmin={isAdmin} activePmids={activePmids} />}
    </>}
    <p className="research-disclaimer" role="note">Research support, not medical advice. Review the original papers.</p>
  </main>;
}
