// Express/Node.js k6 load test template
// Optimized for single-threaded event-loop architecture
// Variables: BASE_URL, ENDPOINTS, DURATION, MAX_VUS

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('errors');
const endpoints = JSON.parse(__ENV.ENDPOINTS || '[]');
const baseUrl = __ENV.BASE_URL || 'http://localhost:3000';

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
  },
  vus: 1,
  duration: '10s',
};

export default function () {
  if (endpoints.length === 0) {
    http.get(`${baseUrl}/`);
    return;
  }

  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];
  const url = `${baseUrl}${ep.path || ''}`;
  const method = (ep.method || 'GET').toLowerCase();
  const params = {
    headers: { 'User-Agent': 'BackendTestForge-k6', 'Connection': 'keep-alive' },
    tags: { endpoint: ep.path || '/', method: ep.method || 'GET' },
  };

  let resp;
  switch (method) {
    case 'get': resp = http.get(url, params); break;
    case 'post': resp = http.post(url, JSON.stringify(ep.sample_body || {}), {
      ...params, headers: { ...params.headers, 'Content-Type': 'application/json' },
    }); break;
    default: resp = http.get(url, params);
  }
  check(resp, { 'ok': (r) => r.status < 500 });
}
