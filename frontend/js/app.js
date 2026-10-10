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
    if (typeof window.EDUSAARTHI_API_BASE === "string" && window.EDUSAARTHI_API_BASE) {
      Api.setBaseUrl(window.EDUSAARTHI_API_BASE);
    }

    State.init();
    refs = Render.init();

    State.subscribe(renderTick);
    wireEvents();
    renderTick(State.get());

    // Restore profile form values from state
    populateProfileForm();
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
    refs.composerStatus.textContent = loading ? "Thinking\u2026" : "";
    updateSendState();
  }

  /* ------------------------------- request flow ------------------------------- */

  function submitCurrentMessage(opts) {
    opts = opts || {};
    var text = opts.text !== undefined ? String(opts.text).trim() : refs.composerInput.value.trim();
    if (!text || State.get().request.status === "loading") return;

    // Ensure there is an active conversation
    var active = State.getActive();
    if (!active || (!opts.continueCurrent && active.messages.length > 0 && active.title)) {
      State.newConversation(true);
    } else if (!active) {
      State.newConversation(true);
    }

    active = State.getActive();
    if (active.messages.length === 0 && !active.title) {
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
        error: { message: "The request could not be completed. Please try again.", code: "failed" },
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
        : "Here is what I found.";
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
      var el = refs.conversation;
      if (!el) return;
      // Auto-scroll only if user is near the bottom
      var threshold = 150;
      var atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
      if (atBottom || State.get().request.status === "loading") {
        el.scrollTop = el.scrollHeight;
      }
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

  /* ------------------------------- profile ------------------------------- */

  function openProfileDialog() {
    if (refs.profileDialog && typeof refs.profileDialog.showModal === "function") {
      populateProfileForm();
      refs.profileDialog.showModal();
    }
  }

  function closeProfileDialog() {
    if (refs.profileDialog) {
      refs.profileDialog.close();
    }
  }

  function populateProfileForm() {
    var form = document.getElementById("studentProfileForm");
    if (!form) return;
    var profile = State.get().studentProfile || {};
    Object.keys(profile).forEach(function (key) {
      if (form.elements[key]) form.elements[key].value = profile[key];
    });
  }

  function handleProfileSave(e) {
    e.preventDefault();
    var form = e.target;
    var formData = new FormData(form);
    var profile = {};
    formData.forEach(function (value, key) {
      if (value.trim() !== "") {
        profile[key] = value.trim();
      }
    });
    State.setStudentProfile(profile);
    closeProfileDialog();
    toast("Profile saved!");
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
      case "toggle-activity":
        toggleActivity(el);
        break;
      case "open-conversation":
        handleOpenConversation(el.getAttribute("data-id"));
        break;
      case "delete-conversation":
        handleDeleteConversation(el.getAttribute("data-id"));
        break;
      case "rename-conversation":
        handleRenameConversation(el.getAttribute("data-id"));
        break;
      case "close-profile":
        closeProfileDialog();
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
      toast("Plan saved!");
    } else {
      toast("Nothing to save.", "warn");
    }
  }

  function toggleActivity(button) {
    var parent = button.closest(".activity");
    if (!parent) return;
    var body = parent.querySelector(".activity__body");
    if (!body) return;
    var open = body.hidden;
    body.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.classList.toggle("activity__toggle--open", open);
  }

  function handleOpenConversation(id) {
    State.loadConversation(id);
    closeSidebar();
    focusComposer();
  }

  function handleDeleteConversation(id) {
    if (!confirm("Delete this conversation?")) return;
    State.deleteConversation(id);
    toast("Conversation deleted");
    // If no active conversation, don't auto-create one — show welcome screen
  }

  function handleRenameConversation(id) {
    var conv = State.get().investigations.filter(function (i) { return i.id === id; })[0];
    if (!conv) return;
    var current = conv.title || "";
    var newTitle = prompt("Rename conversation:", current);
    if (newTitle !== null && newTitle.trim() !== current.trim()) {
      State.renameConversation(id, newTitle.trim());
      toast("Conversation renamed");
    }
  }

  function closeSidebar() {
    if (State.get().sidebarOpen) State.setSidebarOpen(false);
  }

  /* ------------------------------- event wiring ------------------------------- */

  function wireEvents() {
    // Delegated click handler for data-action elements
    document.addEventListener("click", function (e) {
      var el = e.target.closest("[data-action]");
      if (!el) return;
      handleAction(el);
    });

    // Keyboard: Enter/Space on actionable items, Escape to close sidebar
    document.addEventListener("keydown", function (e) {
      var el = e.target;
      if (el && el.getAttribute && el.getAttribute("data-action")) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleAction(el);
        }
      }
      if (e.key === "Escape") {
        if (State.get().sidebarOpen) {
          closeSidebar();
        }
      }
    });

    // Change handler for checkboxes
    document.addEventListener("change", function (e) {
      var input = e.target;
      if (!input || !input.dataset) return;
      if (input.dataset.action === "checklist-toggle") {
        State.updateChecklist(Number(input.dataset.index), input.checked);
      }
    });

    // Sidebar toggle (mobile hamburger)
    refs.menuBtn.addEventListener("click", function () {
      State.setSidebarOpen(!State.get().sidebarOpen);
    });

    // Sidebar collapse (desktop)
    if (refs.sidebarCollapseBtn) {
      refs.sidebarCollapseBtn.addEventListener("click", function () {
        State.setSidebarCollapsed(true);
      });
    }
    if (refs.sidebarExpandBtn) {
      refs.sidebarExpandBtn.addEventListener("click", function () {
        State.setSidebarCollapsed(false);
      });
    }

    // Scrim click closes sidebar on mobile
    refs.scrim.addEventListener("click", closeSidebar);

    // Demo toggle
    refs.demoToggle.addEventListener("click", function () {
      var on = !(State.get().demoMode);
      State.setDemoMode(on);
      toast(on ? "Demo mode enabled." : "Demo mode disabled.", "warn");
    });

    // New chat button
    refs.newChatBtn.addEventListener("click", function () {
      State.newConversation(true);
      closeSidebar();
      focusComposer();
    });

    // Brand link = new chat
    refs.brandLink.addEventListener("click", function (e) {
      e.preventDefault();
      State.newConversation(true);
      closeSidebar();
      focusComposer();
    });

    // Profile button
    refs.profileBtn.addEventListener("click", function () {
      openProfileDialog();
    });

    // Profile form submit
    var profileForm = document.getElementById("studentProfileForm");
    if (profileForm) {
      profileForm.addEventListener("submit", handleProfileSave);
    }

    // Composer submit
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
  }

  /* ------------------------------- boot ------------------------------- */

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();