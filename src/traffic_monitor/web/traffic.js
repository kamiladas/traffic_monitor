const analysisDrawer=document.querySelector('#analysisDrawer');
const drawerToggle=document.querySelector('#toggleAnalysisDrawer');
const laneTables=document.querySelector('#laneTables');
const workspace=document.querySelector('.measurement-workspace');
const workspaceSplitter=document.querySelector('#workspaceSplitter');
let measurementRows=[];
let measurementStatus={};
let laneRenderSignature='';
const expandedMeasurements=new Set();
const measurementShowView=showView;
showView=function(live){if(!live)setDrawer(false);measurementShowView(live);if(live)requestAnimationFrame(restoreWorkspaceSplit)};

function setDrawer(open){
  analysisDrawer.classList.toggle('open',open);
  analysisDrawer.setAttribute('aria-hidden',String(!open));
  drawerToggle.setAttribute('aria-expanded',String(open));
}
drawerToggle.onclick=()=>setDrawer(!analysisDrawer.classList.contains('open'));
document.querySelector('#closeAnalysisDrawer').onclick=()=>setDrawer(false);

function setWorkspaceSplit(panelWidth,persist=false){
  const width=workspace.getBoundingClientRect().width;
  if(width<=0)return;
  const limited=Math.max(365,Math.min(Number(panelWidth),width-330));
  liveView.classList.add('manual-split');
  liveView.style.setProperty('--lane-panel-width',`${limited}px`);
  workspaceSplitter.setAttribute('aria-valuenow',String(Math.round(limited/width*100)));
  if(persist)localStorage.setItem('traffic-lane-panel-ratio',String(limited/width));
}
function restoreWorkspaceSplit(){
  const ratio=Number(localStorage.getItem('traffic-lane-panel-ratio'));
  if(Number.isFinite(ratio)&&ratio>0)setWorkspaceSplit(workspace.getBoundingClientRect().width*ratio);
}
workspaceSplitter.onpointerdown=event=>{workspaceSplitter.setPointerCapture(event.pointerId);document.body.classList.add('workspace-resizing');event.preventDefault()};
workspaceSplitter.onpointermove=event=>{if(workspaceSplitter.hasPointerCapture(event.pointerId)){const rect=workspace.getBoundingClientRect();setWorkspaceSplit(rect.right-event.clientX)}};
workspaceSplitter.onpointerup=event=>{if(workspaceSplitter.hasPointerCapture(event.pointerId))workspaceSplitter.releasePointerCapture(event.pointerId);document.body.classList.remove('workspace-resizing');const width=parseFloat(getComputedStyle(liveView).getPropertyValue('--lane-panel-width'));if(Number.isFinite(width))setWorkspaceSplit(width,true)};
workspaceSplitter.onpointercancel=()=>document.body.classList.remove('workspace-resizing');
workspaceSplitter.ondblclick=()=>{localStorage.removeItem('traffic-lane-panel-ratio');liveView.classList.remove('manual-split');liveView.style.removeProperty('--lane-panel-width')};
workspaceSplitter.onkeydown=event=>{if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;event.preventDefault();const current=document.querySelector('.lane-panel').getBoundingClientRect().width;setWorkspaceSplit(current+(event.key==='ArrowLeft'?24:-24),true)};
window.addEventListener('resize',restoreWorkspaceSplit);
restoreWorkspaceSplit();

function displayTime(row){
  if(row.detected_at)return row.detected_at;
  const seconds=Number(row.event_time_s);
  if(!Number.isFinite(seconds))return '—';
  const minutes=Math.floor(seconds/60);
  return `${String(minutes).padStart(2,'0')}:${(seconds-minutes*60).toFixed(3).padStart(6,'0')}`;
}
function number(value,digits=3,suffix=''){
  return value==null||!Number.isFinite(Number(value))?'—':`${Number(value).toFixed(digits)}${suffix}`;
}
function rowStatus(row){
  if(row.status==='valid')return {label:'✓ Pomiar',css:'status-valid'};
  if(row.status==='measuring')return {label:'● W trakcie',css:'status-measuring'};
  if(row.reason==='lane_change')return {label:'↔ Zmiana pasa',css:'status-invalid'};
  if(row.time_a==null)return {label:'⚠ Brak A',css:'status-invalid'};
  if(row.time_b==null)return {label:'⚠ Brak B',css:'status-invalid'};
  return {label:'⚠ Brak pomiaru',css:'status-invalid'};
}
function reasonName(reason){
  return ({tracking_lost_after_gate:'utrata trackingu po pierwszej linii',tracking_lost:'utrata trackingu',occluded_before_complete_measurement:'zasłonięcie przed pełnym pomiarem',lane_change:'zmiana pasa',lane_ambiguous_or_lost:'niejednoznaczny pas',time_discontinuity:'przerwa czasu PTS',wrong_order_direction_or_jump:'zła kolejność linii lub skok',insufficient_observations_or_implausible_speed:'za mało obserwacji lub niewiarygodna prędkość',repeated_entry:'powtórne przecięcie wejścia'})[reason]||reason||'—';
}
function cell(text,className){const td=document.createElement('td');td.textContent=text;if(className)td.className=className;return td}
function detailsRow(row,key){
  const tr=document.createElement('tr');tr.className='details-row';tr.classList.toggle('hidden',!expandedMeasurements.has(key));
  const td=document.createElement('td');td.colSpan=6;
  const detail=document.createElement('div');detail.className='measurement-details';
  const valuesRoot=document.createElement('div');valuesRoot.className='measurement-detail-values';
  const values=[['Pas',row.lane||'—'],['Klasa / typ',`${row.class_name||'unknown'} / ${row.vehicle_group||'unknown'}`],['Linia A',number(row.time_a)],['Linia B',number(row.time_b)],['Odległość',number(row.distance_m,1,' m')],['GAP',number(row.gap_s,2,' s')],['Pewność',row.confidence==null?'—':`${(Number(row.confidence)*100).toFixed(1)}%`],['Wynik',rowStatus(row).label],['Powód techniczny',reasonName(row.reason)]];
  if(row.evidence_file)values.push(['Plik migawki',row.evidence_file]);
  for(const [label,value] of values){const item=document.createElement('span');const b=document.createElement('b');b.textContent=label;item.append(b,document.createTextNode(value));valuesRoot.append(item)}
  detail.append(valuesRoot);
  if(row.has_snapshot){
    const evidence=document.createElement('button');evidence.className='measurement-evidence';evidence.type='button';evidence.title='Kliknij, aby powiększyć lub pomniejszyć';
    const image=document.createElement('img');image.alt=`Pojazd ID ${row.track_id} z ramkami`;image.src=`/api/measurements/${row.track_id}/frame.jpg?thumb=1&t=${Date.now()}`;
    const caption=document.createElement('span');caption.textContent='Klatka zdarzenia';evidence.append(image,caption);
    evidence.onclick=async event=>{
      event.stopPropagation();
      const expanded=evidence.classList.toggle('expanded');
      image.src=`/api/measurements/${row.track_id}/frame.jpg${expanded?'':'?thumb=1'}&t=${Date.now()}`.replace('.jpg&','.jpg?');
      if(expanded)await showMeasurementEvidence(row);
      else await restoreMeasurementPreview();
    };
    detail.append(evidence);
  }
  td.append(detail);tr.append(td);return tr;
}
async function showMeasurementEvidence(row){
  if(!row.has_snapshot)return;
  if(measurementStatus.source_kind==='file'&&measurementStatus.enabled){try{await postJson('/api/file/pause',{paused:true})}catch{}}
  liveFrame.dataset.evidence=String(row.track_id);
  liveFrame.src=`/api/measurements/${row.track_id}/frame.jpg?t=${Date.now()}`;
  document.querySelector('#videoSourceLabel').textContent=`KLATKA ZDARZENIA · ID ${row.track_id} · ${displayTime(row)}`;
}
async function restoreMeasurementPreview(){
  if(!liveFrame.dataset.evidence)return;
  delete liveFrame.dataset.evidence;
  liveFrame.src=`/api/live.mjpg?t=${Date.now()}`;
  if(measurementStatus.source_kind==='file'&&measurementStatus.enabled){try{await postJson('/api/file/pause',{paused:false})}catch{}}
}
function createLaneCard(lane,stats,rows){
  const card=document.createElement('article');card.className='lane-card';card.dataset.lane=lane.id;
  const header=document.createElement('div');header.className='lane-card-header';
  const title=document.createElement('h3');title.textContent=lane.id;
  const summary=document.createElement('span');summary.className='lane-card-summary';summary.textContent=`${stats.count||0} pomiarów · Vśr ${stats.speed_avg_kmh??'—'} km/h · light ${stats.light||0} · heavy ${stats.heavy||0}`;
  const exportButton=document.createElement('button');exportButton.textContent='CSV';exportButton.onclick=()=>exportCsv(lane.id);
  header.append(title,summary,exportButton);card.append(header);
  if(!rows.length){const empty=document.createElement('div');empty.className='empty-lane';empty.textContent='Brak przejazdów';card.append(empty);return card}
  const wrap=document.createElement('div');wrap.className='lane-table-wrap';const table=document.createElement('table');table.className='lane-table';
  const thead=document.createElement('thead');const heading=document.createElement('tr');['Czas','ID','Pojazd','Czas AB','km/h','Status'].forEach(value=>{const th=document.createElement('th');th.textContent=value;heading.append(th)});thead.append(heading);table.append(thead);
  const tbody=document.createElement('tbody');
  for(const row of rows){
    const key=`${lane.id}:${row.track_id}`;
    const status=rowStatus(row);const tr=document.createElement('tr');tr.dataset.track=row.track_id;
    tr.append(cell(displayTime(row)),cell(String(row.track_id)),cell(row.class_name||'unknown'),cell(number(row.duration_s,3,' s')),cell(number(row.speed_kmh,1)),cell(status.label,status.css));
    const details=detailsRow(row,key);tr.onclick=async()=>{const opening=!expandedMeasurements.has(key);if(opening)expandedMeasurements.add(key);else expandedMeasurements.delete(key);details.classList.toggle('hidden',!opening);if(!opening&&liveFrame.dataset.evidence===String(row.track_id))await restoreMeasurementPreview()};tbody.append(tr,details);
  }
  table.append(tbody);wrap.append(table);card.append(wrap);return card;
}
function renderLaneTables(config,stats,rows){
  const horizontal=laneTables.scrollLeft;
  const vertical=new Map(Array.from(laneTables.querySelectorAll('.lane-card')).map(card=>[card.dataset.lane,card.querySelector('.lane-table-wrap')?.scrollTop||0]));
  laneTables.replaceChildren();
  for(const lane of config.lanes||[]){laneTables.append(createLaneCard(lane,stats.lanes?.[lane.id]||{},rows.filter(row=>row.lane===lane.id)))}
  if(!(config.lanes||[]).length){const empty=document.createElement('div');empty.className='empty-lane';empty.textContent='Skonfiguruj przynajmniej jeden pas.';laneTables.append(empty)}
  const laneCount=Math.max(1,(config.lanes||[]).length);
  liveView.style.setProperty('--lane-count',laneCount);
  liveView.style.setProperty('--lane-card-width',laneCount<=3?`calc((100% - ${(laneCount-1)*10}px) / ${laneCount})`:'344px');
  liveView.classList.toggle('compact-lanes',laneCount<=3);
  laneTables.scrollLeft=horizontal;
  for(const card of laneTables.querySelectorAll('.lane-card')){const wrap=card.querySelector('.lane-table-wrap');if(wrap)wrap.scrollTop=vertical.get(card.dataset.lane)||0}
}
function csvValue(value){
  let text=value==null?'':String(value);
  if(/^[=+\-@]/.test(text))text=`'${text}`;
  return /[;"\r\n]/.test(text)?`"${text.replaceAll('"','""')}"`:text;
}
function exportCsv(lane=null){
  const fields=['source','event_time','track_id','lane','class','vehicle_group','time_a_s','time_b_s','duration_s','distance_m','speed_kmh','gap_s','confidence','status','reason'];
  const selected=measurementRows.filter(row=>row.status!=='measuring'&&(!lane||row.lane===lane));
  const lines=[fields.join(';')];
  for(const row of selected){const values=[measurementStatus.file_name||measurementStatus.source_kind||'',displayTime(row),row.track_id,row.lane,row.class_name,row.vehicle_group,row.time_a,row.time_b,row.duration_s,row.distance_m,row.speed_kmh,row.gap_s,row.confidence,row.status,row.reason];lines.push(values.map(csvValue).join(';'))}
  const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`pomiary_${lane||'wszystkie'}_${new Date().toISOString().slice(0,19).replaceAll(':','-')}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
}
document.querySelector('#exportAllCsv').onclick=()=>exportCsv();

async function refreshTrafficTables(){
  if(liveView.classList.contains('hidden'))return;
  try{
    const [config,status,stats,rows]=await Promise.all([fetch('/api/config').then(r=>r.json()),fetch('/api/analyzer/status').then(r=>r.json()),fetch('/api/stats').then(r=>r.json()),fetch('/api/measurements').then(r=>r.json())]);
    measurementRows=rows;measurementStatus=status;
    const signature=JSON.stringify({lanes:(config.lanes||[]).map(l=>[l.id,l.distance_m]),stats:stats.lanes,rows:rows.map(r=>[r.track_id,r.lane,r.status,r.time_a,r.time_b,r.speed_kmh,r.reason,r.has_snapshot,r.evidence_file])});
    if(signature!==laneRenderSignature){laneRenderSignature=signature;renderLaneTables(config,stats,rows)}
    document.querySelector('#unmeasuredCount').textContent=stats.unmeasured_total??rows.filter(row=>row.status==='invalid').length;
    const device=status.inference_backend==='ultralytics_cuda'?'NVIDIA CUDA':status.inference_backend==='openvino_intel_gpu'?'INTEL IRIS XE':'CPU';
    if(!liveFrame.dataset.evidence)document.querySelector('#videoSourceLabel').textContent=`YOLO26 · FASTTRACK · ${device.toUpperCase()}`;
    const progress=status.frames_total?`${status.frames_processed||0}/${status.frames_total}`:(status.source_kind==='camera'?'Live':'gotowy');
    document.querySelector('#measurementBar').textContent=status.enabled?`● ${device} · ${progress} · ${status.active_tracks||0} aktywne ID · ${status.inference_ms??'—'} ms`:'AI wyłączone';
  }catch(error){document.querySelector('#measurementBar').textContent=`Błąd: ${error.message}`}
}
setInterval(refreshTrafficTables,1000);refreshTrafficTables();
