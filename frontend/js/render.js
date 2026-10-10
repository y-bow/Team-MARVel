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

  var STATUS_LABELS = {
    idle: "Idle",
    queued: "Queued",
    running: "Running",
    completed: "Findings ready",
    failed: "Failed",
    clarification: "Needs input",
    no_results: "No records"
  };

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

  function formatDateTime(ts) {
    return formatDate(ts) + " · " + formatTime(ts);
  }

  function pluralise(count, singular, plural) {
    return count === 1 ? singular : (plural || singular + "s");
  }

  /* ------------------------------- icons per status ------------------------------- */

  function statusIcon(status) {
    if (status === "completed") return svgIcon("check");
    if (status === "running") return svgIcon("loader", "spin");
    if (status === "queued") return svgIcon("clock");
    if (status === "failed") return svgIcon("x");
    return svgIcon("clock");
  }

  /* =============================== Conversation =============================== */

  var STARTERS = [
    {
      icon: "i-search",
      title: "Find scholarships for my course",
      desc: "Search the records that match your programme.",
      prompt: "Find scholarships for my course."
    },
    {
      icon: "i-badge-check",
      title: "Help me understand eligibility",
      desc: "See what you meet, and what is still missing.",
      prompt: "Help me understand eligibility."
    },
    {
      icon: "i-list-checks",
      title: "Prepare my application document checklist",
      desc: "Get an organised list of documents to gather.",
      prompt: "Prepare my application document checklist."
    },
    {
      icon: "i-compass",
      title: "Guide me through a certificate application",
      desc: "Follow a clear, step-by-step process.",
      prompt: "Guide me through a certificate application."
    }
  ];

  function renderWelcome() {
    var starters = h(
      "div",
      { class: "starters" },
      STARTERS.map(function (s) {
        return h(
          "button",
          {
            type: "button",
            class: "starter",
            "data-action": "starter",
            "data-prompt": s.prompt
          },
          [
            h("span", { class: "starter__icon" }, svgIcon(s.icon)),
            h("span", { class: "starter__body" }, [
              h("span", { class: "starter__title", text: s.title }),
              h("span", { class: "starter__desc", text: s.desc })
            ])
          ]
        );
      })
    );

    return h("div", { class: "welcome" }, [
      h("span", { class: "welcome__eyebrow" }, [svgIcon("sparkles"), "Student Opportunity Navigator"]),
      h("h2", { class: "welcome__title", text: "Describe your situation. Get a clear path to the right opportunities." }),
      h("p", {
        class: "welcome__lead",
        text:
          "EduSaarthi investigates scholarships and education services on your " +
          "behalf — matching records, showing eligibility gaps, listing required " +
          "documents and pointing you to the official sources."
      }),
      h("p", { class: "welcome__section-label", text: "Start with a question" }),
      starters
    ]);
  }

  function renderMessage(message) {
    if (message.role === "user") {
      return h("div", { class: "msg msg--user" }, [
        h("div", { class: "msg__user-bubble", text: message.text })
      ]);
    }

    var bodyChildren = [];
    if (message.kind === "clarification") {
      bodyChildren.push(renderClarificationCard({ question: message.text, options: message.options || [] }));
    } else {
      bodyChildren.push(h("p", { class: "msg__text", text: message.text }));
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
          h("span", { text: "Investigating your request" }),
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
        h(
          "div",
          { class: "clarify__options" },
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
    var message = (error && error.message) || "Something went wrong while investigating your request.";
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
        h("p", { class: "inline-error__title", text: "We couldn't complete that investigation" }),
        h("p", { class: "inline-error__text", text: message }),
        h("div", { class: "inline-error__actions" }, actions)
      ])
    ]);
  }

  function renderConversation(state) {
    var active = EduState.getActive() || { messages: [], events: [], result: null };
    var conv = refs.conversation;
    var loading = state.request.status === "loading";
    var errored = state.request.status === "error";
    var hasMessages = active.messages.length > 0;

    if (!hasMessages && !loading && !errored) {
      replace(conv, renderWelcome());
      return;
    }

    var thread = h("div", { class: "thread" });
    active.messages.forEach(function (m) {
      thread.appendChild(renderMessage(m));
    });
    if (loading) thread.appendChild(renderProcessing());
    if (errored) thread.appendChild(renderInlineError(state.request.error));

    replace(conv, thread);
  }

  /* =============================== Panel =============================== */

  function section(iconName, title, count, children, extra) {
    var head = [svgIcon(iconName), h("h3", { class: "section__title", text: title })];
    if (typeof count === "number") head.push(h("span", { class: "section__count", text: String(count) }));
    if (extra) head.push(h("span", { class: "section__spacer" }), extra);
    return h("div", { class: "section" }, [
      h("div", { class: "section__head" }, head),
      h("div", {}, children)
    ]);
  }

  function renderSkeletonEvents() {
    function row() {
      return h("div", { class: "skeleton-event" }, [
        h("span", { class: "skeleton skeleton--dot" }),
        h("span", { class: "skeleton-event__lines" }, [
          h("span", { class: "skeleton skeleton--line", style: "width:45%" }),
          h("span", { class: "skeleton skeleton--line", style: "width:75%" })
        ])
      ]);
    }
    return h("div", { class: "events", "aria-label": "Activity in progress" }, [row(), row(), row()]);
  }

  function renderEvents(events) {
    return h(
      "div",
      { class: "events" },
      events.map(function (event) {
        var children = [
          h("span", { class: "event__dot" }, statusIcon(event.status)),
          h("div", { class: "event__top" }, [
            h("span", { class: "event__tool", text: event.tool }),
            statusBadge(event.status, event.status)
          ])
        ];
        if (event.summary) children.push(h("p", { class: "event__summary", text: event.summary }));

        if (event.detail) {
          var detailId = "evt-detail-" + event.id;
          var button = h("button", {
            type: "button",
            class: "event__toggle",
            "data-action": "event-toggle",
            "aria-expanded": "false",
            "aria-controls": detailId
          }, ["Details", svgIcon("chevron-down")]);
          var pre = h("pre", { class: "event__details", id: detailId, hidden: true, text: event.detail });
          children.push(button, pre);
        }

        return h("div", { class: "event event--" + event.status }, children);
      })
    );
  }

  function statusBadge(status, label) {
    var text = label || STATUS_LABELS[status] || status;
    var cls = "status-badge status-badge--" + status;
    var iconMap = {
      completed: "check",
      running: "loader",
      queued: "clock",
      failed: "x",
      clarification: "circle-alert",
      no_results: "search"
    };
    var children = [];
    if (iconMap[status]) children.push(svgIcon(iconMap[status], status === "running" ? "spin" : ""));
    children.push(String(text));
    return h("span", { class: cls }, children);
  }

  function renderRecordCard(record) {
    var foot = [];
    if (record.url) {
      foot.push(
        h("a", {
          class: "record__link",
          href: record.url,
          target: "_blank",
          rel: "noopener noreferrer",
          "data-action": "source-link"
        }, ["Open official source", svgIcon("external")])
      );
    }
    if (record.match) foot.push(matchTag(record.match));

    return h("div", { class: "record" }, [
      h("div", { class: "record__top" }, [
        h("div", {}, [
          h("p", { class: "record__title", text: record.title }),
          record.id ? h("p", { class: "record__id", text: record.id }) : null,
          record.provider ? h("p", { class: "record__provider", text: record.provider }) : null
        ])
      ]),
      record.summary ? h("p", { class: "record__summary", text: record.summary }) : null,
      foot.length ? h("div", { class: "record__foot" }, foot) : null
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

  function renderEligibility(elig) {
    function row(kind, iconName, label, items) {
      if (!items.length) return null;
      return h("div", { class: "elig__row elig__row--" + kind }, [
        h("span", { class: "elig__row-icon" }, svgIcon(iconName)),
        h("div", {}, [
          h("p", { class: "elig__row-label", text: label }),
          h(
            "ul",
            { class: "elig__list" },
            items.map(function (item) {
              return h("li", { text: item });
            })
          )
        ])
      ]);
    }
    var rows = [
      row("met", "circle-check", "Criteria you appear to meet", elig.met),
      row("missing", "circle-alert", "Information missing", elig.missing),
      row("unknown", "info", "Could not be determined", elig.unknown)
    ].filter(Boolean);

    return h("div", {}, [
      h("div", { class: "elig" }, rows),
      h("p", {
        class: "notice__text",
        style: "margin-top:8px;color:var(--muted)",
        text: "Eligibility shown here is indicative, based on the details you shared. It is not an official decision."
      })
    ]);
  }

  function renderDocuments(documents) {
    return h(
      "div",
      { class: "tick-list" },
      documents.map(function (doc) {
        return h("div", { class: "tick-item" }, [
          svgIcon("file-text"),
          h("span", {}, [
            doc.name,
            doc.note ? h("span", { class: "tick-item__note", text: doc.note }) : null
          ])
        ]);
      })
    );
  }

  function renderSteps(steps) {
    return h(
      "div",
      { class: "steps" },
      steps.map(function (step) {
        return h("div", { class: "step" }, [
          h("span", { class: "step__num" }),
          h("div", {}, [
            h("p", { class: "step__title", text: step.title }),
            step.detail ? h("p", { class: "step__detail", text: step.detail }) : null
          ])
        ]);
      })
    );
  }

  function renderChecklist(actionPlan) {
    return h(
      "div",
      { class: "checklist" },
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
    );
  }

  function renderSources(sources) {
    return h(
      "div",
      { class: "records" },
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
                  rel: "noopener noreferrer",
                  "data-action": "source-link"
                }, ["Open official source", svgIcon("external")])
              ])
            : h("p", { class: "record__summary", text: "No link provided for this source." })
        ]);
      })
    );
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

  function renderResult(result) {
    var nodes = [];

    if (result.answer) {
      nodes.push(
        h("div", { class: "summary-card" }, [
          h("p", { class: "summary-card__label" }, [svgIcon("sparkles"), "Summary"]),
          h("p", { class: "summary-card__text", text: result.answer })
        ])
      );
    }

    if (result.status === "no_results") {
      nodes.push(renderNoResults(result.answer));
      return nodes;
    }

    if (result.clarification) {
      nodes.push(renderClarificationCard(result.clarification));
    }

    if (result.matches && result.matches.length) {
      nodes.push(section("target", "Potential matches", result.matches.length,
        h("div", { class: "records" }, result.matches.map(renderRecordCard))
      ));
    }

    if (result.eligibility) {
      nodes.push(section("badge-check", "Eligibility", null, renderEligibility(result.eligibility)));
    }

    if (result.documents && result.documents.length) {
      nodes.push(section("file-text", "Required documents", result.documents.length, renderDocuments(result.documents)));
    }

    if (result.steps && result.steps.length) {
      nodes.push(section("list-checks", "Application steps", result.steps.length, renderSteps(result.steps)));
    }

    if (result.sources && result.sources.length) {
      nodes.push(section("link", "Sources & official links", result.sources.length, renderSources(result.sources)));
    }

    if (result.actionPlan && result.actionPlan.length) {
      var saveBtn = h("button", {
        type: "button",
        class: "btn btn--ghost btn--sm",
        "data-action": "save-plan"
      }, [svgIcon("bookmark"), "Save plan"]);
      nodes.push(
        section("list-checks", "Next steps", result.actionPlan.length, renderChecklist(result.actionPlan), saveBtn)
      );
    }

    return nodes;
  }

  function renderPanel(state) {
    var active = EduState.getActive() || { messages: [], events: [], result: null };
    var status = panelStatus(state);

    // Header status badge
    var badge = statusBadge(status, STATUS_LABELS[status] || status);
    badge.id = "panelStatus";
    refs.panelStatus.replaceWith(badge);
    refs.panelStatus = badge;

    // Subtitle
    var sub = "Activity and findings";
    if (state.request.status === "loading") sub = "Investigating your request…";
    else if (state.request.status === "error") sub = "The last request failed";
    else if (active.result) sub = statusSubtitle(status, active.result);

    refs.panelSub.textContent = sub;

    // Body
    var body = [];
    var loading = state.request.status === "loading";

    if (loading && (!active.events || !active.events.length)) {
      body.push(section("loader", "Activity", null, renderSkeletonEvents()));
    } else if (active.events && active.events.length) {
      body.push(section("loader", "Activity", active.events.length, renderEvents(active.events)));
    }

    if (active.result) {
      renderResult(active.result).forEach(function (node) {
        body.push(node);
      });
    }

    if (!body.length) {
      body.push(renderPanelEmpty());
    }

    refs.panelBody.replaceChildren.apply(refs.panelBody, body);
  }

  function panelStatus(state) {
    if (state.request.status === "loading") return "running";
    if (state.request.status === "error") return "failed";
    var active = EduState.getActive();
    if (active && active.result) return active.result.status;
    return "idle";
  }

  function statusSubtitle(status, result) {
    if (status === "clarification") return "Waiting for your answer";
    if (status === "no_results") return "No records found";
    if (status === "failed") return "Investigation failed";
    if (status === "running") return "Investigating your request…";
    var parts = [];
    if (result.matches && result.matches.length) parts.push(result.matches.length + " " + pluralise(result.matches.length, "match", "matches"));
    if (result.sources && result.sources.length) parts.push(result.sources.length + " " + pluralise(result.sources.length, "source", "sources"));
    return parts.length ? parts.join(" · ") : "Findings ready";
  }

  function renderPanelEmpty() {
    return h("div", { class: "panel-empty" }, [
      h("span", { class: "panel-empty__icon" }, svgIcon("compass")),
      h("p", { class: "panel-empty__title", text: "No investigation yet" }),
      h("p", {
        class: "panel-empty__text",
        text: "Ask a question to begin. Progress, matched records and your next steps will appear here."
      })
    ]);
  }

  /* =============================== List views =============================== */

  function renderListView(state) {
    var content = refs.listContent;
    if (state.view === "history") replace(content, renderHistory(state));
    else if (state.view === "saved") replace(content, renderSaved(state));
    else if (state.view === "sources") replace(content, renderSourcesView(state));
  }

  function listHead(title, sub) {
    return h("div", { class: "list-head" }, [
      h("div", {}, [
        h("h2", { class: "list-head__title", text: title }),
        h("p", { class: "list-head__sub", text: sub })
      ])
    ]);
  }

  function emptyList(iconName, title, text) {
    return h("div", { class: "empty-list" }, [
      h("span", { class: "empty-list__icon" }, svgIcon(iconName)),
      h("p", { class: "empty-list__title", text: title }),
      h("p", { class: "empty-list__text", text: text })
    ]);
  }

  function renderHistory(state) {
    var items = state.investigations.filter(function (inv) {
      return inv.messages.length || inv.result;
    });

    var wrap = h("div", {}, [
      listHead("Investigations", "Every investigation you run is saved in this browser."),
      items.length
        ? h(
            "div",
            { class: "list-rows" },
            items.map(function (inv) {
              return h(
                "div",
                {
                  class: "list-row",
                  role: "button",
                  tabindex: "0",
                  "data-action": "open-investigation",
                  "data-id": inv.id
                },
                [
                  h("span", { class: "list-row__icon" }, svgIcon("compass")),
                  h("span", { class: "list-row__body" }, [
                    h("span", { class: "list-row__title", text: inv.title }),
                    h("span", { class: "list-row__meta" }, [
                      svgIcon("clock"),
                      formatDateTime(inv.updatedAt) + " · " + inv.messages.length + " " + pluralise(inv.messages.length, "message")
                    ])
                  ]),
                  h("span", { class: "list-row__actions" }, [
                    h("button", {
                      type: "button",
                      class: "icon-btn",
                      "data-action": "delete-investigation",
                      "data-id": inv.id,
                      "aria-label": "Delete investigation"
                    }, svgIcon("trash"))
                  ])
                ]
              );
            })
          )
        : emptyList("history", "No investigations yet", "Your conversations and findings will be listed here once you start.")
    ]);
    return wrap;
  }

  function renderSaved(state) {
    var plans = state.savedPlans;
    var wrap = h("div", {}, [
      listHead("Saved plans", "Action checklists you saved for later."),
      plans.length
        ? h("div", {}, plans.map(renderPlan))
        : emptyList("bookmark", "No saved plans", "Save a plan from any investigation's Next steps to see it here.")
    ]);
    return wrap;
  }

  function renderPlan(plan) {
    var done = plan.items.filter(function (i) {
      return i.completed;
    }).length;
    return h("div", { class: "plan" }, [
      h("div", { class: "plan__head" }, [
        h("div", {}, [
          h("p", { class: "plan__title", text: plan.title }),
          h("p", { class: "plan__meta", text: "Saved " + formatDate(plan.createdAt) + (plan.sources.length ? " · " + plan.sources.length + " " + pluralise(plan.sources.length, "source") : "") })
        ]),
        h("div", { class: "list-row__actions" }, [
          h("span", { class: "plan__progress", text: done + "/" + plan.items.length + " done" })
        ])
      ]),
      h(
        "div",
        { class: "checklist" },
        plan.items.map(function (item, index) {
          var inputId = "saved-" + plan.id + "-" + index;
          return h("label", { class: "check-item", for: inputId }, [
            h("input", {
              type: "checkbox",
              id: inputId,
              checked: item.completed,
              "data-action": "saved-toggle",
              "data-plan-id": plan.id,
              "data-index": String(index)
            }),
            h("span", { class: "check-item__box" }, svgIcon("check")),
            h("span", { class: "check-item__text", text: item.title })
          ]);
        })
      ),
      h("div", { class: "record__foot" }, [
        h("button", {
          type: "button",
          class: "btn btn--ghost btn--sm",
          "data-action": "open-investigation",
          "data-id": plan.investigationId
        }, [svgIcon("arrow-right"), "Open investigation"]),
        h("button", {
          type: "button",
          class: "icon-btn",
          "data-action": "delete-plan",
          "data-plan-id": plan.id,
          "aria-label": "Delete saved plan"
        }, svgIcon("trash"))
      ])
    ]);
  }

  function renderSourcesView(state) {
    var sources = EduState.getAllSources();
    return h("div", {}, [
      listHead("Sources", "Official links gathered across your investigations. Always verify on the official page."),
      sources.length
        ? h(
            "div",
            { class: "list-rows" },
            sources.map(function (src) {
              var row = [
                h("span", { class: "list-row__icon" }, svgIcon("link")),
                h("span", { class: "list-row__body" }, [
                  h("span", { class: "list-row__title", text: src.title }),
                  h("span", { class: "list-row__meta" }, [
                    src.id ? src.id + " · " : "",
                    "from " + src.investigationTitle
                  ])
                ])
              ];
              if (src.url) {
                row.push(
                  h("span", { class: "list-row__actions" }, [
                    h("a", {
                      class: "record__link",
                      href: src.url,
                      target: "_blank",
                      rel: "noopener noreferrer",
                      "data-action": "source-link"
                    }, ["Open", svgIcon("external")])
                  ])
                );
                return h("div", { class: "list-row" }, row);
              }
              return h("div", { class: "list-row" }, row);
            })
          )
        : emptyList("link", "No sources yet", "Official links from your investigations will be collected here.")
    ]);
  }

  /* =============================== Root render =============================== */

  var VIEW_META = {
    investigation: { title: "Investigation", subtitle: "" },
    history: { title: "Investigations", subtitle: "Your saved investigation history" },
    saved: { title: "Saved plans", subtitle: "Checklists you saved for later" },
    sources: { title: "Sources", subtitle: "Official links you have gathered" }
  };

  function render(state) {
    var body = document.body;
    body.dataset.mobileView = state.mobileView;
    body.dataset.sidebarOpen = state.sidebarOpen ? "true" : "false";

    // Demo indicators
    refs.demoBanner.hidden = !state.demoMode;
    refs.demoBadge.hidden = !state.demoMode;
    refs.demoToggle.setAttribute("aria-checked", state.demoMode ? "true" : "false");

    // Mobile tabs
    refs.tabChat.classList.toggle("is-active", state.mobileView === "chat");
    refs.tabChat.setAttribute("aria-selected", state.mobileView === "chat" ? "true" : "false");
    refs.tabPanel.classList.toggle("is-active", state.mobileView === "panel");
    refs.tabPanel.setAttribute("aria-selected", state.mobileView === "panel" ? "true" : "false");
    refs.menuBtn.setAttribute("aria-expanded", state.sidebarOpen ? "true" : "false");

    // Nav
    Array.prototype.forEach.call(refs.navItems, function (item) {
      var active = item.getAttribute("data-view") === state.view;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-current", active ? "page" : "false");
    });
    var historyCount = state.investigations.filter(function (inv) {
      return inv.messages.length || inv.result;
    }).length;
    updateCount(refs.navCountHistory, historyCount);
    updateCount(refs.navCountSaved, state.savedPlans.length);

    // Views
    var isInvestigation = state.view === "investigation";
    refs.chatView.hidden = !isInvestigation;
    refs.listView.hidden = isInvestigation;

    // Titles
    var meta = VIEW_META[state.view] || VIEW_META.investigation;
    refs.viewTitle.textContent = meta.title;
    if (isInvestigation) {
      refs.viewSubtitle.textContent = "Describe your situation to begin.";
    } else {
      refs.viewSubtitle.textContent = meta.subtitle;
    }

    if (isInvestigation) {
      renderConversation(state);
      renderPanel(state);
    } else {
      renderListView(state);
    }

    // Sidebar scrim
    refs.scrim.hidden = !state.sidebarOpen;
  }

  function updateCount(node, value) {
    if (value > 0) {
      node.hidden = false;
      node.textContent = String(value);
    } else {
      node.hidden = true;
      node.textContent = "";
    }
  }

  function cacheRefs() {
    var id = function (x) { return document.getElementById(x); };
    refs = {
      conversation: id("conversation"),
      chatView: id("chatView"),
      listView: id("listView"),
      listContent: id("listContent"),
      panelBody: id("panelBody"),
      panelStatus: id("panelStatus"),
      panelSub: id("panelSub"),
      viewTitle: id("viewTitle"),
      viewSubtitle: id("viewSubtitle"),
      demoBanner: id("demoBanner"),
      demoBadge: id("demoBadge"),
      demoToggle: id("demoToggle"),
      navItems: document.querySelectorAll("[data-view]"),
      navCountHistory: id("navCountHistory"),
      navCountSaved: id("navCountSaved"),
      scrim: id("sidebarScrim"),
      menuBtn: id("menuBtn"),
      panelBack: id("panelBack"),
      tabChat: id("tabChat"),
      tabPanel: id("tabPanel"),
      brandLink: id("brandLink"),
      newInvestigationBtn: id("newInvestigationBtn"),
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
    hydrateStaticIcons: hydrateStaticIcons,
    formatDateTime: formatDateTime
  };
})();
