const recorderView=document.querySelector('#recorderView');
const recordPlayer=document.querySelector('#recordPlayer');
const recordPreviewState=document.querySelector('#recordPreviewState');
const recordPreviewPlaceholder=document.querySelector('#recordPreviewPlaceholder');
const originalShowView=showView;
function setRecorderPreview(connected){
  const visible=!recorderView.classList.contains('hidden');
  const enabled=connected&&visible;
  if(enabled&&!recordPlayer.getAttribute('src'))recordPlayer.src='http://127.0.0.1:8889/camera/';
  if(!enabled)recordPlayer.removeAttribute('src');
  recordPlayer.classList.toggle('hidden',!enabled);
  recordPreviewPlaceholder.classList.toggle('hidden',enabled);
  recordPreviewState.textContent=connected?'Kamera połączona · obraz live':'Połącz kamerę';
  recordPreviewState.classList.toggle('connected',connected);
}
showView=function(live){recorderView.classList.add('hidden');document.querySelector('#showRecorder').classList.remove('active');setRecorderPreview(false);originalShowView(live)};
document.querySelector('#showRecorder').onclick=()=>{showView(false);editorView.classList.add('hidden');recorderView.classList.remove('hidden');document.querySelector('#showEditor').classList.remove('active');document.querySelector('#showRecorder').classList.add('active');refreshRecorder()};
let controlBusy=false;
const recorderError=document.createElement('p');recorderError.setAttribute('role','alert');recorderError.style.color='#ff8080';document.querySelector('#recordStatus').after(recorderError);
async function control(path){
  if(controlBusy)return;
  controlBusy=true;
  recorderError.textContent='';
  document.querySelectorAll('#recordStart,#recordStop,#aiStart,#aiStop').forEach(b=>b.disabled=true);
  try{
    if(path.endsWith('/recorder/start'))liveFrame.removeAttribute('src');
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'}});
    const data=await response.json();if(!response.ok)throw Error(data.error||'Błąd operacji');
    if(path.endsWith('/analyzer/start')&&!liveView.classList.contains('hidden'))liveFrame.src='/api/live.mjpg';
  }catch(e){recorderError.textContent=e.message;setStatus(e.message,true)}
  finally{controlBusy=false;await refreshRecorder()}
}
document.querySelector('#recordStart').onclick=()=>control('/api/recorder/start');
document.querySelector('#recordStop').onclick=()=>control('/api/recorder/stop');
document.querySelector('#aiStart').onclick=()=>control('/api/analyzer/start');
document.querySelector('#aiStop').onclick=()=>control('/api/analyzer/stop');
async function refreshRecorder(){
  if(controlBusy)return;
  try{
    const [r,a,c]=await Promise.all([fetch('/api/recorder/status').then(r=>r.json()),fetch('/api/analyzer/status').then(r=>r.json()),fetch('/api/camera/status').then(r=>r.json())]);
    setRecorderPreview(c.connected);
    const names={idle:'Gotowy',starting:'Łączenie / oczekiwanie na obraz',recording:'Nagrywanie',stopping:'Zapisywanie',finished:'Zapis zakończony',error:'Błąd nagrywania'};
    document.querySelector('#recordStatus').textContent=`${names[r.state]||r.state} · ${r.elapsed_s} s · ${(r.size_bytes/1048576).toFixed(1)} MB${r.error?' · '+r.error:''}`;
    document.querySelector('#recordPath').textContent=`Folder: ${r.directory}${r.filename?' | Plik: '+r.filename:''}`;
    document.querySelector('#aiStatus').textContent=a.enabled?'AI włączone':'AI wyłączone — dekodowanie i detekcja zatrzymane';
    document.querySelector('#recordStart').disabled=r.active;
    document.querySelector('#recordStop').disabled=!r.active||r.state==='stopping';
    document.querySelector('#aiStart').disabled=r.active||a.enabled;
    document.querySelector('#aiStop').disabled=!a.enabled;
    const root=document.querySelector('#recordFiles');root.replaceChildren();
    for(const file of r.files){const row=document.createElement('p');const active=r.active&&file.name===r.filename;const link=document.createElement(active?'span':'a');link.textContent=`${file.name} · ${(file.size_bytes/1048576).toFixed(1)} MB${active?' · trwa zapis':' · Pobierz'}`;if(!active){link.href='/recordings/'+encodeURIComponent(file.name);link.download=file.name}row.append(link);root.append(row)}
  }catch(e){document.querySelector('#recordStatus').textContent='Backend niedostępny: '+e.message}
}
setInterval(()=>{if(!recorderView.classList.contains('hidden'))refreshRecorder()},1000);
