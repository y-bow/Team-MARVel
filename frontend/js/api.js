/* ============================================================================
 * EduSaarthi AI — api.js
 *
 * HTTP client and response validation for the agreed backend contract:
 *
 *   POST {base}/api/chat
 *   request:  { "message": string, "conversation_id": string|null }
 *   response: { conversation_id, status, answer, sources[], events[],
 *               action_plan[] }
 *
 * The backend emits status "needs_clarification"; it is normalised here to
 * the client-side "clarification" (which also carries a structured
 * `clarification` object). Tool event statuses arrive already normalised to
 * "completed"/"failed".
 *
 * Optional forward-compatible fields (rendered only when present, never
 * fabricated): matches[], eligibility{}, documents[], steps[], clarification{}.
 *
 * The client never trusts the shape of a response: everything is validated and
 * coerced before it reaches the renderer.
 * ========================================================================== */
(function () {
  "use strict";

  var DEFAULT_BASE = ""; // same-origin by default
  var baseUrl = DEFAULT_BASE;
  var REQUEST_TIMEOUT_MS = 120000;

  var EVENT_STATUSES = ["queued", "running", "completed", "failed"];
  var RESPONSE_STATUSES = ["completed", "clarification", "no_results", "failed"];

  function ApiError(message, code, extra) {
    this.name = "ApiError";
    this.message = message || "Something went wrong.";
    this.code = code || "error";
    this.status = (extra && extra.status) || null;
    if (Error.captureStackTrace) Error.captureStackTrace(this, ApiError);
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  var MAX_TEXT = 20000;
  var MAX_SHORT = 600;

  /* ------------------------------- coercion ------------------------------- */

  function asString(value, max) {
    if (value === null || value === undefined) return "";
    var str = typeof value === "string" ? value : String(value);
    str = str.replace(/\u0000/g, "");
    if (max && str.length > max) str = str.slice(0, max) + "…";
    return str;
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function safeUrl(value) {
    var str = typeof value === "string" ? value.trim() : "";
    if (!str) return "";
    var url;
    try {
      url = new URL(str, window.location.href);
    } catch (e) {
      return "";
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    return url.href;
  }

  /* ------------------------------- normalisers ------------------------------- */

  function normaliseSource(raw, index) {
    if (!raw || typeof raw !== "object") return null;
    var title = asString(raw.title || raw.name || raw.label, MAX_SHORT);
    var url = safeUrl(raw.url || raw.link || raw.href);
    if (!title && !url) return null;
    return {
      id: asString(raw.id || raw.key, 80) || "SRC-" + (index + 1),
      title: title || "Untitled source",
      url: url
    };
  }

  function normaliseEvent(raw, index) {
    if (!raw || typeof raw !== "object") return null;
    var status = asString(raw.status).toLowerCase();
    if (EVENT_STATUSES.indexOf(status) === -1) status = "completed";
    var tool = asString(raw.tool || raw.name || raw.step, 80) || "tool_" + (index + 1);
    return {
      id: asString(raw.id, 80) || "evt-" + (index + 1) + "-" + tool,
      tool: tool,
      status: status,
      summary: asString(raw.summary || raw.description || raw.message, MAX_SHORT),
      detail: asString(raw.detail || raw.details || raw.result, 4000)
    };
  }

  function normalisePlanItem(raw) {
    if (raw === null || raw === undefined) return null;
    if (typeof raw === "string") {
      var t = asString(raw, MAX_SHORT);
      return t ? { title: t, completed: false } : null;
    }
    if (typeof raw !== "object") return null;
    var title = asString(raw.title || raw.text || raw.label, MAX_SHORT);
    if (!title) return null;
    return { title: title, completed: !!raw.completed };
  }

  function normaliseMatch(raw, index) {
    if (!raw || typeof raw !== "object") return null;
    var title = asString(raw.title || raw.name, MAX_SHORT);
    if (!title) return null;
    var match = asString(raw.match || raw.confidence || raw.relevance).toLowerCase();
    if (["strong", "high", "exact"].indexOf(match) !== -1) match = "strong";
    else if (["possible", "medium", "partial", "likely"].indexOf(match) !== -1) match = "possible";
    else match = "low";
    return {
      id: asString(raw.id || raw.code, 80) || "MATCH-" + (index + 1),
      title: title,
      provider: asString(raw.provider || raw.authority || raw.organisation, MAX_SHORT),
      summary: asString(raw.summary || raw.description, MAX_SHORT * 2),
      url: safeUrl(raw.url || raw.link),
      match: match
    };
  }

  function normaliseEligibility(raw) {
    if (!raw || typeof raw !== "object") return null;
    var met = asArray(raw.met || raw.matched || raw.satisfied).map(function (v) {
      return asString(v, MAX_SHORT);
    }).filter(Boolean);
    var missing = asArray(raw.missing || raw.unsatisfied || raw.gaps || raw.incomplete).map(function (v) {
      return asString(v, MAX_SHORT);
    }).filter(Boolean);
    var unknown = asArray(raw.unknown || raw.uncertain).map(function (v) {
      return asString(v, MAX_SHORT);
    }).filter(Boolean);
    if (!met.length && !missing.length && !unknown.length) return null;
    return { met: met, missing: missing, unknown: unknown };
  }

  function normaliseDocuments(raw) {
    return asArray(raw)
      .map(function (item) {
        if (typeof item === "string") {
          var name = asString(item, MAX_SHORT);
          return name ? { name: name, note: "" } : null;
        }
        if (!item || typeof item !== "object") return null;
        var n = asString(item.name || item.title || item.document, MAX_SHORT);
        if (!n) return null;
        return { name: n, note: asString(item.note || item.description || item.detail, MAX_SHORT) };
      })
      .filter(Boolean);
  }

  function normaliseSteps(raw) {
    return asArray(raw)
      .map(function (item, index) {
        if (typeof item === "string") {
          var title = asString(item, MAX_SHORT);
          return title ? { title: title, detail: "" } : null;
        }
        if (!item || typeof item !== "object") return null;
        var t = asString(item.title || item.step || item.name, MAX_SHORT);
        if (!t) return null;
        return {
          title: t,
          detail: asString(item.detail || item.description || item.text, MAX_SHORT * 2)
        };
      })
      .filter(Boolean);
  }

  function normaliseClarification(raw) {
    if (!raw) return null;
    if (typeof raw === "string") {
      var q = asString(raw, MAX_SHORT * 2);
      return q ? { question: q, options: [] } : null;
    }
    if (typeof raw !== "object") return null;
    var question = asString(raw.question || raw.prompt || raw.text, MAX_SHORT * 2);
    var options = asArray(raw.options).map(function (o) {
      return asString(o, MAX_SHORT);
    }).filter(Boolean);
    if (!question && !options.length) return null;
    return { question: question, options: options };
  }

  function inferStatus(raw, answer, sources, matches, events, clarification) {
    var status = asString(raw.status).toLowerCase();
    if (status === "needs_clarification") return "clarification";
    if (RESPONSE_STATUSES.indexOf(status) !== -1) return status;
    if (clarification) return "clarification";
    var anyFailed = events.some(function (e) {
      return e.status === "failed";
    });
    if (anyFailed && !answer) return "failed";
    if (!answer && !sources.length && !matches.length) return "no_results";
    return "completed";
  }

  /**
   * Validate and coerce a raw API payload into the canonical client shape.
   * Throws ApiError when the payload is fundamentally unusable.
   */
  function normalise(raw) {
    if (!raw || typeof raw !== "object") {
      throw new ApiError("The service returned an unexpected response.", "malformed");
    }

    var sources = asArray(raw.sources).map(normaliseSource).filter(Boolean);
    var events = asArray(raw.events).map(normaliseEvent).filter(Boolean);
    var actionPlan = asArray(raw.action_plan || raw.actionPlan || raw.checklist)
      .map(normalisePlanItem)
      .filter(Boolean);
    var matches = asArray(raw.matches || raw.schemes || raw.results)
      .map(normaliseMatch)
      .filter(Boolean);
    var eligibility = normaliseEligibility(raw.eligibility);
    var documents = normaliseDocuments(raw.documents || raw.required_documents);
    var steps = normaliseSteps(raw.steps || raw.application_steps || raw.instructions);
    var clarification = normaliseClarification(raw.clarification);
    var answer = asString(raw.answer || raw.message || raw.response, MAX_TEXT);

    var status = inferStatus(raw, answer, sources, matches, events, clarification);

    return {
      conversationId: asString(raw.conversation_id || raw.conversationId, 120) || null,
      status: status,
      answer: answer,
      sources: sources,
      events: events,
      actionPlan: actionPlan,
      matches: matches,
      eligibility: eligibility,
      documents: documents,
      steps: steps,
      clarification: clarification,
      demo: !!raw.demo
    };
  }

  /* ------------------------------- request ------------------------------- */

  function setBaseUrl(value) {
    baseUrl = typeof value === "string" ? value.replace(/\/+$/, "") : DEFAULT_BASE;
  }

  function getBaseUrl() {
    return baseUrl;
  }

  function endpoint() {
    return baseUrl + "/api/chat";
  }

  /**
   * Send a chat request.
   * @param {{message: string, conversationId?: string|null, signal?: AbortSignal}} options
   * @returns {Promise<object>} canonical normalized response
   */
  function sendChat(options) {
    options = options || {};
    var message = typeof options.message === "string" ? options.message.trim() : "";
    if (!message) {
      return Promise.reject(new ApiError("Please enter a message.", "empty"));
    }

    var controller = null;
    var timeoutId = null;
    var signal = options.signal;
    if (typeof AbortController !== "undefined") {
      controller = new AbortController();
      if (signal) {
        if (signal.aborted) controller.abort();
        else signal.addEventListener("abort", function () { controller.abort(); });
      }
      timeoutId = window.setTimeout(function () {
        controller.abort();
      }, REQUEST_TIMEOUT_MS);
    }

    var payload = {
      message: message,
      conversation_id: options.conversationId || null,
      student_profile: options.studentProfile || null
    };

    return fetch(endpoint(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json"
      },
      body: JSON.stringify(payload),
      signal: controller ? controller.signal : undefined,
      credentials: "same-origin"
    })
      .then(function (res) {
        if (!res.ok) {
          return readErrorDetail(res).then(function (detail) {
            throw new ApiError(
              detail || "The service responded with an error (" + res.status + ").",
              "http",
              { status: res.status }
            );
          });
        }
        return res.text().then(function (text) {
          if (!text) {
            throw new ApiError("The service returned an empty response.", "empty");
          }
          var data;
          try {
            data = JSON.parse(text);
          } catch (e) {
            throw new ApiError("The service returned an unreadable response.", "parse");
          }
          return normalise(data);
        });
      })
      .catch(function (err) {
        if (err instanceof ApiError) throw err;
        if (err && err.name === "AbortError") {
          throw new ApiError(
            "The request took too long and was cancelled. Please try again.",
            "timeout"
          );
        }
        throw new ApiError(
          "Unable to reach the EduSaarthi service. Check your connection and try again.",
          "network"
        );
      })
      .finally(function () {
        if (timeoutId) window.clearTimeout(timeoutId);
      });
  }

  function readErrorDetail(res) {
    return res
      .text()
      .then(function (text) {
        if (!text) return "";
        try {
          var data = JSON.parse(text);
          return asString(data.error || data.message || data.detail, MAX_SHORT);
        } catch (e) {
          return "";
        }
      })
      .catch(function () {
        return "";
      });
  }

  window.EduApi = {
    ApiError: ApiError,
    configure: function (opts) {
      if (opts && typeof opts.baseUrl === "string") setBaseUrl(opts.baseUrl);
    },
    setBaseUrl: setBaseUrl,
    getBaseUrl: getBaseUrl,
    endpoint: endpoint,
    sendChat: sendChat,
    normalise: normalise,
    safeUrl: safeUrl
  };
})();
