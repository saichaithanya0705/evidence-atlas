function validateDetails(value, pmid) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.pmid !== pmid) {
    throw new Error('The service returned an unexpected paper-details response.');
  }
  const result = { pmid };
  for (const field of ['mesh_terms', 'keywords', 'authors']) {
    if (field === 'authors' && value[field] === undefined) continue;
    if (!Array.isArray(value[field]) || value[field].some(item => typeof item !== 'string')) {
      throw new Error('The service returned incomplete or invalid paper metadata.');
    }
    result[field] = value[field].map(item => item.trim()).filter(Boolean);
  }
  for (const field of ['title', 'abstract', 'journal', 'publication_date', 'study_type', 'doi']) {
    if (value[field] === undefined) continue;
    if (value[field] !== null && typeof value[field] !== 'string') {
      throw new Error('The service returned invalid paper metadata.');
    }
    result[field] = value[field];
  }
  if (value.year !== undefined) {
    if (value.year !== null && !Number.isInteger(value.year)) throw new Error('Invalid paper year.');
    result.year = value.year;
  }
  return result;
}

export function createPaperDetailsLoader(fetchPaper, cacheLimit = 50) {
  // Scoped to the mounted workspace, not shared across signed-in accounts.
  const cache = new Map();
  return pmid => {
    if (cache.has(pmid)) return cache.get(pmid);
    const request = Promise.resolve().then(() => fetchPaper(pmid))
      .then(value => validateDetails(value, pmid))
      .catch(error => {
        if (cache.get(pmid) === request) cache.delete(pmid);
        throw error;
      });
    cache.set(pmid, request);
    while (cache.size > Math.max(1, cacheLimit)) cache.delete(cache.keys().next().value);
    return request;
  };
}

export function metadataText(value, status) {
  if (Array.isArray(value) && value.length) return value.join(', ');
  if (status === 'loading') return 'Loading paper metadata…';
  if (status === 'error') return 'Unavailable — paper details could not be loaded';
  return Array.isArray(value) ? 'Not provided in the stored PubMed record'
    : 'Not available in the paper-details response';
}
