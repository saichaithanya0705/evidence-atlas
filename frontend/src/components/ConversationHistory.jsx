import ConversationMessage from "./ConversationMessage.jsx";

export default function ConversationHistory({ turns, pending, responseRef, onEvidence, onPaper, isAdmin, navigate, activePmids = [] }) {
  const latestCompleted = [...turns].reverse().find(turn => turn.assistant_message);
  return <section className="conversation-history" aria-label="Conversation messages">
    {turns.map(turn => <div className="conversation-turn" key={turn.turn_id}>
      <ConversationMessage role="user" content={turn.user_message} />
      {turn.assistant_message && <div ref={turn === latestCompleted ? responseRef : undefined} tabIndex={-1}><ConversationMessage role="assistant" content={turn.assistant_message} status={turn.answer_status} action={turn.action} result={turn.result} turnId={turn.turn_id} onEvidence={onEvidence} onPaper={onPaper} isAdmin={isAdmin} activePmids={activePmids} deferDetails={turn === latestCompleted} /></div>}
      {isAdmin && turn.result?.request_id && <a href={`/admin/audits/${encodeURIComponent(turn.result.request_id)}`} onClick={event => { event.preventDefault(); navigate(`/admin/audits/${encodeURIComponent(turn.result.request_id)}`); }}>View turn audit</a>}
    </div>)}
    {pending && <div className="conversation-turn"><div role="status" aria-live="polite" className="conversation-progress"><span className="large-spinner" /><div><strong>Looking into your question</strong><p>Searching abstracts and checking source support. Broader questions can take longer.</p><div className="research-loading-lines" aria-hidden="true"><i /><i /><i /></div></div></div></div>}
  </section>;
}
