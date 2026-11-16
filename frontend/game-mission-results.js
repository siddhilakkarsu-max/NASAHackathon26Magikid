/* Results for one surface objective. Prices are supplied by the player, never attributed to NASA. */
(function () {
  'use strict';
  if (window.MarswalkMissionResults) return;
  const STORE = 'marswalk.surface-cost.v1';
  const RATE_KEYS = ['hour', 'oxygen', 'energy'];
  const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  const rate = value => !['string', 'number'].includes(typeof value) || typeof value === 'string' && value.trim() === '' ? null :
    (Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 1e9 ? Number(value) : null);
  // BVAD 2022 Table 3-31: nominal intravehicular oxygen, averaged over an Earth day.
  // Reporting estimate only; this does not change the game's oxygen tank or drain.
  function cabinOxygenKg(missionElapsedS, crew = 1) {
    if (!finite(missionElapsedS) || !Number.isInteger(crew) || crew < 1) return null;
    const used = missionElapsedS / 86400 * 0.895 * crew;
    return Number.isFinite(used) ? used : null;
  }
  function cost(summary, rates) {
    const parsed = Object.fromEntries(RATE_KEYS.map(key => [key, rate(rates[key])]));
    if (RATE_KEYS.some(key => parsed[key] === null)) return {value: null, reason: 'Enter all three rates (0 to exclude a cost).'};
    const parts = [['hour', summary.missionElapsedS, 3600, 'surface operating time'],
      ['oxygen', summary.oxygenKg, 1, 'oxygen use'], ['energy', summary.energyWh, 1000, 'energy use']];
    let value = 0; const excluded = [], breakdown = {};
    for (const [key, quantity, divisor, label] of parts) {
      if (parsed[key] === 0) { excluded.push(label); breakdown[key] = 0; continue; }
      if (!finite(quantity)) return {value: null, reason: 'Complete cost unavailable: ' + label + ' is not modeled. A rate of 0 explicitly excludes it.'};
      breakdown[key] = quantity / divisor * parsed[key]; value += breakdown[key];
    }
    if (!Number.isFinite(value)) return {value: null, reason: 'These inputs exceed the cost calculator range.'};
    return {value, breakdown, excluded};
  }
  function duration(value) {
    if (!finite(value)) return 'Unavailable';
    const seconds = Math.round(value * 10) / 10;
    if (seconds < 60) return seconds.toFixed(1) + ' s';
    const whole = Math.round(seconds), hours = Math.floor(whole / 3600), minutes = Math.floor(whole % 3600 / 60), rest = whole % 60;
    return (hours ? hours + ' h ' : '') + minutes + ' min ' + rest + ' s';
  }
  const money = value => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(value);
  function element(tag, text, cls) {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function row(table, label, value, key) {
    const tr = element('tr'), th = element('th', label), td = element('td', value);
    th.scope = 'row'; if (key) td.dataset.result = key;
    tr.append(th, td); table.append(tr); return td;
  }
  function sources(summary) {
    const details = element('details'); details.append(element('summary', 'Sources and model assumptions'));
    details.append(element('p','AI times model an ideal driver following every designed route segment at its terrain-limited speed, without steering errors, reaction delays or random incidents. They are best-case model times, not measured autonomous NASA rover performance. Both drivers use the same physical speed envelope and gameplay time compression.'));
    const resourceNote = summary.oxygenBasis === 'cabin-estimate' ?
      'Electrical use is accumulated from the game simulation through sampling. Cabin oxygen is estimated from the mission clock and the NASA baseline below. These are model estimates, not measurements from a real Mars mission.' :
      'Resources are accumulated from the game simulation through sampling. Terrain, carried load, difficulty and hazards affect consumption; these are estimates, not measurements from a real Mars mission.';
    details.append(element('p', summary.resourceNote || resourceNote, 'small'));
    const list = element('ul', null, 'small');
    const add = (title, url, note) => {
      const li = element('li'), a = element('a', title); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      li.append(a, document.createTextNode(' — ' + note)); list.append(li);
    };
    if (summary.oxygenBasis === 'cabin-estimate') {
      add('NASA life-support baseline (2022), Table 3-31', 'https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf#page=72',
        'Nominal intravehicular oxygen is 0.895 kg per crewmember per 24-hour day, including daily exercise. This report applies that average to the simulated mission duration for ' + (summary.crewCount || 1) + ' crew. This is a cabin estimate, not a measured Mars traverse rate; no active suit-tank drain is simulated for the pressurized rover.');
    } else {
      add('NASA life-support baseline (2022), Table 4-70', 'https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf#page=149',
        'Typical EVA oxygen demand is 0.086 kg per crewmember-hour. The existing game uses a 0.114 kg/h baseline with gameplay and terrain adjustments; its total is not this NASA reference rate.');
    }
    if (summary.vehicleKey === 'buggy' || /pressurized/i.test(summary.vehicleLabel || '') && !/unpressurized|open/i.test(summary.vehicleLabel || '')) {
      add('NASA Mars surface-power study (2022), Table 1', 'https://ntrs.nasa.gov/citations/20210022250',
        'Concept rover: 5,193 kg, 60 kWh storage, 1.85 kW hotel load and rolling resistance 0.15. The game derives about 0.80 kWh/km on level Mars terrain, then applies its terrain and load model.');
    } else if (summary.vehicleKey === 'four_wheel' || /Apollo|open crew/i.test(summary.vehicleLabel || '')) {
      add('NASA Apollo 15 rover performance', 'https://history.nasa.gov/wp-content/uploads/static/history/alsj/WOTM/WOTM-LRVPerformance.html',
        'The game uses the observed 13 km/h level-ground maximum as its Apollo-class speed envelope. This is a lunar vehicle analogy, not a Mars rover measurement.');
      add('NASA Apollo Lunar Roving Vehicle', 'https://nssdc.gsfc.nasa.gov/planetary/lunar/apollo_lrv.html',
        'Two 36 V, 121 Ah batteries give 8.712 kWh nominal storage. The game adapts an Apollo-class vehicle to Mars; terrain penalties and its 0.095 kWh/km rate are model assumptions.');
    } else if (summary.vehicleKey === 'two_wheel') {
      list.append(element('li', 'Scout-bike power and driving loads are game engineering assumptions; no NASA vehicle specification is claimed.'));
    }
    if(summary.vehicleKey==='buggy')add('NASA Space Exploration Vehicle concept','https://science.nasa.gov/3d-resources/space-exploration-vehicle/','The pressurized rover model uses the SEV concept speed of about 10 km/h. Terrain reduces this speed.');
    details.append(list, element('p', 'Cost = simulated surface hours × your USD/hour + oxygen kg × your USD/kg + electrical kWh × your USD/kWh. Enter an hourly rate excluding oxygen and electricity to avoid double counting. This covers A to the objective and sampling only. Launches, transit, spacecraft purchase and a return journey are excluded. NASA sources inform physical quantities, not these user-supplied prices.', 'small'));
    return details;
  }
  function render(container, summary) {
    if (!container) return;
    container.replaceChildren(); container.classList.add('mission-results');
    if (!document.getElementById('missionResultsStyle')) {
      const style = element('style'); style.id = 'missionResultsStyle';
      style.textContent = '.mission-results .cost-rates{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}.mission-results .cost-rates label{display:flex;flex-direction:column;gap:5px;flex:1 1 145px;min-width:0}.mission-results .cost-rates input{width:100%;min-width:0;box-sizing:border-box}.mission-results .stat th{text-align:left;font-weight:400}.mission-results details{margin-top:12px}.mission-results li{margin:7px 0}.mission-results .stat{width:100%;table-layout:fixed}.mission-results td,.mission-results th{overflow-wrap:anywhere}.mission-results [data-cost-status]{min-height:1.4em}.mission-results .stat{font-size:clamp(20px,2vw,26px);line-height:1.45}.mission-results .stat th{width:62%;padding:14px 10px;color:#e9dfd4}.mission-results .stat td{padding:14px 10px;text-align:right;font-weight:650;font-variant-numeric:tabular-nums}.mission-results h3{font-size:25px}.mission-results summary{font-size:20px}.mission-results .small{font-size:16px;line-height:1.5}.mission-results .stat [data-cost-status]{font-size:20px}@media(max-width:600px){.mission-results .stat{font-size:20px}.mission-results .stat th{width:56%;padding:12px 4px}.mission-results .stat td{padding:12px 4px}.mission-results .stat [data-cost-status]{font-size:18px}}';
      document.head.append(style);
    }
    container.append(element('h3', 'Mission results'));
    const times = element('table', null, 'stat'); times.setAttribute('aria-label', 'Mission time comparison');
    row(times, 'Your total time', duration(summary.totalElapsedS), 'total-time');
    row(times, 'Your driving time', duration(summary.drivingElapsedS), 'driving-time');
    const comparison=summary.aiComparison;
    const aiTime=result=>result?.status==='complete'?duration(result.seconds):result?.status==='failed'?'Did not finish':comparison?.status==='failed'?'Unavailable':'AI driving…';
    row(times, 'AI on your route', aiTime(comparison?.own), 'player-model-time');
    row(times, 'AI on its own route', aiTime(comparison?.reference), 'reference-model-time');
    container.append(times, element('p', 'Driving times use the same gameplay clock and exclude sampling. Total time includes sampling. Pauses and menus are excluded.', 'small'));
    const resources = element('table', null, 'stat'); resources.setAttribute('aria-label', 'Surface mission resources');
    const oxygenLabel = summary.oxygenBasis === 'cabin-estimate' ? 'Oxygen used · cabin estimate (' + (summary.crewCount || 1) + ' crew)' : 'Oxygen used · game model';
    row(resources, oxygenLabel, finite(summary.oxygenKg) ? summary.oxygenKg.toFixed(3) + ' kg' : 'Not modeled for this vehicle', 'oxygen');
    row(resources, 'Electrical energy used · game model', finite(summary.energyWh) ? summary.energyWh.toFixed(1) + ' Wh' : 'Not modeled for this vehicle', 'energy');
    if (finite(summary.distanceM)) row(resources, 'Distance traveled · A → B', (summary.distanceM / 1000).toFixed(2) + ' km', 'distance');
    container.append(resources);
    const output = row(resources, 'Your cost', '', 'cost'); output.dataset.costStatus = ''; output.setAttribute('aria-live', 'polite');
    const settings = element('details'), controls = element('div', null, 'cost-rates'); settings.append(element('summary', 'Your cost model · USD'));
    settings.append(element('p', 'Set your rates to calculate an estimate. These are your assumptions, not NASA prices. Use 0 only for a cost you want to exclude.', 'small'));
    let saved = {}; try { saved = JSON.parse(localStorage.getItem(STORE) || '{}') || {}; } catch (_) {}
    const inputs = {};
    for (const [key, label] of [['hour', 'Operations · USD/hour'], ['oxygen', 'Oxygen · USD/kg'], ['energy', 'Electricity · USD/kWh']]) {
      const wrapper = element('label'), input = element('input'); input.type = 'number'; input.min = '0'; input.max = '1000000000'; input.step = 'any';
      input.inputMode = 'decimal'; input.placeholder = 'Enter rate'; input.id = 'missionCost-' + key; input.dataset.costRate = key;
      if (rate(saved[key]) !== null) input.value = String(saved[key]); wrapper.append(element('span', label, 'small'), input); controls.append(wrapper); inputs[key] = input;
    }
    const breakdown = element('p', null, 'small'); breakdown.dataset.costBreakdown = '';
    settings.append(controls, breakdown); container.append(settings, sources(summary));
    function update() {
      const values = Object.fromEntries(RATE_KEYS.map(key => [key, inputs[key].value]));
      const result = cost(summary, values);
      RATE_KEYS.forEach(key => inputs[key].setAttribute('aria-invalid', String(inputs[key].value !== '' && rate(inputs[key].value) === null)));
      output.textContent = result.value === null ? 'Set your cost model below' : money(result.value) + ' USD';
      breakdown.textContent = result.value === null ? result.reason : 'Operations ' + money(result.breakdown.hour) + ' + oxygen ' + money(result.breakdown.oxygen) + ' + electricity ' + money(result.breakdown.energy) + (result.excluded.length ? '. Excluded at your zero rate: ' + result.excluded.join(', ') + '.' : '.');
      try { localStorage.setItem(STORE, JSON.stringify(values)); } catch (_) {}
    }
    RATE_KEYS.forEach(key => inputs[key].addEventListener('input', update)); update();
  }
  window.MarswalkMissionResults = Object.freeze({render, cost, duration, cabinOxygenKg});
})();
