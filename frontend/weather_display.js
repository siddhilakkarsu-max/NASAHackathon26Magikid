"use strict";

const weatherDisplay = (() => {
  const layerNotes = {
    global_temperature: "Simulated ground temperature. Uncolored areas lack thermal inertia.",
    temperature: "Simulated ground temperature for this region. Uncolored areas lack thermal inertia.",
    openmars_surface_temperature: "OpenMARS ground temperature reference. Historical model output at 5°, for the selected hour and season.",
    air_temperature: "Air at the lowest OpenMARS model level. Historical estimate for the selected hour and season.",
    surface_pressure: "Atmospheric pressure at ground level. Historical estimate for the selected hour and season.",
    wind_speed: "Near-surface wind speed. Historical estimate for the selected hour and season.",
    wind_direction: "Arrowheads point toward modeled wind flow. Motion is sped up for display. The background shows wind speed.",
    dust_opacity: "Higher values mean more atmospheric dust opacity. Seasonal average at 9.3 µm, normalized to 610 Pa. This layer varies with season.",
    radiation_dose: "Pressure-based galactic cosmic ray (GCR) estimates. Not surface measurements or a current radiation forecast.",
    illumination: "0 means no direct light. 1 means sunlight hits the surface head-on.",
    slope: "Steeper slopes have higher values.",
    firmness: "Relative ground firmness inferred from nighttime infrared imagery. Higher values indicate firmer ground.",
    cost: "Estimated seconds needed to travel one meter.",
    shelter: "Estimated travel time to terrain flagged as potential cover.",
    elevation: "Surface height relative to the Mars reference datum.",
    imagery: "Grayscale CTX imagery.",
    suitability: "Safety, science value and radiation shielding combined. 0 = poor place to go, 1 = best. Green is better.",
    science: "Green marks where NASA's CRISM spectrometer detected at least one target mineral (clay, carbonate, olivine…).",
    minerals: "Each colour is a different CRISM mineral class (a kind of mineral, not an amount).
    thermal_inertia: "How slowly the ground heats and cools (THEMIS). High: rock or firm ground. Low: loose dust.",
    air_column_vs_gale: "Air overhead compared with Gale crater. More air blocks more cosmic radiation: above 1 is better shielded.",
    albedo: "How much sunlight the ground reflects. Bright: dust. Dark: sand or bare rock.",
  };
  const titles = {
    imagery: "CTX imagery", illumination: "Direct sunlight", slope: "Slope",
    firmness: "Ground firmness", cost: "Travel cost", shelter: "Time to cover",
    elevation: "Elevation", walkback: "Walk-back zone",
    suitability: "Mission suitability", science: "Science targets (CRISM minerals)",
    minerals: "Dominant mineral (CRISM class map)", thermal_inertia: "Thermal inertia",
    air_column_vs_gale: "Radiation shielding (air column)", albedo: "Albedo (brightness)",
  };
  const units = { elevation: "m", firmness: "", illumination: "", suitability: "", albedo: "",
                  thermal_inertia: "TIU", air_column_vs_gale: "× Gale" };
  // Layers whose numbers mean nothing on their own: words at the ends of the colour bar instead
  const tickWords = { science: ["", "target mineral found", ""], minerals: ["", "one colour per mineral class", ""],
                      suitability: ["worse", "", "better"] };
  const format = new Intl.NumberFormat("en", { maximumFractionDigits: 4 });

  function renderLegend({ bar, text, name, response, sources }) {
    text.replaceChildren();
    if (sources && sources !== text) sources.replaceChildren();
    const sourceTarget = sources ?? text;
    bar.style.background = "";
    bar.hidden = !response;
    if (!response) return;
    const { legend } = response;
    const unit = units[name] ?? legend.unit;
    const display = value => format.format(value) + (unit ? " " + unit : "");
    const title = document.createElement("strong");
    title.textContent = titles[name] ?? legend.name;
    const ticks = document.createElement("div");
    ticks.className = "legend-ticks";
    [legend.min, (legend.min + legend.max) / 2, legend.max].forEach((value, i) => {
      const tick = document.createElement("span");
      const words = tickWords[name];
      tick.textContent = !words ? display(value) : name === "suitability" && words[i] ? `${display(value)} ${words[i]}` : words[i];
      ticks.append(tick);
    });
    const detail = document.createElement("div");
    detail.className = "legend-note";
    detail.textContent = layerNotes[name] ?? "";
    text.append(ticks, title, detail);
    if ("temperature_range" in response || "data_range" in response) {
      const range = response.temperature_range ?? response.data_range;
      const values = document.createElement("div");
      values.textContent = range ? (response.viewport ? "View range " : "Map range ") +
        display(range[0]) + " to " + display(range[1]) : "No values for this selection.";
      text.append(values);
    }
    if (response.radiation) {
      const radiation = response.radiation;
      if (radiation.note) detail.textContent = radiation.note;
      const addNote = (parent, value) => {
        if (!value) return;
        const node = document.createElement("div");
        node.className = "legend-note";
        node.textContent = value;
        parent.append(node);
      };
      addNote(text, "Purple = lower dose · green = higher dose. µSv/h = microsieverts per hour (effective dose rate).");
      addNote(text, "GCR = galactic cosmic rays. Solar particle events and spacesuit shielding are not included.");
      if (Number.isFinite(radiation.coverage_percent)) {
        addNote(text, `${format.format(radiation.coverage_percent)}% of grid cells have estimates. Uncolored cells are N/A, not zero dose.`);
      }
      const assumptions = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Model assumptions and sources";
      assumptions.append(summary);
      addNote(assumptions, radiation.model_label);
      const bounds = radiation.valid_pressure_pa;
      if (bounds?.length === 2 && bounds.every(Number.isFinite)) {
        addNote(assumptions, `Modeled pressure range: ${format.format(bounds[0])}–${format.format(bounds[1])} Pa. Outside this range: N/A.`);
      }
      addNote(assumptions, radiation.dust_note);
      for (const limitation of radiation.limitations ?? []) addNote(assumptions, limitation);
      for (const { title, url } of radiation.sources ?? []) {
        const source = document.createElement("a");
        source.href = url;
        source.target = "_blank";
        source.rel = "noopener";
        source.textContent = title;
        assumptions.append(source);
      }
      sourceTarget.append(assumptions);
    } else if (response.weather || "temperature_range" in response) {
      const source = document.createElement("a");
      const thermal = "temperature_range" in response;
      source.href = thermal ? "https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html"
        : name === "dust_opacity" ? "https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/index.html"
        : "https://doi.org/10.57967/hf/8741";
      source.target = "_blank";
      source.rel = "noopener";
      source.textContent = thermal ? "NASA PDS TES thermal inertia"
        : name === "dust_opacity" ? "LMD dust climatology" : "OpenMARS · Mars Year 29";
      sourceTarget.append(source);
    }
    bar.style.background = "linear-gradient(90deg, " + legend.colors.join(", ") + ")";
  }

  async function renderWind(response) {
    if (!response.wind_vectors) return response.image;
    const image = new Image();
    image.src = response.image;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = 1440;
    canvas.height = 720;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const { lat, lon, east_ms: east, north_ms: north } of response.wind_vectors) {
      const speed = Math.hypot(east, north);
      if (speed <= 0) continue;
      const latScale = Math.cos(lat * Math.PI / 180);
      let dx = east / (speed * latScale);
      let dy = -north / speed;
      const length = 7 + Math.min(speed, 30) * 0.6;
      const scale = Math.min(length, 28 / Math.hypot(dx, dy));
      dx *= scale;
      dy *= scale;
      const angle = Math.atan2(dy, dx);
      const centerX = (lon + 180) * 4;
      const centerY = (90 - lat) * 4;
      for (const x of [centerX - canvas.width, centerX, centerX + canvas.width]) {
        if (x < -30 || x > canvas.width + 30) continue;
        const tipX = x + dx / 2, tipY = centerY + dy / 2;
        ctx.beginPath();
        ctx.moveTo(x - dx / 2, centerY - dy / 2);
        ctx.lineTo(tipX, tipY);
        const size = Math.min(6, Math.hypot(dx, dy) * 0.45);
        for (const side of [-0.57, 0.57]) {
          ctx.moveTo(tipX - size * Math.cos(angle + side), tipY - size * Math.sin(angle + side));
          ctx.lineTo(tipX, tipY);
        }
        ctx.strokeStyle = "#111421";
        ctx.lineWidth = 4;
        ctx.stroke();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.8;
        ctx.stroke();
      }
    }
    return canvas.toDataURL("image/png");
  }
  return { renderLegend, renderWind };
})();
