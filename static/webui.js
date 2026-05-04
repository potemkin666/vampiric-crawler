const state = {
  status: 'idle',
  timer: null,
  eventSource: null,
  viewRunId: null,
  lastFeedKey: '',
  sortKey: 'discovery_time',
  sortDirection: 'desc',
  lastState: null,
  busyActions: {
    crawl: false,
    pause: false,
    stop: false,
  },
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

const DEFAULT_SPECIMEN = 'https://example.com';
const DRY_RUN_ON_MESSAGE = 'Dry run is enabled: the crawl button validates the rite and exits before visiting the target.';
const DRY_RUN_OFF_MESSAGE = 'Dry run is disabled: the crawl button will visit the target.';
const MOBILE_BREAKPOINT = 980;
let panelResizeTimer = null;

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
  resultSortDirection: document.getElementById('resultSortDirection'),
  resultStateFilter: document.getElementById('resultStateFilter'),
  resultStatusBucketFilter: document.getElementById('resultStatusBucketFilter'),
  resultErrorFilter: document.getElementById('resultErrorFilter'),
  resultTypeFilter: document.getElementById('resultTypeFilter'),
  resultSourceFilter: document.getElementById('resultSourceFilter'),
  resultLedger: document.getElementById('resultLedger'),
  resultFilterSummary: document.getElementById('resultFilterSummary'),
  runBrowserSummary: document.getElementById('runBrowserSummary'),
  runBrowserDetail: document.getElementById('runBrowserDetail'),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightText(value, query) {
  const text = String(value || '');
  if (!query) return escapeHtml(text);
  const matcher = new RegExp(`(${escapeRegExp(query)})`, 'ig');
  return escapeHtml(text).replace(matcher, '<mark>$1</mark>');
}

function statusBucketForRow(row) {
  const statusCode = Number(row?.status_code || 0);
  if (row?.error_kind === 'blocked' || [401, 403, 429].includes(statusCode)) return 'blocked';
  if (statusCode >= 200 && statusCode < 300) return '2xx';
  if (statusCode >= 300 && statusCode < 400) return '3xx';
  if (statusCode >= 400 && statusCode < 500) return '4xx';
  if (statusCode >= 500 && statusCode < 600) return '5xx';
  if (row?.state === 'failed') return 'failed';
  if (row?.state === 'skipped') return 'skipped';
  return 'other';
}

function setActionBusy(action, isBusy) {
  const mapping = {
    crawl: els.beginButton,
    pause: els.pauseButton,
    stop: els.stopButton,
  };
  state.busyActions[action] = isBusy;
  const button = mapping[action];
  if (!button) return;
  button.classList.toggle('is-busy', isBusy);
  button.setAttribute('aria-busy', isBusy ? 'true' : 'false');
  updateActionButtons(state.lastState || { status: state.status });
}

function updateActionButtons(data) {
  const status = data?.status || state.status || 'idle';
  const canPause = Boolean(data?.can_pause);
  const canStop = Boolean(data?.can_stop);
  const canResume = Boolean(data?.can_resume);
  els.beginButton.disabled = state.busyActions.crawl || status === 'running' || status === 'paused' || status === 'stopping';
  els.pauseButton.disabled = state.busyActions.pause || !(canPause || canResume);
  els.stopButton.disabled = state.busyActions.stop || !canStop;
}

async function withActionLock(action, callback) {
  if (state.busyActions[action]) return null;
  setActionBusy(action, true);
  try {
    return await callback();
  } finally {
    setActionBusy(action, false);
  }
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

function defaultCommandPreview(payload) {
  return `> CRAWL ${payload.target_specimen || DEFAULT_SPECIMEN} --depth ${payload.depth}`;
}

function updateIdlePreview(payload) {
  const notes = [
    'Awaiting target specimen to build preview.',
    payload.dry_run ? DRY_RUN_ON_MESSAGE : DRY_RUN_OFF_MESSAGE,
  ];
  els.commandPreview.textContent = defaultCommandPreview(payload);
  els.configPreview.textContent = notes.join('\n');
}

async function renderCommandPreview() {
  const payload = formPayload();
  if (!payload.target_specimen) {
    updateIdlePreview(payload);
    return;
  }
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
      resolved.dry_run ? DRY_RUN_ON_MESSAGE : DRY_RUN_OFF_MESSAGE,
      `Shadow words: ${(resolved.hidden_words || []).join(', ') || '-'}`,
      `Temporal baseline: ${resolved.temporal_baseline || '-'}`,
    ].join('\n');
  } catch (error) {
    els.commandPreview.textContent = defaultCommandPreview(payload);
    els.configPreview.textContent = `Failed to load preview: ${String(error.message || error)}`;
  }
}

function syncModeControls({ announce = true, preview = true } = {}) {
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
  if (announce) {
    announceFlagSummary(`Mode changed to ${config.label}. ${describeVisibleFlags()}`);
  }
  if (preview) {
    renderCommandPreview();
  }
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
    <section class="terminal-panel" id="panel-${escapeHtml(panel.key || 'panel')}" data-collapsible="mobile" data-collapsed-default="true">
      <div class="panel-title">${escapeHtml(panel.title)} // ${escapeHtml(panel.count)}</div>
      <div class="result-list">
        ${(panel.items && panel.items.length)
          ? panel.items.map((item) => `<div class="result-item" data-decrypt data-source-text="${escapeHtml(item)}">${escapeHtml(item)}</div>`).join('')
          : '<span class="empty-note">THE ARCHIVE IS SILENT</span>'}
      </div>
      <div class="panel-match-state">Showing all panel items.</div>
    </section>
  `).join('');
  attachDecryptHover();
  initializeCollapsiblePanels();
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

function renderBuffers(data) {
  els.liveFeed.textContent = (data.feed && data.feed.length) ? data.feed.join('\n') : 'Awaiting target acquisition…';
  els.errorConsole.textContent = (data.errors && data.errors.length)
    ? data.errors.join('\n')
    : ((data.logs && data.logs.length) ? data.logs.slice(-18).join('\n') : 'No omens yet.');
}

function renderRunBrowser(data) {
  const browser = data.run_browser || {};
  const runs = browser.runs || [];
  const selected = browser.selected || null;
  const diff = browser.diff_against_previous || null;
  els.runBrowserSummary.textContent = runs.length
    ? `${runs.length} sealed record${runs.length === 1 ? '' : 's'} in the archive.`
    : 'Awaiting sealed records.';
  els.sealedRecords.innerHTML = runs.length
    ? [
      data.is_historical ? '<button type="button" class="terminal-button record-open" data-run-id="">> RETURN TO CURRENT RITE</button>' : '',
      ...runs.map((record) => `
        <div class="record-card ${record.id === browser.selected_run_id ? 'record-card--selected' : ''}">
          <div class="panel-title">${escapeHtml(record.status_message || record.status)}</div>
          <strong>${escapeHtml(record.target_url || record.id)}</strong>
          <div>${escapeHtml(record.mode_label || record.mode || 'generic')}</div>
          <div>${escapeHtml(record.ended_at || record.started_at || '')}</div>
          <div class="result-meta">
            <span>visited=${escapeHtml(record.counts?.visited ?? 0)}</span>
            <span>failures=${escapeHtml(record.counts?.failures ?? 0)}</span>
            <span>links=${escapeHtml(record.counts?.links ?? 0)}</span>
            <span>relics=${escapeHtml(record.counts?.relics ?? 0)}</span>
          </div>
          <div class="result-link-list">
            <button type="button" class="terminal-button record-open" data-run-id="${escapeHtml(record.id || '')}">REOPEN RECORD</button>
            ${(record.exports || []).filter((item) => ['timeline-jsonl', 'timeline-json', 'bundle'].includes(item.kind))
              .map((item) => `<a class="result-link" href="${escapeHtml(item.href)}">${escapeHtml(item.kind)}</a>`).join(' ')}
          </div>
        </div>
      `),
    ].join('')
    : '<span class="empty-note">NO SEALED RECORDS YET</span>';
  els.runBrowserDetail.innerHTML = selected
    ? `
      <article class="result-row">
        <div class="result-row-header">
          <strong>${escapeHtml(selected.target_url || selected.id)}</strong>
          <span class="panel-title">${escapeHtml(selected.status_message || selected.status || '')}</span>
        </div>
        <div class="result-meta">
          <span>mode=${escapeHtml(selected.mode_label || selected.mode || '')}</span>
          <span>visited=${escapeHtml(selected.counts?.visited ?? 0)}</span>
          <span>failures=${escapeHtml(selected.counts?.failures ?? 0)}</span>
          <span>links=${escapeHtml(selected.counts?.links ?? 0)}</span>
          <span>relics=${escapeHtml(selected.counts?.relics ?? 0)}</span>
        </div>
        <div class="result-actions">
          <div class="result-link-list">
            ${(selected.exports || []).map((item) => `<a class="result-link" href="${escapeHtml(item.href)}">${escapeHtml(item.label || item.kind)}</a>`).join(' ')}
          </div>
        </div>
        ${diff ? `
          <details class="result-trace" open>
            <summary>DIFF AGAINST PREVIOUS // ${escapeHtml(diff.against_run_id || '')}</summary>
            <div class="result-trace-grid">
              <div><strong>SUMMARY</strong><div>added=${escapeHtml(diff.summary?.added ?? 0)} removed=${escapeHtml(diff.summary?.removed ?? 0)} changed=${escapeHtml(diff.summary?.changed ?? 0)}</div></div>
              <div><strong>CHANGES</strong><div>${(diff.items || []).length ? diff.items.map((item) => `<div>${escapeHtml(item)}</div>`).join('') : 'No prior diff lines.'}</div></div>
            </div>
          </details>
        ` : '<div class="panel-match-state">No older sealed record is available for diff.</div>'}
      </article>
    `
    : '<span class="empty-note">NO SEALED RECORD SELECTED</span>';
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

function renderRecords(data) {
  renderRunBrowser(data);
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
  const direction = state.sortDirection === 'asc' ? 1 : -1;
  return [...(rows || [])].sort((left, right) => {
    const a = left?.[sortKey];
    const b = right?.[sortKey];
    if (sortKey === 'status_code' || sortKey === 'depth' || sortKey === 'discovery_time') {
      const comparison = (Number(a || 0) - Number(b || 0)) || String(left.url || '').localeCompare(String(right.url || ''));
      return comparison * direction;
    }
    const comparison = String(a || '').localeCompare(String(b || '')) || String(left.url || '').localeCompare(String(right.url || ''));
    return comparison * direction;
  });
}

function populateLedgerFilterOptions(rows) {
  const filters = [
    { node: els.resultStateFilter, values: rows.map((row) => row.state).filter(Boolean), fallback: 'ALL STATES' },
    { node: els.resultStatusBucketFilter, values: rows.map((row) => statusBucketForRow(row)).filter(Boolean), fallback: 'ALL BUCKETS' },
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
    if (els.resultStatusBucketFilter.value && statusBucketForRow(row) !== els.resultStatusBucketFilter.value) return false;
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
  const query = (els.resultSearch?.value || '').trim();
  els.resultFilterSummary.textContent = rows.length
    ? `Showing ${rows.length} of ${allRows.length} result rows${query ? ` matching "${query}"` : '.'}`
    : `0 matches out of ${allRows.length} result rows${query ? ` for "${query}"` : '.'}`;
  els.resultLedger.innerHTML = rows.length
    ? rows.map((row) => `
      <article class="result-row" data-result-row>
        <div class="result-row-header">
          <strong>${highlightText(row.url || '-', query)}</strong>
          <span class="panel-title">bucket=${escapeHtml(statusBucketForRow(row))}</span>
        </div>
        <div class="result-meta">
          <span>state=${highlightText(row.state || '-', query)}</span>
          <span>status=${escapeHtml(row.status_code ?? '-')}</span>
          <span>type=${highlightText(row.content_type || '-', query)}</span>
          <span>depth=${escapeHtml(row.depth ?? '-')}</span>
          <span>source=${highlightText(row.source_page || '-', query)}</span>
          <span>source_kind=${highlightText(row.source_kind || '-', query)}</span>
          <span>discovery=#${escapeHtml(row.discovery_time ?? 0)}</span>
        </div>
        ${(row.error_message || row.error_kind)
          ? `<div class="result-error">${highlightText(row.error_message || row.error_kind, query)}</div>`
          : ''}
        <div class="result-actions">
          <div class="result-link-list">
            <a class="result-link export-link" href="${escapeHtml(row.url || '#')}" target="_blank" rel="noopener noreferrer">OPEN</a>
            <button type="button" class="terminal-button result-copy" data-copy="${escapeHtml(row.url || '')}">COPY URL</button>
          </div>
          <span class="result-copy-feedback" aria-live="polite"></span>
        </div>
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
    : '<div class="result-zero-state">0 matches. Adjust the filter rites or clear the search to reveal hidden records.</div>';
  bindLedgerActions();
}

function renderState(data) {
  state.lastState = data;
  state.viewRunId = data.is_historical ? (data.id || null) : null;
  state.status = data.status || 'idle';
  els.app.dataset.status = state.status;
  els.statusMessage.textContent = data.status_message || 'THE CRAWLER SLEEPS';
  els.asciiMeter.textContent = buildMeter(data);
  renderSummary(data);
  renderBuffers(data);
  renderPauseState(data);
  renderQueue(data);
  renderRobots(data);
  renderSitemaps(data);
  renderResultLedger(data);
  renderPanels(data);
  renderExports(data);
  renderRecords(data);
  updateActionButtons(data);
  els.pauseButton.textContent = data.can_resume ? '> REAWAKEN THE RITE' : '> SUSPEND THE RITE';
  syncModeControls({ announce: false, preview: false });
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

function pushLimited(list, value, limit) {
  const next = [...(list || []), value];
  return next.slice(-limit);
}

function ensureStreamState(runId) {
  if (!state.lastState) return false;
  if (state.viewRunId) return state.viewRunId === runId;
  if (!state.lastState.id || !runId) return true;
  return state.lastState.id === runId;
}

function refreshDerivedSummary(data) {
  const rows = data.result_rows || [];
  const completedCount = rows.filter((row) => ['completed', 'failed', 'skipped'].includes(row.state)).length;
  const failureCount = rows.filter((row) => ['failed', 'skipped'].includes(row.state)).length;
  data.summary = data.summary || {};
  data.summary.visited = Math.max(Number(data.summary.visited || 0), completedCount);
  data.summary.failures = Math.max(Number(data.summary.failures || 0), failureCount);
}

function upsertStreamResultRow(data, row) {
  const rows = [...(data.result_rows || [])];
  const existingIndex = rows.findIndex((item) => item.url === row.url);
  const nextRow = {
    ...(existingIndex >= 0 ? rows[existingIndex] : {}),
    ...row,
  };
  nextRow.redirect_chain = nextRow.redirect_chain || [];
  nextRow.discovery_path = nextRow.discovery_path || [nextRow.source_page, nextRow.url].filter(Boolean);
  if (existingIndex >= 0) {
    rows.splice(existingIndex, 1, nextRow);
  } else {
    rows.push(nextRow);
  }
  data.result_rows = rows;
  refreshDerivedSummary(data);
}

function applyStreamEvent(message) {
  const runId = message.run_id || '';
  const payload = message.payload || {};
  if (!ensureStreamState(runId)) return;
  if (!state.lastState) {
    refreshState();
    return;
  }
  if (payload.line) {
    state.lastState.logs = pushLimited(state.lastState.logs, payload.line, 500);
    if ((payload.channels || []).includes('feed')) {
      state.lastState.feed = pushLimited(state.lastState.feed, payload.line, 250);
    }
    if ((payload.channels || []).includes('errors')) {
      state.lastState.errors = pushLimited(state.lastState.errors, payload.line, 150);
    }
    renderBuffers(state.lastState);
    return;
  }
  switch (message.event_type || payload.event_type) {
    case 'queue':
      state.lastState.queue = payload;
      renderQueue(state.lastState);
      return;
    case 'result':
      upsertStreamResultRow(state.lastState, payload);
      els.asciiMeter.textContent = buildMeter(state.lastState);
      renderSummary(state.lastState);
      renderResultLedger(state.lastState);
      return;
    case 'robots':
      state.lastState.robots_details = payload;
      renderRobots(state.lastState);
      return;
    case 'sitemap':
      state.lastState.sitemap_details = payload;
      renderSitemaps(state.lastState);
      return;
    case 'error': {
      const parts = [payload.message || 'The rite failed.'];
      if (payload.category) parts.push(`category=${payload.category}`);
      if (payload.status_code) parts.push(`status=${payload.status_code}`);
      if (payload.url) parts.push(`url=${payload.url}`);
      state.lastState.errors = pushLimited(state.lastState.errors, parts.join(' | '), 150);
      state.lastState.summary = state.lastState.summary || {};
      state.lastState.summary.failures = Number(state.lastState.summary.failures || 0) + 1;
      els.asciiMeter.textContent = buildMeter(state.lastState);
      renderSummary(state.lastState);
      renderBuffers(state.lastState);
      return;
    }
    default:
      return;
  }
}

function stopRealtime() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

function startFallbackPolling() {
  if (state.timer || state.eventSource) return;
  state.timer = setInterval(refreshState, 1500);
}

function startRealtime() {
  if (typeof window.EventSource !== 'function') {
    startFallbackPolling();
    return;
  }
  stopRealtime();
  const source = new EventSource('/api/events');
  state.eventSource = source;
  source.addEventListener('snapshot', (event) => {
    const data = JSON.parse(event.data || '{}');
    if (state.viewRunId && !data.is_historical && state.viewRunId !== data.id) {
      return;
    }
    renderState(data);
  });
  source.addEventListener('log', (event) => {
    applyStreamEvent(JSON.parse(event.data || '{}'));
  });
  source.addEventListener('crawl-event', (event) => {
    const message = JSON.parse(event.data || '{}');
    applyStreamEvent({
      run_id: message.run_id,
      event_type: message.payload?.event_type,
      payload: message.payload?.payload || {},
    });
  });
  source.addEventListener('status', () => {
    if (!state.viewRunId) {
      refreshState();
    }
  });
  source.onerror = () => {
    stopRealtime();
    startFallbackPolling();
  };
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
  await withActionLock('crawl', async () => {
    try {
      const data = await postJson('/api/crawl', payload);
      renderState(data);
    } catch (error) {
      els.errorConsole.textContent = String(error.message || error);
    }
  });
}

async function togglePause() {
  await withActionLock('pause', async () => {
    try {
      const endpoint = state.status === 'paused' ? '/api/crawl/resume' : '/api/crawl/pause';
      const data = await postJson(endpoint);
      renderState(data);
    } catch (error) {
      els.errorConsole.textContent = String(error.message || error);
    }
  });
}

async function stopCrawl() {
  await withActionLock('stop', async () => {
    try {
      const data = await postJson('/api/crawl/stop');
      renderState(data);
    } catch (error) {
      els.errorConsole.textContent = String(error.message || error);
    }
  });
}

function decryptText(node) {
  const target = node.dataset.sourceText || node.dataset.original || node.textContent;
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

function bindLedgerActions() {
  els.resultLedger.querySelectorAll('.result-copy').forEach((button) => {
    if (button.dataset.bound === 'true') return;
    button.dataset.bound = 'true';
    button.addEventListener('click', async () => {
      const value = button.dataset.copy || '';
      const feedback = button.closest('.result-actions')?.querySelector('.result-copy-feedback');
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
        } else {
          const helper = document.createElement('textarea');
          helper.value = value;
          document.body.appendChild(helper);
          helper.select();
          document.execCommand('copy');
          helper.remove();
        }
        if (feedback) feedback.textContent = 'Copied.';
      } catch (error) {
        if (feedback) feedback.textContent = `Copy failed: ${String(error.message || error)}`;
      }
    });
  });
}

function initializeCollapsiblePanels() {
  document.querySelectorAll('[data-collapsible="mobile"]').forEach((panel) => {
    if (panel.dataset.collapsibleBound === 'true') return;
    const title = panel.querySelector('.panel-title');
    if (!title) return;
    const body = document.createElement('div');
    body.className = 'panel-collapse-body';
    const siblings = [];
    let next = title.nextSibling;
    while (next) {
      siblings.push(next);
      next = next.nextSibling;
    }
    siblings.forEach((node) => body.appendChild(node));
    const header = document.createElement('div');
    header.className = 'panel-header';
    title.parentNode.insertBefore(header, title);
    header.appendChild(title);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'panel-toggle';
    const collapsedDefault = panel.dataset.collapsedDefault === 'true';
    const setExpanded = (expanded) => {
      body.classList.toggle('is-collapsed', !expanded);
      button.textContent = expanded ? 'COLLAPSE' : 'EXPAND';
      button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    };
    button.addEventListener('click', () => {
      setExpanded(button.getAttribute('aria-expanded') !== 'true');
    });
    header.appendChild(button);
    panel.appendChild(body);
    setExpanded(window.innerWidth > MOBILE_BREAKPOINT ? true : !collapsedDefault);
    panel.dataset.collapsibleBound = 'true';
  });
}

function syncCollapsiblePanelsToViewport() {
  document.querySelectorAll('[data-collapsible="mobile"]').forEach((panel) => {
    const body = panel.querySelector('.panel-collapse-body');
    const button = panel.querySelector('.panel-toggle');
    if (!body || !button) return;
    const expanded = window.innerWidth > MOBILE_BREAKPOINT ? true : panel.dataset.collapsedDefault !== 'true';
    body.classList.toggle('is-collapsed', !expanded);
    button.textContent = expanded ? 'COLLAPSE' : 'EXPAND';
    button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  });
}

function applyResultFilter() {
  const query = (els.resultSearch?.value || '').trim();
  const loweredQuery = query.toLowerCase();
  document.querySelectorAll('.result-item').forEach((node) => {
    const rawText = node.dataset.sourceText || node.textContent;
    const visible = !loweredQuery || rawText.toLowerCase().includes(loweredQuery);
    node.innerHTML = highlightText(rawText, query);
    node.style.display = visible ? '' : 'none';
  });
  document.querySelectorAll('#resultPanels .terminal-panel').forEach((panel) => {
    const items = Array.from(panel.querySelectorAll('.result-item'));
    const visibleCount = items.filter((item) => item.style.display !== 'none').length;
    const stateNode = panel.querySelector('.panel-match-state');
    if (stateNode) {
      stateNode.textContent = visibleCount
        ? `Showing ${visibleCount} panel item${visibleCount === 1 ? '' : 's'}${query ? ` matching "${query}"` : '.'}`
        : `0 matches${query ? ` for "${query}"` : ''}.`;
    }
  });
}

['input', 'change'].forEach((eventName) => {
  els.form.addEventListener(eventName, renderCommandPreview);
});
els.form.addEventListener('submit', (event) => {
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
els.resultSortDirection.addEventListener('change', () => {
  state.sortDirection = els.resultSortDirection.value;
  if (state.lastState) {
    renderResultLedger(state.lastState);
  }
});
['resultStateFilter', 'resultStatusBucketFilter', 'resultErrorFilter', 'resultTypeFilter', 'resultSourceFilter'].forEach((key) => {
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
initializeCollapsiblePanels();
syncCollapsiblePanelsToViewport();
refreshState();
refreshSetupDiagnostics();
startRealtime();
window.addEventListener('resize', () => {
  clearTimeout(panelResizeTimer);
  panelResizeTimer = setTimeout(() => {
    syncCollapsiblePanelsToViewport();
  }, 120);
});
