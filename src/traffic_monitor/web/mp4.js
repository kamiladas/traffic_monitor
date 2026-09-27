let reviewPacket=null,reviewPlaying=false,reviewBusy=false;
document.querySelector('#refresh').onclick=()=>{reviewPlaying=false;if(reviewPacket)reviewFrame(reviewPacket.index);else setStatus('Najpierw wybierz MP4',true)};
async function postJson(url,data={}){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const value=await r.json();if(!r.ok)throw Error(value.error||'Błąd');return value}
function displayReview(p){reviewPacket=p;document.querySelector('#frameIndex').value=p.index;document.querySelector('#mp4Info').textContent=`Klatka ${p.index} / ${p.frames} · czas ${p.pts_s.toFixed(6)} s · nominalnie ${p.fps_nominal.toFixed(2)} FPS`;frame.onload=resize;frame.src=p.image}
async function reviewFrame(index){if(reviewBusy)return;reviewBusy=true;try{displayReview(await postJson('/api/file/frame',{index}))}catch(e){reviewPlaying=false;setStatus(e.message,true)}finally{reviewBusy=false}}
async function refreshReferenceLanes(){
  const c=await fetch('/api/config').then(r=>r.json());
  const select=document.querySelector('#referenceLane');
  const previous=select.value;
  select.replaceChildren();
  for(const l of c.lanes||[]){
    const option=document.createElement('option');
    option.value=l.id;
    option.textContent=`${l.id} · A–B ${l.distance_m} m`;
    select.append(option);
  }
  if(Array.from(select.options).some(option=>option.value===previous))select.value=previous;
}
async function selectedMp4(p){
  displayReview(p);
  setMode(null);
  document.querySelector('#confirmGeometry').checked=false;
  document.querySelector('#manualResult').textContent='Oznacz przecięcia A i B tego samego pojazdu.';
  setStatus('Wybrano '+p.file_name);
  await refreshReferenceLanes();
}
const mp4Picker=document.querySelector('#mp4Picker');
document.querySelector('#chooseMp4').onclick=async()=>{
  reviewPlaying=false;
  const path=document.querySelector('#mp4Path').value.trim();
  if(!path){mp4Picker.click();return}
  const button=document.querySelector('#chooseMp4');button.disabled=true;
  try{await selectedMp4(await postJson('/api/file/select',{path}))}
  catch(e){setStatus(e.message,true)}
  finally{button.disabled=false}
};
mp4Picker.onchange=async()=>{
  const file=mp4Picker.files?.[0];if(!file)return;
  const button=document.querySelector('#chooseMp4');button.disabled=true;
  setStatus(`Wczytywanie MP4 (${(file.size/1048576).toFixed(1)} MB)…`);
  try{
    const response=await fetch('/api/file/upload',{method:'POST',headers:{'Content-Type':'video/mp4'},body:file});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'Nie można otworzyć MP4.');
    await selectedMp4(result);
    document.querySelector('#mp4Path').value='';
  }catch(e){setStatus(e.message,true)}
  finally{mp4Picker.value='';button.disabled=false}
};
document.querySelector('#prevFrame').onclick=()=>{reviewPlaying=false;reviewFrame((reviewPacket?.index??1)-1)};
document.querySelector('#nextFrame').onclick=()=>{reviewPlaying=false;reviewFrame((reviewPacket?.index??-1)+1)};
document.querySelector('#seekFrame').onclick=()=>{reviewPlaying=false;reviewFrame(Number(document.querySelector('#frameIndex').value))};
document.querySelector('#playReview').onclick=()=>{reviewPlaying=!reviewPlaying;playReview()};
async function playReview(){if(!reviewPlaying||!reviewPacket)return;if(reviewPacket.index>=reviewPacket.frames-1){reviewPlaying=false;return}await reviewFrame(reviewPacket.index+1);if(reviewPlaying)setTimeout(playReview,40)}
for(const gate of ['a','b'])document.querySelector(gate==='a'?'#markA':'#markB').onclick=async()=>{reviewPlaying=false;if(reviewBusy)return;try{const r=await postJson('/api/file/mark',{gate,lane:document.querySelector('#referenceLane').value});document.querySelector('#manualResult').textContent=Object.entries(r.marks).map(([key,m])=>`${key.toUpperCase()}: kl. ${m.index}, ${m.pts_s.toFixed(3)} s`).join(' · ')+(r.speed_kmh!=null?` | ${r.distance_m} m / ${r.duration_s.toFixed(3)} s → ${r.speed_kmh.toFixed(1)} km/h`:'')}catch(e){setStatus(e.message,true)}};
const analysisSource=document.querySelector('#analysisSource');
function updateSourceControls(){const live=analysisSource.value==='live';document.querySelector('#aiStart').textContent=live?'Uruchom AI Live':'Analizuj MP4 od początku';document.querySelector('#analysisSourceHint').textContent=live?'Live: analiza z rtsp://127.0.0.1:8554/camera. Najpierw połącz kamerę w Rejestratorze.':'MP4: analizowane są kolejno wszystkie klatki wybranego pliku.'}
analysisSource.onchange=updateSourceControls;
updateSourceControls();
document.querySelector('#aiStart').onclick=async()=>{try{if(!document.querySelector('#confirmGeometry').checked)throw Error('Potwierdź geometrię i odległości dla wybranego źródła.');const source=analysisSource.value;if(source==='live'){const camera=await fetch('/api/camera/status').then(r=>r.json());if(!camera.connected)throw Error('Najpierw połącz kamerę w Rejestratorze.')}reviewPlaying=false;await postJson('/api/analyzer/stop');await postJson('/api/analyzer/start',{source});showView(true);delete liveFrame.dataset.evidence;liveFrame.src='/api/live.mjpg?t='+Date.now();document.querySelector('#aiStatus').textContent=source==='live'?'AI Live uruchomione. Czekam na klatki i PTS kamery.':'Analiza MP4 uruchomiona od początku.'}catch(e){setStatus(e.message,true);document.querySelector('#aiStatus').textContent=e.message}};
document.querySelector('#pauseFile').onclick=async()=>{try{const s=await fetch('/api/analyzer/status').then(r=>r.json());const paused=!s.paused;await postJson('/api/file/pause',{paused});if(!paused&&liveFrame.dataset.evidence){delete liveFrame.dataset.evidence;liveFrame.src='/api/live.mjpg?t='+Date.now()}}catch(e){setStatus(e.message,true)}};
setInterval(async()=>{if(liveView.classList.contains('hidden'))return;try{const s=await fetch('/api/analyzer/status').then(r=>r.json());if(s.source_kind==='camera'){document.querySelector('#fileProgress').textContent=`Live RTSP · ${s.connected?'połączony':'oczekiwanie na obraz'} · ${s.analysis_fps_actual??0} kl./s · PTS: ${s.timing_source||'brak'} · pominięte klatki: ${s.skipped_frames??0}${s.error?' · '+s.error:''}`}else{const frames=s.frames_total?` · klatki ${s.frames_processed??0}/${s.frames_total}`:'';const pace=s.analysis_fps_actual?` · ${s.analysis_fps_actual} kl./s (${s.file_speed_factor??'?'}× czasu filmu)` : '';const eta=s.remaining_wall_s!=null?` · do końca około ${(s.remaining_wall_s/3600).toFixed(1)} h`:'';document.querySelector('#fileProgress').textContent=`${s.file_name||'Wybierz MP4 w kalibracji'} · ${s.file_state||'gotowy'}${s.paused?' · PAUZA':''} · ${s.position_s??0} / ${s.duration_s?.toFixed(1)??'?'} s${frames}${pace}${eta}`}document.querySelector('#pauseFile').disabled=s.source_kind!=='file'||!s.enabled;document.querySelector('#aiStart').disabled=false;document.querySelector('#aiStop').disabled=!s.enabled}catch{}},1000);
document.querySelector('#connectCamera').onclick=async()=>{try{await postJson('/api/camera/connect',{ip:document.querySelector('#cameraIp').value,user:document.querySelector('#cameraUser').value,password:document.querySelector('#cameraPassword').value,channel:document.querySelector('#cameraChannel').value});document.querySelector('#cameraConnection').textContent='Połączenie uruchomione. Dostępność obrazu sprawdź podglądem lub nagrywaniem.'}catch(e){document.querySelector('#cameraConnection').textContent=e.message}finally{document.querySelector('#cameraPassword').value=''}};
document.querySelector('#disconnectCamera').onclick=async()=>{try{await postJson('/api/camera/disconnect');setRecorderPreview(false);document.querySelector('#cameraConnection').textContent='Rozłączono'}catch(e){setStatus(e.message,true)}};
