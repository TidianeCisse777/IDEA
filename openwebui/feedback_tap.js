(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.OpenWebUIFeedbackTap = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : window, function () {
  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function isOpenWebUIFeedbackRequest(url, method) {
    const href = String(url || "");
    return method === "POST" && /\/api\/v1\/evaluations\/feedback\/?$/.test(href);
  }

  async function readRequestBody(input, init) {
    if (typeof init?.body === "string") {
      return init.body;
    }

    if (input && typeof input === "object" && typeof input.clone === "function") {
      try {
        return await input.clone().text();
      } catch (err) {
        return "";
      }
    }

    return "";
  }

  function normalizeOpenWebUIFeedback(record) {
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      return null;
    }

    const data = asObject(record.data);
    const meta = asObject(record.meta);

    const chatId =
      record.chat_id ||
      meta.chat_id ||
      data.chat_id ||
      meta.conversation_id ||
      null;

    let score = data.score;
    if (score === undefined || score === null) {
      score = data.rating;
    }
    if (score === undefined || score === null) {
      score = record.score;
    }
    if (score === undefined || score === null) {
      score = record.rating;
    }

    if (!chatId || score === undefined || score === null) {
      return null;
    }

    const payload = {
      chat_id: String(chatId),
      score: Number(score),
    };

    const comment = data.comment || record.comment;
    const reason = data.reason || record.reason;
    if (comment) payload.comment = String(comment);
    if (reason) payload.reason = String(reason);

    return payload;
  }

  async function forwardFeedbackToBackend(payload, backendBaseUrl, fetchImpl) {
    const response = await fetchImpl(backendBaseUrl.replace(/\/$/, "") + "/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return response;
  }

  function installOpenWebUIFeedbackTap(options = {}) {
    const backendBaseUrl = options.backendBaseUrl || "http://localhost:8000";
    const fetchImpl = options.fetchImpl || globalThis.fetch?.bind(globalThis);
    if (!fetchImpl) {
      throw new Error("fetch is not available");
    }

    const originalFetch = options.originalFetch || globalThis.fetch?.bind(globalThis);
    if (!originalFetch) {
      throw new Error("original fetch is not available");
    }

    const originalXhr = globalThis.XMLHttpRequest;
    const tapPingPayload = {
      event: "tap_installed",
      href: String(globalThis.location?.href || ""),
    };

    globalThis.fetch = async function patchedFetch(input, init = {}) {
      const url = typeof input === "string" ? input : String(input?.url || "");
      const method =
        String(init.method || (typeof input !== "string" ? input.method : "") || "GET").toUpperCase();
      const bodyText = await readRequestBody(input, init);

      const response = await originalFetch(input, init);

      if (!isOpenWebUIFeedbackRequest(url, method)) {
        return response;
      }

      try {
        const record = bodyText ? JSON.parse(bodyText) : null;
        const payload = normalizeOpenWebUIFeedback(record);
        if (payload) {
          void forwardFeedbackToBackend(payload, backendBaseUrl, fetchImpl);
        }
      } catch (err) {
        console.error("OpenWebUI feedback tap failed", err);
      }

      return response;
    };

    if (originalXhr) {
      globalThis.XMLHttpRequest = class PatchedXMLHttpRequest extends originalXhr {
        open(method, url, ...rest) {
          this.__openwebui_method = String(method || "GET").toUpperCase();
          this.__openwebui_url = String(url || "");
          return super.open(method, url, ...rest);
        }

        send(body) {
          this.addEventListener("loadend", () => {
            try {
              if (!isOpenWebUIFeedbackRequest(this.__openwebui_url, this.__openwebui_method)) {
                return;
              }
              const record = typeof body === "string" ? JSON.parse(body) : body;
              const payload = normalizeOpenWebUIFeedback(record);
              if (payload) {
                void forwardFeedbackToBackend(payload, backendBaseUrl, fetchImpl);
              }
            } catch (err) {
              console.error("OpenWebUI feedback tap XHR failed", err);
            }
          }, { once: true });
          return super.send(body);
        }
      };
    }

    void fetchImpl(backendBaseUrl.replace(/\/$/, "") + "/feedback/tap/ping", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(tapPingPayload),
    }).catch((err) => {
      console.error("OpenWebUI feedback tap ping failed", err);
    });

    return {
      backendBaseUrl,
      restore() {
        globalThis.fetch = originalFetch;
        if (originalXhr) {
          globalThis.XMLHttpRequest = originalXhr;
        }
      },
    };
  }

  return {
    installOpenWebUIFeedbackTap,
    isOpenWebUIFeedbackRequest,
    normalizeOpenWebUIFeedback,
  };
});
