import assert from 'node:assert/strict';
import { normalizeTraceIteration } from '../src/auditTrace.js';

const iteration = normalizeTraceIteration({ iteration: 0, query: 'original query',
  query_plan: { subqueries: ['expanded query'] }, candidate_pmids: ['123'],
  retrieval: { channels: { bm25: { accepted: 2 }, dense_original: { accepted: 1 } } },
  grade: { grade: 'PARTIAL' } });
assert.deepEqual(iteration.queries, ['original query', 'expanded query']);
assert.deepEqual(iteration.pmids, ['123']);
assert.deepEqual(iteration.channels, ['bm25', 'dense_original']);
assert.equal(iteration.grade, 'PARTIAL');
assert.equal(iteration.iteration, 0);
assert.deepEqual(normalizeTraceIteration({ subqueries: ['legacy'], retrieved_pmids: ['456'], channels_used: ['bm25'] }).pmids, ['456']);
assert.deepEqual(normalizeTraceIteration({ query_plan: [], candidate_pmids: 'invalid' }).pmids, []);
console.log('Audit trace contract passed');
