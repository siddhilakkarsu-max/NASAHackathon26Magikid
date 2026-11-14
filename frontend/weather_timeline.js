"use strict";

function createWeatherTimeline({ calendars, controls, readSeason, showSol }) {
  const { group, start, end, position, play, message, readout, note } = controls;
  let calendar = calendars.seasonal;
  let mode = "", generation = 0, playing = false, timer;

  function stop() {
    ++generation;
    clearTimeout(timer);
    playing = false;
    play.textContent = "Play timeline";
  }

  function findSol(ls) {
    let best = 0;
    for (let i = 1; i < calendar.ls.length; i++) {
      if (Math.abs(calendar.ls[i] - ls) < Math.abs(calendar.ls[best] - ls)) best = i;
    }
    return calendar.sols[best];
  }

  function season(sol) {
    return calendar.ls[sol - calendar.sols[0]];
  }

  function showPosition(sol, apply = false) {
    position.value = sol;
    readout.textContent = `Sol ${sol} · season ${season(sol).toFixed(1)}° Ls`;
    if (apply) return showSol(season(sol));
  }

  function sync() {
    if (group.hidden) return;
    const sol = findSol(readSeason());
    readout.textContent = `Sol ${sol} · season ${season(sol).toFixed(1)}° Ls`;
    position.value = sol;
  }

  function setLayer(name, isGlobal) {
    stop();
    group.hidden = !isGlobal;
    if (!isGlobal) return;
    const next = name === "storm_dust" ? "storm" : "seasonal";
    if (next === mode) { sync(); return; }
    mode = next;
    calendar = calendars[next];
    const first = calendar.sols[0], last = calendar.sols.at(-1);
    for (const input of [start, end, position]) {
      input.min = first;
      input.max = last;
    }
    start.value = next === "storm" ? findSol(180) : first;
    end.value = next === "storm" ? findSol(270) : last;
    note.textContent = next === "storm"
      ? "Historical Mars Year 34 archive. The preset dates cover the 2018 storm’s growth and fade."
      : "One sol is one Martian day. This replay shows seasonal estimates at the selected local hour.";
    message.textContent = "";
    sync();
  }

  async function run() {
    if (playing) { stop(); return; }
    const first = Number(start.value), last = Number(end.value);
    if (!start.checkValidity() || !end.checkValidity() || first >= last) {
      message.textContent = "Enter a start sol before the end sol, within the available year.";
      return;
    }
    const skip = Math.max(1, Math.ceil((last - first) / 32));
    message.textContent = skip > 1 ? `Playing every ${skip} sols. Scrub to view individual sols.` : "";
    playing = true;
    play.textContent = "Pause timeline";
    const runId = ++generation;
    async function step(sol) {
      const shown = await showPosition(sol, true);
      if (runId !== generation) return;
      if (shown === false || sol >= last) { stop(); return; }
      timer = setTimeout(() => step(Math.min(last, sol + skip)), 420);
    }
    await step(first);
  }

  play.addEventListener("click", run);
  position.addEventListener("input", () => {
    stop();
    showPosition(Number(position.value));
  });
  position.addEventListener("change", () => showPosition(Number(position.value), true));
  for (const input of [start, end]) input.addEventListener("input", stop);
  return { setLayer, sync, stop };
}
