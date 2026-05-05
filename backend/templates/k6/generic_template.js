// Generic k6 load test template
// Variables filled by K6Runner:
//   __ENV.BASE_URL    — target service URL
//   __ENV.ENDPOINTS   — JSON array of {method, path}
//   __ENV.DURATION    — seconds per step
//   __ENV.MAX_VUS     — max virtual users

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const latencyTrend = new Trend('latency');

// Parse endpoints from environment
const endpoints = JSON.parse(__ENV.ENDPOINTS || '[]');
const baseUrl = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
  },
  // Will be overridden by K6Runner for each step
  vus: 1,
  duration: '10s',
};

export default function () {
  if (endpoints.length === 0) {
    // Health check endpoint as fallback
    const resp = http.get(`${baseUrl}/health`);
    check(resp, { 'status is 200': (r) => r.status === 200 });
    errorRate.add(resp.status >= 400);
    latencyTrend.add(resp.timings.duration);
    return;
  }

  // Pick a random endpoint
  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];
  const url = `${baseUrl}${ep.path || ''}`;
  const method = (ep.method || 'GET').toLowerCase();

  let resp;
  const params = {
    headers: { 'User-Agent': 'BackendTestForge-k6' },
    tags: { endpoint: ep.path || '/', method: ep.method || 'GET' },
  };

  switch (method) {
    case 'get':
      resp = http.get(url, params);
      break;
    case 'post':
      resp = http.post(url, JSON.stringify(ep.sample_body || {}), {
        ...params,
        headers: { ...params.headers, 'Content-Type': 'application/json' },
      });
      break;
    case 'put':
      resp = http.put(url, JSON.stringify(ep.sample_body || {}), {
        ...params,
        headers: { ...params.headers, 'Content-Type': 'application/json' },
      });
      break;
    case 'delete':
      resp = http.del(url, null, params);
      break;
    case 'patch':
      resp = http.patch(url, JSON.stringify(ep.sample_body || {}), {
        ...params,
        headers: { ...params.headers, 'Content-Type': 'application/json' },
      });
      break;
    default:
      resp = http.get(url, params);
  }

  check(resp, {
    'status < 500': (r) => r.status < 500,
    'response time < 2s': (r) => r.timings.duration < 2000,
  });

  errorRate.add(resp.status >= 400);
  latencyTrend.add(resp.timings.duration);
}
