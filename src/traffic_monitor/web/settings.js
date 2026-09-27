const fpsInput=document.querySelector('#analysisFpsInput');
const confidenceInput=document.querySelector('#confidenceInput');
const trackHighInput=document.querySelector('#trackHighInput');
const trackLowInput=document.querySelector('#trackLowInput');
const newTrackInput=document.querySelector('#newTrackInput');
const trackingGraceInput=document.querySelector('#trackingGraceInput');
const backendInput=document.querySelector('#inferenceBackend');
const calibrationBackendInput=document.querySelector('#calibrationBackend');
const previewFpsInput=document.querySelector('#previewFpsInput');
const calibrationBackendStatus=document.querySelector('#calibrationBackendStatus');
const settingsMessage=document.querySelector('#analysisSettingsMessage');
let settingsLoaded=false;
let calibrationBackendDirty=false;
function backendName(value){return ({ultralytics_auto:'Automatycznie (NVIDIA/CPU)',ultralytics_cuda:'NVIDIA / CUDA',openvino_intel_gpu:'Intel Iris Xe / OpenVINO',ultralytics_cpu:'CPU'})[value]||value}
function syncCalibrationBackend(value,previewFps=3){
  const backend=value||'ultralytics_auto';
  calibrationBackendInput.value=backend;
  backendInput.value=backend;
  previewFpsInput.value=previewFps;
  calibrationBackendDirty=false;
  calibrationBackendStatus.textContent=`Zapisany silnik: ${backendName(backend)}.`;
}
calibrationBackendInput.onchange=()=>{
  calibrationBackendDirty=true;
  calibrationBackendStatus.textContent=`Wybrano ${backendName(calibrationBackendInput.value)}, ale jeszcze nie zapisano. Kliknij „Zapisz silnik i podgląd”.`;
};
previewFpsInput.oninput=()=>{calibrationBackendDirty=true;calibrationBackendStatus.textContent=`Limit podglądu ${previewFpsInput.value} kl./s jest niezapisany. Kliknij „Zapisz silnik i podgląd”.`};
document.querySelector('#saveCalibrationBackend').onclick=async()=>{
  if(!previewFpsInput.reportValidity())return;
  const button=document.querySelector('#saveCalibrationBackend');button.disabled=true;
  try{
    const response=await fetch('/api/analysis/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inference_backend:calibrationBackendInput.value,preview_fps:Number(previewFpsInput.value)})});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Błąd zapisu');
    if(state.config){state.config.inference_backend=result.config.inference_backend;state.config.preview_fps=result.config.preview_fps}
    syncCalibrationBackend(result.config.inference_backend,result.config.preview_fps);
    await refreshSettings();
  }catch(e){calibrationBackendStatus.textContent='Nie zapisano silnika: '+e.message}
  finally{button.disabled=false}
};
async function refreshSettings(){
  try{
    const [config,status]=await Promise.all([fetch('/api/config').then(r=>r.json()),fetch('/api/analyzer/status').then(r=>r.json())]);
    if(!settingsLoaded){fpsInput.value=config.analysis_fps??6;confidenceInput.value=config.detection_confidence??.20;trackHighInput.value=config.track_high_thresh??.25;trackLowInput.value=config.track_low_thresh??.10;newTrackInput.value=config.new_track_thresh??.25;trackingGraceInput.value=config.tracking_grace_s??.5;if(!calibrationBackendDirty)syncCalibrationBackend(config.inference_backend,config.preview_fps??3);settingsLoaded=true}
    const active=status.enabled??status.running;
    if(!calibrationBackendDirty){
      const saved=config.inference_backend??'ultralytics_auto';
      const actual=active?backendName(status.inference_backend):'wyłączony';
      const restart=active&&status.inference_backend!==saved?' · Uruchom analizę od początku, aby zastosować wybór.':'';
      calibrationBackendStatus.textContent=`Zapisany: ${backendName(saved)}, podgląd ${config.preview_fps??3} kl./s · W tej sesji: ${actual}, podgląd ${status.preview_fps_target??'?'} kl./s${status.inference_backend_error?' · '+status.inference_backend_error:''}${restart}`;
    }
    document.querySelector('#previewHint').textContent=`Limit podglądu AI: ${status.preview_fps_target??config.preview_fps??3} kl./s. ${status.source_kind==='camera'?'Live: najnowsze klatki z RTSP, czas z PTS.':'MP4: wszystkie klatki po kolei, czas z PTS.'}`;
    const confirmed=active&&status.lane_distances_m;
    const distances=confirmed?Object.entries(status.lane_distances_m):(config.lanes||[]).map(l=>[l.id,l.distance_m]);
    document.querySelector('#measurementDistances').textContent=distances.map(([id,d])=>`${id}: ${d} m`).join(' · ')||'Brak skonfigurowanych pasów';
    document.querySelector('#distanceSource').textContent=confirmed?'Wartości używane przez działający silnik.':active?'Wartości zapisane w profilu; backend nie potwierdził jeszcze aktywnych odległości.':'Wartości zapisane w profilu — AI wyłączone.';
    if(active&&status.inference_backend_requested){settingsMessage.textContent=`Silnik: ${status.inference_backend}${status.inference_backend_error?' · GPU/CPU niedostępne: '+status.inference_backend_error:''}`}
  }catch(e){settingsMessage.textContent='Nie można odczytać ustawień: '+e.message;document.querySelector('#distanceSource').textContent='Nie udało się odświeżyć — ostatni odczyt może być nieaktualny.'}
}
document.querySelector('#saveAnalysisSettings').onclick=async()=>{
  if(!fpsInput.reportValidity()||!confidenceInput.reportValidity()||!trackHighInput.reportValidity()||!trackLowInput.reportValidity()||!newTrackInput.reportValidity()||!trackingGraceInput.reportValidity())return;
  if(Number(trackLowInput.value)>Number(trackHighInput.value)){settingsMessage.textContent='Niski prog trackera nie moze byc wyzszy od wysokiego.';return}
  const button=document.querySelector('#saveAnalysisSettings');button.disabled=true;
  try{
    const response=await fetch('/api/analysis/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_fps:Number(fpsInput.value),detection_confidence:Number(confidenceInput.value),track_high_thresh:Number(trackHighInput.value),track_low_thresh:Number(trackLowInput.value),new_track_thresh:Number(newTrackInput.value),tracking_grace_s:Number(trackingGraceInput.value),inference_backend:backendInput.value})});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Błąd zapisu');
    if(state.config){state.config.analysis_fps=result.config.analysis_fps;state.config.detection_confidence=result.config.detection_confidence;state.config.inference_backend=result.config.inference_backend}
    syncCalibrationBackend(result.config.inference_backend,result.config.preview_fps??3);
    const status=await fetch('/api/analyzer/status').then(r=>r.json());
    if(status.enabled&&status.source_kind==='file'){
      await postJson('/api/analyzer/stop');
      await postJson('/api/analyzer/start',{source:'file'});
      delete liveFrame.dataset.evidence;
      liveFrame.src='/api/live.mjpg?t='+Date.now();
      settingsMessage.textContent='Zapisano. Analiza MP4 została uruchomiona od początku z nowymi ustawieniami.';
    }else settingsMessage.textContent='Zapisano. Działające AI zastosuje parametry przy kolejnej klatce.';
  }catch(e){settingsMessage.textContent=e.message}finally{button.disabled=false}
};
document.querySelector('#recommendedTrackingSettings').onclick=()=>{
  confidenceInput.value='0.005';
  trackHighInput.value='0.050';
  trackLowInput.value='0.010';
  newTrackInput.value='0.100';
  trackingGraceInput.value='2.0';
  settingsMessage.textContent='Wpisano ustawienia zalecane. Kliknij Zapisz ustawienia, aby je zastosowac.';
};
refreshSettings();setInterval(()=>{if(!document.hidden)refreshSettings()},3000);
