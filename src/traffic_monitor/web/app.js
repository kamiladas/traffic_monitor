const state={config:null,mode:null,draft:[],pointer:null,drag:null,down:null,moved:false};
const canvas=document.querySelector('#canvas'),ctx=canvas.getContext('2d'),frame=document.querySelector('#frame');
const statusEl=document.querySelector('#status');
const colors={roi:'#ffd54a',lane:'#32d49a',line_a:'#35a7ff',line_b:'#ff4f70',draft:'#ffffff'};

function setStatus(text,error=false){statusEl.textContent=text;statusEl.style.color=error?'#ff8080':'#8fa0b8'}
function points(value){return Array.isArray(value)?value:[]}
function resize(){canvas.width=frame.clientWidth;canvas.height=frame.clientHeight;draw()}
function px(p){return[p[0]*canvas.width,p[1]*canvas.height]}
function norm(event){const r=canvas.getBoundingClientRect();return[(event.clientX-r.left)/r.width,(event.clientY-r.top)/r.height]}
function path(poly,color,closed=true,width=3,fill=false){if(!poly?.length)return;ctx.beginPath();poly.forEach((p,i)=>{const[x,y]=px(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});if(closed&&poly.length>2)ctx.closePath();if(fill){ctx.globalAlpha=.12;ctx.fillStyle=color;ctx.fill();ctx.globalAlpha=1}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();poly.forEach(p=>{const[x,y]=px(p);ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill()})}
function label(poly,text,color){if(!poly?.length)return;const[x,y]=px(poly[0]);ctx.font='bold 16px Segoe UI';ctx.fillStyle='#000b';ctx.fillRect(x+7,y-20,ctx.measureText(text).width+10,23);ctx.fillStyle=color;ctx.fillText(text,x+12,y-3)}
function preview(){if(!state.mode||!state.pointer||!state.draft.length)return;const last=px(state.draft[state.draft.length-1]),cursor=px(state.pointer);ctx.save();ctx.setLineDash([8,6]);ctx.strokeStyle=colors.draft;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(...last);ctx.lineTo(...cursor);if((state.mode==='roi'||state.mode==='lane')&&state.draft.length>1)ctx.lineTo(...px(state.draft[0]));ctx.stroke();ctx.restore()}
function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);if(!state.config)return;path(state.config.roi,colors.roi,true,3,true);label(state.config.roi,'ROI',colors.roi);state.config.lanes.forEach(l=>{path(l.polygon,colors.lane,true,2,true);label(l.polygon,l.id,colors.lane)});path(state.config.line_a,colors.line_a,false,4);label(state.config.line_a,'A',colors.line_a);path(state.config.line_b,colors.line_b,false,4);label(state.config.line_b,'B',colors.line_b);path(state.draft,colors.draft,state.mode==='roi'||state.mode==='lane',2,false);preview()}
function setMode(mode){state.mode=mode;state.draft=[];document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));setStatus(mode?`Rysowanie: ${mode}`:'Gotowe');draw()}
function nextLaneName(){let n=1;const ids=new Set(state.config.lanes.map(l=>l.id));while(ids.has(`L${n}`))n++;return`L${n}`}
function finish(){if(!state.mode)return;if(state.mode==='roi'){if(state.draft.length<3)return setStatus('ROI wymaga minimum 3 punktów',true);state.config.roi=[...state.draft]}else if(state.mode==='lane'){if(state.draft.length<3)return setStatus('Pas wymaga minimum 3 punktów',true);const id=document.querySelector('#laneName').value.trim()||nextLaneName();if(state.config.lanes.some(l=>l.id===id))return setStatus(`Pas ${id} już istnieje`,true);const distance=Number(document.querySelector('#laneDistance').value);if(!Number.isFinite(distance)||distance<=0)return setStatus('Odległość A–B musi być większa od 0 m',true);state.config.lanes.push({id,polygon:[...state.draft],distance_m:distance,direction:document.querySelector('#laneDirection').value});document.querySelector('#laneName').value=nextLaneName();renderLanes(id)}else{if(state.draft.length!==2)return setStatus('Linia wymaga dokładnie 2 punktów',true);state.config[state.mode]=[...state.draft]}setMode(null)}
function selectedLane(){return state.config?.lanes.find(l=>l.id===document.querySelector('#laneEditor').value)}
function showLaneParameters(){
  const lane=selectedLane();
  document.querySelector('#laneName').disabled=!!lane;
  if(lane){document.querySelector('#laneName').value=lane.id;document.querySelector('#laneDistance').value=lane.distance_m;document.querySelector('#laneDirection').value=lane.direction}
  else{document.querySelector('#laneName').value=nextLaneName();document.querySelector('#laneDistance').value=20;document.querySelector('#laneDirection').value='a_to_b'}
}
function renderLanes(preferredId){
  const select=document.querySelector('#laneEditor'),previous=preferredId??(select.dataset.initialized?select.value:(state.config.lanes[0]?.id??''));
  select.replaceChildren();
  for(const lane of state.config.lanes){const option=document.createElement('option');option.value=lane.id;option.textContent=lane.id;select.append(option)}
  const newOption=document.createElement('option');newOption.value='';newOption.textContent='+ nowy pas';select.append(newOption);
  select.value=Array.from(select.options).some(option=>option.value===previous)?previous:(state.config.lanes[0]?.id??'');
  select.dataset.initialized='1';
  const root=document.querySelector('#laneList');root.replaceChildren();
  state.config.lanes.forEach((lane,index)=>{
    const row=document.createElement('div');row.className='lane-item';
    const id=document.createElement('strong');id.textContent=lane.id;
    const distance=document.createElement('input');distance.type='number';distance.min='0.1';distance.step='0.1';distance.value=lane.distance_m;distance.title='Odległość A–B tego pasa w metrach';
    distance.setAttribute('aria-label',`Odległość A–B dla ${lane.id} w metrach`);
    distance.oninput=()=>{
      const number=Number(distance.value);
      if(!distance.value||!Number.isFinite(number)||number<=0){setStatus('Odległość musi być większa od 0 m',true);return}
      lane.distance_m=number;draw();setStatus(`${lane.id}: ${number} m — kliknij Zapisz profil`);
      if(selectedLane()===lane)document.querySelector('#laneDistance').value=number;
      const option=Array.from(document.querySelector('#referenceLane').options).find(item=>item.value===lane.id);
      if(option)option.textContent=`${lane.id} · ${number} m (niezapisane)`;
    };
    const unit=document.createElement('span');unit.textContent='m';
    const remove=document.createElement('button');remove.title='Usuń pas';remove.textContent='×';
    remove.onclick=()=>{state.config.lanes.splice(index,1);renderLanes();draw()};
    row.append(id,distance,unit,remove);root.append(row)
  });showLaneParameters()
}
function handles(){if(!state.config)return[];const result=[];const add=(poly,kind,index=null)=>poly.forEach((point,pointIndex)=>result.push({poly,point,kind,index,pointIndex}));add(state.config.roi,'ROI');state.config.lanes.forEach((lane,index)=>add(lane.polygon,lane.id,index));add(state.config.line_a,'A');add(state.config.line_b,'B');add(state.draft,'rysowana');return result}
function nearestHandle(event){const r=canvas.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top;let best=null,bestDistance=12;handles().forEach(handle=>{const[hx,hy]=px(handle.point),distance=Math.hypot(hx-x,hy-y);if(distance<bestDistance){best=handle;bestDistance=distance}});return best}
async function load(){try{const response=await fetch('/api/config');state.config=await response.json();document.querySelector('#cameraName').textContent=state.config.camera_id;renderLanes();if(typeof syncCalibrationBackend==='function')syncCalibrationBackend(state.config.inference_backend,state.config.preview_fps??3);setStatus('Wybierz MP4 do kalibracji i analizy')}catch(e){setStatus(`Błąd: ${e.message}`,true)}}
function refreshFrame(){setStatus('Pobieranie klatki…');frame.onload=()=>{resize();setStatus('Klatka gotowa')};frame.onerror=()=>setStatus('Uruchom MediaMTX — brak klatki',true);frame.src=`/api/frame.jpg?t=${Date.now()}`}
async function save(){try{const lane=selectedLane();if(lane){const input=document.querySelector('#laneDistance');const distance=Number(input.value);if(!input.value||!Number.isFinite(distance)||distance<=0)throw Error('Odległość A–B musi być większa od 0 m');lane.distance_m=distance;lane.direction=document.querySelector('#laneDirection').value}const previewInput=document.querySelector('#previewFpsInput');if(!previewInput.reportValidity())throw Error('Limit podglądu musi być w zakresie 1–120 kl./s');state.config.inference_backend=document.querySelector('#calibrationBackend').value;state.config.preview_fps=Number(previewInput.value);setStatus('Zapisywanie…');const response=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state.config)});const result=await response.json();if(!response.ok)throw new Error(result.error||'Błąd zapisu');state.config=result.config;renderLanes();draw();if(typeof syncCalibrationBackend==='function')syncCalibrationBackend(result.config.inference_backend,result.config.preview_fps??3);if(typeof refreshSettings==='function')refreshSettings();if(typeof refreshReferenceLanes==='function')refreshReferenceLanes().catch(e=>setStatus('Profil zapisany, ale lista pasów pomiaru nie odświeżyła się: '+e.message,true));const manual=document.querySelector('#manualResult');if(manual)manual.textContent='Profil zmieniony. Oznacz ponownie przecięcia A i B.';setStatus('Profil zapisany: '+state.config.lanes.map(l=>`${l.id}: A–B ${l.distance_m} m`).join(' · '));return true}catch(e){setStatus(e.message,true);return false}}

canvas.addEventListener('pointerdown',event=>{const handle=nearestHandle(event);state.down=norm(event);state.moved=false;if(handle){state.drag=handle;canvas.setPointerCapture(event.pointerId);canvas.style.cursor='grabbing'}else if(state.mode){state.draft.push(state.down);if((state.mode==='line_a'||state.mode==='line_b')&&state.draft.length===2)finish();draw()}});
canvas.addEventListener('pointermove',event=>{state.pointer=norm(event);if(state.drag){const next=state.pointer;if(Math.hypot(next[0]-state.down[0],next[1]-state.down[1])>.002)state.moved=true;state.drag.poly[state.drag.pointIndex]=next;state.drag.point=next;draw();return}canvas.style.cursor=nearestHandle(event)?'grab':'crosshair';draw()});
canvas.addEventListener('pointerup',event=>{if(state.drag){state.drag=null;canvas.releasePointerCapture(event.pointerId);canvas.style.cursor='crosshair';draw()}state.down=null});
canvas.addEventListener('pointerleave',()=>{if(!state.drag){state.pointer=null;draw()}});
document.querySelector('#laneEditor').onchange=showLaneParameters;
document.querySelector('#laneDistance').oninput=()=>{const lane=selectedLane();if(!lane)return;const input=document.querySelector('#laneDistance'),distance=Number(input.value);if(!input.value||!Number.isFinite(distance)||distance<=0){setStatus('Odległość A–B musi być większa od 0 m',true);return}lane.distance_m=distance;const row=Array.from(document.querySelectorAll('#laneList .lane-item')).find(item=>item.querySelector('strong')?.textContent===lane.id);if(row)row.querySelector('input').value=distance;draw();setStatus(`${lane.id}: A–B ${distance} m — kliknij Zapisz profil`)};
document.querySelector('#laneDirection').onchange=()=>{const lane=selectedLane();if(lane){lane.direction=document.querySelector('#laneDirection').value;setStatus(`${lane.id}: kierunek zmieniony — kliknij Zapisz profil`)}};
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{if(b.dataset.mode==='lane'){document.querySelector('#laneEditor').value='';showLaneParameters()}setMode(b.dataset.mode)});
document.querySelector('#finish').onclick=finish;
document.querySelector('#undo').onclick=()=>{state.draft.pop();draw()};
document.querySelector('#refresh').onclick=refreshFrame;
document.querySelector('#save').onclick=save;
document.querySelector('#clear').onclick=()=>{if(confirm('Usunąć ROI, pasy i linie?')){state.config.roi=[];state.config.lanes=[];state.config.line_a=[];state.config.line_b=[];setMode(null);renderLanes();draw()}};
const editorView=document.querySelector('#editorView'),liveView=document.querySelector('#liveView'),liveFrame=document.querySelector('#liveFrame');
function showView(live){editorView.classList.toggle('hidden',live);liveView.classList.toggle('hidden',!live);document.querySelector('#showEditor').classList.toggle('active',!live);document.querySelector('#showLive').classList.toggle('active',live);if(live&&!liveFrame.getAttribute('src'))liveFrame.src='/api/live.mjpg';if(!live)liveFrame.removeAttribute('src')}
document.querySelector('#showEditor').onclick=()=>showView(false);document.querySelector('#showLive').onclick=()=>showView(true);
function value(v,suffix=''){return v==null?'-':`${v}${suffix}`}
function showInferenceDevice(status){
  const badge=document.querySelector('#inferenceDeviceStatus');
  const active=status.inference_backend;
  const requested=status.inference_backend_requested;
  const onGpu=active==='ultralytics_cuda'||active==='openvino_intel_gpu';
  badge.classList.toggle('device-gpu',onGpu);
  badge.classList.toggle('device-warning',!!status.inference_backend_error);
  if(!status.enabled){badge.textContent='Silnik AI: wyłączony';return}
  if(status.inference_backend_error){badge.textContent=`Silnik AI: błąd · ${status.inference_backend_error}`;return}
  const device=active==='ultralytics_cuda'?'NVIDIA / CUDA':active==='openvino_intel_gpu'?'Intel Iris Xe / OpenVINO':'CPU';
  badge.textContent=`Silnik AI: YOLO26s / FastTracker · ${device}${status.file_state==='finished'?' · analiza zakończona':''}`;
}
async function refreshAnalysis(){try{const[status,stats,events]=await Promise.all([fetch('/api/analyzer/status').then(r=>r.json()),fetch('/api/stats').then(r=>r.json()),fetch('/api/events').then(r=>r.json())]);document.querySelector('#analysisStatus').textContent=status.connected?(status.profile_ready?'Strumień połączony · profil gotowy':'Strumień połączony · uzupełnij profil'):(status.error||'Łączenie...');showInferenceDevice(status);document.querySelector('#detectedCount').textContent=stats.detected_total??0;document.querySelector('#totalCount').textContent=stats.total;document.querySelector('#trackCount').textContent=status.active_tracks;document.querySelector('#inferenceTime').textContent=value(status.inference_ms,' ms');const laneRoot=document.querySelector('#laneStats');laneRoot.innerHTML='';const ids=state.config?.lanes?.map(l=>l.id)||Object.keys(stats.lanes);ids.forEach(id=>{const s=stats.lanes[id]||{count:0,light:0,heavy:0};const row=document.createElement('div');row.className='stat-row';row.innerHTML=`<b>${id}: ${s.count}</b><br><span>lekkie ${s.light} · ciężkie ${s.heavy} · Vśr ${value(s.speed_avg_kmh,' km/h')} · odstęp ${value(s.headway_avg_s,' s')}</span>`;laneRoot.append(row)});const eventRoot=document.querySelector('#eventList');eventRoot.innerHTML='';events.slice(0,20).forEach(e=>{const row=document.createElement('div');row.className='event-row';row.innerHTML=`<b>${e.detected_at} · ${e.lane} · ${e.class_name}</b><br><span>${e.speed_kmh} km/h · odstęp ${value(e.headway_s,' s')} · A–B ${value(e.duration_s?.toFixed(3),' s')} · ${value(e.distance_m,' m')} · ${value(e.observations)} obserwacji</span>`;eventRoot.append(row)});if(!events.length)eventRoot.innerHTML='<div class="event-row"><span>Czekam na przejazd przez A i B…</span></div>'}catch(e){document.querySelector('#analysisStatus').textContent=`Błąd: ${e.message}`}}
setInterval(refreshAnalysis,2000);refreshAnalysis();
const timingInfo=document.createElement('p');timingInfo.className='hint';document.querySelector('#analysisStatus').after(timingInfo);
async function refreshTiming(){if(document.hidden)return;try{const s=await fetch('/api/analyzer/status').then(r=>r.json());timingInfo.textContent=`Analiza: ${value(s.analysis_fps_actual,' FPS')} · oczekiwanie klatki: ${value(s.frame_age_ms,' ms')} · wynik po: ${value(s.result_age_ms,' ms')} · odstęp PTS: ${value(s.pts_interval_ms,' ms')}${s.error?' · '+s.error:''}`;timingInfo.title='Czasy od odbioru klatki przez backend. Nie obejmują opóźnienia kamery i LTE.'}catch{timingInfo.textContent='Backend niedostępny'}}
setInterval(refreshTiming,3000);refreshTiming();
window.addEventListener('resize',resize);window.addEventListener('keydown',e=>{if(e.key==='Enter')finish();if(e.key==='Escape')setMode(null);if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save()}});
load();
