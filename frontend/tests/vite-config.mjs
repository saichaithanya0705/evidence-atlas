import assert from 'node:assert/strict';

process.env.VITE_BACKEND_PORT = '8765';
const { default: config } = await import('../vite.config.js');
assert.equal(config.server.proxy['/api'].target, 'http://127.0.0.1:8765');
console.log('PASS custom backend port reaches Vite proxy');
