import ConversationMessage from "./ConversationMessage.jsx";

export default function ConversationHistory({ turns, pending, responseRef, onEvidence, onPaper }) {
  return <section className="conversation-history" aria-label="Conversation messages">
    {turns.map(turn => <div className="conversation-turn" key={turn.turn_id}>
      <ConversationMessage role="user" content={turn.user_message} />
      {turn.assistant_message && <div ref={turn === turns[turns.length - 1] ? responseRef : undefined} tabIndex={-1}><ConversationMessage role="assistant" content={turn.assistant_message} status={turn.answer_status} action={turn.action} result={turn.result} turnId={turn.turn_id} onEvidence={onEvidence} onPaper={onPaper} /></div>}
    </div>)}
    {pending && <div className="conversation-turn"><div role="status" aria-live="polite" className="conversation-progress"><span className="large-spinner" /><strong>Retrieving and reviewing evidence</strong><p>The research service is processing this turn. No answer will appear until its review is complete.</p></div></div>}
  </section>;
}
