"use strict";

const weatherDisplay = (() => {
  const layerNotes = {
    global_temperature: "Simulated ground temperature. Native grid: 0.5°. Uncolored areas lack thermal inertia.",
    temperature: "Simulated ground temperature for this region. Native grid: 0.5°. Uncolored areas lack thermal inertia.",
    air_temperature: "Air at the lowest OpenMARS model level. Historical estimate for the selected hour and season.",
    surface_pressure: "Atmospheric pressure at ground level. Historical estimate for the selected hour and season.",
    wind_speed: "Near-surface wind speed. Historical estimate for the selected hour and season.",
    wind_direction: "Arrowheads point toward modeled wind flow. Motion is sped up for display. The background shows wind speed.",
    dust_opacity: "Higher values mean more atmospheric dust opacity. Seasonal average at 9.3 µm, normalized to 610 Pa. This layer varies with season.",
    storm_dust: "Reconstructed infrared dust opacity at 9.3 µm, normalized to 610 Pa. Cyan outlines mark high opacity. The color scale tops out at 3 τ.",
    illumination: "0 means no direct light. 1 means sunlight hits the surface head-on.",
    slope: "Steeper slopes have higher values.",
    firmness: "Relative ground firmness inferred from nighttime infrared imagery. Higher values indicate firmer ground.",
    cost: "Estimated seconds needed to travel one meter.",
    shelter: "Estimated travel time to terrain flagged as potential cover.",
    elevation: "Surface height relative to the Mars reference datum.",
    imagery: "Grayscale CTX imagery.",
  };
  const titles = {
    imagery: "CTX imagery", illumination: "Direct sunlight", slope: "Slope",
    firmness: "Ground firmness", cost: "Travel cost", shelter: "Time to cover",
    elevation: "Elevation", walkback: "Walk-back zone",
  };
  const units = { elevation: "m", firmness: "", illumination: "" };
  const format = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });

  function renderLegend({ bar, text, name, response }) {
    text.replaceChildren();
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
    for (const value of [legend.min, (legend.min + legend.max) / 2, legend.max]) {
      const tick = document.createElement("span");
      tick.textContent = display(value);
      ticks.append(tick);
    }
    const detail = document.createElement("div");
    detail.className = "legend-note";
    detail.textContent = layerNotes[name] ?? "";
    text.append(ticks, title, detail);
    if ("storm_threshold" in response) {
      const event = document.createElement("div");
      event.textContent = `Sol ${response.archive_sol} · ${response.archive_ls.toFixed(1)}° Ls. Cyan: τ ≥ ${response.storm_threshold}, covering ${response.storm_area_pct}% of Mars.`;
      text.append(event);
    }
    if ("temperature_range" in response || "data_range" in response) {
      const range = response.temperature_range ?? response.data_range;
      const values = document.createElement("div");
      values.textContent = range ? "Map range " + display(range[0]) + " to " + display(range[1]) : "No values for this selection.";
      text.append(values);
    }
    if (response.weather || "temperature_range" in response) {
      const source = document.createElement("a");
      const thermal = "temperature_range" in response;
      source.href = thermal ? "https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html"
        : name === "storm_dust" ? "https://www-mars.lmd.jussieu.fr/mars/dust_climatology/index.html"
        : name === "dust_opacity" ? "https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/index.html"
        : "https://doi.org/10.57967/hf/8741";
      source.target = "_blank";
      source.rel = "noopener";
      source.textContent = thermal ? "NASA PDS TES thermal inertia"
        : name === "storm_dust" ? "LMD / NASA MRO Mars Climate Sounder"
        : name === "dust_opacity" ? "LMD dust climatology" : "OpenMARS · Mars Year 29";
      text.append(source);
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
