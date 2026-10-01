/* Playbook pages: every section folds to its title and a one-line description; click to open.
 *
 * Progressive: the HTML is the full document. Without this script everything simply shows open,
 * and the print view opens everything. Three shapes are handled:
 *   1. an <h2> inside a <section> (the SOPs and standards) → the h2 and everything after it, up to
 *      the next h2, become one fold; the description is the h2's data-desc;
 *   2. a section headed by .sec-head (Lead to Last Nail's reference sections) → the head is the
 *      summary, the rest of the section is the body;
 *   3. a Lead to Last Nail .stage → title, owners and lead paragraph stay visible; the play, the
 *      "write it" and the fail state fold under "Show the play".
 * A link to any id inside a fold (#7-2, #tracker…) opens it first, so deep links keep working.
 */
(function () {
  var main = document.querySelector("main");
  if (!main) return;
  var folds = [];

  function descEl(text) {
    var p = document.createElement("span");
    p.className = "fold-d"; p.textContent = text; return p;
  }
  function slug(t) { return t.toLowerCase().replace(/&amp;/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60); }

  // 1 + 2: sections
  Array.prototype.slice.call(main.querySelectorAll("h2")).forEach(function (h2) {
    if (h2.closest(".fold, .stage, .phase, .nofold")) return;
    var head = h2.closest(".sec-head");
    var d = document.createElement("details"); d.className = "fold";
    var s = document.createElement("summary");
    var body = document.createElement("div"); body.className = "fold-b";
    if (head) {
      var sec = head.parentElement;
      var lead = head.querySelector("p");
      sec.insertBefore(d, head);
      s.appendChild(h2);
      if (h2.dataset.desc) s.appendChild(descEl(h2.dataset.desc));
      else if (lead) { lead.classList.add("fold-d"); s.appendChild(lead); }
      head.remove();
      while (d.nextSibling) body.appendChild(d.nextSibling);
    } else {
      h2.parentElement.insertBefore(d, h2);
      var n = h2.nextSibling;
      while (n && !(n.nodeType === 1 && (n.tagName === "H2" || n.classList.contains("fold")))) { var nx = n.nextSibling; body.appendChild(n); n = nx; }
      s.appendChild(h2);
      if (h2.dataset.desc) s.appendChild(descEl(h2.dataset.desc));
    }
    d.id = d.id || h2.id || "s-" + slug(h2.textContent);
    if (h2.id) h2.removeAttribute("id");
    d.appendChild(s); d.appendChild(body);
    folds.push({ el: d, title: h2.textContent.trim() });
  });

  // 3: Lead to Last Nail stages
  Array.prototype.slice.call(main.querySelectorAll(".stage")).forEach(function (st) {
    var b = st.querySelector(".stage-body");
    if (!b) return;
    var lead = b.querySelector(":scope > p");
    var more = document.createElement("div"); more.className = "stage-more";
    var n = lead ? lead.nextSibling : null;
    while (n) { var nx = n.nextSibling; more.appendChild(n); n = nx; }
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "stage-tog"; btn.setAttribute("aria-expanded", "false");
    btn.textContent = "Show the play ▾";
    b.appendChild(btn); b.appendChild(more);
    st.classList.add("folded");
    var h3 = b.querySelector("h3");
    function set(open) { st.classList.toggle("folded", !open); btn.setAttribute("aria-expanded", String(open)); btn.textContent = open ? "Hide the play ▴" : "Show the play ▾"; }
    btn.addEventListener("click", function () { set(st.classList.contains("folded")); });
    if (h3) { h3.style.cursor = "pointer"; h3.addEventListener("click", function () { set(st.classList.contains("folded")); }); }
    var num = st.querySelector(".stage-num");
    st.id = st.id || "stage-" + (num ? num.textContent.trim() : slug(h3 ? h3.textContent : "x"));
    st._set = set;
    folds.push({ el: st, title: (num ? num.textContent.trim() + " · " : "") + (h3 ? h3.textContent.trim() : "") });
  });
  if (!folds.length) return;

  function openEl(el, on) { if (el.tagName === "DETAILS") el.open = on; else if (el._set) el._set(on); }
  function all(on) { folds.forEach(function (f) { openEl(f.el, on); }); }

  // Contents + expand/collapse, at the top of the document
  var bar = document.createElement("nav");
  bar.className = "fold-bar"; bar.setAttribute("aria-label", "Contents");
  var tools = document.createElement("div"); tools.className = "fold-tools";
  tools.innerHTML = '<span class="k">Contents · ' + folds.length + ' sections</span>';
  [["Expand all", true], ["Collapse all", false]].forEach(function (x) {
    var bt = document.createElement("button"); bt.type = "button"; bt.textContent = x[0];
    bt.addEventListener("click", function () { all(x[1]); }); tools.appendChild(bt);
  });
  bar.appendChild(tools);
  var ol = document.createElement("ol");
  folds.forEach(function (f) {
    var li = document.createElement("li"), a = document.createElement("a");
    a.href = "#" + f.el.id; a.textContent = f.title; li.appendChild(a); ol.appendChild(li);
  });
  bar.appendChild(ol);
  main.insertBefore(bar, main.firstChild);

  // Deep links open whatever holds the target
  function reveal() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    var t = document.getElementById(id);
    if (!t) return;
    var inner = t.querySelector && t.querySelector(":scope > details.fold");
    if (inner) inner.open = true;
    for (var p = t; p && p !== main; p = p.parentElement) {
      if (p.tagName === "DETAILS") p.open = true;
      if (p.classList && p.classList.contains("stage") && p._set) p._set(true);
    }
    setTimeout(function () { t.scrollIntoView({ block: "start" }); }, 0);
  }
  window.addEventListener("hashchange", reveal);
  reveal();
  window.addEventListener("beforeprint", function () { all(true); });
})();
