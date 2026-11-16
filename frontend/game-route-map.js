/* Geographic route editing for the original Marswalk game. No replacement game/world. */
(function () {
  'use strict';
  if (window.MarswalkRouteMap) return;
  const DEG_M = Math.PI * 3396190 / 180, imageCache = new Map(), heightCache = new Map();
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const copy = route => route.map(p => ({lon: +p.lon, lat: +p.lat}));
  const bridge = () => window.__MW && window.__MW.mapBridge;
  const wrap = lon => ((lon + 180) % 360 + 360) % 360 - 180;
  const finitePoint = p => p && Number.isFinite(+p.lon) && Number.isFinite(+p.lat) && Math.abs(+p.lat) <= 90;
  function routeOf(c) {
    return [c.A].concat(c.route.points || [], [c.B]).filter(finitePoint).map(p => ({lon:+p.lon,lat:+p.lat})).filter((p,i,a) => !i || Math.abs(p.lon-a[i-1].lon)+Math.abs(p.lat-a[i-1].lat)>1e-9);
  }
  function unwrapRoute(route) {
    const r = copy(route);
    for (let i=1;i<r.length;i++) r[i].lon += 360*Math.round((r[i-1].lon-r[i].lon)/360);
    return r;
  }
  function fitRect(route, w, h) {
    const r = unwrapRoute(route), lons = r.map(p=>p.lon), lats=r.map(p=>p.lat);
    const lon=(Math.min(...lons)+Math.max(...lons))/2, lat=(Math.min(...lats)+Math.max(...lats))/2;
    const cos=Math.max(.05,Math.cos(lat*Math.PI/180));
    // CTX is natively about 5 m/pixel: show surrounding terrain instead of
    // stretching a short traverse into an apparently blurry satellite image.
    let dx=Math.max(Math.max(1200,w*3.5)/DEG_M/cos,(Math.max(...lons)-Math.min(...lons))*1.4),dy=Math.max(Math.max(800,h*3.5)/DEG_M,(Math.max(...lats)-Math.min(...lats))*1.4);
    dx=Math.max(dx,dy*w/h/cos); dy=Math.max(dy,dx*h/w*cos);
    return {west:lon-dx/2,east:lon+dx/2,south:clamp(lat-dy/2,-89.9,89.9),north:clamp(lat+dy/2,-89.9,89.9)};
  }
  function xy(p,rect,w,h) {
    const lon=+p.lon+360*Math.round(((rect.west+rect.east)/2-p.lon)/360);
    return [(lon-rect.west)/(rect.east-rect.west)*w,(rect.north-p.lat)/(rect.north-rect.south)*h];
  }
  function ll(x,y,rect,w,h) { return {lon:rect.west+x/w*(rect.east-rect.west),lat:rect.north-y/h*(rect.north-rect.south)}; }
  function tilesFor(rect,w,max,min) {
    let z=clamp(Math.ceil(Math.log2(180*w/512/(rect.east-rect.west))),min,max);
    let result;
    do {
      const size=180/2**z, nx=2**(z+1), ny=2**z;
      const x0=Math.floor((rect.west+180)/size), x1=Math.floor((rect.east+180-1e-10)/size);
      const y0=clamp(Math.floor((90-rect.north)/size),0,ny-1), y1=clamp(Math.floor((90-rect.south-1e-10)/size),0,ny-1);
      result=[];
      for(let y=y0;y<=y1;y++) for(let x=x0;x<=x1;x++) result.push({z,x:((x%nx)+nx)%nx,y,west:-180+x*size,east:-180+(x+1)*size,north:90-y*size,south:90-(y+1)*size});
      if(result.length<=16 || z===min) break;
      z--;
    } while(z>=min);
    return result;
  }
  async function fetchTimed(url, ms) {
    const ctl=new AbortController(), timer=setTimeout(()=>ctl.abort(),ms||25000);
    try { const r=await fetch(url,{signal:ctl.signal}); if(!r.ok) throw Error('Map service unavailable'); return r; }
    finally {clearTimeout(timer);}
  }
  function trimCache(cache,limit) { if(cache.size>limit) for(const [k,v] of cache) {if(!v.pending){cache.delete(k);break;}} }
  function tileImage(tile,onReady) {
    const key=[tile.z,tile.y,tile.x].join('/');
    let entry=imageCache.get(key);
    if(entry && entry.failed && Date.now()-entry.failed>30000) {imageCache.delete(key);entry=null;}
    if(!entry) {
      entry={pending:true,listeners:new Set()}; imageCache.set(key,entry);
      fetchTimed('/murray/ctx/'+key,25000).then(async response=>{
        const blob=await response.blob(), src=URL.createObjectURL(blob), im=new Image();
        try {await new Promise((resolve,reject)=>{im.onload=resolve;im.onerror=reject;im.src=src;}); entry.image=im;entry.level=Number(response.headers.get('X-Imagery-Fallback-Level')||tile.z);}
        finally {URL.revokeObjectURL(src);}
      }).catch(()=>{entry.failed=Date.now();}).finally(()=>{entry.pending=false;for(const cb of entry.listeners) cb();entry.listeners.clear();trimCache(imageCache,80);});
    }
    if(entry.pending && onReady) entry.listeners.add(onReady);
    return entry;
  }
  // Paint cached tiles synchronously; caller redraws its route when onReady fires.
  function paintImagery(ctx,rect,onReady) {
    const w=ctx.canvas.width,h=ctx.canvas.height,tiles=tilesFor(rect,w,12,0);
    let ready=0,failed=0,coarse=false;
    for(const tile of tiles) {
      const e=tileImage(tile,onReady), [x,y]=xy({lon:tile.west,lat:tile.north},rect,w,h), [x1,y1]=xy({lon:tile.east,lat:tile.south},rect,w,h);
      if(e.image) {ctx.drawImage(e.image,x-.25,y-.25,x1-x+.5,y1-y+.5);ready++;coarse=coarse||e.level<tile.z;}
      else if(e.failed) failed++;
    }
    return {ready,total:tiles.length,failed,coarse};
  }
  function imageInRect(ctx,image,source,rect) {
    if(!image || !source) return;
    const a=xy({lon:source.west,lat:source.north},rect,ctx.canvas.width,ctx.canvas.height), b=xy({lon:source.east,lat:source.south},rect,ctx.canvas.width,ctx.canvas.height);
    ctx.drawImage(image,a[0],a[1],b[0]-a[0],b[1]-a[1]);
  }
  function line(ctx,route,rect,color,width,dash) {
    if(!route.length) return;
    ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineJoin='round';ctx.lineCap='round';ctx.setLineDash(dash||[]);ctx.beginPath();
    route.forEach((p,i)=>{const a=xy(p,rect,ctx.canvas.width,ctx.canvas.height);if(i)ctx.lineTo(...a);else ctx.moveTo(...a);});ctx.stroke();ctx.setLineDash([]);
  }
  function dot(ctx,p,rect,label,color,radius) {
    const [x,y]=xy(p,rect,ctx.canvas.width,ctx.canvas.height);
    ctx.beginPath();ctx.arc(x,y,radius||6,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.lineWidth=2;ctx.strokeStyle='#17201f';ctx.stroke();
    if(label){ctx.font='600 13px system-ui';ctx.textBaseline='middle';const tw=ctx.measureText(label).width, tx=clamp(x+11,5,ctx.canvas.width-tw-12),ty=clamp(y+(label==='You'?19:-13),12,ctx.canvas.height-15);ctx.fillStyle='rgba(10,17,20,.8)';ctx.fillRect(tx-4,ty-10,tw+8,20);ctx.fillStyle='#fff';ctx.fillText(label,tx,ty);}
  }
  const previews=new WeakMap();
  function render(canvas, options) {
    if(!canvas || !options || !(options.route||[]).length) return;
    previews.set(canvas,options);
    const opts=options,ctx=canvas.getContext('2d'),rect=opts.rect||fitRect(opts.route,canvas.width,canvas.height);
    ctx.fillStyle='#292926';ctx.fillRect(0,0,canvas.width,canvas.height);imageInRect(ctx,opts.imagery,opts.imageryRect,rect);
    paintImagery(ctx,rect,()=>{if(previews.get(canvas)===opts)render(canvas,opts);});
    line(ctx,opts.route,rect,'#182221',6);line(ctx,opts.route,rect,'#ffd08b',3);
    dot(ctx,opts.route[0],rect,'A','#a5d7ff',6);dot(ctx,opts.route[opts.route.length-1],rect,'B','#ffc46e',6);
    if(opts.player)dot(ctx,opts.player,rect,'You','#fff',6);
    return rect;
  }
  let dialog,canvas,status,sourceInfo,removeButton,undoButton,applyButton,reliefControl,layerButtons,materialLegend,resizeObserver;
  let state=null,previousFocus=null,drawQueued=false;
  function scheduleDraw() {if(!drawQueued){drawQueued=true;requestAnimationFrame(()=>{drawQueued=false;if(state&&dialog.open)draw();});}}
  function makeUI() {
    if(dialog)return;
    const style=document.createElement('style');style.textContent=`
      #routeMapDialog{box-sizing:border-box;width:min(940px,calc(100vw - 40px));max-width:none;max-height:min(780px,88dvh);padding:0;border:1px solid #61574e;border-radius:18px;background:#181b1b;color:#f4ede5;box-shadow:0 24px 100px #0008;overflow:auto;font:14px system-ui,sans-serif}
      #routeMapDialog::backdrop{background:#0008;backdrop-filter:blur(3px)}
      #routeMapDialog header,#routeMapDialog footer{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:16px 20px}#routeMapDialog h2{font-size:22px;line-height:1.2;margin:0}#routeMapDialog p{margin:5px 0 0;color:#bdc5c2;font-size:13px;line-height:1.4}
      #routeMapDialog button{font:600 13px system-ui;line-height:1.2;background:#303736;color:inherit;border:1px solid #56615d;border-radius:8px;padding:10px 13px;min-height:38px;white-space:nowrap}#routeMapDialog button:disabled{opacity:.4;cursor:default}#routeMapDialog button[aria-pressed=true]{background:#f4bf85;color:#211b16;border-color:#f4bf85}#routeMapDialog .rm-primary{background:#e77535;border-color:#e77535;color:#fff}#routeMapDialog button:focus-visible,#routeMapDialog canvas:focus-visible,#routeMapDialog input:focus-visible{outline:3px solid #c6f4e5;outline-offset:2px}
      #routeMapDialog .rm-tools{padding:0 20px 12px;display:flex;gap:7px;flex-wrap:wrap;align-items:center}#routeMapDialog .rm-gap{flex:1}#routeMapDialog .rm-relief{display:flex;align-items:center;gap:7px;font-size:12px}#routeMapDialog .rm-relief[hidden]{display:none}#routeMapDialog input{width:80px;accent-color:#f4bf85}
      #routeMapCanvas{width:100%;height:clamp(230px,47dvh,430px);display:block;background:#2c2d28;cursor:grab;touch-action:none}#routeMapDialog .rm-canvas-wrap{margin:0 20px;border:1px solid #4a5451;border-radius:11px;overflow:hidden;position:relative}#routeMapDialog .rm-legend{position:absolute;left:10px;bottom:10px;display:flex;gap:14px;pointer-events:none;background:#101b1bce;padding:7px 10px;border-radius:6px;font-size:11px}.rm-legend span:first-child{color:#ffd08b}.rm-legend span:last-child{color:#97e2d8}
      #routeMapDialog .rm-meta{padding:9px 20px 0;font-size:12px;color:#b7c2bc}#routeMapDialog .rm-meta summary{cursor:pointer}#routeMapDialog .rm-meta p{font-size:12px}#routeMapDialog .rm-meta a{color:#bbdfdf}#routeMapDialog footer{border-top:1px solid #39423f;margin-top:12px}#routeMapDialog #routeMapStatus{font-size:12px;max-width:65%;line-height:1.4;color:#d7dfda}#routeMapDialog .rm-actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
      #routeMapDialog .rm-material-key{display:flex;flex-wrap:wrap;gap:6px 14px;padding:9px 20px 0;font-size:12px;color:#d7dfda}#routeMapDialog .rm-material-key[hidden]{display:none}#routeMapDialog .rm-material-key span{display:inline-flex;align-items:center;gap:5px}#routeMapDialog .rm-material-key i{display:inline-block;width:13px;height:13px;border:1px solid #b9bdbb;border-radius:3px}
      @media(max-width:600px){#routeMapDialog{width:calc(100vw - 24px);max-height:90dvh;border-radius:12px}#routeMapDialog header,#routeMapDialog footer{padding:12px}#routeMapDialog .rm-tools{padding:0 12px 10px}#routeMapDialog .rm-canvas-wrap{margin:0 12px}#routeMapDialog .rm-meta{padding:8px 12px 0}#routeMapDialog h2{font-size:19px}#routeMapDialog footer{align-items:flex-start;flex-direction:column}#routeMapDialog #routeMapStatus{max-width:100%}#routeMapDialog .rm-actions{width:100%}#routeMapDialog button{padding:9px 10px}}
    `;document.head.append(style);
    dialog=document.createElement('dialog');dialog.id='routeMapDialog';dialog.setAttribute('aria-labelledby','routeMapTitle');
    dialog.innerHTML=`<header><div><h2 id="routeMapTitle">Your route</h2><p>Drag a point. Click the route to add one. Drag the map to explore.</p></div><button type="button" data-action="close" aria-label="Close route map">✕</button></header>
      <div class="rm-tools"><button type="button" data-layer="imagery" aria-pressed="true">Satellite</button><button type="button" data-layer="topography" aria-pressed="false">Topography</button><button type="button" data-layer="slope" aria-pressed="false">Slope</button><button type="button" data-layer="firmness" aria-pressed="false">Ground firmness</button><label class="rm-relief" hidden>Relief <input id="routeMapRelief" aria-label="Visual relief exaggeration" type="range" min="1" max="8" step=".5" value="3"><output>3×</output></label><span class="rm-gap"></span><button type="button" data-action="fit">Fit route</button><button type="button" data-action="out" aria-label="Zoom out">−</button><button type="button" data-action="in" aria-label="Zoom in">+</button></div>
      <div class="rm-canvas-wrap"><canvas id="routeMapCanvas" width="900" height="430" tabindex="0" aria-label="Top-down Mars route map. Drag interior route points; endpoints stay fixed. Use arrow keys to move a selected point; Delete removes it."></canvas><div class="rm-legend"><span>━ Your route</span><span>┄ Original plan</span></div></div>
      <div id="routeMapMaterialLegend" class="rm-material-key" hidden aria-label="Estimated ground firmness legend"><strong>Estimated ground</strong><span><i style="background:#e0a763"></i>Soft dust / sand</span><span><i style="background:#b8c68b"></i>Coarse / crusted</span><span><i style="background:#79b9c1"></i>Rock-like</span><span><i style="background:repeating-linear-gradient(135deg,#485052 0 3px,#798082 3px 5px)"></i>Unknown</span></div>
      <div class="rm-tools" style="padding-top:10px;padding-bottom:0"><button type="button" data-action="undo" disabled>Undo</button><button type="button" data-action="remove" disabled>Remove point</button><button type="button" data-action="reset">Reset route</button></div>
      <details class="rm-meta"><summary>Map sources</summary><p id="routeMapSource">Satellite: NASA/JPL/MSSS · <a href="https://murray-lab.caltech.edu/CTX/" target="_blank" rel="noopener">Caltech Murray Lab CTX mosaic</a>, up to 5 m/pixel. Relief is visually exaggerated; route calculations use the original heights.</p></details>
      <footer><span id="routeMapStatus" role="status" aria-live="polite">Driving paused.</span><div class="rm-actions"><button type="button" data-action="close">Back to rover</button><button type="button" data-action="apply" class="rm-primary">Use route</button></div></footer>`;
    document.body.append(dialog);canvas=dialog.querySelector('canvas');status=dialog.querySelector('#routeMapStatus');sourceInfo=dialog.querySelector('#routeMapSource');
    removeButton=dialog.querySelector('[data-action="remove"]');undoButton=dialog.querySelector('[data-action="undo"]');applyButton=dialog.querySelector('[data-action="apply"]');reliefControl=dialog.querySelector('.rm-relief');materialLegend=dialog.querySelector('#routeMapMaterialLegend');layerButtons=[...dialog.querySelectorAll('[data-layer]')];
    dialog.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;if(button.dataset.layer){state.layer=button.dataset.layer;layerButtons.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));reliefControl.hidden=state.layer!=='topography';materialLegend.hidden=state.layer!=='firmness';state.reliefImage=null;scheduleDraw();if(state.layer==='firmness')loadMaterials();else if(state.layer!=='imagery')loadHeights();return;}action(button.dataset.action);});
    dialog.querySelector('input').addEventListener('input',event=>{state.exaggeration=+event.target.value;event.target.nextElementSibling.value=state.exaggeration+'×';state.reliefImage=null;scheduleDraw();});
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    dialog.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close();}event.stopPropagation();});
    canvas.addEventListener('pointerdown',pointerDown);canvas.addEventListener('pointermove',pointerMove);canvas.addEventListener('pointerup',pointerUp);canvas.addEventListener('pointercancel',pointerUp);
    canvas.addEventListener('wheel',event=>{event.preventDefault();zoom(Math.exp(event.deltaY*.001),event.offsetX/canvas.clientWidth,event.offsetY/canvas.clientHeight);},{passive:false});
    canvas.addEventListener('keydown',event=>{if(!state || state.busy || state.selected<1 || state.selected>=state.route.length-1)return;if(event.key==='Delete'||event.key==='Backspace'){event.preventDefault();action('remove');}else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();remember();const p=state.route[state.selected],d=event.shiftKey?20:5;if(event.key==='ArrowLeft')p.lon-=d/canvas.width*(state.rect.east-state.rect.west);if(event.key==='ArrowRight')p.lon+=d/canvas.width*(state.rect.east-state.rect.west);if(event.key==='ArrowUp')p.lat+=d/canvas.height*(state.rect.north-state.rect.south);if(event.key==='ArrowDown')p.lat-=d/canvas.height*(state.rect.north-state.rect.south);changed();}});
    resizeObserver=new ResizeObserver(()=>{if(state&&dialog.open){const b=canvas.getBoundingClientRect(),width=Math.round(b.width),height=Math.round(b.height);if(width&&height&&(canvas.width!==width||canvas.height!==height)){canvas.width=width;canvas.height=height;state.rect=fitRect(state.route,width,height);state.reliefImage=null;scheduleDraw();loadHeights();}}});resizeObserver.observe(canvas);
  }
  function open() {
    if(state&&state.busy)return false;
    const b=bridge(),context=b&&b.getContext();if(!context||!context.C)return false;
    makeUI();previousFocus=document.activeElement;b.pauseForMap();
    const route=unwrapRoute(routeOf(context.C)),reference=unwrapRoute(context.referenceRoute&&context.referenceRoute.length?context.referenceRoute:route);
    state={context,route,reference,initial:JSON.stringify(route),rect:fitRect(route,canvas.width,canvas.height),layer:'imagery',selected:-1,history:[],exaggeration:3,heights:[],material:null,materialBusy:false,materialTried:false,reliefImage:null,terrainBusy:false,loadingPlan:false,loadVersion:0,busy:false};
    layerButtons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.layer==='imagery')));reliefControl.hidden=true;materialLegend.hidden=true;dialog.querySelector('input').value=3;dialog.querySelector('output').value='3×';
    status.textContent='Driving paused. Your start and destination stay fixed.';applyButton.disabled=false;applyButton.textContent='Use route';dialog.showModal();canvas.focus();scheduleDraw();loadPlanHeights();return true;
  }
  function close(committedState) {if(!dialog||!dialog.open||(state&&state.busy&&committedState!==state))return;dialog.close();const b=bridge();if(b&&b.closeMap)b.closeMap();if(previousFocus&&previousFocus.isConnected)previousFocus.focus();}
  function setBusy(value){state.busy=value;dialog.setAttribute('aria-busy',String(value));dialog.querySelectorAll('button,input').forEach(el=>{el.disabled=value;});if(!value)scheduleDraw();}
  function remember(){state.history.push(copy(state.route));if(state.history.length>30)state.history.shift();}
  function changed(){state.dirty=JSON.stringify(state.route)!==state.initial;status.textContent=state.dirty?'Using an edited route restarts this run at the start.':'Driving paused.';scheduleDraw();}
  async function action(name){
    if(!state||state.busy)return;
    if(name==='close'){close();return;}
    if(name==='fit'){state.rect=fitRect(state.route,canvas.width,canvas.height);state.reliefImage=null;loadHeights();scheduleDraw();return;}
    if(name==='in'||name==='out'){zoom(name==='in'?.75:1.35,.5,.5);return;}
    if(name==='undo'&&state.history.length){state.route=state.history.pop();state.selected=-1;changed();return;}
    if(name==='remove'&&state.selected>0&&state.selected<state.route.length-1){remember();state.route.splice(state.selected,1);state.selected=-1;changed();return;}
    if(name==='reset'){remember();state.route=copy(state.reference);state.selected=-1;changed();return;}
    if(name==='apply'){
      if(!state.dirty){close();return;}
      const submitted=state;setBusy(true);applyButton.textContent='Checking route…';status.textContent='Checking the edited route against the mission terrain…';
      try{const result=await bridge().applyRoute(submitted.route.map(p=>({lon:wrap(p.lon),lat:p.lat})));if(result&&result.ok===false)throw Error(result.reason||result.message||'This route cannot be used.');if(state===submitted)close(submitted);}
      catch(error){if(state===submitted)status.textContent=error.message||'Route could not be checked. Try again.';}
      finally{if(state===submitted){setBusy(false);applyButton.textContent='Use route';}}
    }
  }
  function zoom(factor,x,y){if(!state||state.busy)return;const r=state.rect,dx=clamp((r.east-r.west)*factor,.001,25),dy=dx*(r.north-r.south)/(r.east-r.west),p=ll(x,y,r,1,1);state.rect={west:p.lon-dx*x,east:p.lon+dx*(1-x),north:clamp(p.lat+dy*y,-89.9,89.9),south:clamp(p.lat-dy*(1-y),-89.9,89.9)};state.reliefImage=null;loadHeights();scheduleDraw();}
  function mouse(event){const b=canvas.getBoundingClientRect();return [(event.clientX-b.left)*canvas.width/b.width,(event.clientY-b.top)*canvas.height/b.height];}
  function nearest(x,y){let best=-1,dist=17;state.route.forEach((p,i)=>{const a=xy(p,state.rect,canvas.width,canvas.height),d=Math.hypot(x-a[0],y-a[1]);if(d<dist){best=i;dist=d;}});return best;}
  function nearestSegment(x,y){let best=-1,dist=12,point=null;for(let i=1;i<state.route.length;i++){const a=xy(state.route[i-1],state.rect,canvas.width,canvas.height),b=xy(state.route[i],state.rect,canvas.width,canvas.height),dx=b[0]-a[0],dy=b[1]-a[1],t=clamp(((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy||1),0,1),px=a[0]+t*dx,py=a[1]+t*dy,d=Math.hypot(x-px,y-py);if(d<dist){best=i;dist=d;point=ll(px,py,state.rect,canvas.width,canvas.height);}}return {index:best,point};}
  function pointerDown(event){if(!state||state.busy||event.button>0)return;event.preventDefault();canvas.focus();const [x,y]=mouse(event),i=nearest(x,y);state.selected=i;
    if(i===0||i===state.route.length-1){status.textContent='The start and destination stay fixed.';scheduleDraw();return;}
    const segment=i<0?nearestSegment(x,y):null;
    if(i>0){remember();state.drag={type:'point',index:i};}
    else if(segment.index>0&&state.route.length<250){remember();state.route.splice(segment.index,0,segment.point);state.selected=segment.index;state.drag={type:'point',index:segment.index};changed();}
    else state.drag={type:'pan',x,y,rect:{...state.rect}};
    canvas.setPointerCapture(event.pointerId);canvas.style.cursor=state.drag.type==='pan'?'grabbing':'crosshair';scheduleDraw();
  }
  function pointerMove(event){if(!state||!state.drag||state.busy)return;const [x,y]=mouse(event),d=state.drag;
    if(d.type==='point'){state.route[d.index]=ll(clamp(x,0,canvas.width),clamp(y,0,canvas.height),state.rect,canvas.width,canvas.height);changed();}
    else{const dx=(x-d.x)/canvas.width*(d.rect.east-d.rect.west),dy=(y-d.y)/canvas.height*(d.rect.north-d.rect.south);state.rect={west:d.rect.west-dx,east:d.rect.east-dx,north:clamp(d.rect.north+dy,-89.9,89.9),south:clamp(d.rect.south+dy,-89.9,89.9)};state.reliefImage=null;scheduleDraw();}
  }
  function pointerUp(){if(!state)return;state.drag=null;canvas.style.cursor='grab';if(state.layer!=='imagery')loadHeights();}
  function normalizeGrid(terrain){
    if(!terrain||!terrain.grid||!terrain.rect)return null;const g=terrain.grid,a=g.elevation_m;
    if(!a||!a.length)return null;const nested=Array.isArray(a[0]),height=g.height||(nested?a.length:0),width=g.width||(nested?a[0].length:0);if(width<2||height<2)return null;
    const values=nested?a.flat():a,mask=g.valid?(Array.isArray(g.valid[0])?g.valid.flat():g.valid):null;
    const resolution=g.source_resolution_m||terrain.source_resolution_m||g.resolution_m;
    return {rect:terrain.rect,width,height,values:Float32Array.from(values,(v,i)=>v===null||(mask&&!mask[i])?NaN:+v),resolution:Array.isArray(resolution)?Math.max(...resolution):resolution,source:'Mission elevation data'};
  }
  function normalizeMaterial(terrain){
    const g=terrain&&terrain.grid,a=g&&g.thermal_inertia,r=terrain&&terrain.rect;
    if(!a||!a.length||!r||!(r.east>r.west)||!(r.north>r.south))return null;
    const nested=Array.isArray(a[0]),height=g.height||(nested?a.length:g.shape&&g.shape[0]),width=g.width||(nested?a[0].length:g.shape&&g.shape[1]);
    if(!(width>1&&height>1))return null;
    const raw=nested?a.flat():a,firm=g.firmness?(Array.isArray(g.firmness[0])?g.firmness.flat():g.firmness):null;
    // Passability is not a material-data mask: deep dust and steep rocks are
    // useful observations even when the route validator prohibits driving there.
    const values=Float32Array.from(raw,v=>v!==null&&Number.isFinite(+v)&&+v>0?+v:NaN);
    if(values.length!==width*height)return null;
    return {rect:r,width,height,values,firmness:firm&&firm.length===values.length?Float32Array.from(firm,v=>v!==null&&Number.isFinite(+v)?clamp(+v,0,1):NaN):null,
      resolution:terrain.display_resolution_m||g.resolution_m||terrain.source_resolution_m,
      sources:terrain.sources||[],note:terrain.material_note||'Thermal inertia is a surface-material estimate, not measured traction.'};
  }
  async function loadPlanHeights(){const s=state;if(!s||s.loadingPlan||!s.context.N)return;s.loadingPlan=true;
    try{const data=s.context.planData||await(await fetchTimed('/api/game/plans/'+encodeURIComponent(s.context.N.id)+'?candidate='+(s.context.W?s.context.W.ci:(s.context.N.selected||0)),15000)).json(),grid=normalizeGrid(data.terrain);if(state!==s)return;s.material=normalizeMaterial(data.terrain);if(grid){s.heights.unshift(grid);s.heights.sort((a,b)=>(a.priority??1)-(b.priority??1));s.planHeights=true;}s.reliefImage=null;scheduleDraw();}
    catch(_){}finally{if(state===s){s.loadingPlan=false;if(s.layer==='firmness')loadMaterials();else if(s.layer!=='imagery')loadHeights();}}
  }
  async function loadMaterials(){const s=state;if(!s||s.material||s.materialBusy||s.loadingPlan||s.materialTried)return;
    const region=s.context.region||s.context.N&&s.context.N.region;if(!region)return;s.materialBusy=true;s.materialTried=true;scheduleDraw();
    try{const result=await(await fetchTimed('/api/game/materials?region='+encodeURIComponent(region),15000)).json();if(state!==s)return;s.material=normalizeMaterial(result.terrain);s.reliefImage=null;}
    catch(_){}finally{if(state===s){s.materialBusy=false;scheduleDraw();}}
  }
  function heightTile(tile){const key=[tile.z,tile.y,tile.x].join('/');let e=heightCache.get(key);if(e&&e.failed&&Date.now()-e.failed>30000){heightCache.delete(key);e=null;}if(!e){e={pending:true};heightCache.set(key,e);e.promise=fetchTimed('/terrain/detail/'+key+'.bin',45000).then(async r=>{const n=+(r.headers.get('X-Terrain-Grid-Size')||257),a=new Float32Array(await r.arrayBuffer());if(a.length!==n*n)throw Error('Unexpected elevation grid');const global=r.headers.get('X-Terrain-Detail-Status')==='global-fallback';e.grid={rect:tile,width:n,height:n,values:a,source:global?'MOLA/HRSC global elevation (~200 m)':'CTX / HRSC elevation (global data in coverage gaps)',priority:global?2:0,resolution:null};}).catch(()=>{e.failed=Date.now();}).finally(()=>{e.pending=false;trimCache(heightCache,36);});}return e;}
  async function loadHeights(){const s=state;if(!s||s.layer==='imagery')return;if(s.layer==='firmness'){loadMaterials();return;}const version=++s.loadVersion;
    s.terrainBusy=true;
    const tiles=tilesFor(s.rect,canvas.width,11,8);if(tiles.length>16){s.terrainBusy=false;scheduleDraw();return;}
    const entries=tiles.map(heightTile);await Promise.allSettled(entries.map(e=>e.promise));if(state!==s||version!==s.loadVersion)return;
    s.heights=s.heights.filter(g=>g.source==='Mission elevation data').concat(entries.filter(e=>e.grid).map(e=>e.grid)).sort((a,b)=>(a.priority??1)-(b.priority??1));s.terrainBusy=false;s.reliefImage=null;scheduleDraw();
  }
  function sampleHeight(lon,lat){for(const g of state.heights){const r=g.rect,l=lon+360*Math.round(((r.west+r.east)/2-lon)/360);if(l<r.west||l>r.east||lat<r.south||lat>r.north)continue;const x=(l-r.west)/(r.east-r.west)*(g.width-1),y=(r.north-lat)/(r.north-r.south)*(g.height-1),ix=clamp(Math.floor(x),0,g.width-2),iy=clamp(Math.floor(y),0,g.height-2),tx=x-ix,ty=y-iy,i=iy*g.width+ix,a=g.values[i],b=g.values[i+1],c=g.values[i+g.width],d=g.values[i+g.width+1];if([a,b,c,d].every(Number.isFinite))return (a*(1-tx)+b*tx)*(1-ty)+(c*(1-tx)+d*tx)*ty;}return NaN;}
  function materialImage(){const s=state;if(s.reliefImage)return s.reliefImage;
    const w=Math.min(650,canvas.width),h=Math.round(w*canvas.height/canvas.width),out=document.createElement('canvas');out.width=w;out.height=h;
    const c=out.getContext('2d'),im=c.createImageData(w,h),g=s.material,counts=[0,0,0,0];
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const p=ll(x+.5,y+.5,s.rect,w,h);let ti=NaN,firm=NaN;
      if(g){const r=g.rect,lon=p.lon+360*Math.round(((r.west+r.east)/2-p.lon)/360);
        if(lon>=r.west&&lon<=r.east&&p.lat>=r.south&&p.lat<=r.north){const col=Math.round((lon-r.west)/(r.east-r.west)*(g.width-1)),row=Math.round((r.north-p.lat)/(r.north-r.south)*(g.height-1)),i=row*g.width+col;ti=g.values[i];firm=g.firmness?g.firmness[i]:NaN;}}
      // Fixed bins preserve meaning when zooming; never invent fine soil detail
      // from the satellite photo or smooth across a missing thermal observation.
      const group=!Number.isFinite(ti)?3:ti<300?0:ti<600?1:2,color=[[224,167,99],[184,198,139],[121,185,193],[72,80,82]][group];counts[group]++;
      const shade=group===3?((x+y)%12<3?1.55:1):Number.isFinite(firm)?.85+.25*firm:1,k=(y*w+x)*4;
      im.data[k]=color[0]*shade;im.data[k+1]=color[1]*shade;im.data[k+2]=color[2]*shade;im.data[k+3]=group===3?210:165;
    }
    c.putImageData(im,0,0);return s.reliefImage={canvas:out,counts};
  }
  function reliefImage(){const s=state;if(s.reliefImage)return s.reliefImage;const w=Math.min(650,canvas.width),h=Math.round(w*canvas.height/canvas.width),a=new Float32Array(w*h);let lo=Infinity,hi=-Infinity,count=0;
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){const p=ll(x+.5,y+.5,s.rect,w,h),v=sampleHeight(p.lon,p.lat);a[y*w+x]=v;if(Number.isFinite(v)){lo=Math.min(lo,v);hi=Math.max(hi,v);count++;}}
    if(!count)return null;const out=document.createElement('canvas');out.width=w;out.height=h;const c=out.getContext('2d'),im=c.createImageData(w,h),range=Math.max(1,hi-lo),cos=Math.max(.05,Math.cos((s.rect.north+s.rect.south)*Math.PI/360)),dx=(s.rect.east-s.rect.west)*DEG_M*cos/w,dy=(s.rect.north-s.rect.south)*DEG_M/h;
    const contour=10**Math.floor(Math.log10(range/12)),interval=contour*(range/12/contour>5?5:range/12/contour>2?2:1);
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){const i=y*w+x,v=a[i];if(!Number.isFinite(v))continue;const l=a[y*w+Math.max(0,x-1)],r=a[y*w+Math.min(w-1,x+1)],n=a[Math.max(0,y-1)*w+x],b=a[Math.min(h-1,y+1)*w+x],gx=Number.isFinite(r-l)?(r-l)/(2*dx):0,gy=Number.isFinite(b-n)?(b-n)/(2*dy):0,slope=Math.atan(Math.hypot(gx,gy))*180/Math.PI,t=clamp((v-lo)/range,0,1);
      let red,green,blue,alpha=205;
      if(s.layer==='slope'){const q=clamp(slope/30,0,1);red=90+165*q;green=192-123*q;blue=154-91*q;alpha=180;}
      else {const ex=s.exaggeration,shade=clamp((.94-.65*gx*ex-.45*gy*ex)/Math.sqrt(1+(gx*ex)**2+(gy*ex)**2),.45,1.15),contourDistance=Math.abs(v-Math.round(v/interval)*interval),cn=contourDistance<Math.max(.025,Math.hypot(gx*dx,gy*dy)*.65)?.72:1;
        const palette=[[55,94,143],[65,151,161],[190,199,143],[242,179,112]],u=t*3,k=Math.min(2,Math.floor(u)),f=u-k;red=(palette[k][0]*(1-f)+palette[k+1][0]*f)*shade*cn;green=(palette[k][1]*(1-f)+palette[k+1][1]*f)*shade*cn;blue=(palette[k][2]*(1-f)+palette[k+1][2]*f)*shade*cn;alpha=190;}
      const k=i*4;im.data[k]=red;im.data[k+1]=green;im.data[k+2]=blue;im.data[k+3]=alpha;
    }
    c.putImageData(im,0,0);s.reliefImage={canvas:out,lo,hi,interval,count};return s.reliefImage;
  }
  function draw(){
    const s=state,c=canvas.getContext('2d'),w=canvas.width,h=canvas.height;c.fillStyle='#2c2d28';c.fillRect(0,0,w,h);imageInRect(c,s.context.imagery,s.context.imageryRect,s.rect);
    const imagery=paintImagery(c,s.rect,scheduleDraw),relief=s.layer==='firmness'?materialImage():s.layer==='imagery'?null:reliefImage();if(relief)c.drawImage(relief.canvas,0,0,w,h);
    line(c,s.reference,s.rect,'#092522',5,[7,6]);line(c,s.reference,s.rect,'#98e5d9',2,[7,6]);line(c,s.route,s.rect,'#172122',7);line(c,s.route,s.rect,'#ffd08b',3.5);
    s.route.forEach((p,i)=>dot(c,p,s.rect,i===0?'Start':i===s.route.length-1?'Destination':null,i===s.selected?'#fff':i===0?'#9dd6ff':'#ffd08b',i===s.selected?8:i===0||i===s.route.length-1?7:5));
    const W=s.context.W,R=s.context.R;if(W&&R)dot(c,{lon:W.toLon(R.x),lat:W.toLat(R.y)},s.rect,'You','#fff',7);
    c.fillStyle='#101b1bce';c.fillRect(10,10,38,27);c.fillStyle='#fff';c.font='600 13px system-ui';c.fillText('N ↑',17,28);
    if(s.layer!=='imagery'){c.fillStyle='#101b1bdf';c.fillRect(57,10,Math.min(w-67,360),27);c.fillStyle='#e3ede7';c.font='12px system-ui';const caption=s.layer==='firmness'?(s.materialBusy||s.loadingPlan?'Loading ground observations…':relief.counts.slice(0,3).some(n=>n>0)?'Ground estimate · not measured strength':'No ground data in this view · unknown'):relief?(s.layer==='slope'?'Slope · green gentle / red steep':Math.round(relief.lo)+' to '+Math.round(relief.hi)+' m · relief '+s.exaggeration+'×'):(s.terrainBusy||s.loadingPlan?'Loading measured topography…':'Topography unavailable here');c.save();c.beginPath();c.rect(63,10,w-73,27);c.clip();c.fillText(caption,67,28);c.restore();}
    if(!imagery.ready){c.fillStyle='#101b1bd9';c.fillRect(10,h-65,Math.min(w-20,400),26);c.fillStyle='#e4e4db';c.font='12px system-ui';c.fillText(imagery.failed===imagery.total?'Satellite tiles unavailable. Route position is unchanged.':'Loading Mars satellite imagery…',18,h-48);}
    removeButton.disabled=s.selected<1||s.selected>=s.route.length-1||s.busy;undoButton.disabled=!s.history.length||s.busy;
    const source=s.heights.length?s.heights.map(g=>g.source+(g.resolution?' (~'+Math.round(g.resolution)+' m)':'')).filter((v,i,a)=>a.indexOf(v)===i).join('; '):'Measured elevation loading on demand';
    sourceInfo.innerHTML='Satellite: NASA/JPL/MSSS · <a href="https://murray-lab.caltech.edu/CTX/" target="_blank" rel="noopener">Caltech Murray Lab CTX mosaic</a>, up to 5 m/pixel.'+(imagery.coarse?' Some tiles use a coarser source.':'')+'<br>';
    sourceInfo.append(document.createTextNode(source+'. Relief exaggeration changes shading only. Colours stretch to the visible elevation range; route calculations use original heights.'));
    if(s.layer==='firmness'){
      sourceInfo.append(document.createElement('br'),document.createTextNode('Ground firmness is an estimate from saved thermal-inertia observations. Fixed game display classes: below 300 = dust/sand-like; 300 to below 600 = coarse or crusted; 600 and above = rock-like (J m⁻² K⁻¹ s⁻½). These are broad model categories, not measured soil strength or guaranteed traction. Rock, ice, cemented soil and mixed surfaces can overlap. Satellite detail does not increase material resolution. '));
      if(s.material){const g=s.material,res=Array.isArray(g.resolution)?Math.max(...g.resolution):g.resolution;if(Number.isFinite(res))sourceInfo.append(document.createTextNode('Displayed material grid: about '+Math.round(res)+' m; source observations may be coarser. '));if(g.firmness)sourceInfo.append(document.createTextNode('Within-class shading uses the planner’s thermal/night-IR firmness estimate. '));}
      const link=document.createElement('a');link.href='https://ntrs.nasa.gov/citations/20170003773';link.target='_blank';link.rel='noopener';link.textContent='NASA/JPL: thermal properties and mixed surfaces';sourceInfo.append(link,document.createTextNode(' · '));
      const dataLink=document.createElement('a');dataLink.href='https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=MGS-M-TES-5-TIMAP-V1.0';dataLink.target='_blank';dataLink.rel='noopener';dataLink.textContent='NASA PDS: TES thermal-inertia maps';sourceInfo.append(dataLink);
      for(const entry of s.material?s.material.sources:[]){if(typeof entry!=='string'||!/^thermal_inertia:|^themis_night:/i.test(entry))continue;sourceInfo.append(document.createElement('br'));const url=entry.match(/https?:\/\/[^\s"'{}<>]+/);if(url){const a=document.createElement('a');a.href=url[0];a.target='_blank';a.rel='noopener';a.textContent=entry.startsWith('thermal_inertia:')?'Mission thermal-inertia dataset':'Mission night-IR dataset';sourceInfo.append(a);}else sourceInfo.append(document.createTextNode(entry));}
    }
  }
  window.MarswalkRouteMap={open,close,render,paintImagery,fitRect,routeOf,isOpen:()=>!!(dialog&&dialog.open),snapshot:()=>state?{open:dialog.open,layer:state.layer,route:copy(state.route),reference:copy(state.reference),rect:{...state.rect},dirty:!!state.dirty,terrainLoaded:state.heights.length>0,materialLoaded:!!state.material,materialClasses:state.layer==='firmness'&&state.reliefImage?state.reliefImage.counts:null}:null};
}());
