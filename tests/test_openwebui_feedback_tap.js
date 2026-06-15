const assert = require("node:assert/strict");

const tap = require("../openwebui/feedback_tap.js");

async function main() {
  const normalized = tap.normalizeOpenWebUIFeedback({
    type: "rating",
    data: { rating: 1, comment: "Great", reason: "Helpful" },
    meta: { chat_id: "chat-123", message_id: "msg-456" },
  });

  assert.deepEqual(normalized, {
    chat_id: "chat-123",
    score: 1,
    comment: "Great",
    reason: "Helpful",
  });

  assert.equal(
    tap.isOpenWebUIFeedbackRequest("http://localhost:3000/api/v1/evaluations/feedback", "POST"),
    true,
  );
  assert.equal(
    tap.isOpenWebUIFeedbackRequest("http://localhost:3000/api/v1/chat/completions", "POST"),
    false,
  );

  const calls = [];
  const install = tap.installOpenWebUIFeedbackTap({
    backendBaseUrl: "http://localhost:8000",
    originalFetch: async (input, init) => {
      calls.push(["original", input, init]);
      return { ok: true };
    },
    fetchImpl: async (input, init) => {
      calls.push(["backend", input, init]);
      return { ok: true };
    },
  });

  await globalThis.fetch(
    "http://localhost:3000/api/v1/evaluations/feedback",
    {
      method: "POST",
      body: JSON.stringify({
        data: { rating: -1, comment: "Bad", reason: "Too short" },
        meta: { chat_id: "chat-9" },
      }),
    },
  );

  install.restore();

  assert.deepEqual(calls, [
    ["backend", "http://localhost:8000/feedback/tap/ping", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event: "tap_installed",
        href: "",
      }),
    }],
    ["original", "http://localhost:3000/api/v1/evaluations/feedback", {
      method: "POST",
      body: JSON.stringify({
        data: { rating: -1, comment: "Bad", reason: "Too short" },
        meta: { chat_id: "chat-9" },
      }),
    }],
    ["backend", "http://localhost:8000/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: "chat-9",
        score: -1,
        comment: "Bad",
        reason: "Too short",
      }),
    }],
  ]);

  const requestCalls = [];
  const installWithRequest = tap.installOpenWebUIFeedbackTap({
    backendBaseUrl: "http://localhost:8000",
    originalFetch: async (input, init) => {
      requestCalls.push(["original", input.url, input.method, init]);
      return { ok: true };
    },
    fetchImpl: async (input, init) => {
      requestCalls.push(["backend", input, init]);
      return { ok: true };
    },
  });

  const request = new Request("http://localhost:3000/api/v1/evaluations/feedback", {
    method: "POST",
    body: JSON.stringify({
      data: { rating: 1, comment: "Great", reason: "Helpful" },
      meta: { chat_id: "chat-123" },
    }),
  });

  await globalThis.fetch(request);

  installWithRequest.restore();

  assert.deepEqual(requestCalls, [
    ["backend", "http://localhost:8000/feedback/tap/ping", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event: "tap_installed",
        href: "",
      }),
    }],
    ["original", "http://localhost:3000/api/v1/evaluations/feedback", "POST", {}],
    ["backend", "http://localhost:8000/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: "chat-123",
        score: 1,
        comment: "Great",
        reason: "Helpful",
      }),
    }],
  ]);

  const pingCalls = [];
  const installWithPing = tap.installOpenWebUIFeedbackTap({
    backendBaseUrl: "http://localhost:8000",
    originalFetch: async (input, init) => {
      pingCalls.push(["original", input, init]);
      return { ok: true };
    },
    fetchImpl: async (input, init) => {
      pingCalls.push(["backend", input, init]);
      return { ok: true };
    },
  });

  await Promise.resolve();
  installWithPing.restore();

  assert.equal(pingCalls[0][0], "backend");
  assert.equal(pingCalls[0][1], "http://localhost:8000/feedback/tap/ping");
  assert.equal(pingCalls[0][2].method, "POST");
}

main()
  .then(() => {
    console.log("openwebui feedback tap tests passed");
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
