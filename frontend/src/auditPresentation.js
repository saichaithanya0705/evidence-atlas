export function auditDate(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not recorded';
  return new Intl.DateTimeFormat(undefined, {dateStyle:'medium', timeStyle:'long'}).format(new Date(value));
}
export function auditDuration(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? `${(value / 1000).toFixed(3)} s` : 'Not recorded';
}
export function readAuditFilters(search = '') {
  const params = new URLSearchParams(search), result = {};
  for (const key of ['query','account','status','from_date','to_date']) {
    const value = params.get(key);
    if (value && (!key.endsWith('_date') || /^\d{4}-\d{2}-\d{2}$/.test(value))) result[key] = value;
  }
  const offset = Number(params.get('offset'));
  result.offset = Number.isSafeInteger(offset) && offset >= 0 ? offset : 0;
  return result;
}
export function auditListUrl(filters, offset = 0) {
  const params = new URLSearchParams();
  for (const key of ['query','account','status','from_date','to_date']) if (filters[key]) params.set(key, filters[key]);
  if (offset) params.set('offset', String(offset));
  return '/admin/audits' + (params.size ? '?' + params : '');
}
export function auditRequestParams(filters, offset = 0) {
  const result = {...filters, offset, limit:25};
  for (const key of ['from_date','to_date']) {
    if (!filters[key]) continue;
    const [year,month,day] = filters[key].split('-').map(Number);
    // Inclusive local-calendar dates, converted to UTC for stored timestamps.
    const date = new Date(year,month-1,day + (key === 'to_date' ? 1 : 0));
    result[key] = date.toISOString();
  }
  return result;
}
