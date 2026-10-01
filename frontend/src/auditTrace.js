export function normalizeTraceIteration(item = {}) {
  const list = value => Array.isArray(value) ? value.filter(x => typeof x === 'string') : [];
  return {
    iteration: item.iteration ?? item.loop,
    queries: [...new Set([...(typeof item.query === 'string' ? [item.query] : []),
      ...list(item.query_plan?.subqueries || item.subqueries || item.queries)])],
    pmids: list(item.candidate_pmids || item.retrieved_pmids || item.pmids || item.selected_pmids),
    channels: item.retrieval?.channels && typeof item.retrieval.channels === 'object'
      ? Object.keys(item.retrieval.channels)
      : list(item.channels_used || item.channels || item.retrieval_channels),
    grade: typeof item.grade === 'object' ? item.grade?.grade : item.grade,
  };
}
