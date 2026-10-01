import assert from 'node:assert/strict';
import { createPaperDetailsLoader, metadataText } from '../src/paperDetails.js';

const detail = { pmid: '42147601', title: 'Retinal review', mesh_terms: [],
  keywords: ['cardiovascular complications', 'diabetes mellitus'] };
let calls = 0;
const load = createPaperDetailsLoader(async () => { calls++; return detail; });
const [first, second] = await Promise.all([load('42147601'), load('42147601')]);
assert.equal(calls, 1, 'parallel opens must share a detail request');
assert.deepEqual(first.keywords, detail.keywords);
assert.deepEqual(second.mesh_terms, []);
await load('42147601');
assert.equal(calls, 1, 'successful paper details must be reused');

assert.equal(metadataText([], 'loading'), 'Loading paper metadata…');
assert.equal(metadataText(undefined, 'error'), 'Unavailable — paper details could not be loaded');
assert.equal(metadataText([], 'loaded'), 'Not provided in the stored PubMed record');
assert.equal(metadataText(['Humans'], 'loading'), 'Humans');
assert.equal(metadataText(undefined, 'loaded'), 'Not available in the paper-details response');

let attempts = 0;
const retry = createPaperDetailsLoader(async () => {
  attempts++;
  if (attempts === 1) throw new Error('temporary failure');
  return detail;
});
await assert.rejects(retry('42147601'), /temporary failure/);
assert.deepEqual((await retry('42147601')).keywords, detail.keywords);
assert.equal(attempts, 2, 'failed requests must remain retryable');

for (const malformed of [null, {}, {...detail, pmid:'123'}, {...detail, keywords:null},
  {...detail, mesh_terms:['Humans', 42]}, {...detail, keywords:undefined}]) {
  await assert.rejects(createPaperDetailsLoader(async () => malformed)('42147601'),
    /invalid|incomplete|unexpected/i, 'malformed data must not masquerade as absent source metadata');
}

const safe = await createPaperDetailsLoader(async () => ({...detail,
  keywords: ['  diabetes mellitus  ', ''], evidenceRecords: ['unexpected override'], internal: 'hidden'}))('42147601');
assert.deepEqual(safe.keywords, ['diabetes mellitus'], 'blank terms must be normalized');
assert.equal(safe.evidenceRecords, undefined, 'details must not overwrite conversation evidence');
assert.equal(safe.internal, undefined, 'only documented metadata fields may be merged');

let smallCalls = 0;
const small = createPaperDetailsLoader(async pmid => { smallCalls++; return {...detail, pmid}; }, 2);
await small('1'); await small('2'); await small('3');
await small('1');
assert.equal(smallCalls, 4, 'the bounded cache must evict its oldest entry');
console.log('Paper metadata contracts passed: deduplication, caching, source absence, errors, retry, schema validation.');
