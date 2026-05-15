const dropZone   = document.getElementById('dropZone');
const fileInput  = document.getElementById('fileInput');
const fileList   = document.getElementById('fileList');
const analyzeBtn = document.getElementById('analyzeBtn');
const loader     = document.getElementById('loader');
const results    = document.getElementById('results');

let selectedFiles = [];
let rawTexts = {}; // Store raw extracted text

// ── Drag & drop ──────────────────────────────────────────────────────────────
['dragenter','dragover','dragleave','drop'].forEach(e => dropZone.addEventListener(e, ev => { ev.preventDefault(); ev.stopPropagation(); }));
['dragenter','dragover'].forEach(e => dropZone.addEventListener(e, () => dropZone.classList.add('dragover')));
['dragleave','drop'].forEach(e => dropZone.addEventListener(e, () => dropZone.classList.remove('dragover')));
dropZone.addEventListener('drop', e => addFiles(e.dataTransfer.files));
fileInput.addEventListener('change', e => { addFiles(e.target.files); e.target.value = ''; });

function addFiles(files) {
    for (const f of files) {
        if (!selectedFiles.find(x => x.name === f.name)) selectedFiles.push(f);
    }
    renderFileList();
}

function extOf(name) { return name.split('.').pop().toLowerCase(); }

function renderFileList() {
    fileList.innerHTML = selectedFiles.length === 0 ? '' : selectedFiles.map((f, i) => {
        const ext = extOf(f.name);
        return `<div class="file-item">
            <span class="file-name">
                <span class="badge ${ext}">${ext}</span>
                ${f.name}
            </span>
            <button class="remove-btn" onclick="removeFile(${i})" title="Quitar">✕</button>
        </div>`;
    }).join('');
    analyzeBtn.disabled = selectedFiles.length === 0;
    if (selectedFiles.length === 0) {
        results.style.display = 'none';
        document.getElementById('btnDebug').style.display = 'none';
    }
}

window.removeFile = i => { selectedFiles.splice(i, 1); renderFileList(); };

// ── Analyze ──────────────────────────────────────────────────────────────────
analyzeBtn.addEventListener('click', async () => {
    if (!selectedFiles.length) return;
    loader.style.display = 'block';
    results.style.display = 'none';
    analyzeBtn.disabled = true;

    const fd = new FormData();
    selectedFiles.forEach(f => fd.append('files', f));

    try {
        const res = await fetch('/api/analyze', { method: 'POST', body: fd });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Error del servidor (HTTP ${res.status})`);
        }
        const data = await res.json();
        rawTexts = data.raw_texts || {};
        document.getElementById('btnDebug').style.display = 'block';
        renderResults(data);
    } catch (err) {
        alert('Error al procesar los archivos:\n' + err.message);
        console.error(err);
    } finally {
        loader.style.display = 'none';
        analyzeBtn.disabled = false;
    }
});

// ── Render Results ────────────────────────────────────────────────────────────
function renderResults(data) {
    results.style.display = 'block';

    const banner = document.getElementById('statusBanner');
    if (data.status === 'success') {
        banner.className = 'status-banner status-ok';
        banner.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> ${data.message}`;
    } else {
        banner.className = 'status-banner status-err';
        banner.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> ${data.message}`;
    }

    const filenames = Object.keys(data.findings);
    if (filenames.length === 0) return;
    const fields = Object.keys(data.findings[filenames[0]]);
    const conflictFields = new Set(data.inconsistencies.map(i => i.campo));

    const head = document.getElementById('cmpHead');
    head.innerHTML = `<tr>
        <th>Campo</th>
        ${filenames.map(f => `<th class="file-col" title="${f}">${shortName(f)}</th>`).join('')}
    </tr>`;

    const body = document.getElementById('cmpBody');
    body.innerHTML = fields.map(field => {
        const isConflict = conflictFields.has(field);
        const cells = filenames.map(fn => {
            const entry = data.findings[fn][field];
            const val = entry.val;
            const ctx = entry.ctx;
            const isMissing = !val || val === '—';
            
            if (isMissing) {
                return `<td class="val-col"><div class="val-missing">—</div></td>`;
            }

            return `<td class="val-col">
                <div class="val-found">
                    <span class="val-main">${val}</span>
                    ${ctx ? `
                        <span class="val-trigger" onclick="goToContext('${fn}', \`${ctx.replace(/`/g, '\\`').replace(/'/g, "\\'")}\`)">ver contexto</span>
                    ` : ''}
                </div>
            </td>`;
        }).join('');

        const indicator = isConflict ? `<span class="conflict-indicator"></span>` : '';
        return `<tr class="${isConflict ? 'conflict-row' : ''}">
            <td class="field-col">${indicator}${field}</td>
            ${cells}
        </tr>`;
    }).join('');

    const incSection = document.getElementById('incSection');
    const incList = document.getElementById('incList');

    if (data.inconsistencies.length > 0) {
        incSection.style.display = 'block';
        incList.innerHTML = data.inconsistencies.map(inc => {
            const parts = inc.mensaje.split(' | ').map(p => {
                const m = p.match(/^'(.+)'\s*→\s*'(.+)'\s*(?:\((.+)\))?$/);
                return m ? { file: m[1], val: m[2], ctx: m[3] || '' } : { file: '', val: p, ctx: '' };
            });
            
            const gridItems = parts.map(p => `
                <div class="source-item">
                    <div class="source-header">
                        <span class="source-file">${shortName(p.file)}</span>
                        ${p.ctx ? `<span class="val-trigger" style="font-size:0.6rem" onclick="goToContext('${p.file}', \`${p.ctx.replace(/`/g, '\\`').replace(/'/g, "\\'")}\`)">IR AL DOC</span>` : ''}
                    </div>
                    <div class="source-val">${p.val}</div>
                    ${p.ctx ? `<div class="source-snippet">${p.ctx}</div>` : ''}
                </div>`).join('');
                
            return `<div class="conflict-card">
                <div class="conflict-field-header">
                    <span class="conflict-field-name">${inc.campo}</span>
                    <span class="inc-tag">Discrepancia</span>
                </div>
                <div class="conflict-comparison-grid">${gridItems}</div>
            </div>`;
        }).join('');
    } else {
        incSection.style.display = 'none';
    }
}

function shortName(name) {
    const base = name.replace(/\.[^.]+$/, '');
    return base.length > 20 ? base.slice(0, 18) + '…' : base;
}

// ── Debug Window ─────────────────────────────────────────────────────────────
window.toggleDebugModal = function() {
    const m = document.getElementById('debugModal');
    if (m.style.display === 'none') {
        m.style.display = 'flex';
        // render file list
        const flist = document.getElementById('debugFileList');
        flist.innerHTML = Object.keys(rawTexts).map(kn => `
            <div style="padding:8px 12px; background:white; border:1px solid #cbd5e1; border-radius:6px; margin-bottom:8px; cursor:pointer; font-size:0.8rem; font-weight:600;" onclick="showDebugText('${kn}')">
                ${shortName(kn)}
            </div>
        `).join('');
    } else {
        m.style.display = 'none';
    }
};

window.showDebugText = function(filename) {
    const txt = rawTexts[filename];
    document.getElementById('debugTextContent').textContent = txt ? txt : "No hay texto para este archivo.";
}

window.goToContext = function(filename, fullCtx) {
    // 1. Open Modal
    const modal = document.getElementById('debugModal');
    modal.style.display = 'flex';
    
    // 2. Prepare text
    const rawText = rawTexts[filename] || "";
    const container = document.getElementById('debugTextContent');
    
    // 3. Extract core snippet (removing [Ítem ...] and ...)
    let cleanSnippet = fullCtx.replace(/^\[Ítem\s+[\d\.]+\]\s*\.\.\./, "").replace(/\.\.\.$/, "").trim();
    // Snippets have | instead of \n from _get_context, we need to handle that
    let searchParts = cleanSnippet.split(' | ').map(p => p.trim()).filter(p => p.length > 5);
    
    if (searchParts.length === 0) {
        container.textContent = rawText;
        return;
    }
    
    // We'll search for the first long part
    const searchStr = searchParts[0];
    const index = rawText.indexOf(searchStr);
    
    if (index !== -1) {
        const before = rawText.slice(0, index);
        const match = rawText.slice(index, index + searchStr.length);
        const after = rawText.slice(index + searchStr.length);
        
        container.innerHTML = `${before}<span id="scroll-target" class="highlight-found">${match}</span>${after}`;
        
        // Scroll to it
        setTimeout(() => {
            const target = document.getElementById('scroll-target');
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
    } else {
        container.textContent = rawText;
    }
    
    // Update file list selection if possible (optional)
}
