import http from 'k6/http';
import { check, fail } from 'k6';

// Default execution is read-only. Do not place credentials, API keys, or customer data here.
const baseUrl = __ENV.BASE_URL;
const token = __ENV.TOKEN;
const confirmId = __ENV.CONFIRM_ID;

if (!baseUrl || !token) {
  fail('BASE_URL and TOKEN are required. Use an isolated test environment.');
}

const headers = {
  // Confirm the concrete header name from an authenticated browser request before execution.
  // The service login controller returns its token in the framework token header.
  Authorization: token,
  'Content-Type': 'application/x-www-form-urlencoded',
};

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: { http_req_failed: ['rate==0'] },
};

function isSuccessful(response) {
  // Existing controllers may return either a direct body or the project's standard result wrapper.
  return response.status >= 200 && response.status < 300;
}

export default function () {
  const list = http.post(`${baseUrl}/renew/credit/customer/list`, 'page=1&rows=10', { headers });
  check(list, {
    'renew-credit list returns 2xx': isSuccessful,
    'renew-credit list is JSON': (r) => (r.headers['Content-Type'] || '').includes('application/json'),
  });

  // Confirmation changes state. It is deliberately opt-in.
  if (confirmId) {
    const confirm = http.post(
      `${baseUrl}/renew/credit/customer/confirm`,
      `id=${encodeURIComponent(confirmId)}`,
      { headers },
    );
    check(confirm, { 'confirmation returns 2xx': isSuccessful });
  }
}
