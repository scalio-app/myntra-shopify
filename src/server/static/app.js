(() => {
  const lsThemeKey = 'ms_theme';
  const applyTheme = (t) => {
    document.documentElement.setAttribute('data-theme', t);
  };
  const saved = localStorage.getItem(lsThemeKey) || 'light';
  applyTheme(saved);
  document.addEventListener('DOMContentLoaded', () => {
    // Toast helpers
    const toastContainer = document.getElementById('toastContainer');
    const pushToast = (msg, kind='info') => {
      if (!toastContainer) return;
      const div = document.createElement('div');
      const cls = kind === 'error' ? 'alert-error' : kind === 'success' ? 'alert-success' : 'alert-info';
      div.className = `alert ${cls}`;
      div.innerHTML = `<span>${msg}</span>`;
      toastContainer.appendChild(div);
      setTimeout(() => { div.remove(); }, 3000);
    };
    // Flash from storage
    const flash = localStorage.getItem('ms_flash');
    const flashType = localStorage.getItem('ms_flash_type') || 'success';
    if (flash) {
      pushToast(flash, flashType);
      localStorage.removeItem('ms_flash');
      localStorage.removeItem('ms_flash_type');
    }
    const themeBtn = document.getElementById('themeToggle');
    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
        const cur = document.documentElement.getAttribute('data-theme') || 'light';
        const next = cur === 'light' ? 'dark' : 'light';
        localStorage.setItem(lsThemeKey, next);
        applyTheme(next);
      });
    }

    // Job live updates
    const jobDetail = document.querySelector('[data-job-id]');
    if (jobDetail) {
      const id = jobDetail.getAttribute('data-job-id');
      const statusEl = document.getElementById('jobStatus');
      const countsEl = document.getElementById('jobCounts');
      const linkEl = document.getElementById('jobDownload');
      const previewEl = document.getElementById('jobPreview');
      const poll = async () => {
        try {
          const res = await fetch(`/jobs/${id}`);
          if (!res.ok) return;
          const j = await res.json();
          if (statusEl) statusEl.textContent = j.status;
          if (countsEl) countsEl.textContent = JSON.stringify(j.counters || {});
          if (j.status === 'succeeded' && j.result_path && linkEl) {
            linkEl.innerHTML = `<a href="/jobs/${id}/download">Download CSV</a>`;
          }
          if (['queued','running'].includes(j.status)) {
            setTimeout(poll, 2000);
          }
        } catch (e) {
          // silent
        }
      };
      poll();
    }

    // Drag-and-drop upload
    const dz = document.getElementById('dropzone');
    if (dz) {
      const prevent = (e) => { e.preventDefault(); e.stopPropagation(); };
      ['dragenter','dragover','dragleave','drop'].forEach(ev => dz.addEventListener(ev, prevent));
      ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, () => dz.classList.add('dragover')));
      ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, () => dz.classList.remove('dragover')));
      dz.addEventListener('drop', async (e) => {
        const files = Array.from(e.dataTransfer.files || []);
        for (const f of files) {
          const fd = new FormData();
          fd.append('file', f);
          await fetch('/ui/files', { method: 'POST', body: fd });
        }
        localStorage.setItem('ms_flash','Upload complete');
        localStorage.setItem('ms_flash_type','success');
        window.location.href = '/ui';
      });
    }

    // Generic form submit flash messages
    document.body.addEventListener('submit', (e) => {
      try {
        const form = e.target;
        if (!(form instanceof HTMLFormElement)) return;
        const action = (form.getAttribute('action') || '').toLowerCase();
        if (action.includes('/ui/files')) {
          localStorage.setItem('ms_flash','File uploaded');
          localStorage.setItem('ms_flash_type','success');
        } else if (action.includes('/ui/jobs/transform')) {
          localStorage.setItem('ms_flash','Transform job created');
          localStorage.setItem('ms_flash_type','info');
        } else if (action.includes('/ui/jobs/images/by-sku')) {
          localStorage.setItem('ms_flash','Image SKU job created');
          localStorage.setItem('ms_flash_type','info');
        } else if (action.includes('/ui/jobs/images/by-base')) {
          localStorage.setItem('ms_flash','Image base job created');
          localStorage.setItem('ms_flash_type','info');
        } else if (action.includes('/ui/jobs/images/broadcast')) {
          localStorage.setItem('ms_flash','Broadcast job created');
          localStorage.setItem('ms_flash_type','info');
        } else if (action.includes('/ui/settings')) {
          localStorage.setItem('ms_flash','Settings saved');
          localStorage.setItem('ms_flash_type','success');
        }
      } catch {}
    }, true);

    // Test Shopify connection
    const testBtn = document.getElementById('testShopifyBtn');
    if (testBtn) {
      testBtn.addEventListener('click', async () => {
        try {
          const res = await fetch('/ui/settings/test', { method: 'POST' });
          const data = await res.json();
          const el = document.getElementById('shopTestResult');
          if (data.ok) {
            const name = data.shop && (data.shop.name || '');
            const domain = data.shop && (data.shop.domain || '');
            pushToast('Connected to Shopify ✓', 'success');
            if (el) el.textContent = `Shop: ${name} (${domain})`;
          } else {
            pushToast('Shopify connection failed', 'error');
            if (el) el.textContent = `Error: ${data.error || 'Unknown error'}`;
          }
        } catch (e) {
          pushToast('Shopify connection failed', 'error');
          const el = document.getElementById('shopTestResult');
          if (el) el.textContent = `Error: ${e}`;
        }
      });
    }

    // Local staged upload flow
    const folderInput = document.getElementById('localFolderInput');
    const startBtn = document.getElementById('localStartBtn');
    const skuRegexInput = document.getElementById('localSkuRegex');
    const previewTbody = document.getElementById('localPreview');
    const summaryEl = document.getElementById('localSummary');
    const progressEl = document.getElementById('localProgress');
    const linkVariantSel = document.getElementById('localOptionsLinkVariant');
    const altFromSel = document.getElementById('localOptionsAltFrom');
    const delayInput = document.getElementById('localOptionsDelay');

    let localFiles = [];

    const deriveSkuFromPath = (relPath, regex) => {
      const parts = relPath.split('/').slice(0, -1); // drop filename
      for (let i = parts.length - 1; i >= 0; i--) {
        const name = parts[i];
        if (regex.test(name)) return name;
      }
      return '';
    };

    const renderPreview = () => {
      const regex = new RegExp(skuRegexInput.value || '^[A-Za-z0-9-_]+$');
      const groups = new Map();
      for (const f of localFiles) {
        const rel = f.webkitRelativePath || f.name;
        const sku = deriveSkuFromPath(rel, regex);
        if (!sku) continue;
        groups.set(sku, (groups.get(sku) || 0) + 1);
      }
      previewTbody.innerHTML = '';
      Array.from(groups.entries()).slice(0, 50).forEach(([sku, count]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td class="font-mono text-xs">${sku}</td><td>${count}</td>`;
        previewTbody.appendChild(tr);
      });
      summaryEl.textContent = `${localFiles.length} files selected, ${groups.size} SKU folders detected`;
      startBtn.disabled = localFiles.length === 0 || groups.size === 0;
    };

    if (folderInput) {
      folderInput.addEventListener('change', (e) => {
        localFiles = Array.from(folderInput.files || []);
        renderPreview();
      });
    }
    if (skuRegexInput) {
      skuRegexInput.addEventListener('input', renderPreview);
    }

    const stagedParams = async (filesMeta) => {
      const res = await fetch('/uploads/staged/params', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(filesMeta)
      });
      if (!res.ok) throw new Error('Failed to get staged params');
      return res.json();
    };

    const stagedUpload = async (target, file) => {
      // Build FormData with returned parameters + file field
      const fd = new FormData();
      const params = target.parameters || {};
      for (const k of Object.keys(params)) fd.append(k, params[k]);
      // Shopify uses field name 'file' for IMAGE resource staged upload
      fd.append('file', file, target.filename || file.name);
      const resp = await fetch(target.url, { method: 'POST', body: fd });
      if (!resp.ok) throw new Error('Staged upload failed');
      return true;
    };

    const startLocalFlow = async () => {
      try {
        startBtn.disabled = true;
        progressEl.style.display = 'block';
        progressEl.value = 0;
        pushToast('Requesting upload targets…', 'info');
        const filesMeta = localFiles.map(f => ({ filename: f.name, mimeType: f.type || 'image/jpeg', fileSize: f.size }));
        const params = await stagedParams(filesMeta);
        const targets = params.targets || [];
        if (targets.length !== localFiles.length) throw new Error('Target count mismatch');

        const regex = new RegExp(skuRegexInput.value || '^[A-Za-z0-9-_]+$');
        const attachItems = [];
        for (let i = 0; i < localFiles.length; i++) {
          const f = localFiles[i];
          const t = targets[i];
          await stagedUpload(t, f);
          const rel = f.webkitRelativePath || f.name;
          const sku = deriveSkuFromPath(rel, regex);
          const altFrom = altFromSel && altFromSel.value;
          const alt = (altFrom === 'stem') ? (f.name.split('.').slice(0, -1).join('.') || '') : '';
          attachItems.push({ filename: f.name, resourceUrl: t.resourceUrl, sku, alt });
          progressEl.value = Math.round(((i + 1) / localFiles.length) * 100);
        }
        pushToast('Upload complete. Creating attach job…', 'success');
        const attachBody = {
          items: attachItems,
          match_multiple: 'first',
          link_to_variant: (linkVariantSel && linkVariantSel.value === 'true'),
          delay: parseFloat(delayInput && delayInput.value || '0.5') || 0.5,
        };
        const ar = await fetch('/jobs/images/staged/attach-by-sku', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(attachBody) });
        if (!ar.ok) throw new Error('Failed to create attach job');
        const job = await ar.json();
        localStorage.setItem('ms_flash','Attach job created');
        localStorage.setItem('ms_flash_type','success');
        window.location.href = `/ui/jobs/${job.id}`;
      } catch (e) {
        pushToast(`Error: ${e}`, 'error');
        startBtn.disabled = false;
      }
    };

    if (startBtn) startBtn.addEventListener('click', startLocalFlow);
  });
})();
