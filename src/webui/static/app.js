/* True Research web UI — single-file, zero-build, no framework.
 * Hash routes: #/launch  #/runs  #/runs/<id>  #/report/<id>  #/keys
 *
 * SECURITY: no innerHTML anywhere. All dynamic content is inserted via
 * textContent / createElement. The report markdown is pre-escaped
 * (`<` -> &lt;) before marked.parse so raw HTML embedded in the engine
 * report (which quotes excerpts from untrusted web pages) can never become
 * markup; the parsed result is materialized through DOMParser (inert, no
 * script execution) and adopted node-by-node. The `<`-escape does NOT cover
 * link destinations — markdown like [x](javascript:...) contains no angle
 * brackets — so before adoption every <a href> is protocol-allowlisted
 * (http/https/mailto, plus in-page "#..." anchors); anything else has its
 * href stripped (see scrubUnsafeLinks). The report click handler re-checks
 * the protocol as defense in depth.
 */
(() => {
  "use strict";

  // ---------- tiny DOM + format helpers ----------
  const qs = (sel, root) => (root || document).querySelector(sel);
  const qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null) continue;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else node.setAttribute(k, v);
      }
    }
    for (const c of children.flat(Infinity)) {
      if (c == null) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function swap(node, ...children) {
    clear(node);
    for (const c of children.flat(Infinity)) if (c != null) node.appendChild(c);
  }

  const fmtUsd = (n) => "$" + (Number(n) || 0).toFixed(2);

  const fmtDur = (seconds) => {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h + ":" + String(m).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  };

  const fmtLocal = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleString();
  };

  async function fetchJSON(url, opts) {
    const res = await fetch(url, opts);
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON body */ }
    return { ok: res.ok, status: res.status, body };
  }

  function toast(msg, isErr) {
    const t = el("div", { class: "toast" + (isErr ? " err" : ""), text: msg });
    qs("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 6500);
  }

  const reducedMotion = () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function emptyState(message, glyph) {
    return el("div", { class: "empty-state" },
      glyph ? el("span", { class: "empty-glyph", "aria-hidden": "true", text: glyph }) : null,
      message);
  }

  // ---------- state ----------
  const state = {
    view: null,
    selectedRunId: null,
    reportRunId: null,        // last report opened, so the bare Report tab works
    runs: [],
    pollTimers: { list: null, detail: null },
    decisionsCount: -1,       // auto-scroll the log only when it grows
  };

  function clearTimers() {
    for (const k of Object.keys(state.pollTimers)) {
      if (state.pollTimers[k]) {
        clearInterval(state.pollTimers[k]);
        state.pollTimers[k] = null;
      }
    }
  }

  // ---------- routing ----------
  function parseHash() {
    const parts = (location.hash || "#/launch")
      .replace(/^#\/?/, "").split("/").filter(Boolean);
    if (parts[0] === "runs") return { view: "runs", id: parts[1] || null };
    if (parts[0] === "report") return { view: "report", id: parts[1] || null };
    if (parts[0] === "keys") return { view: "keys", id: null };
    return { view: "launch", id: null };
  }

  function route() {
    const r = parseHash();
    clearTimers();
    state.view = r.view;

    for (const sec of qsa("main > section")) sec.hidden = true;
    qs("#view-" + r.view).hidden = false;
    for (const a of qsa("#nav a"))
      a.classList.toggle("active", a.dataset.view === r.view);

    if (r.view === "runs") {
      state.selectedRunId = r.id;
      state.decisionsCount = -1;
      loadRuns();
      state.pollTimers.list = setInterval(loadRuns, 5000);
      if (r.id) startDetail(r.id);
      else swap(qs("#run-detail"), emptyState("Select a run to inspect its live state.", "◎"));
    } else if (r.view === "report") {
      const id = r.id || state.reportRunId;
      if (r.id) state.reportRunId = r.id;
      renderReport(id);
    } else if (r.view === "keys") {
      renderKeys();
    }
    if (r.view === "launch") updateBackendHint();
  }

  // ---------- launch view ----------
  const selectedPreset = () => {
    const card = qs(".preset-card.selected");
    return card ? card.dataset.preset : "quick";
  };

  // Long-paste threshold (spec): distill when > 400 chars OR > 3 lines.
  const needsDistill = (text) =>
    text.length > 400 || text.split("\n").length > 3;

  function wireLaunch() {
    qs("#preset-grid").addEventListener("click", (e) => {
      const card = e.target.closest(".preset-card");
      if (!card) return;
      for (const c of qsa(".preset-card")) {
        c.classList.toggle("selected", c === card);
        c.setAttribute("aria-checked", c === card ? "true" : "false");
      }
    });
    // Editing the original text invalidates a distilled question composed
    // from an older version of it — hide the panel so a stale hybrid can
    // never be launched.
    qs("#q").addEventListener("input", hideDistillPanel);
    qs("#btn-launch").addEventListener("click", onLaunchClick);
    qs("#btn-launch-distilled").addEventListener("click", () => {
      const original = qs("#q").value;
      const edited = qs("#distilled-q").value.trim();
      if (!edited) { showFieldError("question", "distilled question is empty"); return; }
      submitLaunch(edited + "\n\n## Original brief\n\n" + original);
    });
    qs("#btn-skip-distill").addEventListener("click", () => {
      hideDistillPanel();
      submitLaunch(qs("#q").value);
    });
  }

  function hideDistillPanel() {
    qs("#distill-panel").hidden = true;
    qs("#btn-launch").hidden = false;
  }

  async function onLaunchClick() {
    clearFieldErrors();
    const raw = qs("#q").value;
    if (!needsDistill(raw.trim())) {
      await submitLaunch(raw);
      return;
    }
    const btn = qs("#btn-launch");
    btn.disabled = true;
    btn.textContent = "Distilling…";
    try {
      const { ok, body } = await fetchJSON("/api/distill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: raw }),
      });
      if (ok && body && body.research_question) {
        qs("#distilled-q").value = body.research_question;
        qs("#distill-context").textContent =
          body.context_summary ? "Context: " + body.context_summary : "";
        qs("#distill-panel").hidden = false;
        // One launch surface at a time: the panel's buttons take over, so
        // hide the top button (it would silently re-distill). hideDistillPanel
        // restores it.
        btn.hidden = true;
        qs("#distill-panel").scrollIntoView({
          behavior: reducedMotion() ? "auto" : "smooth", block: "center" });
      } else {
        // Distill must never block a launch (spec): fall back to the raw
        // paste. Await so `finally` cannot re-enable the button while the
        // launch POST is still in flight (double-submit = duplicate run).
        toast("Distill unavailable — launching with your text as-is", true);
        await submitLaunch(raw);
      }
    } catch (err) {
      toast("Distill unavailable — launching with your text as-is", true);
      await submitLaunch(raw);
    } finally {
      btn.disabled = false;
      btn.textContent = "Begin research";
    }
  }

  function clearFieldErrors() {
    for (const e of qsa(".field-err")) { e.hidden = true; e.textContent = ""; }
  }

  function showFieldError(field, msg) {
    const map = {
      question: "#err-question",
      preset: "#err-preset",
      max_budget_usd: "#err-budget",
      max_wall_hours: "#err-wall",
    };
    const box = qs(map[field] || "#err-general");
    box.textContent = msg;
    box.hidden = false;
  }

  // Every launch surface (top button + both distill-panel buttons) is
  // disabled for the whole POST so neither a double click nor a click on
  // the sibling panel button mid-flight can commission two paid runs.
  async function submitLaunch(questionText) {
    clearFieldErrors();
    const btn = qs("#btn-launch");
    const allBtns = [btn, qs("#btn-launch-distilled"), qs("#btn-skip-distill")];
    const payload = {
      question: questionText,
      preset: selectedPreset(),
    };
    const budget = qs("#budget").value.trim();
    const wall = qs("#wall").value.trim();
    if (budget !== "") payload.max_budget_usd = Number(budget);
    if (wall !== "") payload.max_wall_hours = Number(wall);

    for (const b of allBtns) b.disabled = true;
    try {
      const { ok, status, body } = await fetchJSON("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (ok && body && body.launched) {
        const backendNote = body.backend === "anthropic"
          ? " · all-Anthropic backend" : "";
        toast("Run launched (pid " + body.pid + ")" + backendNote +
              " — it will appear in the list within ~30s");
        qs("#q").value = "";
        hideDistillPanel();
        location.hash = "#/runs";
      } else if (status === 422 && body && body.detail) {
        if (Array.isArray(body.detail)) {
          for (const item of body.detail) {
            const field = item.loc ? String(item.loc[item.loc.length - 1]) : "general";
            showFieldError(field, item.msg || "invalid value");
          }
        } else {
          showFieldError("general", String(body.detail));
        }
      } else {
        showFieldError("general", "Launch failed (HTTP " + status + ")");
      }
    } catch (err) {
      showFieldError("general", "Network error: " + err.message);
    } finally {
      for (const b of allBtns) b.disabled = false;
    }
  }

  async function updateBackendHint() {
    const hint = qs("#backend-hint");
    const { ok, body } = await fetchJSON("/api/keys");
    if (!ok || !Array.isArray(body)) { hint.hidden = true; return; }
    const deepseek = body.find((k) => k.name === "DEEPSEEK_API_KEY");
    if (deepseek && deepseek.set) { hint.hidden = true; return; }
    hint.textContent =
      "No DeepSeek key set — runs use the all-Anthropic backend. " +
      "Comprehensive will likely stop at the budget cap with a partial " +
      "report. Add a DeepSeek key in the Keys tab for the advertised costs.";
    hint.hidden = false;
  }

  // ---------- keys view ----------
  async function renderKeys() {
    const host = qs("#keys-list");
    const { ok, body } = await fetchJSON("/api/keys");
    if (!ok || !Array.isArray(body)) {
      swap(host, emptyState("Could not load key status.", "⚠"));
      return;
    }
    swap(host, body.map((k) => {
      const input = el("input", {
        type: "password", placeholder: k.set ? "replace key…" : "paste key…",
        autocomplete: "off", "aria-label": k.name,
      });
      const save = el("button", { type: "button", class: "btn-primary btn-small", text: "Save" });
      const row = el("div", { class: "keys-row" },
        el("div", { class: "keys-head" },
          el("span", { class: "keys-name", text: k.name }),
          el("span", { class: "badge " + (k.set ? "verified" : "unverified"),
                       text: k.set ? "set" : "not set" })),
        el("p", { class: "keys-desc", text: k.used_for }),
        el("div", { class: "keys-input" }, input, save));
      save.addEventListener("click", async () => {
        const value = input.value.trim();
        if (!value) return;
        save.disabled = true;
        try {
          const res = await fetchJSON("/api/keys", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: k.name, value }),
          });
          if (res.ok) {
            toast(k.name + " saved");
            input.value = "";
            renderKeys();
          } else {
            toast("Could not save " + k.name + " (HTTP " + res.status + ")", true);
          }
        } finally {
          save.disabled = false;
        }
      });
      return row;
    }));
  }

  // ---------- runs list ----------
  async function loadRuns() {
    const { ok, body } = await fetchJSON("/api/runs");
    if (!ok || !Array.isArray(body)) return;
    state.runs = body;
    if (state.view === "runs") renderRunList();
  }

  function dotClass(r) {
    if (r.status === "running") return "running";
    if (r.status === "finished" && r.finish_reason === "conclusive") return "done";
    return "idle";
  }

  function renderRunList() {
    const host = qs("#run-list");
    if (!state.runs.length) {
      swap(host, emptyState("No runs yet — commission one from the New Run tab."));
      return;
    }
    swap(host, state.runs.map((r) => {
      const row = el("button", {
        type: "button",
        class: "run-row" + (r.run_id === state.selectedRunId ? " selected" : ""),
        "data-id": r.run_id,
        title: fmtLocal(r.created_at),
      },
        el("span", { class: "dot " + dotClass(r), "aria-hidden": "true" }),
        el("span", null,
          el("span", { class: "run-q", text: r.question }),
          el("span", { class: "run-meta" },
            el("span", { class: "spend", text: fmtUsd(r.spend_usd) }),
            el("span", { text: "c" + (r.last_cycle == null ? "?" : r.last_cycle) }),
            el("span", { class: "rid", text: r.run_id }))));
      if (!r.has_report) return row;
      const base = "/api/runs/" + encodeURIComponent(r.run_id) + "/report";
      return el("div", { class: "run-row-wrap" }, row,
        el("span", { class: "run-dl" },
          el("a", { href: base + ".md", download: "", title: "Download markdown", text: "md" }),
          el("a", { href: base + ".pdf", download: "", title: "Download PDF", text: "pdf" })));
    }));
  }

  // ---------- run detail ----------
  function startDetail(id) {
    loadDetail(id);
    state.pollTimers.detail = setInterval(() => loadDetail(id), 3000);
  }

  async function loadDetail(id) {
    const { ok, body } = await fetchJSON("/api/runs/" + encodeURIComponent(id));
    if (state.view !== "runs" || state.selectedRunId !== id) return; // stale response
    if (!ok || !body) {
      swap(qs("#run-detail"), emptyState("Could not load run " + id + ".", "⚠"));
      return;
    }
    renderDetail(body);
    if (body.meta && body.meta.status !== "running" && state.pollTimers.detail) {
      clearInterval(state.pollTimers.detail);
      state.pollTimers.detail = null;
    }
  }

  function statusPill(meta) {
    if (meta.status === "running") {
      return el("span", { class: "pill running" },
        el("span", { class: "dot running" }),
        "running · cycle " + meta.last_cycle);
    }
    const reason = meta.finish_reason || "finished";
    return el("span",
      { class: "pill " + (reason === "conclusive" ? "conclusive" : "stopped") },
      "finished · " + reason);
  }

  const Q_GLYPH = { open: "○", in_progress: "◐", resolved: "●" };

  function metric(label, valueNode) {
    return el("div", { class: "metric" },
      el("span", { class: "m-label", text: label }),
      el("span", { class: "m-value" }, valueNode));
  }

  function renderDetail(d) {
    const meta = d.meta || {};

    const sessionsText = Object.entries(d.ledger_by_type || {})
      .sort((a, b) => b[1] - a[1])
      .map(([t, n]) => t.slice(0, 4) + " ×" + n)
      .join(" · ") || "—";

    const questionRows = (d.questions || []).map((q) =>
      el("div", { class: "q-row" + (q.status === "resolved" ? " resolved-row" : "") },
        el("span", { class: "q-glyph " + q.status, "aria-hidden": "true",
                     text: Q_GLYPH[q.status] || "○" }),
        el("span", { text: q.question }),
        el("span", { class: "q-pri", text: "P" + q.priority })));

    const findingRows = (d.findings || []).map((f) => {
      const conf = Math.round(Math.max(0, Math.min(1, Number(f.confidence) || 0)) * 100);
      const v = String(f.verification_status || "unverified").toLowerCase();
      const fill = el("i");
      fill.style.width = conf + "%";
      return el("div", { class: "f-row" },
        el("span", { class: "f-slug" }, f.slug + " ",
          el("small", { text: "← " + f.question_id })),
        el("span", { class: "conf-bar", title: "confidence " + conf + "%" }, fill),
        el("span", { class: "badge " + v, text: v }));
    });

    const decisionLines = (d.decisions || []).map((line) =>
      el("div", { class: "d-line", text: line }));

    const log = el("div", { class: "decisions", id: "decisions-log" },
      decisionLines.length ? decisionLines
        : el("span", { style: "opacity:.5", text: "no decisions logged" }));

    swap(qs("#run-detail"),
      el("h2", { class: "detail-q", text: meta.question }),
      el("div", { class: "chip-row" },
        statusPill(meta),
        el("span", { class: "chip", text: meta.profile }),
        el("span", { class: "chip", text: "wave · " + meta.wave }),
        el("span", { class: "chip", title: "created", text: fmtLocal(meta.created_at) })),
      el("div", { class: "metrics" },
        metric("Spend", fmtUsd(d.spend_usd)),
        metric("Cycles", String(meta.last_cycle == null ? "?" : meta.last_cycle)),
        metric("Active", fmtDur(meta.active_seconds)),
        metric("Sessions", el("small", { text: sessionsText }))),
      el("div", { class: "detail-h", text: "Question tree" }),
      questionRows.length ? questionRows : emptyState("No questions yet."),
      el("div", { class: "detail-h", text: "Findings" }),
      findingRows.length ? findingRows : emptyState("No findings yet."),
      el("div", { class: "detail-h", text: "Decisions" }),
      log,
      meta.status === "finished"
        ? el("a", { class: "report-cta", href: "#/report/" + meta.run_id,
                    text: "Read report →" })
        : null);

    const n = (d.decisions || []).length;
    if (n !== state.decisionsCount) {
      log.scrollTop = log.scrollHeight;
      state.decisionsCount = n;
    }
  }

  // ---------- report view ----------
  // Escape `<` before parsing so raw HTML in the report can never open a
  // tag. `>` stays: at line starts it is blockquote syntax, and inline it
  // is inert once `<` is neutralized.
  const sanitizeMarkdown = (md) => String(md).replace(/</g, "&lt;");

  // marked has no URL sanitizer: [x](javascript:alert(1)) parses to a live
  // javascript: link. Allowlist every <a href> in the (still inert) parsed
  // document BEFORE adoption: keep http/https/mailto and in-page "#..."
  // anchors (citation targets); strip the href from everything else, keeping
  // the visible text. Relative hrefs resolve to the page origin (http:) and
  // therefore pass.
  const SAFE_LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

  function linkProtocol(href) {
    try { return new URL(href, document.baseURI).protocol; }
    catch (_) { return null; }
  }

  function scrubUnsafeLinks(root) {
    for (const a of qsa("a[href]", root)) {
      const href = a.getAttribute("href");
      if (href.startsWith("#")) continue; // in-page citation anchor — keep
      if (!SAFE_LINK_PROTOCOLS.has(linkProtocol(href))) {
        a.removeAttribute("href");
        a.setAttribute("title", "link removed (unsafe URL)");
      }
    }
  }

  // Materialize marked's output via DOMParser (inert document — scripts do
  // not execute) and adopt the nodes. Belt-and-braces on top of the escape.
  function setMarkdownHTML(container, html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    scrubUnsafeLinks(doc.body); // before any node reaches the live page
    clear(container);
    for (const node of Array.from(doc.body.childNodes)) {
      container.appendChild(document.adoptNode(node));
    }
  }

  const SRC_RE = /^src-[\w.-]+$/;

  function linkCitations(container) {
    // 1) registry entries: "- `src-x` — Title …" → give the <li> the id
    for (const li of qsa("li", container)) {
      const code = li.querySelector("code");
      if (code && li.firstElementChild === code) {
        const t = code.textContent.trim();
        if (SRC_RE.test(t) && !document.getElementById(t)) li.id = t;
      }
    }
    // 2) wrap [src-...] occurrences in plain text nodes with anchors
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) =>
        node.parentElement.closest("a, code, pre")
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT,
    });
    const hits = [];
    let node;
    while ((node = walker.nextNode())) {
      if (/\[src-[\w.-]+\]/.test(node.nodeValue)) hits.push(node);
    }
    for (const textNode of hits) {
      const frag = document.createDocumentFragment();
      for (const part of textNode.nodeValue.split(/(\[src-[\w.-]+\])/g)) {
        const m = part.match(/^\[(src-[\w.-]+)\]$/);
        if (m) frag.appendChild(el("a", { class: "cite", href: "#" + m[1], text: part }));
        else if (part) frag.appendChild(document.createTextNode(part));
      }
      textNode.parentNode.replaceChild(frag, textNode);
    }
    // 3) smooth scroll + flash on citation click
    container.addEventListener("click", (e) => {
      // Defense in depth on top of scrubUnsafeLinks: never honor a
      // scriptable-protocol navigation from inside the report.
      const anyLink = e.target.closest("a[href]");
      if (anyLink) {
        const href = anyLink.getAttribute("href") || "";
        if (!href.startsWith("#")) {
          const proto = linkProtocol(href);
          if (proto === "javascript:" || proto === "vbscript:" || proto === "data:") {
            e.preventDefault();
            return;
          }
        }
      }
      const a = e.target.closest("a.cite");
      if (!a) return;
      e.preventDefault();
      const target = document.getElementById(a.getAttribute("href").slice(1));
      if (!target) return;
      target.scrollIntoView({
        behavior: reducedMotion() ? "auto" : "smooth",
        block: "center",
      });
      target.classList.remove("flash");
      void target.offsetWidth; // restart the flash animation
      target.classList.add("flash");
    });
  }

  async function renderReport(id) {
    const shell = qs("#report-shell");
    if (!id) {
      swap(shell, emptyState("No report selected — pick a finished run.", "◇"));
      return;
    }
    swap(shell, emptyState("Fetching report…"));
    const { ok, body } = await fetchJSON("/api/runs/" + encodeURIComponent(id) + "/report");
    if (state.view !== "report") return; // navigated away mid-fetch
    if (!ok || !body) {
      swap(shell, emptyState("Could not load the report for " + id + ".", "⚠"));
      return;
    }
    if (!body.available) {
      swap(shell,
        emptyState("Report not written yet — the run may still be working.", "⧖"),
        el("div", { style: "text-align:center;margin-top:-30px" },
          el("a", { class: "back", style: "color:var(--accent)",
                    href: "#/runs/" + id, text: "← back to the live view" })));
      return;
    }

    const article = el("article", { class: "reading", id: "report-content" });
    swap(shell,
      el("div", { class: "report-toolbar" },
        el("a", { class: "back", href: "#/runs/" + id, text: "← Back to run" }),
        el("span", { class: "rid", text: id }),
        el("a", { class: "btn-pdf", href: "/api/runs/" + encodeURIComponent(id) + "/report.md",
                  download: "", text: "Download .md" }),
        el("a", { class: "btn-pdf", href: "/api/runs/" + encodeURIComponent(id) + "/report.pdf",
                  download: "", text: "Download PDF" })),
      article);

    setMarkdownHTML(article,
      marked.parse(sanitizeMarkdown(body.markdown), { gfm: true, breaks: false }));
    linkCitations(article);
  }

  // ---------- boot ----------
  wireLaunch();
  qs("#run-list").addEventListener("click", (e) => {
    const row = e.target.closest(".run-row");
    if (row) location.hash = "#/runs/" + row.dataset.id;
  });
  window.addEventListener("hashchange", route);
  if (!location.hash) location.hash = "#/launch";
  route();
})();
