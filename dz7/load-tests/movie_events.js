import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = __ENV.BASE_URL || "http://producer-service:8000";
const aggregationUrl = __ENV.AGGREGATION_URL || "http://aggregation-service:8001";

export const options = {
  scenarios: {
    producer_load: {
      executor: "constant-vus",
      vus: 12,
      duration: "35s",
      exec: "producerLoad",
    },
    aggregation_smoke: {
      executor: "constant-vus",
      vus: 2,
      duration: "35s",
      exec: "aggregationHealth",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{scenario:producer_load}": ["p(95)<500"],
    checks: ["rate>0.99"],
  },
};

function randomEvent(vu, iter) {
  const now = new Date();
  return JSON.stringify({
    user_id: `load-user-${vu % 20}`,
    movie_id: `movie-${iter % 10}`,
    event_type: iter % 2 === 0 ? "VIEW_STARTED" : "VIEW_FINISHED",
    timestamp: now.toISOString(),
    device_type: "DESKTOP",
    session_id: `load-session-${vu}-${iter}`,
    progress_seconds: iter % 2 === 0 ? 0 : 3600,
  });
}

export function producerLoad() {
  const payload = randomEvent(__VU, __ITER);
  const response = http.post(`${baseUrl}/events`, payload, {
    headers: { "Content-Type": "application/json" },
    tags: { scenario: "producer_load" },
  });

  check(response, {
    "producer returns 200": (r) => r.status === 200,
  });
  sleep(0.2);
}

export function aggregationHealth() {
  const response = http.get(`${aggregationUrl}/health`, {
    tags: { scenario: "aggregation_smoke" },
  });
  check(response, {
    "aggregation healthy": (r) => r.status === 200,
  });
  sleep(1);
}
