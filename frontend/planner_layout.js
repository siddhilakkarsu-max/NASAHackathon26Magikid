"use strict";

// Reuse the existing controls and stylesheet; only their grouping and disclosure change.
function createPlannerLayout() {
  const byId = id => document.getElementById(id);
  const make = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const canonical = byId("layer");
  let mapChoice = "", mapDefinitions = [];
  const optionMarkup = new Map();
  const globalChoice = () => canonical.selectedOptions[0]?.parentElement.id === "globalWeather"
    ? canonical.value : mapChoice;
  function syncLayers() {
    const global = canonical.selectedOptions[0]?.parentElement.id === "globalWeather";
    for (const [id, wantGlobal, empty] of [
      ["globalLayer", true, "The planner's own map"],
      ["regionalLayer", false, "No regional data layer"],
    ]) {
      const select = byId(id), first = make("option", empty);
      first.value = "";
      const nodes = [first];
      if (wantGlobal && mapDefinitions.length) {
        const group = make("optgroup");
        group.label = "Imagery & 3D terrain";
        for (const def of mapDefinitions) {
          const option = make("option", def.label);
          option.value = `map:${def.id}`;
          group.append(option);
        }
        nodes.push(group);
      }
      for (const child of canonical.children) {
        if (child.tagName === "OPTION") {
          if (!wantGlobal && child.value) nodes.push(child.cloneNode(true));
        } else if ((child.id === "globalWeather") === wantGlobal) {
          const group = child.cloneNode(true);
          group.removeAttribute("id");
          nodes.push(group);
        }
      }
      const markup = nodes.map(node => node.outerHTML).join("");
      if (optionMarkup.get(id) !== markup) {
        select.replaceChildren(...nodes);
        optionMarkup.set(id, markup);
      }
      select.value = wantGlobal ? globalChoice() : (global ? "" : canonical.value);
    }
  }
  for (const id of ["globalLayer", "regionalLayer"]) {
    byId(id).addEventListener("change", () => {
      const value = byId(id).value;
      mapChoice = id === "globalLayer" && value.startsWith("map:") ? value : "";
      canonical.value = mapChoice ? "" : value;
      syncLayers();
      canonical.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  new MutationObserver(syncLayers).observe(canonical, {
    childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "hidden", "label"],
  });
  syncLayers();
  function setGlobalMaps(definitions) { mapDefinitions = definitions; syncLayers(); }
  function resetGlobalMap() { mapChoice = ""; syncLayers(); }

  const sourcesButton = byId("sourcesButton"), sources = byId("sourcesPanel");
  sourcesButton.addEventListener("click", () => {
    sources.hidden = !sources.hidden;
    sourcesButton.setAttribute("aria-expanded", String(!sources.hidden));
  });
  function syncKey() {
    byId("mapKey").hidden = !canonical.value && !byId("legendText").textContent && !byId("layerStatus").textContent;
  }
  for (const id of ["legendText", "layerStatus"]) {
    new MutationObserver(syncKey).observe(byId(id), { childList: true, subtree: true, characterData: true });
  }
  canonical.addEventListener("change", syncKey);

  function revealResults() {
    byId("missionResults").hidden = false;
    byId("missionResults").open = true;
  }
  function captureMissionSections() {
    return new Map([...byId("mResult").querySelectorAll("details[data-mission-section]")]
      .map(node => [node.id, node.open]));
  }
  function organizeMission(result, selected, previousState) {
    const out = byId("mResult"), newMission = out.dataset.missionId !== result.id;
    const state = newMission ? new Map() : previousState;
    const specs = [
      ["Your mission", "missionSettings", "Mission settings"],
      ["What to bring", "missionEquipment", "What to bring"],
      ["Why this plan", "missionWhy", "Why this plan"],
      ["Notes on the map", "missionNotes", "Notes on the map"],
      ["Decision matrix", "missionComparison", "Technical route comparison"],
      ["Compared with the previous plan", "missionPrevious", "Compare with previous plan"],
    ];
    const sections = new Map(), notices = [], routes = make("div");
    routes.id = "missionRoutes";
    let target = null;
    for (const node of [...out.children]) {
      if (node.tagName === "H3") {
        const spec = specs.find(([prefix]) => node.textContent.startsWith(prefix));
        if (spec) {
          const [, id, label] = spec, details = make("details");
          details.id = id;
          details.dataset.missionSection = "true";
          details.open = state.get(id) ?? false;
          if (node.classList.contains("adv")) details.className = "adv";
          details.append(make("summary", label));
          sections.set(id, details);
          target = details;
          continue;
        }
        target = routes;
        node.textContent = result.candidates.length ? "Routes (best match first)" : "No suitable routes";
      }
      if (node.dataset.missionNotice) notices.push(node);
      else (target || routes).append(node);
    }
    const summary = make("div");
    summary.className = "small";
    const chosen = result.candidates[selected];
    summary.textContent = chosen
      ? `Showing route #${chosen.rank} · ${chosen.route.distance_km} km · ${chosen.route.round_trip_h} h round trip. Open a route to compare or choose it.`
      : "Try another goal, vehicle or region.";
    out.replaceChildren(summary, ...notices, routes,
      ...["missionSettings", "missionEquipment", "missionWhy", "missionNotes", "missionComparison", "missionPrevious"]
        .map(id => sections.get(id)).filter(Boolean));
    out.dataset.missionId = result.id;
    byId("missionResults").hidden = false;
    if (newMission) revealResults();

    const credits = [...new Set(result.candidates.flatMap(c => c.resources.items.map(item => item.source)).filter(Boolean))];
    const list = make("ul");
    list.append(...credits.map(value => make("li", value)));
    byId("missionSources").replaceChildren(...(credits.length ? [make("h2", "Mission resource sources"), list] : []));
  }
  function mapCredits(definitions) {
    byId("mapSources").replaceChildren(...definitions.filter(def => def.credit).map(def =>
      make("li", `${def.title}: ${def.credit}`)));
  }
  function clearMission() {
    byId("missionResults").hidden = true;
    byId("missionResults").open = false;
    delete byId("mResult").dataset.missionId;
    byId("missionSources").replaceChildren();
  }
  return { syncLayers, globalChoice, setGlobalMaps, resetGlobalMap,
    captureMissionSections, organizeMission, revealResults, mapCredits, clearMission };
}
