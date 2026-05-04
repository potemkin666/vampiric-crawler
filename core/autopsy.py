"""Autopsy, anatomy, mutation, and genealogy helpers."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from urllib.parse import urlsplit

from core.config import RuntimeConfig

ANALYSIS_DATASET_NAMES = (
    'site_anatomy',
    'mutation_probes',
    'artifact_genealogy',
)
TEMPORAL_BASELINE_FILE = 'temporal-baseline.json'

AUTH_RE = re.compile(r'/(?:login|logout|signin|signout|auth|register|password|session|account)\b', re.I)
API_RE = re.compile(r'/(?:api|graphql|graphiql|swagger|openapi|v\d+/)', re.I)
ADMIN_RE = re.compile(r'/(?:admin|dashboard|portal|manage|console|cpanel|staff|moderator)\b', re.I)
OLD_RE = re.compile(r'/(?:old|legacy|backup|bak|draft|archive|deprecated|v\d{1,2}|20\d{2})', re.I)
DOC_EXTS = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.rtf')
STATIC_EXTS = ('.js', '.css', '.map', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.json', '.xml', '.txt')
TRUST_RE = re.compile(r'(?:github|discord|slack|trustpilot|statuspage|linkedin|twitter|x\.com|facebook|docs|privacy|terms)', re.I)
ANALYTICS_RE = re.compile(r'(?:google-analytics|googletagmanager|segment|mixpanel|amplitude|gtm-|ua-\d+|ga4)', re.I)
CDN_RE = re.compile(r'(?:cloudfront\.net|amazonaws\.com|storage\.googleapis\.com|blob\.core\.windows\.net|cdn\.|fastly|akamai)', re.I)
HASH_CHUNK_SIZE = 65536


def record_artifact_discovery(
    genealogy: dict[str, dict[str, object]],
    artifact_url: str,
    discovered_on: str | None = None,
    source_kind: str = 'link',
    note: str | None = None,
) -> None:
    """Track a newly discovered artifact reference."""
    if not artifact_url:
        return
    record = genealogy.setdefault(artifact_url, {
        'url': artifact_url,
        'found_on': set(),
        'linked_by': set(),
        'source_kinds': set(),
        'content_type': '',
        'size': 0,
        'sha256': '',
        'title': '',
        'metadata': set(),
        'archive_presence': False,
        'duplicates': set(),
        'redirects': set(),
        'first_seen': '',
        'last_seen': '',
        'notes': set(),
    })
    if discovered_on:
        record['found_on'].add(discovered_on)
        record['linked_by'].add(discovered_on)
    record['source_kinds'].add(source_kind)
    if note:
        record['notes'].add(note)


def update_artifact_observation(
    genealogy: dict[str, dict[str, object]],
    artifact_url: str,
    *,
    content_type: str = '',
    body: bytes | None = None,
    title: str = '',
    metadata: list[str] | None = None,
    archive_presence: bool | None = None,
    redirects: list[str] | None = None,
    seen_label: str | None = None,
) -> None:
    """Enrich an artifact genealogy record with fetched details."""
    record_artifact_discovery(genealogy, artifact_url)
    record = genealogy[artifact_url]
    if content_type:
        record['content_type'] = content_type
    if title:
        record['title'] = title
    if metadata:
        record['metadata'].update(str(item) for item in metadata if item)
    if archive_presence is not None:
        record['archive_presence'] = bool(archive_presence)
    if redirects:
        record['redirects'].update(redirects)
    if body is not None:
        record['size'] = len(body)
        record['sha256'] = hashlib.sha256(body).hexdigest()
    if seen_label:
        if not record['first_seen']:
            record['first_seen'] = seen_label
        record['last_seen'] = seen_label


def finalize_genealogy(genealogy: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """Return a JSON-serializable genealogy mapping with duplicate hints."""
    by_hash: dict[str, list[str]] = {}
    for url, record in genealogy.items():
        sha256 = str(record.get('sha256') or '')
        if sha256:
            by_hash.setdefault(sha256, []).append(url)
    finalized = {}
    for url, record in genealogy.items():
        sha256 = str(record.get('sha256') or '')
        duplicates = set(record.get('duplicates') or ())
        if sha256 and len(by_hash.get(sha256, [])) > 1:
            duplicates.update(other for other in by_hash[sha256] if other != url)
        finalized[url] = {
            'url': url,
            'found_on': sorted(record.get('found_on') or ()),
            'linked_by': sorted(record.get('linked_by') or ()),
            'source_kinds': sorted(record.get('source_kinds') or ()),
            'content_type': record.get('content_type') or '',
            'size': int(record.get('size') or 0),
            'sha256': record.get('sha256') or '',
            'title': record.get('title') or '',
            'metadata': sorted(record.get('metadata') or ()),
            'archive_presence': bool(record.get('archive_presence')),
            'duplicates': sorted(duplicates),
            'redirects': sorted(record.get('redirects') or ()),
            'first_seen': record.get('first_seen') or '',
            'last_seen': record.get('last_seen') or '',
            'notes': sorted(record.get('notes') or ()),
        }
    return finalized


def genealogy_lines(genealogy: dict[str, dict[str, object]]) -> list[str]:
    """Return compact artifact genealogy lines."""
    lines = []
    for url, record in sorted(finalize_genealogy(genealogy).items()):
        lines.append(
            f'url={url} content_type={record["content_type"] or "-"} size={record["size"]} '
            f'sha256={record["sha256"][:16] or "-"} title={record["title"] or "-"} '
            f'found_on={",".join(record["found_on"][:3]) or "-"} duplicates={len(record["duplicates"])} '
            f'archive={str(record["archive_presence"]).lower()} first_seen={record["first_seen"] or "-"} '
            f'last_seen={record["last_seen"] or "-"}'
        )
    return lines


def build_site_anatomy(
    main_url: str,
    datasets: dict[str, list[str]],
    genealogy: dict[str, dict[str, object]],
    specimen: dict[str, object] | None = None,
) -> dict[str, list[str]]:
    """Build a structural map of the target."""
    internals = datasets.get('internal', [])
    externals = datasets.get('external', [])
    files = datasets.get('files', [])
    endpoints = datasets.get('endpoints', [])
    forms = datasets.get('forms', [])
    failed = datasets.get('failed', [])
    scripts = datasets.get('scripts', [])
    specimen = specimen or {}

    auth_form_targets = []
    for item in forms:
        action_match = re.search(r'action=([^\s]+)', item)
        if action_match:
            auth_form_targets.append(action_match.group(1))
        if any(marker in item.lower() for marker in ('password', 'email', 'token', 'login', 'auth')):
            auth_form_targets.append(item)
    auth_surfaces = _unique([url for url in internals if AUTH_RE.search(url)] + auth_form_targets)
    docs = _unique([url for url in files if _path_matches(url, DOC_EXTS)])
    apis = _unique([url for url in internals if API_RE.search(url)] + list(endpoints))
    static_assets = _unique([url for url in files if _path_matches(url, STATIC_EXTS)] + scripts)
    admin_ish = _unique([url for url in internals + failed if ADMIN_RE.search(url)])
    old_paths = _unique([url for url in internals + failed + files if OLD_RE.search(url)])
    analytics = _unique([url for url in externals if ANALYTICS_RE.search(url)])
    cdn_assets = _unique([url for url in externals if CDN_RE.search(url)])
    external_trust = _unique([url for url in externals if TRUST_RE.search(url)])
    external_refs = _unique([
        url for url in externals
        if _external_host(url, main_url)
        and url not in analytics
        and url not in cdn_assets
        and url not in external_trust
    ])
    archive_only = _unique([
        url for url, record in finalize_genealogy(genealogy).items()
        if record['archive_presence'] and url not in internals and url not in files
    ])
    dead_ends = _unique(failed + datasets.get('skipped', []))

    anatomy = {
        'auth_surfaces': auth_surfaces,
        'docs': docs,
        'apis': apis,
        'forms': _unique(forms),
        'static_assets': static_assets,
        'admin_ish_routes': admin_ish,
        'old_paths': old_paths,
        'analytics': analytics,
        'cdn_assets': cdn_assets,
        'external_refs': external_refs,
        'archive_only_paths': archive_only,
        'trust_links': external_trust,
        'dead_ends': dead_ends,
    }
    if specimen.get('archive_hint'):
        anatomy['archive_only_paths'] = _unique(anatomy['archive_only_paths'] + list(specimen.get('crawl_roots') or ()))
    return anatomy


def anatomy_lines(anatomy: dict[str, list[str]]) -> list[str]:
    """Return anatomy lines for text exports."""
    lines = []
    for section, items in anatomy.items():
        for item in items:
            lines.append(f'section={section} value={item}')
    return lines


def build_mutation_probes(main_url: str, datasets: dict[str, list[str]]) -> list[dict[str, str]]:
    """Build bounded smart probes from discovered paths."""
    parsed = urlsplit(main_url)
    root = f'{parsed.scheme}://{parsed.netloc}'
    sources = _unique(datasets.get('internal', []) + datasets.get('files', []) + [root + path for path in datasets.get('endpoints', []) if str(path).startswith('/')])
    probes = []
    seen = set()
    if datasets.get('forms'):
        for variant, reason in (
            ('/admin', 'form-neighbor'),
            ('/dashboard', 'form-neighbor'),
            ('/api/login', 'form-auth-api'),
            ('/old-login', 'form-legacy-auth'),
            ('/signin', 'form-auth-alias'),
            ('/auth/callback', 'form-auth-callback'),
        ):
            _append_probe(probes, seen, root + variant, root, reason)
    for source in sources:
        path = urlsplit(source).path or '/'
        basename = os.path.basename(path)
        if AUTH_RE.search(path):
            for variant, reason in (
                ('/admin', 'auth-neighbor'),
                ('/dashboard', 'auth-neighbor'),
                ('/api/login', 'auth-api-neighbor'),
                ('/old-login', 'auth-legacy-neighbor'),
                ('/signin', 'auth-alias'),
                ('/auth/callback', 'auth-callback'),
            ):
                _append_probe(probes, seen, root + variant, source, reason)
        if basename.lower().endswith(DOC_EXTS):
            for candidate in _document_mutations(root, path):
                _append_probe(probes, seen, candidate, source, 'document-mutation')
        if ADMIN_RE.search(path):
            for variant in ('/login', '/admin/login', '/dashboard', '/api/admin'):
                _append_probe(probes, seen, root + variant, source, 'admin-neighbor')
        if len(probes) >= 64:
            break
    return probes[:64]


def mutation_lines(probes: list[dict[str, str]]) -> list[str]:
    """Return mutation probe lines for text export."""
    return [f'probe={item["probe"]} source={item["source"]} reason={item["reason"]}' for item in probes]


def build_autopsy(
    *,
    specimen: dict[str, object],
    ritual: dict[str, object],
    preset: str,
    mode: str,
    datasets: dict[str, list[str]],
    stats: dict[str, object],
    genealogy: dict[str, dict[str, object]],
    anatomy: dict[str, list[str]],
    mutation_probes: list[dict[str, str]],
    exports: list[str] | None = None,
    duration_seconds: float | int | None = None,
    content_types: dict[str, int] | None = None,
    run_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return the final crawl autopsy."""
    finalized_genealogy = finalize_genealogy(genealogy)
    what_exposes = {
        'internal_links': len(datasets.get('internal', [])),
        'forms': len(datasets.get('forms', [])),
        'documents': len(anatomy.get('docs', [])),
        'apis': len(anatomy.get('apis', [])),
        'scripts': len(datasets.get('scripts', [])),
    }
    what_broke = datasets.get('failed', []) + datasets.get('skipped', [])
    what_changed = datasets.get('temporal_diffs', [])
    what_looks_fake = datasets.get('scam_signals', []) + anatomy.get('trust_links', [])
    worth_probing_next = [item['probe'] for item in mutation_probes[:12]]
    return {
        'what_the_target_is': {
            'specimen_type': specimen.get('type'),
            'source': specimen.get('source'),
            'canonical_target': specimen.get('canonical_target'),
            'crawl_roots': list(specimen.get('crawl_roots') or ()),
            'ritual_chain': ritual.get('ritual_chain'),
            'ritual_label': ritual.get('label'),
            'mode': mode,
            'preset': preset,
            'confidence': specimen.get('confidence'),
            'notes': list(specimen.get('notes') or ()),
        },
        'what_it_exposes': what_exposes,
        'what_broke': what_broke,
        'what_changed': what_changed,
        'what_looks_fake': what_looks_fake,
        'worth_probing_next': worth_probing_next,
        'site_anatomy': anatomy,
        'mutation_engine': mutation_probes,
        'artifact_genealogy': finalized_genealogy,
        'endpoint_archaeology': datasets.get('js_intel', []),
        'run_metadata': dict(run_metadata or {}),
        'run_summary': {
            'pages_crawled': int(stats.get('visited', len(datasets.get('internal', []))) or 0),
            'skipped': int(stats.get('skipped', len(datasets.get('skipped', []))) or 0),
            'failed': int(stats.get('failures', len(datasets.get('failed', []))) or 0),
            'exports': list(exports or ()),
            'duration_seconds': float(duration_seconds or 0.0),
            'top_content_types': sorted((content_types or {}).items(), key=lambda item: (-item[1], item[0]))[:8],
        },
    }


def render_autopsy_markdown(autopsy: dict[str, object]) -> str:
    """Render a readable Markdown autopsy."""
    target = autopsy.get('what_the_target_is', {})
    anatomy = autopsy.get('site_anatomy', {})
    run_metadata = autopsy.get('run_metadata', {})
    runtime = run_metadata.get('runtime', {}) if isinstance(run_metadata, dict) else {}
    summary = autopsy.get('run_summary', {})
    lines = [
        '# Vampiric Crawler Autopsy',
        '',
        '## What the target is',
        f'- Specimen type: `{target.get("specimen_type", "-")}`',
        f'- Source: `{target.get("source", "-")}`',
        f'- Canonical target: `{target.get("canonical_target", "-")}`',
        f'- Ritual chain: `{target.get("ritual_chain", "-")}`',
        f'- Mode: `{target.get("mode", "-")}`',
        f'- Preset: `{target.get("preset", "-")}`',
        '',
        '## Run summary',
        f'- Pages crawled: {summary.get("pages_crawled", 0)}',
        f'- Skipped: {summary.get("skipped", 0)}',
        f'- Failed: {summary.get("failed", 0)}',
        f'- Duration (s): {float(summary.get("duration_seconds") or 0):.2f}',
        '',
        '## Run metadata',
        f'- Run ID: `{run_metadata.get("run_id", "-")}`',
        f'- Saved at: `{run_metadata.get("saved_at", "-")}`',
        f'- Command: `{run_metadata.get("command_line", "-")}`',
        f'- Baseline source: `{run_metadata.get("baseline_source", "-")}`',
        f'- Git commit: `{runtime.get("git_commit", "-")}`',
        f'- Python: `{runtime.get("python_version", "-")}`',
        '',
        '## Site anatomy',
    ]
    for section, items in anatomy.items():
        lines.append(f'### {section.replace("_", " ").title()}')
        if items:
            lines.extend(f'- {item}' for item in items[:20])
        else:
            lines.append('- None observed')
        lines.append('')
    lines.extend([
        '## What broke',
        *([f'- {item}' for item in autopsy.get('what_broke', [])[:20]] or ['- None observed']),
        '',
        '## What changed',
        *([f'- {item}' for item in autopsy.get('what_changed', [])[:20]] or ['- No temporal changes recorded']),
        '',
        '## What looks fake',
        *([f'- {item}' for item in autopsy.get('what_looks_fake', [])[:20]] or ['- No strong fake signals recorded']),
        '',
        '## Worth probing next',
        *([f'- {item}' for item in autopsy.get('worth_probing_next', [])[:20]] or ['- No next probes suggested']),
    ])
    return '\n'.join(lines).rstrip() + '\n'


def write_autopsy_files(output_dir: str, autopsy: dict[str, object]) -> tuple[str, str]:
    """Write autopsy JSON and Markdown files."""
    json_path = os.path.join(output_dir, 'autopsy.json')
    md_path = os.path.join(output_dir, 'autopsy.md')
    with open(json_path, 'w', encoding='utf-8') as handle:
        json.dump(autopsy, handle, indent=2, ensure_ascii=False)
    with open(md_path, 'w', encoding='utf-8') as handle:
        handle.write(render_autopsy_markdown(autopsy))
    return json_path, md_path


def build_crawl_manifest(
    *,
    specimen: dict[str, object],
    ritual: dict[str, object],
    preset: str,
    mode: str,
    command: list[str],
    output_dir: str,
    main_url: str,
    resolved_config: dict[str, object],
    checkpoint_path: str | None = None,
    resumed_from: str | None = None,
    temporal_baseline: str | None = None,
    stage: str = 'complete',
    run_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a canonical crawl manifest for a run."""
    return {
        'manifest_version': 1,
        'stage': stage,
        'generated_at': _now_iso(),
        'target': {
            'main_url': main_url,
            'specimen': specimen,
            'ritual_chain': ritual.get('ritual_chain'),
            'ritual_label': ritual.get('label'),
            'preset': preset,
            'mode': mode,
        },
        'resolved_config': resolved_config,
        'runtime': {
            'python_version': sys.version,
            'python_executable': sys.executable,
            'platform': platform.platform(),
            'cwd': os.getcwd(),
            'dependency_versions': _dependency_versions(('requests', 'urllib3', 'tldextract', 'flask', 'playwright')),
        },
        'command': list(command or ()),
        'run_metadata': dict(run_metadata or {}),
        'lineage': {
            'checkpoint_path': checkpoint_path or '',
            'resumed_from': resumed_from or '',
            'temporal_baseline': temporal_baseline or '',
            'output_dir': output_dir,
        },
        'artifacts': _hash_output_dir(output_dir),
    }


def write_manifest_file(output_dir: str, manifest: dict[str, object]) -> str:
    """Write crawl manifest JSON to *output_dir*."""
    path = os.path.join(output_dir, 'crawl-manifest.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    return path


def write_structured_snapshot_file(output_dir: str, snapshot: dict[str, object]) -> str:
    """Write the structured temporal baseline manifest for later comparisons."""
    path = os.path.join(output_dir, TEMPORAL_BASELINE_FILE)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(snapshot, handle, indent=2, ensure_ascii=False)
    return path


def snapshot_exists(snapshot_dir: str, dataset_names: list[str] | tuple[str, ...]) -> bool:
    """Return whether *snapshot_dir* contains any baseline material."""
    if not snapshot_dir or not os.path.isdir(snapshot_dir):
        return False
    baseline_path = os.path.join(snapshot_dir, TEMPORAL_BASELINE_FILE)
    if os.path.exists(baseline_path):
        return True
    manifest_path = os.path.join(snapshot_dir, 'crawl-manifest.json')
    autopsy_path = os.path.join(snapshot_dir, 'autopsy.json')
    if os.path.exists(manifest_path) or os.path.exists(autopsy_path):
        return True
    return any(
        os.path.exists(os.path.join(snapshot_dir, f'{name}.txt'))
        for name in list(dataset_names) + ['stats']
    )


def load_previous_snapshot(snapshot_dir: str, dataset_names: list[str] | tuple[str, ...]) -> dict[str, object]:
    """Load a prior structured or text-only snapshot for temporal comparisons."""
    if not snapshot_exists(snapshot_dir, dataset_names):
        return {}
    snapshot: dict[str, object] = {}
    baseline_path = os.path.join(snapshot_dir, TEMPORAL_BASELINE_FILE)
    baseline_snapshot = _load_json_file(baseline_path)
    if isinstance(baseline_snapshot, dict):
        snapshot.update(baseline_snapshot)
    for name in list(dataset_names) + ['stats']:
        path = os.path.join(snapshot_dir, f'{name}.txt')
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as handle:
            lines = [line.rstrip('\n') for line in handle if line.strip()]
        if name == 'stats':
            stats_dict = {}
            for line in lines:
                key, _, value = line.partition('=')
                if key:
                    stats_dict[key] = value
            snapshot.setdefault(name, stats_dict)
        else:
            snapshot.setdefault(name, lines)

    manifest = _load_json_file(os.path.join(snapshot_dir, 'crawl-manifest.json'))
    if isinstance(manifest, dict):
        snapshot.setdefault('artifact_hashes', manifest.get('artifacts') or {})
        snapshot.setdefault('report_metadata', _manifest_report_metadata(manifest))

    autopsy = _load_json_file(os.path.join(snapshot_dir, 'autopsy.json'))
    if isinstance(autopsy, dict):
        snapshot.setdefault('artifact_genealogy', _snapshot_genealogy(autopsy.get('artifact_genealogy') or {}))
        snapshot.setdefault('content_types', _top_content_type_map(autopsy.get('run_summary', {})))
        snapshot.setdefault('autopsy_summary', _autopsy_summary_for_snapshot(autopsy))
        if not snapshot.get('report_metadata'):
            snapshot['report_metadata'] = _report_metadata_from_autopsy(autopsy)
    return snapshot


def build_run_metadata(
    *,
    run_id: str,
    preset: str,
    mode: str,
    ritual_chain: str,
    command: list[str] | tuple[str, ...] | None = None,
    runtime_config: RuntimeConfig | dict[str, object] | None = None,
    baseline_source: str | None = None,
    output_dir: str | None = None,
    saved_at: str | None = None,
) -> dict[str, object]:
    """Return traceable run metadata for autopsy and manifest files."""
    config = runtime_config if isinstance(runtime_config, RuntimeConfig) else RuntimeConfig.from_mapping(runtime_config)
    command_list = [str(item) for item in (command or ())]
    return {
        'run_id': run_id,
        'saved_at': saved_at or _now_iso(),
        'command': command_list,
        'command_line': ' '.join(command_list),
        'preset': preset,
        'mode': mode,
        'ritual_chain': ritual_chain,
        'baseline_source': baseline_source or '',
        'output_dir': output_dir or '',
        'flags': config.flags(),
        'config': config.as_dict(),
        'runtime': {
            'python_version': sys.version,
            'python_executable': sys.executable,
            'platform': platform.platform(),
            'dependency_versions': _dependency_versions(('requests', 'urllib3', 'tldextract', 'flask', 'playwright')),
            'git_commit': _git_commit(),
        },
    }


def build_structured_snapshot(
    *,
    dataset_names: list[str] | tuple[str, ...],
    datasets: dict[str, list[str]],
    stats: dict[str, object],
    autopsy: dict[str, object],
    manifest: dict[str, object],
    content_types: dict[str, int] | None = None,
) -> dict[str, object]:
    """Build the structured temporal baseline manifest used for later diffs."""
    run_metadata = autopsy.get('run_metadata', {}) if isinstance(autopsy, dict) else {}
    snapshot = {
        'snapshot_version': 2,
        **{name: list(datasets.get(name, [])) for name in dataset_names if name in datasets},
        'stats': dict(stats or {}),
        'content_types': {str(name): int(count) for name, count in sorted((content_types or {}).items())},
        'artifact_genealogy': _snapshot_genealogy(autopsy.get('artifact_genealogy') or {}),
        'artifact_hashes': manifest.get('artifacts') or {},
        'report_metadata': {
            'mode': manifest.get('target', {}).get('mode'),
            'preset': manifest.get('target', {}).get('preset'),
            'ritual_chain': manifest.get('target', {}).get('ritual_chain'),
            'command_line': run_metadata.get('command_line', ''),
            'baseline_source': run_metadata.get('baseline_source', ''),
            'flags': dict(run_metadata.get('flags') or {}),
            'python_version': ((run_metadata.get('runtime') or {}).get('python_version') or ''),
            'git_commit': ((run_metadata.get('runtime') or {}).get('git_commit') or ''),
        },
        'autopsy_summary': _autopsy_summary_for_snapshot(autopsy),
    }
    return snapshot


def _append_probe(probes: list[dict[str, str]], seen: set[str], probe: str, source: str, reason: str) -> None:
    if probe in seen:
        return
    seen.add(probe)
    probes.append({'probe': probe, 'source': source, 'reason': reason})


def _document_mutations(root: str, path: str) -> list[str]:
    basename = os.path.basename(path)
    directory = path.rsplit('/', 1)[0].strip('/')
    stem, dot, suffix = basename.rpartition('.')
    stem = stem or basename
    candidates = []
    year_match = re.search(r'(20\d{2})', stem)
    if year_match:
        year = int(year_match.group(1))
        for older in range(max(year - 2, 2000), year):
            candidates.append(stem.replace(str(year), str(older)) + dot + suffix)
    for affix in ('draft', 'backup', 'old', 'final', 'en', 'fr'):
        candidates.append(f'{stem}-{affix}{dot}{suffix}')
        candidates.append(f'{affix}-{stem}{dot}{suffix}')
    prefix = f'{root}/{directory}' if directory else root
    return [f'{prefix}/{candidate}' for candidate in candidates]


def _path_matches(url: str, suffixes: tuple[str, ...]) -> bool:
    return urlsplit(url).path.lower().endswith(suffixes)


def _external_host(url: str, main_url: str) -> bool:
    return bool(urlsplit(url).netloc and urlsplit(url).netloc != urlsplit(main_url).netloc)


def _unique(items: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _dependency_versions(names: tuple[str, ...]) -> dict[str, str]:
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'missing'
    return versions


def _hash_output_dir(output_dir: str) -> dict[str, dict[str, object]]:
    artifacts: dict[str, dict[str, object]] = {}
    if not output_dir or not os.path.isdir(output_dir):
        return artifacts
    for entry in sorted(os.listdir(output_dir)):
        if entry in {'crawl-manifest.json', TEMPORAL_BASELINE_FILE}:
            continue
        path = os.path.join(output_dir, entry)
        if not os.path.isfile(path):
            continue
        artifacts[entry] = {
            'sha256': _hash_file(path),
            'size': os.path.getsize(path),
        }
    return artifacts


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _load_json_file(path: str) -> dict[str, object] | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _top_content_type_map(summary: dict[str, object]) -> dict[str, int]:
    entries = summary.get('top_content_types', []) if isinstance(summary, dict) else []
    mapping: dict[str, int] = {}
    for item in entries:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            mapping[str(item[0])] = int(item[1])
    return mapping


def _snapshot_genealogy(genealogy: dict[str, object]) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    if not isinstance(genealogy, dict):
        return snapshot
    for url, record in genealogy.items():
        if not isinstance(record, dict):
            continue
        snapshot[str(url)] = {
            'content_type': str(record.get('content_type') or ''),
            'sha256': str(record.get('sha256') or ''),
            'size': int(record.get('size') or 0),
            'archive_presence': bool(record.get('archive_presence')),
            'first_seen': str(record.get('first_seen') or ''),
            'last_seen': str(record.get('last_seen') or ''),
            'title': str(record.get('title') or ''),
        }
    return snapshot


def _autopsy_summary_for_snapshot(autopsy: dict[str, object]) -> dict[str, object]:
    summary = autopsy.get('run_summary', {}) if isinstance(autopsy, dict) else {}
    return {
        'pages_crawled': int(summary.get('pages_crawled', 0) or 0),
        'skipped': int(summary.get('skipped', 0) or 0),
        'failed': int(summary.get('failed', 0) or 0),
        'exports': [str(item) for item in (summary.get('exports') or [])],
        'top_content_types': _top_content_type_map(summary),
    }


def _report_metadata_from_autopsy(autopsy: dict[str, object]) -> dict[str, object]:
    run_metadata = autopsy.get('run_metadata', {}) if isinstance(autopsy, dict) else {}
    runtime = run_metadata.get('runtime', {}) if isinstance(run_metadata, dict) else {}
    return {
        'mode': autopsy.get('what_the_target_is', {}).get('mode'),
        'preset': autopsy.get('what_the_target_is', {}).get('preset'),
        'ritual_chain': autopsy.get('what_the_target_is', {}).get('ritual_chain'),
        'command_line': run_metadata.get('command_line', ''),
        'baseline_source': run_metadata.get('baseline_source', ''),
        'flags': dict(run_metadata.get('flags') or {}),
        'python_version': runtime.get('python_version', ''),
        'git_commit': runtime.get('git_commit', ''),
    }


def _manifest_report_metadata(manifest: dict[str, object]) -> dict[str, object]:
    run_metadata = manifest.get('run_metadata', {}) if isinstance(manifest, dict) else {}
    runtime = run_metadata.get('runtime', {}) if isinstance(run_metadata, dict) else {}
    return {
        'mode': manifest.get('target', {}).get('mode'),
        'preset': manifest.get('target', {}).get('preset'),
        'ritual_chain': manifest.get('target', {}).get('ritual_chain'),
        'command_line': run_metadata.get('command_line', ''),
        'baseline_source': run_metadata.get('baseline_source', ''),
        'flags': dict(run_metadata.get('flags') or {}),
        'python_version': runtime.get('python_version', ''),
        'git_commit': runtime.get('git_commit', ''),
    }


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    return result.stdout.strip() if result.returncode == 0 else ''
