/* ---------- Report form: live auto-tag + priority preview ---------- */
function initReportForm() {
  const f = document.getElementById('reportForm');
  if (!f) return;
  let timer;
  const $ = id => document.getElementById(id);
  const run = async () => {
    const title = $('title').value, description = $('description').value;
    if ((title + description).trim().length < 4) {
      $('liveEmpty').hidden = false; $('liveBody').hidden = true; return;
    }
    const sev = f.querySelector('input[name=severity]:checked');
    const body = { title, description, category: $('category').value,
                   severity: sev ? sev.value : 'Moderate', safety: $('safety').checked };
    try {
      const r = await fetch('/api/suggest', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      $('liveEmpty').hidden = true; $('liveBody').hidden = false;
      $('lvCat').textContent = d.category + (d.category !== d.detected && $('category').value !== 'Auto-detect' ? ' (selected)' : '');
      $('lvKw').innerHTML = d.keywords.length
        ? d.keywords.map(k => `<span class="chip">${k.replace(/</g,'&lt;')}</span>`).join('') : '<em class="muted">none</em>';
      $('lvSafetyRow').hidden = !d.safety_detected;
      $('lvScore').textContent = d.score; $('lvMax').textContent = d.max_score;
      const bar = $('lvBar'); bar.style.width = Math.round(d.score / d.max_score * 100) + '%';
      bar.className = 'p-' + d.priority.toLowerCase();
      const p = $('lvPrio'); p.textContent = d.priority; p.className = 'badge p-' + d.priority.toLowerCase();
    } catch (e) { /* preview is optional; ignore network errors */ }
  };
  const debounced = () => { clearTimeout(timer); timer = setTimeout(run, 300); };
  f.addEventListener('input', debounced);
  f.addEventListener('change', debounced);
  run();
}

/* ---------- Heatmap ---------- */
function heatColor(t) {            // 0 → green, 0.5 → amber, 1 → red
  const hue = 130 - 130 * t;
  return `hsl(${hue}, 70%, ${t === 0 ? 92 : 62 - 14 * t}%)`;
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function initHeatmap() {
  const zonesEl = document.getElementById('zones');
  let current = [];
  async function load() {
    const mode = document.querySelector('input[name=mode]:checked').value;
    const cat = document.getElementById('catFilter').value;
    const r = await fetch(`/api/heatmap?mode=${mode}&category=${encodeURIComponent(cat)}`);
    const data = await r.json();
    current = data.locations;
    render();
    renderRank();
  }
  function render() {
    const zones = {};
    current.forEach(l => (zones[l.zone] = zones[l.zone] || []).push(l));
    zonesEl.innerHTML = Object.entries(zones).map(([z, locs]) => `
      <h3 class="zone-h">${esc(z)}</h3>
      <div class="tiles">${locs.map(l => `
        <button class="tile" data-name="${esc(l.name)}"
          style="background:${heatColor(l.intensity)}">
          <span class="tn">${esc(l.name)}${l.recurring ? ' <b title="Recurring problem area">↻</b>' : ''}</span>
          <span class="tc">${l.count}</span>
          <span class="ts">${l.count === 1 ? 'issue' : 'issues'}${l.urgent ? ` · ${l.urgent} urgent` : ''}</span>
        </button>`).join('')}</div>`).join('');
    zonesEl.querySelectorAll('.tile').forEach(b => b.onclick = () => showDetail(b.dataset.name));
  }
  function renderRank() {
    const el = document.getElementById('rank');
    const top = current.filter(l => l.count > 0).slice(0, 8);
    el.innerHTML = top.length ? top.map(l =>
      `<li><span>${esc(l.name)}</span><div class="rbar"><i style="width:${l.intensity * 100}%;background:${heatColor(l.intensity)}"></i></div><b>${l.count}</b></li>`
    ).join('') : '<li class="muted">No issues match the filters.</li>';
  }
  function showDetail(name) {
    const l = current.find(x => x.name === name);
    document.getElementById('detail').innerHTML = `
      <h3>${esc(l.name)}</h3>
      <p class="muted">${l.count} issue(s) · ${l.urgent} urgent · avg score ${l.avg_score}${l.top_category ? ' · mostly ' + esc(l.top_category) : ''}${l.recurring ? ' · <b class="red">recurring area</b>' : ''}</p>
      ${l.issues.length ? '<ul class="plain">' + l.issues.map(i => `<li><span class="badge p-${i.priority.toLowerCase()}">${i.priority}</span> <b>${esc(i.ticket)}</b> ${esc(i.title)} <small class="muted">(${esc(i.status)})</small></li>`).join('') + '</ul>' : '<p>No issues here 🎉</p>'}`;
  }
  document.querySelectorAll('input[name=mode]').forEach(i => i.onchange = load);
  document.getElementById('catFilter').onchange = load;
  load();
}

/* ---------- Polished interface details ---------- */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-count]').forEach((node) => {
    const target = Number(node.dataset.count || 0);
    if (!Number.isFinite(target) || target < 1) return;
    const duration = 850;
    const start = performance.now();
    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      node.textContent = Math.round(target * eased).toLocaleString();
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  const current = location.pathname;
  document.querySelectorAll('.nav-links a').forEach((link) => {
    if (link.getAttribute('href') === current) link.classList.add('active');
  });
});

/* ---------- Guided report studio ---------- */
function initReportForm() {
  const f = document.getElementById('reportForm'); if (!f) return;
  let timer, step = 1; const $ = id => document.getElementById(id);
  const sections = [...f.querySelectorAll('[data-section]')];
  const back = $('formBack'), next = $('formNext'), submit = $('submitReport');
  const requiredByStep = {1:['name'],2:['title','description'],3:['location'],4:[]};
  function updateWizard() {
    sections.forEach(s => s.classList.toggle('section-active', Number(s.dataset.section) === step));
    $('formProgressLabel').textContent = `0${step} / 04`;
    $('formProgressBar').style.width = `${step*25}%`;
    back.disabled = step === 1; next.hidden = step === 4; submit.hidden = step !== 4;
    $('stepHint').textContent = ['A few quick details to get started','The more detail, the better','Help us find the right place','Final check before sending'][step-1];
  }
  function validateStep() {
    for (const name of requiredByStep[step] || []) {
      const el = f.elements[name]; if (!el || !el.value.trim() || !el.checkValidity()) { el?.focus(); el?.reportValidity(); return false; }
    }
    return true;
  }
  next?.addEventListener('click', () => { if (validateStep()) { step = Math.min(4,step+1); updateWizard(); if(step===4) $('safety')?.focus({preventScroll:true}); } });
  back?.addEventListener('click', () => { step = Math.max(1,step-1); updateWizard(); });
  f.addEventListener('submit', e => { step=4; updateWizard(); for(let s=1;s<=4;s++){step=s;if(!validateStep()){e.preventDefault();updateWizard();return;}} step=4;updateWizard(); });
  updateWizard();
  const title = $('title'), desc = $('description'), location = $('location'), category = $('category');
  const preview = () => {
    $('previewTitle').textContent = title.value.trim() || 'Your issue title will appear here';
    $('previewDescription').textContent = desc.value.trim() || 'A short description helps the team understand what needs attention.';
    $('previewLocation').textContent = location.value || 'Location pending';
    $('previewCategory').textContent = category.value || 'Auto-detect';
    $('descCount').textContent = desc.value.length;
  };
  [title,desc,location,category].forEach(el=>el?.addEventListener('input',preview));
  f.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{desc.value=(desc.value.trim()?desc.value.trim()+' ':'')+b.dataset.prompt;desc.focus();preview();run();}));
  preview();
  const run = async () => {
    if ((title.value + desc.value).trim().length < 4) { $('liveEmpty').hidden=false; $('liveBody').hidden=true; return; }
    const sev=f.querySelector('input[name=severity]:checked');
    try { const r=await fetch('/api/suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:title.value,description:desc.value,category:category.value,severity:sev?sev.value:'Moderate',safety:$('safety').checked})}); if(!r.ok)return; const d=await r.json();
      $('liveEmpty').hidden=true;$('liveBody').hidden=false;$('lvCat').textContent=d.category+(d.category!==d.detected&&category.value!=='Auto-detect'?' (selected)':'');
      $('lvKw').innerHTML=d.keywords.length?d.keywords.map(k=>`<span class="chip">${esc(k)}</span>`).join(''):'<em class="muted">No matching keywords yet</em>';
      $('lvSafetyRow').hidden=!d.safety_detected;$('lvScore').textContent=d.score;$('lvMax').textContent=d.max_score;$('lvBar').style.width=Math.round(d.score/d.max_score*100)+'%';$('lvBar').className='p-'+d.priority.toLowerCase();$('lvPrio').textContent=d.priority;$('lvPrio').className='badge p-'+d.priority.toLowerCase();
    } catch(e) { /* optional live preview */ }
  };
  const debounce=()=>{clearTimeout(timer);timer=setTimeout(run,280)}; f.addEventListener('input',debounce);f.addEventListener('change',debounce);run();
  const fab=$('helpFab'), pop=$('helpPopover');fab?.addEventListener('click',()=>pop.hidden=!pop.hidden);$('closeHelp')?.addEventListener('click',()=>pop.hidden=true);
}
function initTrackPage(){
  document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',async()=>{const value=b.dataset.copy;try{await navigator.clipboard.writeText(value);const old=b.textContent;b.textContent='Copied ✓';setTimeout(()=>b.textContent=old,1600);}catch(e){b.textContent=value;}}));
  const fab=document.getElementById('trackHelpFab'),pop=document.getElementById('trackHelpPopover');fab?.addEventListener('click',()=>pop.hidden=!pop.hidden);document.getElementById('trackHelpClose')?.addEventListener('click',()=>pop.hidden=true);
}


/* ---------- Visual issue evidence + optional AI vision ---------- */
function initIssuePhotos() {
  const input = document.getElementById('issuePhotos');
  if (!input) return;
  const form = document.getElementById('reportForm');
  const drop = document.getElementById('photoDrop');
  const grid = document.getElementById('photoPreviewGrid');
  const count = document.getElementById('photoCount');
  const analyze = document.getElementById('analyzePhotos');
  const note = document.getElementById('photoActionNote');
  const result = document.getElementById('visualAnalysisResult');
  let selected = [];
  let lastAnalysis = null;
  const maxFiles = 5, maxBytes = 5 * 1024 * 1024;
  const allowed = ['image/jpeg','image/png','image/webp'];
  const say = (message, error=false) => { note.textContent = message; note.classList.toggle('is-error', error); };
  function paint() {
    count.textContent = `${selected.length} / ${maxFiles} photos`;
    grid.innerHTML = '';
    selected.forEach((file, index) => {
      const card = document.createElement('div'); card.className = 'photo-thumb';
      const img = document.createElement('img'); img.alt = `Selected issue photo ${index+1}`;
      const url = URL.createObjectURL(file); img.src = url;
      img.onload = () => URL.revokeObjectURL(url);
      const meta = document.createElement('div'); meta.className = 'photo-thumb-meta';
      const name = document.createElement('span'); name.textContent = file.name;
      const size = document.createElement('small'); size.textContent = `${(file.size/1024/1024).toFixed(1)} MB`;
      const remove = document.createElement('button'); remove.type='button'; remove.textContent='×'; remove.setAttribute('aria-label',`Remove ${file.name}`);
      remove.addEventListener('click',()=>{ selected.splice(index,1); syncInput(); paint(); result.hidden=true; lastAnalysis=null; });
      meta.append(name,size); card.append(img,meta,remove); grid.append(card);
    });
    analyze.disabled = selected.length === 0;
  }
  function syncInput() { const dt = new DataTransfer(); selected.forEach(f=>dt.items.add(f)); input.files = dt.files; }
  function addFiles(files) {
    const incoming = [...files];
    for (const file of incoming) {
      if (selected.length >= maxFiles) { say(`You can attach up to ${maxFiles} photos.`, true); break; }
      if (!allowed.includes(file.type)) { say(`${file.name}: choose a JPG, PNG or WEBP image.`, true); continue; }
      if (file.size > maxBytes) { say(`${file.name}: each photo must be 5 MB or smaller.`, true); continue; }
      if (selected.some(x=>x.name===file.name && x.size===file.size)) continue;
      selected.push(file);
    }
    syncInput(); paint();
    if (selected.length) say('Photos ready. You can analyse them now or submit without analysis.');
  }
  input.addEventListener('change',()=>{addFiles(input.files);});
  ['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag-over');}));
  ['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag-over');}));
  drop.addEventListener('drop',e=>addFiles(e.dataTransfer.files));
  analyze.addEventListener('click', async()=>{
    if (!selected.length) return;
    analyze.disabled=true; analyze.classList.add('is-loading'); analyze.textContent='Analysing photos…';
    say('Reviewing visible details. This can take a few seconds…'); result.hidden=true;
    const data = new FormData(); selected.forEach(file=>data.append('images',file));
    data.append('title',document.getElementById('title')?.value || '');
    data.append('description',document.getElementById('description')?.value || '');
    data.append('severity', form.querySelector('input[name="severity"]:checked')?.value || 'Moderate');
    data.append('safety', document.getElementById('safety')?.checked ? 'true' : 'false');
    const csrf = form.querySelector('input[name="_csrf"]')?.value || '';
    try {
      const response = await fetch('/api/analyze-images',{method:'POST',headers:{'X-CSRF-Token':csrf},body:data});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not analyse these photos.');
      lastAnalysis = payload.result;
      document.getElementById('visualAnalysisMode').textContent = lastAnalysis.analysis_label || 'Analysis suggestions · review before applying';
      document.getElementById('visualModePill').textContent = lastAnalysis.analysis_mode === 'demo' ? 'DEMO' : 'LIVE';
      result.classList.toggle('demo-result', lastAnalysis.analysis_mode === 'demo');
      document.getElementById('visualSummary').textContent=lastAnalysis.visual_summary || 'No visual summary was returned.';
      document.getElementById('visualCategory').textContent=lastAnalysis.suggested_category || 'Other';
      document.getElementById('visualSeverity').textContent=lastAnalysis.suggested_severity || 'Moderate';
      const safety=document.getElementById('visualSafety');
      safety.hidden=!lastAnalysis.safety_flag;
      safety.textContent=lastAnalysis.safety_flag ? `⚠ Possible safety concern: ${lastAnalysis.safety_reason || 'Please have onsite staff verify this immediately.'}` : '';
      document.getElementById('useVisualSafety').hidden=!lastAnalysis.safety_flag;
      document.getElementById('visualCaveat').textContent=lastAnalysis.confidence_note || 'Visual suggestions are not a professional safety inspection.';
      result.hidden=false;
      say(lastAnalysis.analysis_mode === 'demo' ? 'Free demo analysis complete. These are rule-based suggestions from your notes, not image recognition.' : 'OpenAI visual analysis complete. Review each suggestion before applying it.');
    } catch(error) { say(error.message, true); }
    finally { analyze.disabled=selected.length===0; analyze.classList.remove('is-loading'); analyze.innerHTML='✳ Analyse with Corefix <span>→</span>'; }
  });
  document.getElementById('useVisualTitle')?.addEventListener('click',()=>{
    if(!lastAnalysis)return;const field=document.getElementById('title');const text=lastAnalysis.suggested_title || '';if(text){field.value=text.slice(0,120);field.dispatchEvent(new Event('input',{bubbles:true}));say('Suggested title applied. Please review it.');}
  });
  document.getElementById('useVisualDescription')?.addEventListener('click',()=>{
    if(!lastAnalysis)return; const field=document.getElementById('description');
    const text=lastAnalysis.suggested_description || lastAnalysis.visual_summary || '';
    if(text){field.value=(field.value.trim()?field.value.trim()+'\n\n':'')+'Visual notes: '+text;field.dispatchEvent(new Event('input',{bubbles:true}));say('Visual notes added. Please edit them to match what you observed.');}
  });
  document.getElementById('useVisualCategory')?.addEventListener('click',()=>{
    if(!lastAnalysis)return;const field=document.getElementById('category');field.value=lastAnalysis.suggested_category || 'Other';field.dispatchEvent(new Event('change',{bubbles:true}));say('Suggested category applied. You can change it any time.');
  });
  document.getElementById('useVisualSafety')?.addEventListener('click',()=>{
    if(!lastAnalysis?.safety_flag)return;const field=document.getElementById('safety');field.checked=true;field.dispatchEvent(new Event('change',{bubbles:true}));say('Safety risk marked. Keep away from the hazard and contact onsite staff if danger may be immediate.');
  });
  document.getElementById('useVisualSeverity')?.addEventListener('click',()=>{
    if(!lastAnalysis)return;const radio=form.querySelector(`input[name="severity"][value="${CSS.escape(lastAnalysis.suggested_severity || 'Moderate')}"]`);if(radio){radio.checked=true;radio.dispatchEvent(new Event('change',{bubbles:true}));say('Suggested severity selected. Please confirm it is accurate.');}
  });
  document.querySelectorAll('.demo-sample').forEach(sample => sample.addEventListener('click', async () => {
    const oldLabel = sample.querySelector('i').textContent;
    sample.querySelector('i').textContent = 'Loading example…';
    try {
      const response = await fetch(`/static/demo/${encodeURIComponent(sample.dataset.image)}`);
      if (!response.ok) throw new Error('Could not load this sample image.');
      const blob = await response.blob();
      const file = new File([blob], sample.dataset.image, {type: blob.type || 'image/jpeg'});
      selected = [file]; syncInput(); paint();
      const titleField = document.getElementById('title');
      const descField = document.getElementById('description');
      titleField.value = sample.dataset.title;
      descField.value = sample.dataset.description;
      titleField.dispatchEvent(new Event('input', {bubbles:true}));
      descField.dispatchEvent(new Event('input', {bubbles:true}));
      const cat = document.getElementById('category'); cat.value = sample.dataset.category; cat.dispatchEvent(new Event('change',{bubbles:true}));
      const sev = form.querySelector(`input[name="severity"][value="${CSS.escape(sample.dataset.severity)}"]`);
      if (sev) { sev.checked = true; sev.dispatchEvent(new Event('change',{bubbles:true})); }
      const safety = document.getElementById('safety'); safety.checked = sample.dataset.safety === 'true'; safety.dispatchEvent(new Event('change',{bubbles:true}));
      result.hidden = true; lastAnalysis = null;
      say('Sample loaded. Running the free Corefix demo analysis…');
      analyze.click();
      document.getElementById('photoStudioTitle')?.scrollIntoView({behavior:'smooth',block:'center'});
    } catch (error) { say(error.message, true); }
    finally { sample.querySelector('i').textContent = oldLabel; }
  }));
  paint();
}

document.addEventListener('DOMContentLoaded', initIssuePhotos);
