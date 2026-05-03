const state = {
  status: 'idle',
  timer: null,
  lastFeedKey: '',
};

const PRESET_CONFIG = {
  balanced: 'Sensible defaults for most hunts.',
  quick: 'Fast first pass with shallow depth and low ceremony.',
  polite: 'Lower concurrency and longer delays for fragile targets.',
  'document-heavy': 'Bias toward linked document harvesting and archive context.',
  'javascript-heavy': 'Bias toward rendering and script archaeology.',
};

const MODE_CONFIG = {
  generic: {
    label: 'GENERIC HUNT',
    description: 'Balanced reconnaissance across pages, forms, scripts, and relics.',
    flags: ['scope', 'intel', 'secrets', 'robots', 'render', 'archive', 'dns', 'dry'],
    force: {},
  },
  document: {
    label: 'DOCUMENT HARVESTER',
    description: 'Exhume PDF and office tombs for metadata, authors, internal paths, and mail leaks.',
    flags: ['scope', 'intel', 'robots', 'archive', 'dry'],
    force: { render: false },
  },
  'js-intel': {
    label: 'JS INTELLIGENCE',
    description: 'Read occult JavaScript sigils for hidden routes, tokens, feature flags, and config relics.',
    flags: ['scope', 'secrets', 'robots', 'render', 'archive', 'dry'],
    force: { secrets: true },
  },
  forum: {
    label: 'THREAD NECROMANCY',
    description: 'Reanimate conversations through replies, quotes, and deleted-user shadows.',
    flags: ['scope', 'intel', 'robots', 'render', 'dry'],
    force: {},
  },
  geo: {
    label: 'GEO-INTELLIGENCE',
    description: 'Collect coordinates, place names, and geo tags into map-ready blood trails.',
    flags: ['scope', 'intel', 'robots', 'render', 'dry'],
    force: {},
  },
  news: {
    label: 'NEWS PROPAGATION',
    description: 'Follow one story through outlets, tongues, regions, and mutations.',
    flags: ['scope', 'robots', 'render', 'archive', 'dry'],
    force: {},
  },
  hidden: {
    label: 'SHADOW GATE HUNT',
    description: 'Blend learned paths with a bounded wordlist to find sealed routes and hidden doors.',
    flags: ['scope', 'robots', 'archive', 'dry'],
    force: {},
  },
  scam: {
    label: 'SCAM / DARK PATTERN',
    description: 'Flag fake urgency, coercive funnels, cloned trust marks, and cursed checkout flows.',
    flags: ['scope', 'intel', 'robots', 'render', 'dry'],
    force: {},
  },
  temporal: {
    label: 'TEMPORAL CHANGE',
    description: 'Compare the current harvest against an older night and mark what shifted in silence.',
    flags: ['scope', 'intel', 'secrets', 'robots', 'render', 'archive', 'dns', 'dry'],
    force: {},
  },
};

const els = {
  app: document.getElementById('app'),
  form: document.getElementById('crawlForm'),
  targetUrl: document.getElementById('targetUrl'),
  ritualChain: document.getElementById('ritualChain'),
  crawlPreset: document.getElementById('crawlPreset'),
  inputKind: document.getElementById('inputKind'),
  crawlMode: document.getElementById('crawlMode'),
  depth: document.getElementById('depth'),
  threads: document.getElementById('threads'),
  delay: document.getElementById('delay'),
  timeout: document.getElementById('timeout'),
  scopeDomain: document.getElementById('scopeDomain'),
  extractIntel: document.getElementById('extractIntel'),
  extractSecrets: document.getElementById('extractSecrets'),
  respectRobots: document.getElementById('respectRobots'),
  renderJs: document.getElementById('renderJs'),
  archiveSeeds: document.getElementById('archiveSeeds'),
  dns: document.getElementById('dns'),
  dryRun: document.getElementById('dryRun'),
  beginButton: document.getElementById('beginButton'),
  pauseButton: document.getElementById('pauseButton'),
  stopButton: document.getElementById('stopButton'),
  commandPreview: document.getElementById('commandPreview'),
  statusMessage: document.getElementById('statusMessage'),
  asciiMeter: document.getElementById('asciiMeter'),
  summaryChips: document.getElementById('summaryChips'),
  liveFeed: document.getElementById('liveFeed'),
  errorConsole: document.getElementById('errorConsole'),
  resultPanels: document.getElementById('resultPanels'),
  exportButtons: document.getElementById('exportButtons'),
  recordPath: document.getElementById('recordPath'),
  sealedRecords: document.getElementById('sealedRecords'),
  modeHint: document.getElementById('modeHint'),
  configPreview: document.getElementById('configPreview'),
  resultSearch: document.getElementById('resultSearch'),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formPayload() {
  return {
    target_specimen: els.targetUrl.value.trim(),
    target_url: els.targetUrl.value.trim(),
    ritual_chain: els.ritualChain.value || undefined,
    preset: els.crawlPreset.value,
    input_kind: els.inputKind.value,
    mode: els.crawlMode.value,
    depth: Number(els.depth.value || 2),
    threads: Number(els.threads.value || 4),
    delay: Number(els.delay.value || 0),
    timeout: Number(els.timeout.value || 8),
    scope: els.scopeDomain.checked ? 'domain' : 'host',
    extract_intel: els.extractIntel.checked,
    extract_secrets: els.extractSecrets.checked,
    respect_robots_delay: els.respectRobots.checked,
    render_js: els.renderJs.checked,
    archive_seeds: els.archiveSeeds.checked,
    enumerate_subdomains: els.dns.checked,
    dry_run: els.dryRun.checked,
  };
}

async function renderCommandPreview() {
  const payload = formPayload();
  try {
    const preview = await postJson('/api/preview', payload);
    els.commandPreview.textContent = `> ${preview.command_preview}`;
    const resolved = preview.resolved || {};
    els.configPreview.textContent = [
      `Specimen: ${resolved.specimen?.type || 'auto'}`,
      `Ritual: ${resolved.ritual_chain || 'domain_necropsy'}`,
      `Mode: ${resolved.mode || 'generic'}`,
      `Preset: ${resolved.preset || 'balanced'} // ${PRESET_CONFIG[resolved.preset || 'balanced'] || ''}`,
      `Target URL: ${resolved.target_url || '-'}`,
      `Depth=${resolved.depth} Threads=${resolved.threads} Delay=${resolved.delay} Timeout=${resolved.timeout}`,
      `Flags: scope=${resolved.scope} render=${resolved.render_js} archive=${resolved.archive_seeds} dns=${resolved.enumerate_subdomains} dry=${resolved.dry_run}`,
    ].join('\n');
  } catch (error) {
    els.commandPreview.textContent = `> CRAWL ${payload.target_specimen || 'https://example.com'} --depth ${payload.depth}`;
    els.configPreview.textContent = String(error.message || error);
  }
}

function syncModeControls() {
  const config = MODE_CONFIG[els.crawlMode.value] || MODE_CONFIG.generic;
  els.modeHint.textContent = `${config.label} // ${config.description}`;
  document.querySelectorAll('[data-flag]').forEach((node) => {
    node.classList.toggle('is-hidden', !config.flags.includes(node.dataset.flag));
  });
  if (Object.prototype.hasOwnProperty.call(config.force, 'secrets')) {
    els.extractSecrets.checked = config.force.secrets;
  }
  if (Object.prototype.hasOwnProperty.call(config.force, 'render')) {
    els.renderJs.checked = config.force.render;
  }
  renderCommandPreview();
}

function buildMeter(data) {
  const visited = Number(data.summary?.visited || 0);
  const failures = Number(data.summary?.failures || 0);
  if (data.status === 'running') {
    const cursor = visited % 12;
    const chars = Array.from({ length: 16 }, (_, index) => {
      if (index >= cursor && index < cursor + 4) return '█';
      return index < visited % 16 ? '▓' : '░';
    });
    return `[${chars.join('')}] DESCENT IN PROGRESS // ${visited} VISITED // ${failures} OMENS`;
  }
  if (data.status === 'complete') {
    return `[████████████████] CRAWL SEALED // ${visited} VISITED`;
  }
  if (data.status === 'paused') {
    return `[██████░░░░░░░░░░] RITE SUSPENDED // ${visited} VISITED`;
  }
  if (data.status === 'error' || data.status === 'blocked' || data.status === 'stopping') {
    return `[███░░░░░░░░░░░░░] OMEN DETECTED // ${failures} BROKEN GATES`;
  }
  return '[░░░░░░░░░░░░░░░░] IDLE';
}

function renderSummary(data) {
  const summary = data.summary || {};
  const chips = summary.summary_cards || [];
  els.summaryChips.innerHTML = chips.map((item) => `
    <div class="summary-chip">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
    </div>
  `).join('');
}

function renderPanels(data) {
  const panels = data.panels || [];
  els.resultPanels.innerHTML = panels.map((panel) => `
    <section class="terminal-panel">
      <div class="panel-title">${escapeHtml(panel.title)} // ${escapeHtml(panel.count)}</div>
      <div class="result-list">
        ${(panel.items && panel.items.length)
          ? panel.items.map((item) => `<div class="result-item" data-decrypt>${escapeHtml(item)}</div>`).join('')
          : '<span class="empty-note">THE ARCHIVE IS SILENT</span>'}
      </div>
    </section>
  `).join('');
  attachDecryptHover();
  applyResultFilter();
}

function renderExports(data) {
  if (!data.exports || !data.exports.length) {
    els.exportButtons.innerHTML = '<span class="empty-note">THE ARCHIVE IS SILENT</span>';
  } else {
    els.exportButtons.innerHTML = data.exports.map((item) => `
      <a class="export-link" href="${escapeHtml(item.href)}">${escapeHtml(item.label)}</a>
    `).join('');
  }
  els.recordPath.textContent = data.output_dir ? `SEALED PATH // ${data.output_dir}` : '';
}

function renderRecords(data) {
  const records = data.sealed_records || [];
  els.sealedRecords.innerHTML = records.length
    ? records.map((record) => `
      <div class="record-card">
        <div class="panel-title">${escapeHtml(record.status_message || record.status)}</div>
        <strong>${escapeHtml(record.target_url || record.id)}</strong>
        <div>${escapeHtml(record.mode || 'generic')} // ${escapeHtml(record.status || '')}</div>
        <div>${escapeHtml(record.ended_at || '')}</div>
      </div>
    `).join('')
    : '<span class="empty-note">NO SEALED RECORDS YET</span>';
}

function renderState(data) {
  state.status = data.status || 'idle';
  els.app.dataset.status = state.status;
  els.statusMessage.textContent = data.status_message || 'THE CRAWLER SLEEPS';
  els.asciiMeter.textContent = buildMeter(data);
  renderSummary(data);
  els.liveFeed.textContent = (data.feed && data.feed.length) ? data.feed.join('\n') : 'Awaiting target acquisition…';
  els.errorConsole.textContent = (data.errors && data.errors.length)
    ? data.errors.join('\n')
    : ((data.logs && data.logs.length) ? data.logs.slice(-18).join('\n') : 'No omens yet.');
  renderPanels(data);
  renderExports(data);
  renderRecords(data);
  els.pauseButton.disabled = !data.can_pause;
  els.stopButton.disabled = !data.can_stop;
  els.beginButton.disabled = data.status === 'running' || data.status === 'paused' || data.status === 'stopping';
  els.pauseButton.textContent = data.can_resume ? '> REAWAKEN THE RITE' : '> SUSPEND THE RITE';
  syncModeControls();
}

async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || 'The rite failed.');
  }
  return data;
}

async function refreshState() {
  try {
    const response = await fetch('/api/state');
    const data = await response.json();
    renderState(data);
  } catch (error) {
    els.errorConsole.textContent = String(error.message || error);
  }
}

async function beginCrawl() {
  const payload = formPayload();
  if (!payload.target_specimen) {
    els.errorConsole.textContent = 'TARGET SPECIMEN is required.';
    els.targetUrl.focus();
    return;
  }
  try {
    const data = await postJson('/api/crawl', payload);
    renderState(data);
  } catch (error) {
    els.errorConsole.textContent = String(error.message || error);
  }
}

async function togglePause() {
  try {
    const endpoint = state.status === 'paused' ? '/api/crawl/resume' : '/api/crawl/pause';
    const data = await postJson(endpoint);
    renderState(data);
  } catch (error) {
    els.errorConsole.textContent = String(error.message || error);
  }
}

async function stopCrawl() {
  try {
    const data = await postJson('/api/crawl/stop');
    renderState(data);
  } catch (error) {
    els.errorConsole.textContent = String(error.message || error);
  }
}

function decryptText(node) {
  const target = node.dataset.original || node.textContent;
  node.dataset.original = target;
  const glyphs = '†‡▒░█<>/{}[]';
  let frame = 0;
  clearInterval(node._decryptTimer);
  node._decryptTimer = setInterval(() => {
    frame += 1;
    node.textContent = target.split('').map((char, index) => {
      if (char === ' ') return ' ';
      return index < frame ? target[index] : glyphs[Math.floor(Math.random() * glyphs.length)];
    }).join('');
    if (frame >= target.length) {
      clearInterval(node._decryptTimer);
      node.textContent = target;
    }
  }, 18);
}

function attachDecryptHover() {
  document.querySelectorAll('[data-decrypt]').forEach((node) => {
    if (node.dataset.bound === 'true') return;
    node.dataset.bound = 'true';
    node.addEventListener('mouseenter', () => decryptText(node));
    node.addEventListener('focus', () => decryptText(node));
  });
}

function applyResultFilter() {
  const query = (els.resultSearch?.value || '').trim().toLowerCase();
  document.querySelectorAll('.result-item').forEach((node) => {
    const visible = !query || node.textContent.toLowerCase().includes(query);
    node.style.display = visible ? '' : 'none';
  });
  document.querySelectorAll('#resultPanels .terminal-panel').forEach((panel) => {
    const anyVisible = Array.from(panel.querySelectorAll('.result-item')).some((item) => item.style.display !== 'none');
    const hasEmpty = panel.querySelector('.empty-note');
    panel.style.display = (anyVisible || hasEmpty || !query) ? '' : 'none';
  });
}

['input', 'change'].forEach((eventName) => {
  els.form.addEventListener(eventName, renderCommandPreview);
});
els.form.addEventListener('submit', (event) => {
  event.preventDefault();
  beginCrawl();
});
els.form.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  if (event.target instanceof HTMLTextAreaElement) return;
  event.preventDefault();
  beginCrawl();
});
els.crawlMode.addEventListener('change', syncModeControls);
els.resultSearch.addEventListener('input', applyResultFilter);

els.beginButton.addEventListener('click', beginCrawl);
els.pauseButton.addEventListener('click', togglePause);
els.stopButton.addEventListener('click', stopCrawl);

syncModeControls();
refreshState();
state.timer = setInterval(refreshState, 1500);
