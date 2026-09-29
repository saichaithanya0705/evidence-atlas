import { useEffect, useRef, useState } from "react";
import { createConversation, getConversation, listConversations, submitConversationTurn } from "../api.js";
import ConversationHistory from "./ConversationHistory.jsx";
import ConversationList from "./ConversationList.jsx";
import ResearchComposer from "./ResearchComposer.jsx";

function errorText(error) { return error instanceof Error ? error.message : "An unexpected error occurred."; }

export default function ConversationWorkspace({ conversationId, isAdmin, navigate }) {
  const [conversations, setConversations] = useState([]);
  const [turns, setTurns] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [listState, setListState] = useState({ loading: true, error: "" });
  const [detailState, setDetailState] = useState({ loading: !!conversationId, error: "" });
  const [submitting, setSubmitting] = useState(false);
  const [submissionError, setSubmissionError] = useState("");
  const [pending, setPending] = useState(null);
  const [showList, setShowList] = useState(!conversationId);
  const [selection, setSelection] = useState(null);
  const loadGeneration = useRef(0);
  const skipLoadId = useRef(null);
  const submittingRef = useRef(false);
  const responseRef = useRef(null);
  const focusAfterResponse = useRef(false);

  useEffect(() => {
    let active = true;
    listConversations().then(result => { if (active) { setConversations(result.items || []); setListState({ loading: false, error: "" }); } }).catch(error => { if (active) setListState({ loading: false, error: errorText(error) }); });
    return () => { active = false; };
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId) { setTurns([]); setActiveConversation(null); setDetailState({ loading: false, error: "" }); return undefined; }
    if (skipLoadId.current === conversationId) { skipLoadId.current = null; return undefined; }
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
        setTurns(allTurns.sort((left, right) => left.sequence - right.sequence).map(turn => ({ ...turn })));
        setDetailState({ loading: false, error: "" });
      } catch (error) { if (active && generation === loadGeneration.current) setDetailState({ loading: false, error: errorText(error) }); }
    }
    loadAllTurns();
    return () => { active = false; };
  }, [conversationId]);

  useEffect(() => { if (focusAfterResponse.current && !submitting) { responseRef.current?.focus(); focusAfterResponse.current = false; } }, [turns, submitting]);

  async function startNew() { setShowList(false); setSelection(null); navigate(isAdmin ? "/admin/research" : "/research"); }
  function selectConversation(id) { setShowList(false); setSelection(null); navigate(`${isAdmin ? "/admin" : ""}/research/${encodeURIComponent(id)}`); }
  async function submit(message) {
    if (submittingRef.current) return false;
    const shouldFocusResponse = document.activeElement?.id !== "conversation-message";
    submittingRef.current = true;
    setSubmitting(true);
    setSubmissionError("");
    setDetailState({ loading: false, error: "" });
    let id = conversationId;
    let localTurn = null;
    try {
      if (!id) {
        const created = await createConversation();
        id = created.conversation_id;
        setActiveConversation(created);
        skipLoadId.current = id;
        navigate(`${isAdmin ? "/admin" : ""}/research/${encodeURIComponent(id)}`);
      }
      localTurn = { turn_id: `pending-${Date.now()}`, user_message: message, action: null, answer_status: null, assistant_message: null };
      setTurns(current => [...current, localTurn]);
      setPending({ message });
      const response = await submitConversationTurn(id, { message });
      const completedTurn = { ...localTurn, turn_id: response.turn_id, action: response.action, answer_status: response.answer_status, assistant_message: response.assistant_message, result: response };
      setTurns(current => [...current.filter(turn => turn.turn_id !== localTurn.turn_id), completedTurn]);
      setPending(null);
      setConversations(current => [{ conversation_id: id, title: message.slice(0, 80), updated_at: new Date().toISOString() }, ...current.filter(item => item.conversation_id !== id)]);
      focusAfterResponse.current = shouldFocusResponse;
      return true;
    } catch (error) {
      if (localTurn) setTurns(current => current.map(turn => turn.turn_id === localTurn.turn_id ? { ...turn, answer_status: "FAILED", action: "RESEARCH", assistant_message: "A technical failure prevented this turn from completing. Please try again." } : turn));
      setSubmissionError(`${errorText(error)} Your message is still here; retry when ready.`);
      setPending(null);
      return false;
    } finally { submittingRef.current = false; setSubmitting(false); }
  }

  const title = activeConversation?.title || "Research conversations";
  return <main className={`app-main conversation-workspace ${isAdmin ? "admin-research" : "user-research"}`}>
    <header className="conversation-header"><div><span className="eyebrow">{isAdmin ? "ADMIN RESEARCH DESK" : "YOUR RESEARCH DESK"}</span><h1>{title}</h1><p>Follow the evidence through focused research questions and follow-up discussion.</p></div><div className="conversation-header-actions"><button type="button" onClick={() => setShowList(value => !value)} aria-expanded={showList}>Conversations</button><button type="button" onClick={startNew}>New conversation</button></div></header>
    {showList && <ConversationList conversations={conversations} activeId={conversationId} loading={listState.loading} error={listState.error} onNew={startNew} onSelect={selectConversation} />}
    {detailState.loading && <p role="status">Loading conversation…</p>}
    {detailState.error && <p className="conversation-error" role="alert">{detailState.error}</p>}
    {!detailState.loading && !detailState.error && <>
      {conversationId && <ConversationHistory turns={turns} pending={pending} responseRef={responseRef} onEvidence={pmid => setSelection({ type: "evidence", pmid })} onPaper={paper => setSelection({ type: "paper", paper })} />}
      {!conversationId && !showList && <p className="conversation-empty">Start with a research question. Your messages will be saved in this conversation.</p>}
      <ResearchComposer onSubmit={submit} submitting={submitting} />
      {submissionError && <p className="conversation-error" role="alert">{submissionError}</p>}
      {selection && <p className="message-context" role="status">Selected source {selection.pmid || selection.paper?.pmid}. Open the paper from its source record to review the original study.</p>}
    </>}
    <p className="research-disclaimer" role="note">Research support, not medical advice. Review the original papers.</p>
  </main>;
}
