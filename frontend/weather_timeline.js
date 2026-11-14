"use strict";

function createWeatherTimeline({ calendar, controls, readSeason, showSol }) {
  const { group, start, end, position, play, message, readout, note } = controls;
  let generation = 0, playing = false, timer;
  const firstSol = calendar.sols[0], lastSol = calendar.sols.at(-1);
  for (const input of [start, end, position]) {
    input.min = firstSol;
    input.max = lastSol;
  }
  start.value = firstSol;
  end.value = lastSol;
  note.textContent = "One sol is one Martian day. This timeline shows seasonal estimates at the selected local hour.";

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

  function setEnabled(isGlobal) {
    stop();
    group.hidden = !isGlobal;
    if (isGlobal) sync();
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
  return { setEnabled, sync, stop };
}
