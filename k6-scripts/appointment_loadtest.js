// Direct load test for GET /api/user/appointment
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('errors');
const latencyTrend = new Trend('latency');

const BASE_URL = 'http://localhost:8001';
const ENDPOINT = '/api/user/appointment';

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2000'],
  },
  vus: 1,
  duration: '10s',
};

export default function () {
  const resp = http.get(`${BASE_URL}${ENDPOINT}`, {
    headers: { 'User-Agent': 'BackendTestForge-k6' },
    tags: { endpoint: ENDPOINT, method: 'GET' },
  });

  check(resp, {
    'status is 200': (r) => r.status === 200,
    'has data': (r) => {
      try { return JSON.parse(r.body).data.length > 0; } catch { return false; }
    },
    'response time < 2s': (r) => r.timings.duration < 2000,
  });

  errorRate.add(resp.status >= 400);
  latencyTrend.add(resp.timings.duration);
}
