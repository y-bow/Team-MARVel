/* ============================================================================
 * EduSaarthi AI — state.js
 *
 * Single source of truth for client-side application state, with lightweight
 * local persistence for investigation history and saved plans.
 *
 * Persistence note: conversation text is stored in the user's own browser so
 * that investigation history works. Only what the user typed is stored; no
 * credentials or privileged data are kept here.
 * ========================================================================== */
(function () {
  "use strict";

  var STORAGE_KEY = "edusaarthi.v1";
  var MAX_INVESTIGATIONS = 40;
  var MAX_MESSAGES = 60;

  var listeners = [];
  var state = null;

  /* ------------------------------- helpers ------------------------------- */

  function uid(prefix) {
    return (
      (prefix || "id") +
      "-" +
      Date.now().toString(36) +
      "-" +
      Math.random().toString(36).slice(2, 8)
    );
  }

  function clone(value) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (e) {
      return value;
    }
  }

  function createInvestigation() {
    var now = Date.now();
    return {
      id: uid("inv"),
      title: "New investigation",
      createdAt: now,
      updatedAt: now,
      conversationId: null,
      messages: [],
      events: [],
      result: null
    };
  }

  function defaultState() {
    return {
      view: "investigation",
      demoMode: false,
      sidebarOpen: false,
      mobileView: "chat",
      request: { status: "idle", error: null, lastMessage: null },
      investigations: [],
      activeId: null,
      savedPlans: [],
      studentProfile: {}
    };
  }

  function loadPersisted() {
    var base = defaultState();
    var raw = null;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return base;
    }
    if (!raw) return base;
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      return base;
    }
    if (!parsed || typeof parsed !== "object") return base;

    if (Array.isArray(parsed.investigations)) {
      base.investigations = parsed.investigations.filter(function (inv) {
        return inv && typeof inv === "object" && typeof inv.id === "string";
      });
    }
    if (Array.isArray(parsed.savedPlans)) {
      base.savedPlans = parsed.savedPlans.filter(function (p) {
        return p && typeof p === "object" && typeof p.id === "string";
      });
    }
    if (typeof parsed.demoMode === "boolean") base.demoMode = parsed.demoMode;
    if (typeof parsed.activeId === "string") base.activeId = parsed.activeId;
    if (parsed.studentProfile && typeof parsed.studentProfile === "object") {
      base.studentProfile = parsed.studentProfile;
    }

    // Ensure there is always a usable active investigation.
    var active = base.investigations.filter(function (i) {
      return i.id === base.activeId;
    })[0];
    if (!active) {
      var created = createInvestigation();
      base.investigations.unshift(created);
      base.activeId = created.id;
    }
    return base;
  }

  function persist() {
    try {
      var slim = {
        demoMode: state.demoMode,
        activeId: state.activeId,
        studentProfile: state.studentProfile || {},
        savedPlans: state.savedPlans,
        investigations: state.investigations.slice(0, MAX_INVESTIGATIONS).map(function (inv) {
          return {
            id: inv.id,
            title: inv.title,
            createdAt: inv.createdAt,
            updatedAt: inv.updatedAt,
            conversationId: inv.conversationId,
            messages: (inv.messages || []).slice(-MAX_MESSAGES),
            events: inv.events || [],
            result: inv.result || null
          };
        })
      };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(slim));
    } catch (e) {
      /* Storage may be unavailable (private mode, quota). Non-fatal. */
    }
  }

  function emit() {
    for (var i = 0; i < listeners.length; i++) {
      try {
        listeners[i](state);
      } catch (e) {
        /* Keep one broken listener from stopping the rest. */
        if (window.console && console.error) console.error(e);
      }
    }
  }

  function commit(mutator, skipPersist) {
    if (typeof mutator === "function") mutator(state);
    if (!skipPersist) persist();
    emit();
    return state;
  }

  /* ------------------------------- queries ------------------------------- */

  function getActive() {
    for (var i = 0; i < state.investigations.length; i++) {
      if (state.investigations[i].id === state.activeId) {
        return state.investigations[i];
      }
    }
    return null;
  }

  function isEmptyInvestigation(inv) {
    return (
      inv &&
      (!inv.messages || inv.messages.length === 0) &&
      !inv.result &&
      (!inv.events || inv.events.length === 0)
    );
  }

  function titleFromMessage(text) {
    var clean = String(text || "").replace(/\s+/g, " ").trim();
    if (!clean) return "New investigation";
    if (clean.length <= 64) return clean;
    return clean.slice(0, 61).trim() + "…";
  }

  /* ------------------------------- actions ------------------------------- */

  function setView(view) {
    commit(function (s) {
      s.view = view;
    });
  }

  function setDemoMode(on) {
    commit(function (s) {
      s.demoMode = !!on;
    });
  }

  function setSidebarOpen(open) {
    commit(function (s) {
      s.sidebarOpen = !!open;
    }, true);
  }

  function setMobileView(view) {
    commit(function (s) {
      s.mobileView = view === "panel" ? "panel" : "chat";
    }, true);
  }

  function setStudentProfile(profile) {
    commit(function (s) {
      s.studentProfile = profile || {};
    });
  }

  function newInvestigation(force) {
    var active = getActive();
    if (active && isEmptyInvestigation(active) && !force) {
      commit(function (s) {
        s.view = "investigation";
      });
      return active.id;
    }
    var created = createInvestigation();
    commit(function (s) {
      s.investigations.unshift(created);
      s.activeId = created.id;
      s.view = "investigation";
      s.request = { status: "idle", error: null, lastMessage: null };
    });
    return created.id;
  }

  function loadInvestigation(id) {
    var found = state.investigations.filter(function (i) {
      return i.id === id;
    })[0];
    if (!found) return false;
    commit(function (s) {
      s.activeId = id;
      s.view = "investigation";
      s.request = { status: "idle", error: null, lastMessage: null };
    });
    return true;
  }

  function deleteInvestigation(id) {
    commit(function (s) {
      s.investigations = s.investigations.filter(function (i) {
        return i.id !== id;
      });
      if (s.activeId === id) {
        var created = createInvestigation();
        s.investigations.unshift(created);
        s.activeId = created.id;
      }
    });
  }

  function renameActiveFromMessage(text) {
    var active = getActive();
    if (!active) return;
    if (active.title && active.title !== "New investigation") return;
    commit(function () {
      active.title = titleFromMessage(text);
    });
  }

  function setConversationId(id) {
    var active = getActive();
    if (!active) return;
    commit(function () {
      active.conversationId = id || active.conversationId;
      active.updatedAt = Date.now();
    });
  }

  function appendMessage(message) {
    var active = getActive();
    if (!active) return;
    commit(function () {
      active.messages.push(message);
      active.updatedAt = Date.now();
    });
  }

  function appendEvent(event) {
    var active = getActive();
    if (!active) return;
    commit(function () {
      active.events = active.events || [];
      active.events.push(event);
      active.updatedAt = Date.now();
    });
  }

  function replaceLastMessage(message) {
    var active = getActive();
    if (!active || !active.messages.length) return;
    commit(function () {
      active.messages[active.messages.length - 1] = message;
      active.updatedAt = Date.now();
    });
  }

  function removeLastMessageIfStreaming() {
    var active = getActive();
    if (!active || !active.messages.length) return;
    var last = active.messages[active.messages.length - 1];
    if (last && last.kind === "streaming") {
      commit(function () {
        active.messages.pop();
        active.updatedAt = Date.now();
      });
    }
  }

  function setRequest(patch) {
    commit(function (s) {
      s.request = Object.assign({ status: "idle", error: null, lastMessage: null }, s.request, patch);
    }, true);
  }

  function setEvents(events) {
    var active = getActive();
    if (!active) return;
    commit(function () {
      active.events = Array.isArray(events) ? events : [];
      active.updatedAt = Date.now();
    });
  }

  function setResult(result) {
    var active = getActive();
    if (!active) return;
    commit(function () {
      active.result = result || null;
      active.updatedAt = Date.now();
    });
  }

  function updateChecklist(index, completed) {
    var active = getActive();
    if (!active || !active.result || !Array.isArray(active.result.actionPlan)) return;
    if (index < 0 || index >= active.result.actionPlan.length) return;
    commit(function () {
      active.result.actionPlan[index].completed = !!completed;
      active.updatedAt = Date.now();
    });
  }

  function savePlanFromActive() {
    var active = getActive();
    if (!active || !active.result || !Array.isArray(active.result.actionPlan)) {
      return null;
    }
    var items = active.result.actionPlan.map(function (item) {
      return { title: item.title, completed: !!item.completed };
    });
    var existing = state.savedPlans.filter(function (p) {
      return p.investigationId === active.id;
    })[0];
    var plan = {
      id: existing ? existing.id : uid("plan"),
      investigationId: active.id,
      title: active.title || "Saved plan",
      createdAt: existing ? existing.createdAt : Date.now(),
      updatedAt: Date.now(),
      items: items,
      sources: (active.result.sources || []).map(function (s) {
        return { id: s.id, title: s.title, url: s.url };
      })
    };
    commit(function (s) {
      s.savedPlans = s.savedPlans.filter(function (p) {
        return p.id !== plan.id;
      });
      s.savedPlans.unshift(plan);
    });
    return plan.id;
  }

  function toggleSavedItem(planId, index) {
    commit(function (s) {
      s.savedPlans = s.savedPlans.map(function (p) {
        if (p.id !== planId) return p;
        if (p.items[index]) p.items[index].completed = !p.items[index].completed;
        p.updatedAt = Date.now();
        return p;
      });
    });
  }

  function deleteSavedPlan(id) {
    commit(function (s) {
      s.savedPlans = s.savedPlans.filter(function (p) {
        return p.id !== id;
      });
    });
  }

  /* ------------------------------- sources ------------------------------- */

  function getAllSources() {
    var seen = {};
    var out = [];
    state.investigations.forEach(function (inv) {
      var sources = (inv.result && inv.result.sources) || [];
      sources.forEach(function (src) {
        var key = (src.id || "") + "|" + (src.url || src.title || "");
        if (seen[key]) {
          seen[key].investigations = seen[key].investigations + 1;
          return;
        }
        seen[key] = {
          id: src.id,
          title: src.title,
          url: src.url,
          investigationTitle: inv.title,
          investigationId: inv.id
        };
        out.push(seen[key]);
      });
    });
    return out;
  }

  /* ------------------------------- lifecycle ------------------------------- */

  function init() {
    state = loadPersisted();
    // Re-clone to detach from localStorage references and normalise shape.
    state.investigations = state.investigations.map(function (inv) {
      return Object.assign(createInvestigation(), inv, {
        messages: inv.messages || [],
        events: inv.events || []
      });
    });
    state.request = { status: "idle", error: null, lastMessage: null };
    persist();
  }

  function subscribe(fn) {
    listeners.push(fn);
    return function unsubscribe() {
      listeners = listeners.filter(function (l) {
        return l !== fn;
      });
    };
  }

  window.EduState = {
    init: init,
    subscribe: subscribe,
    get: function () {
      return state;
    },
    getActive: getActive,
    getAllSources: getAllSources,
    createInvestigation: createInvestigation,
    uid: uid,
    clone: clone,
    setView: setView,
    setDemoMode: setDemoMode,
    setSidebarOpen: setSidebarOpen,
    setMobileView: setMobileView,
    setStudentProfile: setStudentProfile,
    newInvestigation: newInvestigation,
    loadInvestigation: loadInvestigation,
    deleteInvestigation: deleteInvestigation,
    renameActiveFromMessage: renameActiveFromMessage,
    setConversationId: setConversationId,
    appendMessage: appendMessage,
    appendEvent: appendEvent,
    replaceLastMessage: replaceLastMessage,
    removeLastMessageIfStreaming: removeLastMessageIfStreaming,
    setRequest: setRequest,
    setEvents: setEvents,
    setResult: setResult,
    updateChecklist: updateChecklist,
    savePlanFromActive: savePlanFromActive,
    toggleSavedItem: toggleSavedItem,
    deleteSavedPlan: deleteSavedPlan
  };
})();
