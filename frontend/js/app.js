/* ============================================================================
 * EduSaarthi AI — app.js
 *
 * Application bootstrap, event handling and the orchestration between
 * state.js (data), api.js (network) and render.js (DOM).
 *
 * No network calls live outside api.js; no DOM-heavy logic lives in app.js
 * beyond wiring forms and handling delegated user actions.
 * ========================================================================== */
(function () {
  "use strict";

  var State = window.EduState;
  var Api = window.EduApi;
  var Render = window.EduRender;
  var refs = {};

  var DEMO_DELAY_MS = 950;

  /* ------------------------------- init ------------------------------- */

  function init() {
    // Optional base URL override for separately-hosted frontend/backend:
    // window.EDUSAARTHI_API_BASE = "https://backend.example.com";
    if (typeof window.EDUSAARTHI_API_BASE === "string" && window.EDUSAARTHI_API_BASE) {
      Api.setBaseUrl(window.EDUSAARTHI_API_BASE);
    }

    State.init();
    refs = Render.init();

    // Kept on every state change.
    State.subscribe(renderTick);

    wireEvents();
    renderTick(State.get());
    focusComposer();
  }

  function renderTick(state) {
    Render.render(state);
    updateComposer(state);
  }

  /* ------------------------------- composer ------------------------------- */

  function focusComposer() {
    if (refs.composerInput && document.activeElement !== refs.composerInput) {
      refs.composerInput.focus();
    }
  }

  function autosize() {
    var el = refs.composerInput;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }

  function clearComposer() {
    refs.composerInput.value = "";
    autosize();
    refs.composerInput.focus();
    updateSendState();
  }

  function updateSendState() {
    var state = State.get();
    var loading = state.request.status === "loading";
    var empty = !refs.composerInput.value.trim();
    refs.sendBtn.disabled = loading || empty;
  }

  function updateComposer(state) {
    var loading = state.request.status === "loading";
    refs.composer.classList.toggle("is-loading", loading);
    refs.composerStatus.textContent = loading ? "Investigating…" : "";
    updateSendState();
  }

  /* ------------------------------- request flow ------------------------------- */

  function submitCurrentMessage(opts) {
    opts = opts || {};
    var text = opts.text !== undefined ? String(opts.text).trim() : refs.composerInput.value.trim();
    if (!text || State.get().request.status === "loading") return;

    if (!opts.continueCurrent) {
      State.newInvestigation();
    }
    var active = State.getActive();
    if (active.messages.length === 0 && active.title === "New investigation") {
      State.renameActiveFromMessage(text);
    }
    State.appendMessage({
      id: State.uid("m"),
      role: "user",
      text: text,
      ts: Date.now()
    });
    if (!opts.continueCurrent) clearComposer();
    runRequest(text);
  }

  function runRequest(text) {
    State.setEvents([]);
    State.setResult(null);
    State.setRequest({ status: "loading", error: null, lastMessage: text });
    scrollConversation();

    var active = State.getActive();
    var conversationId = active ? active.conversationId : null;
    var isDemo = State.get().demoMode;
    var profile = State.get().studentProfile || {};

    var promise = isDemo ? demoRequest(text) : Api.sendChat({ message: text, conversationId: conversationId, studentProfile: profile });
    promise.then(handleResponse).catch(function (err) {
      handleFailure(err, text);
    });
  }

  function demoRequest(text) {
    return new Promise(function (resolve) {
      var info = window.EduDemo.resolve(text);
      var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      var delay = reduced ? 250 : DEMO_DELAY_MS;
      window.setTimeout(function () {
        resolve(Api.normalise(info.response));
      }, delay);
    });
  }

  function handleResponse(response) {
    var text = State.get().request.lastMessage || "";
    State.setConversationId(response.conversationId);
    State.setEvents(response.events);
    State.setResult(response);
    State.setRequest({ status: "idle", error: null, lastMessage: text });

    if (response.status === "failed") {
      State.setRequest({
        status: "error",
        error: { message: "The investigation could not be completed. Review the failed activity in the Investigation panel, then retry with the same or adjusted details.", code: "failed" },
        lastMessage: text
      });
    } else if (response.status === "clarification" && response.clarification) {
      State.appendMessage({
        id: State.uid("m"),
        role: "assistant",
        kind: "clarification",
        text: response.clarification.question || response.answer || "Could you provide a little more detail?",
        options: response.clarification.options || [],
        ts: Date.now()
      });
    } else {
      var fallback = response.status === "no_results"
        ? "No relevant records were found in the available dataset for this request."
        : "Here is what the investigation found. Full details, sources and next steps are in the Investigation panel.";
      State.appendMessage({
        id: State.uid("m"),
        role: "assistant",
        kind: response.status === "no_results" ? "no_results" : "answer",
        text: response.answer || fallback,
        ts: Date.now()
      });
    }

    scrollConversation();
  }

  function handleFailure(err, text) {
    State.setRequest({
      status: "error",
      error: {
        message: err && err.message ? err.message : "Something went wrong. Please try again.",
        code: err && err.code ? err.code : "error"
      },
      lastMessage: text
    });
    toast(err && err.code === "network" ? "Could not reach the service." : "The request failed.", "warn");
    scrollConversation();
  }

  function retryLast() {
    var last = State.get().request.lastMessage;
    if (!last || State.get().request.status === "loading") return;
    runRequest(last);
  }

  function scrollConversation() {
    window.requestAnimationFrame(function () {
      refs.conversation.scrollTop = refs.conversation.scrollHeight;
    });
  }

  /* ------------------------------- toasts ------------------------------- */

  function toast(text, type) {
    var el = Render.h("div", { class: "toast" + (type === "warn" ? " toast--warn" : ""), role: "status" }, [
      Render.svgIcon(type === "warn" ? "triangle-alert" : "circle-check"),
      String(text)
    ]);
    refs.toastRegion.appendChild(el);
    window.setTimeout(function () {
      el.remove();
    }, 3800);
  }

  /* ------------------------------- actions ------------------------------- */

  function handleAction(el) {
    var action = el.getAttribute("data-action");
    if (!action) return;

    switch (action) {
      case "starter":
        submitPrompt(el.getAttribute("data-prompt"));
        break;
      case "clarify-option":
        submitCurrentMessage({ text: el.getAttribute("data-prompt"), continueCurrent: true });
        break;
      case "retry":
        retryLast();
        break;
      case "enable-demo":
        State.setDemoMode(true);
        refs.demoToggle.setAttribute("aria-checked", "true");
        retryLast();
        break;
      case "save-plan":
        handleSavePlan();
        break;
      case "event-toggle":
        toggleEventDetails(el);
        break;
      case "open-investigation":
        State.loadInvestigation(el.getAttribute("data-id"));
        closeSidebar();
        setMobileView("chat");
        focusComposer();
        break;
      case "delete-investigation":
        handleDeleteInvestigation(el.getAttribute("data-id"));
        break;
      case "delete-plan":
        State.deleteSavedPlan(el.getAttribute("data-plan-id"));
        toast("Plan deleted");
        break;
      case "source-link":
        /* Anchors are only rendered with validated http(s) URLs. */
        break;
      default:
        break;
    }
  }

  function submitPrompt(prompt) {
    var text = String(prompt || "").trim();
    if (!text) return;
    refs.composerInput.value = text;
    autosize();
    submitCurrentMessage();
  }

  function handleSavePlan() {
    var id = State.savePlanFromActive();
    if (id) {
      toast("Plan saved to Saved plans");
    } else {
      toast("Nothing to save — no next steps were generated.", "warn");
    }
  }

  function toggleEventDetails(button) {
    var id = button.getAttribute("aria-controls");
    var pre = document.getElementById(id);
    if (!pre) return;
    var open = pre.hidden;
    pre.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function handleDeleteInvestigation(id) {
    State.deleteInvestigation(id);
    toast("Investigation deleted");
  }

  function closeSidebar() {
    if (State.get().sidebarOpen) State.setSidebarOpen(false);
  }

  function setMobileView(view) {
    State.setMobileView(view);
  }

  /* ------------------------------- event wiring ------------------------------- */

  function wireEvents() {
    document.addEventListener("click", function (e) {
      var el = e.target.closest("[data-action]");
      if (!el) return;
      handleAction(el);
    });

    document.addEventListener("keydown", function (e) {
      var el = e.target;
      if (el && el.getAttribute && el.getAttribute("data-action") === "open-investigation") {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleAction(el);
        }
      }
      if (e.key === "Escape" && State.get().sidebarOpen) {
        closeSidebar();
      }
    });

    document.addEventListener("change", function (e) {
      var input = e.target;
      if (!input || !input.dataset) return;
      if (input.dataset.action === "checklist-toggle") {
        State.updateChecklist(Number(input.dataset.index), input.checked);
      } else if (input.dataset.action === "saved-toggle") {
        State.toggleSavedItem(input.dataset.planId, Number(input.dataset.index));
      }
    });

    // Nav
    refs.navItems.forEach(function (item) {
      item.addEventListener("click", function () {
        State.setView(item.getAttribute("data-view"));
        closeSidebar();
      });
    });

    // Top-level controls
    refs.menuBtn.addEventListener("click", function () {
      State.setSidebarOpen(!State.get().sidebarOpen);
    });
    refs.scrim.addEventListener("click", closeSidebar);
    refs.panelBack.addEventListener("click", function () {
      setMobileView("chat");
    });

    refs.tabChat.addEventListener("click", function () {
      setMobileView("chat");
    });
    refs.tabPanel.addEventListener("click", function () {
      setMobileView("panel");
    });

    refs.demoToggle.addEventListener("click", function () {
      var on = !(State.get().demoMode);
      State.setDemoMode(on);
      toast(on ? "Demo mode enabled — data shown is illustrative." : "Demo mode disabled.", "warn");
    });

    refs.newInvestigationBtn.addEventListener("click", function () {
      State.newInvestigation(true);
      closeSidebar();
      setMobileView("chat");
      focusComposer();
    });
    refs.brandLink.addEventListener("click", function (e) {
      e.preventDefault();
      State.newInvestigation(true);
      closeSidebar();
      setMobileView("chat");
      focusComposer();
    });

    // Composer
    refs.composer.addEventListener("submit", function (e) {
      e.preventDefault();
      submitCurrentMessage();
    });
    refs.composerInput.addEventListener("input", function () {
      autosize();
      updateSendState();
    });
    refs.composerInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitCurrentMessage();
      }
    });

    var profileForm = document.getElementById("studentProfileForm");
    if (profileForm) {
      profileForm.addEventListener("submit", function(e) {
        e.preventDefault();
        var formData = new FormData(profileForm);
        var profile = {};
        formData.forEach(function(value, key) {
          if (value.trim() !== "") {
            profile[key] = value.trim();
          }
        });
        State.setStudentProfile(profile);
        toast("Profile saved!");
      });
    }
  }

  /* ------------------------------- boot ------------------------------- */

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Populate profile form on load
  document.addEventListener("DOMContentLoaded", function() {
    var form = document.getElementById("studentProfileForm");
    if (!form) return;
    var profile = State.get().studentProfile || {};
    Object.keys(profile).forEach(function(key) {
      if (form.elements[key]) form.elements[key].value = profile[key];
    });
  });
})();