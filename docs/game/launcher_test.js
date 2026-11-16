// Run with node docs/game/launcher_test.js. No DOM or third-party test package required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const launcherPath = process.argv[2] || path.join(__dirname, '../../frontend/game-launch.js');
const source = fs.readFileSync(launcherPath, 'utf8');
const plan = () => ({
  id: 'selected-plan', request_region: 'area_saved',
  settings: { goal: 'sample olivine', vehicle: {key:'on_foot'}, season:{key:'northern_autumn',ls:247.5}, priority:{key:'safety'},green_only:false },
  candidates:[{rank:1},{rank:2},{rank:3}], science_image:'image-science', offlimits_image:'image-offlimits',
  goal_ai:{reasoning:'goal reasoning',content:'goal content'}, explain_ai:{reasoning:'explain reasoning',content:'explain content'}
});
function host(options={}) {
  const saved=[], opened=[];
  const elements=options.kit ? {
    sheet:{},form:{},vehicle:{value:'pressurized_rover'},ls:{value:'247.5'},region:{value:'gale'},
    goals:{querySelectorAll(){return [{value:'geology'},{value:'biosignatures'},{value:'subsurface'},{value:'water_ice'}]}}
  } : {runMission:{},mResult:{},goal:{value:'changed draft'},mVehicle:{value:'buggy'},mPriority:{value:'science'},greenOnly:{checked:true},region:{value:'here'},ls:{value:'20'},hour:{value:'15'}};
  const window={localStorage:{setItem(key,value){
    if(options.storage==='blocked' || (options.storage==='images-full'&&value.includes('image-science')))throw Error('storage denied');
    saved.push({key,payload:JSON.parse(value)});
  }},open(...args){opened.push(args)}};
  const ctx=vm.createContext({window,document:{readyState:'loading',getElementById:id=>elements[id],addEventListener(){}},fixture:options.plan===undefined?plan():options.plan});
  vm.runInContext("let mission=fixture;let selected=2;function regionId(){return 'area_resolved';}",ctx);
  vm.runInContext(source,ctx);
  return {api:window.MarswalkGameLaunch,saved,opened,ctx,window};
}
const expected={goal:'sample olivine',vehicle:'on_foot',season:'northern_autumn',ls:247.5,priority:'safety',green_only:false};
function plain(value){return JSON.parse(JSON.stringify(value))}
{
  const h=host();const payload=plain(h.api.buildPayload());
  assert.deepEqual(payload.request,expected,'the selected plan must win over edited draft controls');
  assert.equal(payload.region,'area_saved');assert.equal(payload.selected,2);
  assert.equal(payload.mission.goal_ai,undefined);assert.equal(payload.ai.goal.content,'goal content');
  assert.equal(h.api.open(),'game.html?src=planner');
  assert.equal(h.saved[0].key,'marswalk.game.mission');assert.equal(h.saved[0].payload.mission.science_image,'image-science');
  assert.deepEqual(h.opened[0],['game.html?src=planner','_blank','noopener']);
  const original=h.api;vm.runInContext(source,h.ctx);assert.equal(h.window.MarswalkGameLaunch,original,'loading twice must not duplicate mounting');
}
{
  const p=plan();delete p.request_region;assert.equal(host({plan:p}).api.buildPayload().region,'area_resolved','anywhere resolves to a real region');
}
{
  const h=host({storage:'images-full'});assert.equal(h.api.open(),'game.html?src=planner');
  assert.equal(h.saved[0].payload.mission.science_image,undefined);assert.equal(h.saved[0].payload.selected,2);
}
{
  const h=host({storage:'blocked'});const q=new URL(h.api.open(),'http://mars.test/').searchParams;
  for(const [key,value] of Object.entries(expected))assert.equal(q.get(key),key==='green_only'?'0':String(value),key);
  assert.equal(q.get('region'),'area_saved');assert.equal(q.get('cand'),'2');
}
{
  const h=host({plan:null});assert.equal(h.api.buildPayload(),null);assert.equal(h.api.open(),'game.html');
}
for (const options of [{}, {plan:null}, {kit:true}, {storage:'blocked'}]) {
  const h=host(options);
  assert.equal(h.api.openCompetition(),'game.html?mode=competition');
  assert.deepEqual(h.opened[0],['game.html?mode=competition','_blank','noopener']);
  assert.equal(h.saved.length,0,'competition must not overwrite the existing planner mission');
}
{
  const h=host({kit:true});const p=plain(h.api.buildPayload());
  assert.equal(p.source,'kit');assert.equal(p.params.vehicle,'buggy');assert.equal(p.params.region,'gale');
  assert.equal(p.params.goal,'clay and olivine and water-bearing minerals');assert.equal(p.params.season,'northern_autumn');assert.equal(p.params.ls,247.5);
  assert.equal(new URL(h.api.open(),'http://mars.test/').searchParams.get('ls'),'247.5');
}
console.log('PASS: selected mission, resolved region, exact season, storage fallbacks, kit mapping, independent competition entry, and idempotent launcher');
