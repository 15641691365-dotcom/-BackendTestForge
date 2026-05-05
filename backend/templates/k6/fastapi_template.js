// FastAPI-optimized k6 load test template
// Uses Keep-Alive connections and targets health/read-only endpoints first
// Variables filled by K6Runner:
//   __ENV.BASE_URL    — target service URL
//   __ENV.ENDPOINTS   — JSON array of {method, path}
//   __ENV.DURATION    — seconds per step
//   __ENV.MAX_VUS     — max virtual users

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('errors');
const latencyTrend = new Trend('latency');

const endpoints = JSON.parse(__ENV.ENDPOINTS || '[]');
const baseUrl = __ENV.BASE_URL || 'http://localhost:8000';
const duration = parseInt(__ENV.DURATION || '30');

// Connection pool optimization for FastAPI/uvicorn
// Uvicorn uses asyncio, which benefits from keep-alive + parallel connections
export const options = {
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
  },
  // Scenarios allow us to maintain constant VUs without ramping up
  scenarios: {
    constant_load: {
      executor: 'constant-vus',
      vus: 1,
      duration: `${duration}s`,
    },
  },
};

export default function () {
  if (endpoints.length === 0) {
    const resp = http.get(`${baseUrl}/health`);
    check(resp, { 'health ok': (r) => r.status === 200 });
    errorRate.add(resp.status >= 400);
    latencyTrend.add(resp.timings.duration);
    return;
  }

  // Pick a random endpoint, bias towards GET requests (read-heavy load)
  // Sort endpoints: GET first, then POST/PUT/DELETE
  const getEndpoints = endpoints.filter(ep => (ep.method || 'GET').toUpperCase() === 'GET');
  const writeEndpoints = endpoints.filter(ep => (ep.method || 'GET').toUpperCase() !== 'GET');
  const mixedEndpoints = [
    ...getEndpoints,
    ...getEndpoints,  // Double GET weight
    ...writeEndpoints,
  ];

  const ep = mixedEndpoints[Math.floor(Math.random() * mixedEndpoints.length)];
  const url = `${baseUrl}${ep.path || ''}`;
  const method = (ep.method || 'GET').toLowerCase();

  const params = {
    headers: {
      'User-Agent': 'BackendTestForge-k6',
      'Connection': 'keep-alive',
    },
    tags: { endpoint: ep.path || '/', method: ep.method || 'GET' },
  };

  let resp;
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
    default:
      resp = http.get(url, params);
  }

  check(resp, {
    'ok': (r) => r.status < 500,
  });

  errorRate.add(resp.status >= 400);
  latencyTrend.add(resp.timings.duration);
}
