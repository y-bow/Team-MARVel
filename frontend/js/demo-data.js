/* ============================================================================
 * EduSaarthi AI — demo-data.js
 *
 * Deterministic, clearly-labelled illustrative fixtures used ONLY when demo
 * mode is enabled. None of this is real scheme information and none of it is
 * presented as an official eligibility decision.
 *
 * The objects below intentionally mirror the shape of the documented
 * POST /api/chat response so that demo mode exercises the same rendering and
 * validation path as the real backend.
 * ========================================================================== */
(function () {
  "use strict";

  var DISCLAIMER =
    "Illustrative example for demonstration only. This is not real scheme " +
    "data and not an official eligibility decision.";

  /* ----------------------------- fixtures ----------------------------- */

  var SCHOLARSHIPS = {
    conversation_id: "demo-conversation",
    status: "completed",
    answer:
      "Based on the details you shared, I reviewed the illustrative records in " +
      "the demo dataset and found a few opportunities worth exploring. These " +
      "entries are examples only — treat them as a starting point and verify " +
      "every detail against the official source before applying.",
    sources: [
      { id: "SCHEME-DEMO-001", title: "Illustrative Merit Scholarship (Demo)", url: "https://example.org/scholarships/merit-demo" },
      { id: "SCHEME-DEMO-002", title: "Illustrative Need-Based Grant (Demo)", url: "https://example.org/scholarships/need-demo" },
      { id: "SCHEME-DEMO-003", title: "Illustrative STEM Talent Award (Demo)", url: "https://example.org/scholarships/stem-demo" }
    ],
    matches: [
      {
        id: "SCHEME-DEMO-001",
        title: "Illustrative Merit Scholarship (Demo)",
        provider: "Demo Education Trust (illustrative)",
        summary: "Sample merit-based support for undergraduate students. Shown here to demonstrate how a match is presented.",
        url: "https://example.org/scholarships/merit-demo",
        match: "strong"
      },
      {
        id: "SCHEME-DEMO-002",
        title: "Illustrative Need-Based Grant (Demo)",
        provider: "Demo Welfare Board (illustrative)",
        summary: "Sample need-based grant. Eligibility depends on household income criteria that we could not confirm from your message.",
        url: "https://example.org/scholarships/need-demo",
        match: "possible"
      },
      {
        id: "SCHEME-DEMO-003",
        title: "Illustrative STEM Talent Award (Demo)",
        provider: "Demo Science Council (illustrative)",
        summary: "Sample award for students in science and technology programmes. Verify the current cycle on the official page.",
        url: "https://example.org/scholarships/stem-demo",
        match: "possible"
      }
    ],
    eligibility: {
      met: [
        "Enrolled in an undergraduate programme (as described)",
        "Demonstrated academic interest in the chosen field"
      ],
      missing: [
        "Minimum academic percentage required for the illustrative award",
        "Enrolled in an approved science or technology field"
      ],
      unknown: [
        "Annual household income",
        "State or region of permanent residence"
      ]
    },
    documents: [
      { name: "Proof of enrolment", note: "Recent bonafide or institute letter." },
      { name: "Academic marksheets", note: "Latest completed semester or year." },
      { name: "Government photo ID", note: "Verify the exact ID accepted on the official page." },
      { name: "Income certificate", note: "Illustrative requirement — confirm format and validity." }
    ],
    steps: [
      { title: "Shortlist the records that apply", detail: "Read each illustrative record and note the eligibility conditions." },
      { title: "Collect the required documents", detail: "Prepare scanned copies before opening an application." },
      { title: "Create an account on the official portal", detail: "Use only the official source link, never a third-party mirror." },
      { title: "Submit before the deadline", detail: "Keep an acknowledgement reference after submitting." }
    ],
    events: [
      { tool: "parse_intent", status: "completed", summary: "Interpreted your goal as a scholarship search.", detail: "demo · goal=scholarship_search\ncourse=unspecified\nregion=unspecified" },
      { tool: "search_schemes", status: "completed", summary: "Retrieved 3 illustrative records from the demo dataset.", detail: "demo · matched_ids:\nSCHEME-DEMO-001\nSCHEME-DEMO-002\nSCHEME-DEMO-003" },
      { tool: "check_eligibility", status: "completed", summary: "Compared your details with each record; 2 criteria were not met.", detail: "demo · unsatisfied:\nmin_percentage\nfield_of_study" },
      { tool: "summarise", status: "completed", summary: "Prepared a grounded summary with sources.", detail: "demo · summary_generated=true" }
    ],
    action_plan: [
      { title: "Confirm your household income and state of residence", completed: false },
      { title: "Open the official source for each illustrative match", completed: false },
      { title: "Collect scanned copies of the required documents", completed: false },
      { title: "Note the application deadlines for each record", completed: false },
      { title: "Re-run the investigation with the additional information", completed: false }
    ]
  };

  var ELIGIBILITY = {
    conversation_id: "demo-conversation",
    status: "clarification",
    answer:
      "I can help you understand eligibility, but I need a little more " +
      "information before I can compare you against the illustrative records.",
    clarification: {
      question:
        "To check your eligibility accurately, could you tell me your course " +
        "level and your household income range? For example: \"second-year " +
        "B.Tech student, family income under ₹5 lakh per year\".",
      options: [
        "Second-year B.Tech student",
        "Final-year B.Sc student",
        "First-year postgraduate student",
        "I would rather type my details"
      ]
    },
    sources: [],
    matches: [],
    events: [
      { tool: "parse_intent", status: "completed", summary: "Detected an eligibility question.", detail: "demo · goal=eligibility_check" },
      { tool: "search_schemes", status: "completed", summary: "Found records that may apply once details are known.", detail: "demo · candidate_records=3" },
      { tool: "request_clarification", status: "completed", summary: "Requested course level and income range.", detail: "demo · awaiting=user_input" }
    ],
    action_plan: [
      { title: "Share your course level", completed: false },
      { title: "Share your household income range", completed: false }
    ]
  };

  var DOCUMENTS = {
    conversation_id: "demo-conversation",
    status: "completed",
    answer:
      "Here is an illustrative document checklist. Confirm the exact list on " +
      "each official source — requirements vary by scheme and by year.",
    sources: [
      { id: "SCHEME-DEMO-001", title: "Illustrative Merit Scholarship (Demo)", url: "https://example.org/scholarships/merit-demo" }
    ],
    matches: [],
    documents: [
      { name: "Proof of enrolment", note: "Recent bonafide or institute letter." },
      { name: "Academic marksheets", note: "Latest completed semester or year." },
      { name: "Government photo ID", note: "Check which ID is accepted." },
      { name: "Income certificate", note: "Confirm the required format." },
      { name: "Passport-size photographs", note: "Recent, as per official specification." },
      { name: "Bank account details", note: "Account held in the student's name." }
    ],
    steps: [
      { title: "Gather digital copies", detail: "Scan at a legible resolution and check file size limits." },
      { title: "Name the files clearly", detail: "Use a consistent naming scheme such as name_document.pdf." }
    ],
    events: [
      { tool: "parse_intent", status: "completed", summary: "Interpreted your goal as a document checklist.", detail: "demo · goal=document_checklist" },
      { tool: "compile_documents", status: "completed", summary: "Prepared a 6-item illustrative checklist.", detail: "demo · documents=6" }
    ],
    action_plan: [
      { title: "Scan all documents at a legible resolution", completed: false },
      { title: "Name each file consistently", completed: false },
      { title: "Cross-check the exact list on the official source", completed: false }
    ]
  };

  var CERTIFICATE = {
    conversation_id: "demo-conversation",
    status: "completed",
    answer:
      "Here is an illustrative step-by-step guide for a certificate-type " +
      "application. Always complete the final submission on the official " +
      "portal and keep a copy of your acknowledgement.",
    sources: [
      { id: "PORTAL-DEMO-001", title: "Illustrative Certificate Portal (Demo)", url: "https://example.org/portal/certificate-demo" }
    ],
    matches: [],
    steps: [
      { title: "Read the official instructions", detail: "Open the official portal and read the current guidelines fully." },
      { title: "Register and verify identity", detail: "Create an account and complete any identity verification step." },
      { title: "Fill the application form", detail: "Enter details exactly as they appear on your documents." },
      { title: "Upload supporting documents", detail: "Attach the documents listed on the portal, in the stated format." },
      { title: "Pay any applicable fee", detail: "Use the official payment channel only." },
      { title: "Save the acknowledgement", detail: "Download or screenshot the reference number and keep it safe." },
      { title: "Track the status", detail: "Return to the portal periodically and check for updates." }
    ],
    events: [
      { tool: "parse_intent", status: "completed", summary: "Detected a certificate application request.", detail: "demo · goal=application_guidance" },
      { tool: "build_guide", status: "completed", summary: "Generated a 7-step illustrative guide.", detail: "demo · steps=7" }
    ],
    action_plan: [
      { title: "Open the official portal and read the guidelines", completed: false },
      { title: "Create an account and verify your identity", completed: false },
      { title: "Prepare all supporting documents", completed: false },
      { title: "Save the acknowledgement reference number", completed: false }
    ]
  };

  var NO_RESULTS = {
    conversation_id: "demo-conversation",
    status: "no_results",
    answer:
      "I could not find any relevant records in the available demo dataset " +
      "for this request. This is an illustrative no-results state.",
    sources: [],
    matches: [],
    events: [
      { tool: "parse_intent", status: "completed", summary: "Interpreted your request.", detail: "demo · goal=search" },
      { tool: "search_schemes", status: "completed", summary: "Searched the demo dataset; no records matched.", detail: "demo · results=0" }
    ],
    action_plan: []
  };

  var FAILED = {
    conversation_id: "demo-conversation",
    status: "failed",
    answer: "",
    sources: [],
    matches: [],
    events: [
      { tool: "parse_intent", status: "completed", summary: "Interpreted your request.", detail: "demo · goal=search" },
      { tool: "search_schemes", status: "failed", summary: "The dataset lookup failed while running.", detail: "demo · error=DEMO_FAILURE\nThis is an intentionally simulated failure." }
    ],
    action_plan: []
  };

  var GENERIC = SCHOLARSHIPS;

  /* ----------------------------- resolution ----------------------------- */

  function includesAny(text, needles) {
    for (var i = 0; i < needles.length; i++) {
      if (text.indexOf(needles[i]) !== -1) return true;
    }
    return false;
  }

  /**
   * Deterministically choose an illustrative scenario for a message.
   * @param {string} message
   * @returns {{ scenario: string, response: object }}
   */
  function resolve(message) {
    var text = String(message || "").toLowerCase();
    var scenario = "generic";
    var response = GENERIC;

    if (includesAny(text, ["error", "fail", "broken", "outage"])) {
      scenario = "failed";
      response = FAILED;
    } else if (includesAny(text, ["no result", "no results", "nothing", "unavailable", "not available", "empty"])) {
      scenario = "no_results";
      response = NO_RESULTS;
    } else if (includesAny(text, ["eligib", "qualify", "do i qualify", "understand eligibility"])) {
      scenario = "clarification";
      response = ELIGIBILITY;
    } else if (includesAny(text, ["document", "checklist", "prepare my application", "papers"])) {
      scenario = "documents";
      response = DOCUMENTS;
    } else if (includesAny(text, ["certificate", "guide", "application", "apply", "process", "step"])) {
      scenario = "certificate";
      response = CERTIFICATE;
    } else if (includesAny(text, ["scholarship", "scheme", "find", "course", "funding", "grant"])) {
      scenario = "scholarships";
      response = SCHOLARSHIPS;
    }

    var clone;
    try {
      clone = JSON.parse(JSON.stringify(response));
    } catch (e) {
      clone = response;
    }
    clone.disclaimer = DISCLAIMER;
    clone.demo = true;
    return { scenario: scenario, response: clone };
  }

  window.EduDemo = {
    DISCLAIMER: DISCLAIMER,
    resolve: resolve,
    scenarios: {
      scholarships: SCHOLARSHIPS,
      clarification: ELIGIBILITY,
      documents: DOCUMENTS,
      certificate: CERTIFICATE,
      no_results: NO_RESULTS,
      failed: FAILED
    }
  };
})();
