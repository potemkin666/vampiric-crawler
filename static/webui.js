const state = {
  status: 'idle',
  timer: null,
  viewRunId: null,
  lastFeedKey: '',
  sortKey: 'discovery_time',
  lastState: null,
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
    description: 'Blend learned paths with a bounded wordlist, and show which probe came from which source.',
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
  hiddenWords: document.getElementById('hiddenWords'),
  temporalBaseline: document.getElementById('temporalBaseline'),
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
  flagStatus: document.getElementById('flagStatus'),
  setupCheckStatus: document.getElementById('setupCheckStatus'),
  setupCheckDetail: document.getElementById('setupCheckDetail'),
  rerunSetupCheckButton: document.getElementById('rerunSetupCheckButton'),
  liveFeed: document.getElementById('liveFeed'),
  errorConsole: document.getElementById('errorConsole'),
  resultPanels: document.getElementById('resultPanels'),
  exportButtons: document.getElementById('exportButtons'),
  recordPath: document.getElementById('recordPath'),
  sealedRecords: document.getElementById('sealedRecords'),
  modeHint: document.getElementById('modeHint'),
  configPreview: document.getElementById('configPreview'),
  resultSearch: document.getElementById('resultSearch'),
  pauseStateBanner: document.getElementById('pauseStateBanner'),
  pauseStateDetail: document.getElementById('pauseStateDetail'),
  queuePanel: document.getElementById('queuePanel'),
  robotsPanel: document.getElementById('robotsPanel'),
  sitemapPanel: document.getElementById('sitemapPanel'),
  resultSort: document.getElementById('resultSort'),
  resultStateFilter: document.getElementById('resultStateFilter'),
  resultErrorFilter: document.getElementById('resultErrorFilter'),
  resultTypeFilter: document.getElementById('resultTypeFilter'),
  resultSourceFilter: document.getElementById('resultSourceFilter'),
  resultLedger: document.getElementById('resultLedger'),
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
    hidden_words: els.hiddenWords.value.trim(),
    temporal_baseline: els.temporalBaseline.value.trim(),
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
      `Shadow words: ${(resolved.hidden_words || []).join(', ') || '-'}`,
      `Temporal baseline: ${resolved.temporal_baseline || '-'}`,
    ].join('\n');
  } catch (error) {
    els.commandPreview.textContent = `> CRAWL ${payload.target_specimen || 'https://example.com'} --depth ${payload.depth}`;
    els.configPreview.textContent = `Failed to load preview: ${String(error.message || error)}`;
  }
}

function syncModeControls() {
  const config = MODE_CONFIG[els.crawlMode.value] || MODE_CONFIG.generic;
  els.modeHint.textContent = `${config.label} // ${config.description}`;
  document.querySelectorAll('[data-flag]').forEach((node) => {
    const visible = config.flags.includes(node.dataset.flag);
    node.classList.toggle('is-hidden', !visible);
    const input = node.querySelector('input');
    if (input) {
      input.disabled = !visible;
      input.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }
  });
  if (Object.prototype.hasOwnProperty.call(config.force, 'secrets')) {
    els.extractSecrets.checked = config.force.secrets;
  }
  if (Object.prototype.hasOwnProperty.call(config.force, 'render')) {
    els.renderJs.checked = config.force.render;
  }
  announceFlagSummary(`Mode changed to ${config.label}. ${describeVisibleFlags()}`);
  renderCommandPreview();
}

function describeVisibleFlags() {
  const visibleFlags = Array.from(document.querySelectorAll('.flag-option:not(.is-hidden) .flag-label'))
    .map((node) => node.textContent.trim());
  return visibleFlags.length ? `Visible flags: ${visibleFlags.join(', ')}.` : 'No flag controls are visible.';
}

function announceFlagSummary(message) {
  if (!els.flagStatus) return;
  els.flagStatus.textContent = message;
}

function bindFlagAnnouncements() {
  document.querySelectorAll('.flag-option input').forEach((input) => {
    input.addEventListener('change', () => {
      const label = input.closest('.flag-option')?.querySelector('.flag-label')?.textContent?.trim() || 'Flag';
      announceFlagSummary(`${label} ${input.checked ? 'enabled' : 'disabled'}. ${describeVisibleFlags()}`);
    });
  });
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

function renderSetupDiagnostics(data) {
  const checks = data.checks || [];
  els.setupCheckStatus.textContent = data.status_message || 'FIRST-RUN DIAGNOSTICS FOUND ISSUES';
  els.setupCheckDetail.textContent = [
    `Overall: ${data.overall_status || 'issues'}`,
    `Output dir: ${data.output_dir?.status || '-'} // ${data.output_dir?.path || '-'}`,
    `Proxy: ${data.proxy?.status || '-'} // ${data.proxy?.detail || '-'}`,
    '',
    ...checks.map((item) => `${item.name} => ${item.status}${item.detail ? ` // ${item.detail}` : ''}`),
  ].join('\n');
}

function renderPanels(data) {
  const panels = data.panels || [];
  els.resultPanels.innerHTML = panels.map((panel) => `
    <section class="terminal-panel" id="panel-${escapeHtml(panel.key || 'panel')}">
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
    ? [
      data.is_historical ? '<button type="button" class="terminal-button record-open" data-run-id="">> RETURN TO CURRENT RITE</button>' : '',
      ...records.map((record) => `
       <div class="record-card">
         <div class="panel-title">${escapeHtml(record.status_message || record.status)}</div>
         <strong>${escapeHtml(record.target_url || record.id)}</strong>
         <div>${escapeHtml(record.mode || 'generic')} // ${escapeHtml(record.status || '')}</div>
         <div>${escapeHtml(record.ended_at || '')}</div>
         <div class="result-link-list">
           <button type="button" class="terminal-button record-open" data-run-id="${escapeHtml(record.id || '')}">REOPEN RECORD</button>
           ${(record.exports || []).map((item) => `<a class="result-link" href="${escapeHtml(item.href)}">${escapeHtml(item.kind)}</a>`).join(' ')}
         </div>
       </div>
      `),
    ].join('')
    : '<span class="empty-note">NO SEALED RECORDS YET</span>';
  els.sealedRecords.querySelectorAll('.record-open').forEach((button) => {
    button.addEventListener('click', async () => {
      const runId = button.dataset.runId || '';
      if (!runId) {
        state.viewRunId = null;
        refreshState();
        return;
      }
      await openSealedRecord(runId);
    });
  });
}

function renderPauseState(data) {
  const paused = data.status === 'paused';
  const resumeReady = Boolean(data.can_resume);
  els.pauseStateBanner.textContent = paused
    ? 'RITE PAUSED — RESUME IS AVAILABLE'
    : (data.status === 'running' ? 'RITE RUNNING — PAUSE IS AVAILABLE' : 'NO SUSPENDED RITE');
  els.pauseStateDetail.textContent = [
    `Status: ${data.status_message || 'THE CRAWLER SLEEPS'}`,
    `Detail: ${data.status_detail || 'Awaiting the next command.'}`,
    `Pause button: ${data.can_pause ? 'enabled' : 'disabled'}`,
    `Resume button: ${resumeReady ? 'enabled' : 'disabled'}`,
  ].join('\n');
}

function renderQueue(data) {
  const queue = data.queue || {};
  const order = ['pending', 'active', 'completed', 'skipped'];
  els.queuePanel.innerHTML = order.map((key) => {
    const bucket = queue[key] || { count: 0, items: [] };
    return `
      <section class="queue-card">
        <div class="panel-title">${escapeHtml(key)}</div>
        <strong>${escapeHtml(bucket.count)}</strong>
        <div class="queue-items">
          ${(bucket.items && bucket.items.length)
            ? bucket.items.map((item) => `<div class="result-item">${escapeHtml(item)}</div>`).join('')
            : '<span class="empty-note">NONE</span>'}
        </div>
      </section>
    `;
  }).join('');
}

function renderRobots(data) {
  const robots = data.robots_details || {};
  const rules = robots.rules || [];
  els.robotsPanel.textContent = rules.length
    ? [
      `Crawl-delay: ${robots.crawl_delay ?? 'none'}`,
      '',
      ...rules.map((rule) => `${rule.directive || 'RULE'} ${rule.path || ''}`.trim()),
    ].join('\n')
    : 'No robots rules observed yet.';
}

function renderSitemaps(data) {
  const sitemap = data.sitemap_details || {};
  const sitemapUrls = sitemap.sitemap_urls || [];
  const queuedUrls = sitemap.queued_urls || [];
  els.sitemapPanel.textContent = (sitemapUrls.length || queuedUrls.length)
    ? [
      'SITEMAP URLS',
      ...(sitemapUrls.length ? sitemapUrls : ['-']),
      '',
      'QUEUED URLS',
      ...(queuedUrls.length ? queuedUrls : ['-']),
    ].join('\n')
    : 'No sitemap sigils observed yet.';
}

function sortedResultRows(rows) {
  const sortKey = state.sortKey || 'discovery_time';
  return [...(rows || [])].sort((left, right) => {
    const a = left?.[sortKey];
    const b = right?.[sortKey];
    if (sortKey === 'status_code' || sortKey === 'depth' || sortKey === 'discovery_time') {
      return (Number(a || 0) - Number(b || 0)) || String(left.url || '').localeCompare(String(right.url || ''));
    }
    return String(a || '').localeCompare(String(b || '')) || String(left.url || '').localeCompare(String(right.url || ''));
  });
}

function populateLedgerFilterOptions(rows) {
  const filters = [
    { node: els.resultStateFilter, values: rows.map((row) => row.state).filter(Boolean), fallback: 'ALL STATES' },
    { node: els.resultErrorFilter, values: rows.map((row) => row.error_kind).filter(Boolean), fallback: 'ALL ERRORS' },
    { node: els.resultTypeFilter, values: rows.map((row) => row.content_type).filter(Boolean), fallback: 'ALL TYPES' },
    { node: els.resultSourceFilter, values: rows.map((row) => row.source_kind).filter(Boolean), fallback: 'ALL SOURCES' },
  ];
  filters.forEach(({ node, values, fallback }) => {
    const previous = node.value;
    const options = [''].concat([...new Set(values)].sort((left, right) => String(left).localeCompare(String(right))));
    node.innerHTML = options.map((value) => (
      `<option value="${escapeHtml(value)}">${escapeHtml(value || fallback)}</option>`
    )).join('');
    node.value = options.includes(previous) ? previous : '';
  });
}

function filteredResultRows(rows) {
  const query = (els.resultSearch?.value || '').trim().toLowerCase();
  return sortedResultRows(rows).filter((row) => {
    if (els.resultStateFilter.value && row.state !== els.resultStateFilter.value) return false;
    if (els.resultErrorFilter.value && row.error_kind !== els.resultErrorFilter.value) return false;
    if (els.resultTypeFilter.value && row.content_type !== els.resultTypeFilter.value) return false;
    if (els.resultSourceFilter.value && row.source_kind !== els.resultSourceFilter.value) return false;
    if (query && !JSON.stringify(row).toLowerCase().includes(query)) return false;
    return true;
  });
}

function renderResultLedger(data) {
  const allRows = data.result_rows || [];
  populateLedgerFilterOptions(allRows);
  const rows = filteredResultRows(allRows);
  const exportLinks = new Map((data.exports || []).map((item) => [item.kind, item.href]));
  els.resultLedger.innerHTML = rows.length
    ? rows.map((row) => `
      <article class="result-row" data-result-row>
        <strong>${escapeHtml(row.url || '-')}</strong>
        <div class="result-meta">
          <span>state=${escapeHtml(row.state || '-')}</span>
          <span>status=${escapeHtml(row.status_code ?? '-')}</span>
          <span>type=${escapeHtml(row.content_type || '-')}</span>
          <span>depth=${escapeHtml(row.depth ?? '-')}</span>
          <span>source=${escapeHtml(row.source_page || '-')}</span>
          <span>source_kind=${escapeHtml(row.source_kind || '-')}</span>
          <span>discovery=#${escapeHtml(row.discovery_time ?? 0)}</span>
        </div>
        ${(row.error_message || row.error_kind)
          ? `<div class="result-error">${escapeHtml(row.error_message || row.error_kind)}</div>`
          : ''}
        <details class="result-trace">
          <summary>TRACE</summary>
          <div class="result-trace-grid">
            <div><strong>DISCOVERY PATH</strong><div>${escapeHtml((row.discovery_path || []).join(' -> ') || '-')}</div></div>
            <div><strong>REDIRECT CHAIN</strong><div>${escapeHtml((row.redirect_chain || []).join(' -> ') || '-')}</div></div>
            <div><strong>RELATED PANEL</strong><div>${
              row.related_panel_key
                ? `<a class="result-link" href="#panel-${escapeHtml(row.related_panel_key)}">${escapeHtml(row.related_panel_title || row.related_panel_key)}</a>`
                : '-'
            }</div></div>
            <div><strong>EXPORTS</strong><div class="result-link-list">${
              (row.export_kinds || [])
                .filter((kind) => exportLinks.has(kind))
                .map((kind) => `<a class="result-link" href="${escapeHtml(exportLinks.get(kind) || '#')}">${escapeHtml(kind)}</a>`)
                .join(' ') || `<a class="result-link" href="#exportPanel">sealed exports</a>`
            }</div></div>
          </div>
        </details>
      </article>
    `).join('')
    : '<span class="empty-note">NO RESULT RECORDS YET</span>';
}

function renderState(data) {
  state.lastState = data;
  state.viewRunId = data.is_historical ? (data.id || null) : null;
  state.status = data.status || 'idle';
  els.app.dataset.status = state.status;
  els.statusMessage.textContent = data.status_message || 'THE CRAWLER SLEEPS';
  els.asciiMeter.textContent = buildMeter(data);
  renderSummary(data);
  els.liveFeed.textContent = (data.feed && data.feed.length) ? data.feed.join('\n') : 'Awaiting target acquisition…';
  els.errorConsole.textContent = (data.errors && data.errors.length)
    ? data.errors.join('\n')
    : ((data.logs && data.logs.length) ? data.logs.slice(-18).join('\n') : 'No omens yet.');
  renderPauseState(data);
  renderQueue(data);
  renderRobots(data);
  renderSitemaps(data);
  renderResultLedger(data);
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
    const endpoint = state.viewRunId ? `/api/runs/${encodeURIComponent(state.viewRunId)}` : '/api/state';
    const response = await fetch(endpoint);
    const data = await response.json();
    renderState(data);
  } catch (error) {
    els.errorConsole.textContent = String(error.message || error);
  }
}

async function openSealedRecord(runId) {
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error('The sealed record could not be reopened.');
    const data = await response.json();
    renderState(data);
  } catch (error) {
    els.errorConsole.textContent = String(error.message || error);
  }
}

async function refreshSetupDiagnostics() {
  try {
    els.setupCheckStatus.textContent = 'RUNNING FIRST-RUN DIAGNOSTICS…';
    const response = await fetch('/api/setup-check');
    const data = await response.json();
    renderSetupDiagnostics(data);
  } catch (error) {
    els.setupCheckStatus.textContent = 'FIRST-RUN DIAGNOSTICS FOUND ISSUES';
    els.setupCheckDetail.textContent = String(error.message || error);
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
els.resultSearch.addEventListener('input', () => {
  if (state.lastState) {
    renderResultLedger(state.lastState);
  }
  applyResultFilter();
});
els.resultSort.addEventListener('change', () => {
  state.sortKey = els.resultSort.value;
  if (state.lastState) {
    renderResultLedger(state.lastState);
  }
});
['resultStateFilter', 'resultErrorFilter', 'resultTypeFilter', 'resultSourceFilter'].forEach((key) => {
  els[key].addEventListener('change', () => {
    if (state.lastState) {
      renderResultLedger(state.lastState);
    }
  });
});

els.beginButton.addEventListener('click', beginCrawl);
els.pauseButton.addEventListener('click', togglePause);
els.stopButton.addEventListener('click', stopCrawl);
els.rerunSetupCheckButton.addEventListener('click', refreshSetupDiagnostics);

bindFlagAnnouncements();
syncModeControls();
refreshState();
refreshSetupDiagnostics();
state.timer = setInterval(refreshState, 1500);
