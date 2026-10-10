/* ============================================================================
 * EduSaarthi AI — render.js
 *
 * Safe DOM construction and component updates. All dynamic, untrusted values
 * are written with textContent / createElement — never innerHTML. External
 * links are only rendered as anchors when they pass URL validation in api.js.
 *
 * Interactive elements carry data-action attributes; app.js owns the event
 * delegation so rendering stays side-effect free.
 * ========================================================================== */
(function () {
  "use strict";

  var SVGNS = "http://www.w3.org/2000/svg";
  var refs = {};

  /* ------------------------------- DOM helpers ------------------------------- */

  function appendChildren(node, children) {
    if (children === null || children === undefined || children === false) return;
    if (Array.isArray(children)) {
      children.forEach(function (child) {
        appendChildren(node, child);
      });
      return;
    }
    if (children instanceof Node) {
      node.appendChild(children);
      return;
    }
    node.appendChild(document.createTextNode(String(children)));
  }

  function h(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "hidden") node.hidden = !!value;
        else if (key === "disabled") node.disabled = !!value;
        else if (key === "value") node.value = value;
        else if (key === "checked") node.checked = !!value;
        else node.setAttribute(key, value === true ? "" : String(value));
      });
    }
    appendChildren(node, children);
    return node;
  }

  function svgIcon(name, extraClass) {
    var svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("class", "icon" + (extraClass ? " " + extraClass : ""));
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var use = document.createElementNS(SVGNS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function hydrateStaticIcons(root) {
    var nodes = (root || document).querySelectorAll("[data-icon]");
    Array.prototype.forEach.call(nodes, function (node) {
      var name = node.getAttribute("data-icon");
      node.removeAttribute("data-icon");
      node.appendChild(svgIcon(name));
    });
  }

  function replace(node, child) {
    node.replaceChildren();
    if (child) node.appendChild(child);
  }

  function renderMarkdown(text, className) {
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      return h("div", { class: className, text: text });
    }

    var rawHtml = marked.parse(text || "", { breaks: true, gfm: true });
    var cleanHtml = DOMPurify.sanitize(rawHtml);

    var container = document.createElement("div");
    container.className = "markdown-body " + (className || "");
    container.innerHTML = cleanHtml;

    var links = container.querySelectorAll("a");
    for (var i = 0; i < links.length; i++) {
      links[i].setAttribute("target", "_blank");
      links[i].setAttribute("rel", "noopener noreferrer");
    }

    return container;
  }

  /* ------------------------------- formatting ------------------------------- */

  function formatTime(ts) {
    try {
      return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      return "";
    }
  }

  function formatDate(ts) {
    try {
      return new Date(ts).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
    } catch (e) {
      return "";
    }
  }

  /* =============================== Sidebar =============================== */

  var GROUP_LABELS = {
    today: "Today",
    yesterday: "Yesterday",
    thisWeek: "This week",
    older: "Older"
  };

  function renderSidebarConversations(state) {
    var container = refs.sidebarConversations;
    if (!container) return;

    var groups = EduState.groupByRecency();
    var hasAny = groups.today.length || groups.yesterday.length || groups.thisWeek.length || groups.older.length;

    if (!hasAny) {
      container.replaceChildren();
      return;
    }

    var frag = document.createDocumentFragment();
    var groupOrder = ["today", "yesterday", "thisWeek", "older"];

    groupOrder.forEach(function (key) {
      var items = groups[key];
      if (!items.length) return;

      frag.appendChild(h("div", { class: "conv-group" }, [
        h("div", { class: "conv-group__label", text: GROUP_LABELS[key] }),
        h("div", { class: "conv-group__list" },
          items.map(function (inv) {
            var isActive = inv.id === state.activeId;
            var title = inv.title || "New conversation";
            return h("div", {
              class: "conv-item" + (isActive ? " conv-item--active" : ""),
              role: "button",
              tabindex: "0",
              "data-action": "open-conversation",
              "data-id": inv.id
            }, [
              h("span", { class: "conv-item__title", text: title }),
              h("div", { class: "conv-item__actions" }, [
                h("button", {
                  type: "button",
                  class: "icon-btn conv-item__btn",
                  "data-action": "rename-conversation",
                  "data-id": inv.id,
                  "aria-label": "Rename conversation"
                }, svgIcon("pencil")),
                h("button", {
                  type: "button",
                  class: "icon-btn conv-item__btn",
                  "data-action": "delete-conversation",
                  "data-id": inv.id,
                  "aria-label": "Delete conversation"
                }, svgIcon("trash"))
              ])
            ]);
          })
        )
      ]));
    });

    container.replaceChildren(frag);
  }

  /* =============================== Welcome =============================== */

  var STARTERS = [
    {
      icon: "search",
      title: "Find scholarships matching my profile",
      prompt: "Find scholarships matching my profile."
    },
    {
      icon: "badge-check",
      title: "Check my eligibility for available scholarships",
      prompt: "Check my eligibility for available scholarships."
    },
    {
      icon: "compass",
      title: "Compare scholarships and their requirements",
      prompt: "Compare scholarships and their requirements."
    },
    {
      icon: "list-checks",
      title: "Help me prepare an application checklist",
      prompt: "Help me prepare an application checklist."
    }
  ];

  function renderWelcome() {
    return h("div", { class: "welcome" }, [
      h("div", { class: "welcome__brand" }, [
        h("span", { class: "welcome__mark" }, svgIcon("sparkles")),
        h("h2", { class: "welcome__title", text: "EduSaarthi AI" })
      ]),
      h("p", {
        class: "welcome__lead",
        text: "Your AI-powered scholarship assistant. Ask about scholarships, check eligibility, compare requirements, or get help with your application."
      }),
      h("div", { class: "starters" },
        STARTERS.map(function (s) {
          return h("button", {
            type: "button",
            class: "starter",
            "data-action": "starter",
            "data-prompt": s.prompt
          }, [
            h("span", { class: "starter__icon" }, svgIcon(s.icon)),
            h("span", { class: "starter__title", text: s.title })
          ]);
        })
      )
    ]);
  }

  /* =============================== Messages =============================== */

  function renderMessage(message) {
    if (message.role === "user") {
      return h("div", { class: "msg msg--user" }, [
        h("div", { class: "msg__bubble msg__bubble--user", text: message.text })
      ]);
    }

    var bodyChildren = [];
    if (message.kind === "clarification") {
      bodyChildren.push(renderClarificationCard({ question: message.text, options: message.options || [] }));
    } else {
      bodyChildren.push(renderMarkdown(message.text, "msg__text"));
    }
    bodyChildren.push(
      h("div", { class: "msg__meta" }, [
        h("span", { class: "msg__time" }, [svgIcon("clock"), formatTime(message.ts)])
      ])
    );

    return h("div", { class: "msg msg--assistant" }, [
      h("span", { class: "msg__avatar" }, svgIcon("mark")),
      h("div", { class: "msg__body" }, bodyChildren)
    ]);
  }

  function renderProcessing() {
    return h("div", { class: "msg msg--assistant" }, [
      h("span", { class: "msg__avatar" }, svgIcon("mark")),
      h("div", { class: "msg__body" }, [
        h("div", { class: "msg__thinking" }, [
          svgIcon("loader", "spin"),
          h("span", { text: "Thinking\u2026" }),
          h("span", { class: "thinking-dots" }, [h("span"), h("span"), h("span")])
        ])
      ])
    ]);
  }

  function renderClarificationCard(clarification) {
    var children = [
      h("div", { class: "clarify__head" }, [svgIcon("circle-alert"), "A little more information"]),
      h("p", { class: "clarify__q", text: clarification.question })
    ];
    if (clarification.options && clarification.options.length) {
      children.push(
        h("div", { class: "clarify__options" },
          clarification.options.map(function (option) {
            return h("button", {
              type: "button",
              class: "chip",
              "data-action": "clarify-option",
              "data-prompt": option
            }, option);
          })
        )
      );
    }
    return h("div", { class: "clarify" }, children);
  }

  function renderInlineError(error) {
    var message = (error && error.message) || "Something went wrong while processing your request.";
    var code = error && error.code;
    var actions = [
      h("button", { type: "button", class: "btn btn--accent btn--sm", "data-action": "retry" }, [
        svgIcon("refresh"),
        "Retry"
      ])
    ];
    if (code === "network" || code === "timeout" || code === "http") {
      actions.push(
        h("button", { type: "button", class: "btn btn--ghost btn--sm", "data-action": "enable-demo" }, [
          svgIcon("sparkles"),
          "Explore demo mode"
        ])
      );
    }
    return h("div", { class: "inline-error msg msg--assistant" }, [
      h("span", { class: "inline-error__icon" }, svgIcon("circle-alert")),
      h("div", { class: "inline-error__body" }, [
        h("p", { class: "inline-error__title", text: "Something went wrong" }),
        h("p", { class: "inline-error__text", text: message }),
        h("div", { class: "inline-error__actions" }, actions)
      ])
    ]);
  }

  /* =============================== Inline tool activity =============================== */

  function renderInlineActivity(events) {
    if (!events || !events.length) return null;

    var listEl = h("div", { class: "activity__list" },
      events.map(function (evt) {
        var statusClass = "activity__dot--" + evt.status;
        return h("div", { class: "activity__item" }, [
          h("span", { class: "activity__dot " + statusClass }),
          h("span", { class: "activity__tool", text: evt.tool }),
          h("span", { class: "activity__summary", text: evt.summary || evt.status })
        ]);
      })
    );

    var body = h("div", { class: "activity__body", hidden: true }, [listEl]);

    var toggle = h("button", {
      type: "button",
      class: "activity__toggle",
      "data-action": "toggle-activity",
      "aria-expanded": "false"
    }, [
      svgIcon("loader"),
      h("span", { text: events.length + " tool" + (events.length !== 1 ? "s" : "") + " used" }),
      svgIcon("chevron-down")
    ]);

    return h("div", { class: "activity" }, [toggle, body]);
  }

  /* =============================== Inline results =============================== */

  function renderInlineResult(result) {
    if (!result) return null;
    var nodes = [];

    if (result.matches && result.matches.length) {
      nodes.push(renderInlineMatches(result.matches));
    }

    if (result.eligibility) {
      nodes.push(renderInlineEligibility(result.eligibility));
    }

    if (result.documents && result.documents.length) {
      nodes.push(renderInlineDocuments(result.documents));
    }

    if (result.steps && result.steps.length) {
      nodes.push(renderInlineSteps(result.steps));
    }

    if (result.sources && result.sources.length) {
      nodes.push(renderInlineSources(result.sources));
    }

    if (result.actionPlan && result.actionPlan.length) {
      nodes.push(renderInlineChecklist(result.actionPlan));
    }

    if (result.clarification) {
      nodes.push(renderClarificationCard(result.clarification));
    }

    return nodes.length ? h("div", { class: "inline-result" }, nodes) : null;
  }

  function renderInlineMatches(matches) {
    return h("div", { class: "result-section" }, [
      h("div", { class: "result-section__head" }, [svgIcon("target"), h("span", { text: "Potential matches" })]),
      h("div", { class: "records" }, matches.map(function (m) {
        var foot = [];
        if (m.url) {
          foot.push(h("a", {
            class: "record__link",
            href: m.url,
            target: "_blank",
            rel: "noopener noreferrer"
          }, ["Open official source", svgIcon("external")]));
        }
        if (m.match) foot.push(matchTag(m.match));
        return h("div", { class: "record" }, [
          h("div", { class: "record__top" }, [
            h("div", {}, [
              h("p", { class: "record__title", text: m.title }),
              m.id ? h("p", { class: "record__id", text: m.id }) : null,
              m.provider ? h("p", { class: "record__provider", text: m.provider }) : null
            ])
          ]),
          m.summary ? h("p", { class: "record__summary", text: m.summary }) : null,
          foot.length ? h("div", { class: "record__foot" }, foot) : null
        ]);
      }))
    ]);
  }

  function matchTag(match) {
    var map = {
      strong: ["match-tag--strong", "badge-check", "Strong match"],
      possible: ["match-tag--possible", "target", "Possible match"],
      low: ["match-tag--low", "info", "Verify"]
    };
    var conf = map[match] || map.low;
    return h("span", { class: "match-tag " + conf[0] }, [svgIcon(conf[1]), conf[2]]);
  }

  function renderInlineEligibility(elig) {
    function row(kind, iconName, label, items) {
      if (!items.length) return null;
      return h("div", { class: "elig__row elig__row--" + kind }, [
        h("span", { class: "elig__row-icon" }, svgIcon(iconName)),
        h("div", {}, [
          h("p", { class: "elig__row-label", text: label }),
          h("ul", { class: "elig__list" },
            items.map(function (item) { return h("li", { text: item }); })
          )
        ])
      ]);
    }
    var rows = [
      row("met", "circle-check", "Criteria you appear to meet", elig.met),
      row("missing", "circle-alert", "Does not meet criteria", elig.missing),
      row("unknown", "info", "Information missing", elig.unknown)
    ].filter(Boolean);

    return h("div", { class: "result-section" }, [
      h("div", { class: "result-section__head" }, [svgIcon("badge-check"), h("span", { text: "Eligibility" })]),
      h("div", { class: "elig" }, rows),
      h("p", {
        class: "elig__disclaimer",
        text: "Eligibility shown here is indicative, based on the details you shared. It is not an official decision."
      })
    ]);
  }

  function renderInlineDocuments(documents) {
    return h("div", { class: "result-section" }, [
      h("div", { class: "result-section__head" }, [svgIcon("file-text"), h("span", { text: "Required documents" })]),
      h("div", { class: "tick-list" },
        documents.map(function (doc) {
          return h("div", { class: "tick-item" }, [
            svgIcon("file-text"),
            h("span", {}, [
              doc.name,
              doc.note ? h("span", { class: "tick-item__note", text: doc.note }) : null
            ])
          ]);
        })
      )
    ]);
  }

  function renderInlineSteps(steps) {
    return h("div", { class: "result-section" }, [
      h("div", { class: "result-section__head" }, [svgIcon("list-checks"), h("span", { text: "Application steps" })]),
      h("div", { class: "steps" },
        steps.map(function (step) {
          return h("div", { class: "step" }, [
            h("span", { class: "step__num" }),
            h("div", {}, [
              h("p", { class: "step__title", text: step.title }),
              step.detail ? h("p", { class: "step__detail", text: step.detail }) : null
            ])
          ]);
        })
      )
    ]);
  }

  function renderInlineSources(sources) {
    return h("div", { class: "result-section" }, [
      h("div", { class: "result-section__head" }, [svgIcon("link"), h("span", { text: "Sources & official links" })]),
      h("div", { class: "records" },
        sources.map(function (src) {
          return h("div", { class: "record" }, [
            h("div", { class: "record__top" }, [
              h("div", {}, [
                h("p", { class: "record__title", text: src.title }),
                src.id ? h("p", { class: "record__id", text: src.id }) : null
              ])
            ]),
            src.url
              ? h("div", { class: "record__foot" }, [
                  h("a", {
                    class: "record__link",
                    href: src.url,
                    target: "_blank",
                    rel: "noopener noreferrer"
                  }, ["Open official source", svgIcon("external")])
                ])
              : h("p", { class: "record__summary", text: "No link provided for this source." })
          ]);
        })
      )
    ]);
  }

  function renderInlineChecklist(actionPlan) {
    return h("div", { class: "result-section" }, [
      h("div", { class: "result-section__head" }, [
        svgIcon("list-checks"),
        h("span", { text: "Next steps" }),
        h("span", { class: "result-section__spacer" }),
        h("button", {
          type: "button",
          class: "btn btn--ghost btn--sm",
          "data-action": "save-plan"
        }, [svgIcon("bookmark"), "Save plan"])
      ]),
      h("div", { class: "checklist" },
        actionPlan.map(function (item, index) {
          var inputId = "check-" + index;
          return h("label", { class: "check-item", for: inputId }, [
            h("input", {
              type: "checkbox",
              id: inputId,
              checked: item.completed,
              "data-action": "checklist-toggle",
              "data-index": String(index)
            }),
            h("span", { class: "check-item__box" }, svgIcon("check")),
            h("span", { class: "check-item__text", text: item.title })
          ]);
        })
      )
    ]);
  }

  function renderNoResults(answer) {
    return h("div", { class: "no-results" }, [
      h("div", { class: "no-results__head" }, [svgIcon("search"), "No relevant records found"]),
      h("p", { class: "no-results__text", text: answer || "The available dataset did not contain a record matching this request." }),
      h("div", { class: "no-results__actions" }, [
        h("button", { type: "button", class: "chip", "data-action": "starter", "data-prompt": "Find scholarships for my course." }, "Try a broader search"),
        h("button", { type: "button", class: "chip", "data-action": "starter", "data-prompt": "Help me understand eligibility." }, "Check eligibility instead")
      ])
    ]);
  }

  /* =============================== Conversation thread =============================== */

  function renderConversation(state) {
    var active = EduState.getActive();
    var conv = refs.conversation;
    var loading = state.request.status === "loading";
    var errored = state.request.status === "error";

    if (!active || (active.messages.length === 0 && !loading && !errored)) {
      replace(conv, renderWelcome());
      return;
    }

    var thread = h("div", { class: "thread" });
    active.messages.forEach(function (m, idx) {
      thread.appendChild(renderMessage(m));

      // Inline tool activity after the last assistant message with events
      if (m.role === "assistant" && active.events && active.events.length && idx === active.messages.length - 1) {
        var activityEl = renderInlineActivity(active.events);
        if (activityEl) thread.appendChild(activityEl);
      }

      // Inline result after the last assistant message
      if (m.role === "assistant" && active.result && idx === active.messages.length - 1) {
        var resultEl = renderInlineResult(active.result);
        if (resultEl) thread.appendChild(resultEl);
      }
    });
    if (loading) thread.appendChild(renderProcessing());
    if (errored) thread.appendChild(renderInlineError(state.request.error));

    replace(conv, thread);
  }

  /* =============================== Title update =============================== */

  function updateTitle(state) {
    var active = EduState.getActive();
    if (active && active.title) {
      refs.viewTitle.textContent = active.title;
    } else {
      refs.viewTitle.textContent = "EduSaarthi AI";
    }
  }

  /* =============================== Root render =============================== */

  function render(state) {
    var body = document.body;

    // Sidebar collapsed state
    if (state.sidebarCollapsed) {
      body.dataset.sidebarCollapsed = "true";
    } else {
      delete body.dataset.sidebarCollapsed;
    }

    // Sidebar mobile open
    body.dataset.sidebarOpen = state.sidebarOpen ? "true" : "false";

    // Demo indicators
    refs.demoBanner.hidden = !state.demoMode;
    refs.demoBadge.hidden = !state.demoMode;
    refs.demoToggle.setAttribute("aria-checked", state.demoMode ? "true" : "false");

    // Menu button
    refs.menuBtn.setAttribute("aria-expanded", state.sidebarOpen ? "true" : "false");

    // Sidebar expand button (visible when collapsed on desktop)
    if (refs.sidebarExpandBtn) {
      refs.sidebarExpandBtn.hidden = !state.sidebarCollapsed;
    }

    // Render conversation
    renderConversation(state);
    updateTitle(state);

    // Render sidebar conversation list
    renderSidebarConversations(state);

    // Scrim
    refs.scrim.hidden = !state.sidebarOpen;
  }

  /* =============================== Refs =============================== */

  function cacheRefs() {
    var id = function (x) { return document.getElementById(x); };
    refs = {
      conversation: id("conversation"),
      chatView: id("chatView"),
      demoBanner: id("demoBanner"),
      demoBadge: id("demoBadge"),
      demoToggle: id("demoToggle"),
      scrim: id("sidebarScrim"),
      menuBtn: id("menuBtn"),
      sidebarCollapseBtn: id("sidebarCollapseBtn"),
      sidebarExpandBtn: id("sidebarExpandBtn"),
      viewTitle: id("viewTitle"),
      brandLink: id("brandLink"),
      newChatBtn: id("newChatBtn"),
      profileBtn: id("profileBtn"),
      profileDialog: id("profileDialog"),
      sidebarConversations: id("sidebarConversations"),
      composer: id("composer"),
      composerInput: id("composerInput"),
      sendBtn: id("sendBtn"),
      composerStatus: id("composerStatus"),
      toastRegion: id("toastRegion")
    };
  }

  function init() {
    cacheRefs();
    hydrateStaticIcons();
    return refs;
  }

  window.EduRender = {
    init: init,
    render: render,
    refs: function () {
      return refs;
    },
    h: h,
    svgIcon: svgIcon,
    hydrateStaticIcons: hydrateStaticIcons
  };
})();