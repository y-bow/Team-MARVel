/* ============================================================================
 * EduSaarthi AI — state.js
 *
 * Single source of truth for client-side application state, with lightweight
 * local persistence for conversation history.
 *
 * Persistence note: conversation text is stored in the user's own browser so
 * that history works. Only what the user typed is stored; no credentials or
 * privileged data are kept here.
 *
 * Backward compatibility: the internal data structure still uses
 * "investigations" to preserve localStorage compatibility with existing data.
 * ========================================================================== */
(function () {
  "use strict";

  var STORAGE_KEY = "edusaarthi.v1";
  var MAX_CONVERSATIONS = 40;
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

  function createConversation() {
    var now = Date.now();
    return {
      id: uid("inv"),
      title: "",
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
      demoMode: false,
      sidebarOpen: false,
      sidebarCollapsed: false,
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
    if (typeof parsed.sidebarCollapsed === "boolean") base.sidebarCollapsed = parsed.sidebarCollapsed;
    if (parsed.studentProfile && typeof parsed.studentProfile === "object") {
      base.studentProfile = parsed.studentProfile;
    }

    return base;
  }

  function persist() {
    try {
      var slim = {
        demoMode: state.demoMode,
        activeId: state.activeId,
        sidebarCollapsed: state.sidebarCollapsed,
        studentProfile: state.studentProfile || {},
        savedPlans: state.savedPlans,
        investigations: state.investigations.slice(0, MAX_CONVERSATIONS).map(function (inv) {
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

  function isEmptyConversation(inv) {
    return (
      inv &&
      (!inv.messages || inv.messages.length === 0) &&
      !inv.result &&
      (!inv.events || inv.events.length === 0)
    );
  }

  function titleFromMessage(text) {
    var clean = String(text || "").replace(/\s+/g, " ").trim();
    if (!clean) return "";
    if (clean.length <= 64) return clean;
    return clean.slice(0, 61).trim() + "\u2026";
  }

  /**
   * Group conversations by recency for sidebar display.
   * Returns { today: [], yesterday: [], thisWeek: [], older: [] }
   */
  function groupByRecency() {
    var now = new Date();
    var todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    var yesterdayStart = todayStart - 86400000;
    var weekStart = todayStart - 6 * 86400000;

    var groups = { today: [], yesterday: [], thisWeek: [], older: [] };
    state.investigations.forEach(function (inv) {
      if (isEmptyConversation(inv)) return;
      var t = inv.updatedAt || inv.createdAt;
      if (t >= todayStart) groups.today.push(inv);
      else if (t >= yesterdayStart) groups.yesterday.push(inv);
      else if (t >= weekStart) groups.thisWeek.push(inv);
      else groups.older.push(inv);
    });
    return groups;
  }

  /* ------------------------------- actions ------------------------------- */

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

  function setSidebarCollapsed(collapsed) {
    commit(function (s) {
      s.sidebarCollapsed = !!collapsed;
    });
  }

  function setStudentProfile(profile) {
    commit(function (s) {
      s.studentProfile = profile || {};
    });
  }

  function newConversation(force) {
    var active = getActive();
    if (active && isEmptyConversation(active) && !force) {
      return active.id;
    }
    var created = createConversation();
    commit(function (s) {
      s.investigations.unshift(created);
      s.activeId = created.id;
      s.request = { status: "idle", error: null, lastMessage: null };
    });
    return created.id;
  }

  function loadConversation(id) {
    var found = state.investigations.filter(function (i) {
      return i.id === id;
    })[0];
    if (!found) return false;
    commit(function (s) {
      s.activeId = id;
      s.request = { status: "idle", error: null, lastMessage: null };
    });
    return true;
  }

  function deleteConversation(id) {
    commit(function (s) {
      s.investigations = s.investigations.filter(function (i) {
        return i.id !== id;
      });
      if (s.activeId === id) {
        s.activeId = null;
      }
    });
  }

  function renameConversation(id, newTitle) {
    commit(function (s) {
      var inv = s.investigations.filter(function (i) { return i.id === id; })[0];
      if (inv) {
        inv.title = String(newTitle || "").trim();
      }
    });
  }

  function renameActiveFromMessage(text) {
    var active = getActive();
    if (!active) return;
    if (active.title) return;
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

  /* ------------------------------- lifecycle ------------------------------- */

  function init() {
    state = loadPersisted();
    state.investigations = state.investigations.map(function (inv) {
      return Object.assign(createConversation(), inv, {
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
    groupByRecency: groupByRecency,
    createConversation: createConversation,
    uid: uid,
    clone: clone,
    isEmptyConversation: isEmptyConversation,
    setDemoMode: setDemoMode,
    setSidebarOpen: setSidebarOpen,
    setSidebarCollapsed: setSidebarCollapsed,
    setStudentProfile: setStudentProfile,
    newConversation: newConversation,
    loadConversation: loadConversation,
    deleteConversation: deleteConversation,
    renameConversation: renameConversation,
    renameActiveFromMessage: renameActiveFromMessage,
    setConversationId: setConversationId,
    appendMessage: appendMessage,
    setRequest: setRequest,
    setEvents: setEvents,
    setResult: setResult,
    updateChecklist: updateChecklist,
    savePlanFromActive: savePlanFromActive,
    toggleSavedItem: toggleSavedItem,
    deleteSavedPlan: deleteSavedPlan
  };
})();