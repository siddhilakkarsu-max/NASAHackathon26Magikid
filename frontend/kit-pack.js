// Gear manifest conveniences: Copy link, Download CSV and a packing-list mode with check-offs.
// Loaded after kit.js and reads its globals (state, esc, kg, CARRIER). The pure functions at the top
// (kitToCsv, kitSignature, buildShareUrl) also run under node for the tests.
//
// Debug URL params, so a headless browser can show the packing list without clicking:
//   ?pack=1      packing mode on at load
//   ?packdemo=1  packing mode on and the first 3 items ticked (in memory only, not saved)
"use strict";

// ---------------------------------------------------------------- pure

const CSV_COLUMNS = ["category", "item", "qty", "priority", "carried_by", "unit_mass_kg", "total_mass_kg", "evidence", "rules", "sources", "note"];

function csvField(v) {
  const s = v == null ? "" : String(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

// items in the order the page shows them (by group), falling back to the flat list
function kitItems(manifest) {
  if (manifest && Array.isArray(manifest.groups) && manifest.groups.length) return manifest.groups.flatMap((g) => g.items || []);
  return (manifest && manifest.items) || [];
}

function kitToCsv(manifest) {
  const rows = [CSV_COLUMNS];
  for (const e of kitItems(manifest)) {
    rows.push([
      e.category_label || e.category, e.name, e.qty, e.priority, e.carried_by, e.mass_kg, e.total_mass_kg,
      e.confidence ? e.confidence.tag : "", (e.rules || []).join(" "), (e.sources || []).map((s) => s.title).join(" | "), e.note,
    ]);
  }
  return "\uFEFF" + rows.map((r) => r.map(csvField).join(",")).join("\r\n") + "\r\n";
}

// stable across reloads of the same kit: archetype plus every item id and quantity
function kitSignature(manifest) {
  const arch = (manifest && manifest.context && manifest.context.archetype) || "kit";
  const parts = kitItems(manifest).map((e) => `${e.id}x${e.qty}`).sort();
  let h = 0x811c9dc5;
  for (const ch of parts.join(",")) { h ^= ch.charCodeAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
  return `${arch}-${h.toString(16).padStart(8, "0")}`;
}

// params are exactly the ones kit.js prefillFromURL() reads
function buildShareUrl(f, mode, base = "kit.html") {
  const p = [];
  const add = (k, v) => { if (v != null && String(v).trim() !== "") p.push(`${k}=${encodeURIComponent(String(v).trim()).replace(/%2C/g, ",")}`); };
  add("archetype", f.archetype);
  add("crew", f.crew);
  add("stay", f.stay);
  if (f.useRoute) {
    add("region", f.region);
    add("vehicle", f.vehicle);
    const pt = (a, b) => (Number.isFinite(parseFloat(a)) && Number.isFinite(parseFloat(b)) ? `${parseFloat(a)},${parseFloat(b)}` : null);
    add("base", pt(f.baseLat, f.baseLon));
    add("target", pt(f.targetLat, f.targetLon));
    add("hour", f.hour);
    add("budget", f.budget);
  }
  add("ls", f.ls);
  if (mode === "published") add("tab", "published");
  return p.length ? `${base}?${p.join("&")}` : base;
}

if (typeof module !== "undefined") module.exports = { kitToCsv, kitSignature, buildShareUrl, csvField, CSV_COLUMNS };

// ---------------------------------------------------------------- page

if (typeof document !== "undefined") (function packPage() {
  const q = new URLSearchParams(location.search);
  const demo = q.get("packdemo") === "1";
  const pk = { on: demo || q.get("pack") === "1", demo, sig: null, ticks: new Set() };
  const sheet = document.getElementById("sheet");
  if (!sheet) return;
  const val = (id) => { const el = document.getElementById(id); return el ? el.value : undefined; };
  const store = (sig) => "marswalk-pack:" + sig;

  function formValues() {
    const r = document.getElementById("useRoute");
    return {
      archetype: val("archetype"), crew: val("crew"), stay: val("stay"), useRoute: !!(r && r.checked && !r.disabled),
      region: val("region"), vehicle: val("vehicle"), baseLat: val("baseLat"), baseLon: val("baseLon"),
      targetLat: val("targetLat"), targetLon: val("targetLon"), hour: val("hour"), budget: val("budget"), ls: val("ls"),
    };
  }

  function stamp() {
    const d = new Date(), z = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}`;
  }

  function flash(btn, text, back) { btn.textContent = text; setTimeout(() => (btn.textContent = back), 1400); }

  async function copyLink(btn) {
    const url = new URL(buildShareUrl(formValues(), state.mode, location.pathname), location.origin).href;
    try {
      await navigator.clipboard.writeText(url);
      flash(btn, "Link copied", "Copy link");
    } catch (_) {
      let f = document.getElementById("packUrl");
      if (!f) {
        f = document.createElement("input");
        f.id = "packUrl"; f.className = "pk-url"; f.readOnly = true; f.setAttribute("aria-label", "Link to this kit");
        f.addEventListener("blur", () => f.remove());
        btn.closest(".tools").appendChild(f);
      }
      f.value = url; f.focus(); f.select();
    }
  }

  function downloadCsv() {
    const m = state.manifest; if (!m) return;
    const blob = new Blob([kitToCsv(m)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `marswalk-kit-${(m.context && m.context.archetype) || "kit"}-${stamp()}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function loadTicks(m) {
    pk.sig = kitSignature(m);
    pk.ticks = new Set();
    try { (JSON.parse(localStorage.getItem(store(pk.sig))) || []).forEach((id) => pk.ticks.add(id)); } catch (_) {}
    if (pk.demo) { kitItems(m).slice(0, 3).forEach((e) => pk.ticks.add(e.id)); }
  }
  function saveTicks() {
    try { pk.ticks.size ? localStorage.setItem(store(pk.sig), JSON.stringify([...pk.ticks])) : localStorage.removeItem(store(pk.sig)); } catch (_) {}
  }

  function massCell(e) {
    if (e.per_use_kg != null) return `${kg(e.per_use_kg)}<small>/EVA</small>`;
    if (e.id === "c_cabin") return '<span class="none">see budget</span>';
    if (e.total_mass_kg == null) return '<span class="none">n/a</span>';
    return kg(e.total_mass_kg);
  }

  function packHTML(m) {
    const groups = (m.groups && m.groups.length) ? m.groups : [{ id: "all", label: "Items", items: m.items || [] }];
    const body = groups.map((g) => {
      const rows = g.items.map((e) => {
        const car = esc(CARRIER[e.carried_by] || e.carried_by);
        const on = pk.ticks.has(e.id);
        return `<li class="pk-line p-${esc(e.priority)}${on ? " done" : ""}" data-pk="${esc(e.id)}"><label class="pk-row">
          <span class="pk-bar" title="${esc(e.priority_label || e.priority)}"></span>
          <input type="checkbox" class="pk-box" value="${esc(e.id)}"${on ? " checked" : ""}>
          <span class="pk-nm">${esc(e.name)}<small>${car}</small></span>
          <span class="pk-qty">x${esc(e.qty)}</span><span class="pk-car">${car}</span><span class="pk-mass">${massCell(e)}</span></label></li>`;
      }).join("");
      return `<div class="pk-group" data-group="${esc(g.id)}"><h3>${esc(g.label)} <span class="n" data-count></span></h3><ul>${rows}</ul></div>`;
    }).join("");
    return `<div class="pk-head">
        <span class="pk-title">Packing list</span>
        <span class="pk-count" id="packCount" aria-live="polite"></span>
        <span class="pk-meter" aria-hidden="true"><i id="packMeter"></i></span>
        <button type="button" class="link" id="packClear">Clear ticks</button>
      </div>${body}`;
  }

  function updateCounts(box) {
    const lines = [...box.querySelectorAll(".pk-line")];
    const done = lines.filter((l) => l.classList.contains("done")).length;
    box.querySelector("#packCount").textContent = `${done} of ${lines.length} packed`;
    box.querySelector("#packMeter").style.width = lines.length ? `${(done / lines.length) * 100}%` : "0";
    box.querySelector("#packClear").hidden = !done;
    box.querySelectorAll(".pk-group").forEach((g) => {
      const ls = g.querySelectorAll(".pk-line"), d = g.querySelectorAll(".pk-line.done").length;
      g.querySelector("[data-count]").textContent = `${d} of ${ls.length}`;
    });
  }

  function showPack() {
    const cats = document.getElementById("cats");
    const m = state.manifest;
    const sec = cats && cats.closest(".sec");
    document.body.classList.toggle("packing", pk.on && !!cats);
    let box = document.getElementById("packList");
    if (!cats || !m) return;
    sec.classList.add("pk-sec");
    if (!pk.on) { if (box) box.remove(); cats.hidden = false; return; }
    if (kitSignature(m) !== pk.sig || !box) loadTicks(m);
    if (!box) {
      box = document.createElement("div");
      box.id = "packList"; box.className = "pack";
      cats.after(box);
      box.addEventListener("change", (ev) => {
        const c = ev.target.closest(".pk-box"); if (!c) return;
        c.checked ? pk.ticks.add(c.value) : pk.ticks.delete(c.value);
        c.closest(".pk-line").classList.toggle("done", c.checked);
        saveTicks(); updateCounts(box);
      });
    }
    box.innerHTML = packHTML(m);
    cats.hidden = true;
    box.querySelector("#packClear").onclick = () => {
      pk.ticks.clear(); saveTicks();
      box.querySelectorAll(".pk-box").forEach((c) => { c.checked = false; c.closest(".pk-line").classList.remove("done"); });
      updateCounts(box);
    };
    updateCounts(box);
  }

  function decorate() {
    const tools = sheet.querySelector(".head .tools");
    if (!tools || tools.querySelector("[data-pack-tool]")) return;
    const mk = (id, text, fn) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "ghost"; b.id = id; b.textContent = text; b.dataset.packTool = "";
      b.onclick = () => fn(b); return b;
    };
    const toggle = mk("packToggle", "Packing list", () => {
      pk.on = !pk.on; pk.demo = false;
      toggle.setAttribute("aria-pressed", String(pk.on));
      showPack();
      const sec = document.querySelector(".pk-sec");
      if (pk.on && sec) sec.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    toggle.setAttribute("aria-pressed", String(pk.on));
    tools.prepend(toggle, mk("packLink", "Copy link", copyLink), mk("packCsv", "Download CSV", downloadCsv));
    showPack();
  }

  new MutationObserver(decorate).observe(sheet, { childList: true });
  decorate();
})();
