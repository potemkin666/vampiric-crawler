#!/usr/bin/env python3
"""Flask web console for Vampiric Crawler."""
from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
import threading
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, render_template, request, send_file

from core.autopsy import (
    ANALYSIS_DATASET_NAMES,
    build_autopsy,
    build_crawl_manifest,
    build_run_metadata,
    build_mutation_probes,
    build_site_anatomy,
    build_structured_snapshot,
    finalize_genealogy,
    render_autopsy_markdown,
    write_manifest_file,
    write_structured_snapshot_file,
)
from core.config import RuntimeConfig
from core.modes import (
    MODE_DATASET_NAMES,
    MODE_DEFINITIONS,
    PRESET_DEFINITIONS,
    RITUAL_CHAIN_DEFINITIONS,
    coerce_mode,
    coerce_preset,
    coerce_ritual_chain,
)
from core.specimen import apply_preset, classify_specimen, resolve_ritual_plan, setup_status
from plugins.exporter import exporter

REPO_ROOT = Path(__file__).resolve().parent
RUNS_ROOT = REPO_ROOT / 'webui_runs'
ENTRYPOINT = REPO_ROOT / 'vampire.py'
ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
URL_RE = re.compile(r'https?://[^\s]+')
DATASET_FILES = (
    'internal',
    'external',
    'fuzzable',
    'intel',
    'keys',
    'forms',
    'files',
    'scripts',
    'endpoints',
    'robots',
    'custom',
    'failed',
    'skipped',
    'redirects',
    'stats',
    'subdomains',
    *MODE_DATASET_NAMES,
    *ANALYSIS_DATASET_NAMES,
)
TEXT_LIMIT = 250
WEBUI_EVENT_PREFIX = '[WEBUI]'
STATUS_MESSAGES = {
    'idle': 'THE CRAWLER SLEEPS',
    'ready': 'TARGET ACQUIRED',
    'running': 'DESCENT IN PROGRESS',
    'paused': 'RITE SUSPENDED',
    'complete': 'CRAWL SEALED',
    'error': 'OMEN DETECTED',
    'blocked': 'GATE SEALED',
    'empty': 'THE ARCHIVE IS SILENT',
    'stopping': 'HALT RITE',
}


def default_queue_snapshot() -> dict[str, dict[str, Any]]:
    return {
        name: {'count': 0, 'items': []}
        for name in ('pending', 'active', 'completed', 'skipped')
    }


def default_robots_metadata() -> dict[str, Any]:
    return {'rules': [], 'crawl_delay': None}


def default_sitemap_metadata() -> dict[str, Any]:
    return {'sitemap_urls': [], 'queued_urls': []}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_ansi(value: str) -> str:
    return ANSI_RE.sub('', value).replace('\r', '').strip()


def slugify_target(target_url: str) -> str:
    parsed = urlparse(target_url)
    host = parsed.netloc or parsed.path or 'target'
    return re.sub(r'[^a-z0-9]+', '-', host.lower()).strip('-') or 'target'


def read_text_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8') as handle:
        return [line.rstrip('\n') for line in handle if line.strip()]


def read_stats(path: Path) -> dict[str, Any]:
    stats = {}
    for line in read_text_lines(path):
        key, _, value = line.partition('=')
        if not key:
            continue
        value = value.strip()
        if value.isdigit():
            stats[key] = int(value)
        else:
            try:
                stats[key] = float(value)
            except ValueError:
                stats[key] = value
    return stats


def parse_redirects(items: list[str]) -> dict[str, list[str]]:
    """Return {source_url: [redirect trail...]} parsed from `url => a -> b` lines."""
    mapping: dict[str, list[str]] = {}
    for item in items:
        source, _, trail = item.partition(' => ')
        source = source.strip()
        if not source or not trail:
            continue
        chain = []
        for part in trail.split(' -> '):
            cleaned = part.strip()
            if cleaned:
                chain.append(cleaned)
        mapping[source] = chain
    return mapping


def filter_documents(items: list[str]) -> list[str]:
    doc_exts = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.rtf')
    return [item for item in items if item.lower().split('?', 1)[0].endswith(doc_exts)]


def filter_mail_sigils(items: list[str]) -> list[str]:
    return [item for item in items if 'EMAIL:' in item]


def mode_label(mode: str) -> str:
    return MODE_DEFINITIONS.get(coerce_mode(mode), MODE_DEFINITIONS['generic'])['label']


def mode_description(mode: str) -> str:
    return MODE_DEFINITIONS.get(coerce_mode(mode), MODE_DEFINITIONS['generic'])['description']


def count_unique_scam_signal_types(items: list[str]) -> int:
    return len({item.split(' signal=', 1)[-1].split(' ', 1)[0] for item in items})


def resolve_payload(payload: dict[str, Any]) -> dict[str, Any]:
    specimen_input = (payload.get('target_specimen') or payload.get('target_url') or '').strip()
    if not specimen_input:
        raise ValueError('TARGET SPECIMEN is required.')
    specimen = classify_specimen(specimen_input, payload.get('input_kind'))
    ritual = resolve_ritual_plan(specimen, payload.get('ritual_chain'), payload.get('mode'))
    resolved = {
        'target_specimen': specimen_input,
        'target_url': (specimen.get('crawl_roots') or [''])[0] or specimen_input,
        'specimen': specimen,
        'ritual_chain': ritual['ritual_chain'],
        'ritual_label': ritual['label'],
        'ritual_description': ritual['description'],
        'mode': ritual['mode'],
        'input_kind': payload.get('input_kind', 'auto'),
        'scope': payload.get('scope', 'host'),
        'extract_intel': payload.get('extract_intel', True),
        'extract_secrets': payload.get('extract_secrets', False),
        'respect_robots_delay': payload.get('respect_robots_delay', True),
        'render_js': payload.get('render_js', False),
        'archive_seeds': payload.get('archive_seeds', False),
        'enumerate_subdomains': payload.get('enumerate_subdomains', False),
        'dry_run': payload.get('dry_run', False),
        'hidden_words': payload.get('hidden_words', []),
        'preset': coerce_preset(payload.get('preset')),
        'depth': payload.get('depth', 2),
        'threads': payload.get('threads', 4),
        'delay': payload.get('delay', 0),
        'timeout': payload.get('timeout', 8),
    }
    explicit = {'scope', 'extract_intel', 'extract_secrets', 'respect_robots_delay', 'render_js', 'archive_seeds', 'enumerate_subdomains', 'dry_run', 'input_kind'}
    if 'depth' in payload:
        explicit.add('depth')
    if 'threads' in payload:
        explicit.add('threads')
    if 'delay' in payload:
        explicit.add('delay')
    if 'timeout' in payload:
        explicit.add('timeout')
    for key, value in ritual.get('defaults', {}).items():
        if key not in explicit:
            resolved[key] = value
    resolved = apply_preset(resolved, resolved['preset'], explicit)
    resolved['mode'] = coerce_mode(payload.get('mode') or resolved['mode'])
    if payload.get('temporal_baseline'):
        resolved['temporal_baseline'] = payload['temporal_baseline']
    runtime_config = RuntimeConfig.from_mapping({
        **resolved,
        'ritual_chain': ritual['ritual_chain'],
    })
    resolved.update(runtime_config.as_dict())
    resolved['ritual_chain'] = ritual['ritual_chain']
    return resolved


def build_crawl_command(payload: dict[str, Any], output_dir: Path, checkpoint_path: Path) -> list[str]:
    payload = resolve_payload(payload)
    target_specimen = (payload.get('target_specimen') or '').strip()
    if not target_specimen:
        raise ValueError('TARGET SPECIMEN is required.')
    runtime_config = RuntimeConfig.from_mapping(payload)

    depth = min(runtime_config.depth, 8)
    threads = min(runtime_config.threads, 32)
    delay = runtime_config.delay
    timeout = runtime_config.timeout
    scope = runtime_config.scope
    mode = coerce_mode(runtime_config.mode)

    command = [
        sys.executable,
        '-u',
        str(ENTRYPOINT),
        '--target',
        target_specimen,
        '-l',
        str(depth),
        '-t',
        str(threads),
        '-d',
        str(delay),
        '--timeout',
        str(timeout),
        '--scope',
        scope,
        '--mode',
        mode,
        '--ritual-chain',
        coerce_ritual_chain(payload.get('ritual_chain')),
        '--preset',
        coerce_preset(payload.get('preset')),
        '--input-kind',
        runtime_config.input_kind,
        '--checkpoint',
        str(checkpoint_path),
        '-o',
        str(output_dir),
        '-v',
    ]

    if runtime_config.respect_robots_delay:
        command.append('--respect-robots-delay')
    if runtime_config.render_js:
        command.append('--render-js')
    if runtime_config.enumerate_subdomains:
        command.append('--dns')
    if runtime_config.archive_seeds:
        command.append('--wayback')
    if runtime_config.extract_secrets:
        command.append('--keys')
    if runtime_config.only_urls:
        command.append('--only-urls')
    if runtime_config.dry_run:
        command.append('--dry-run')
    if runtime_config.temporal_baseline:
        command.extend(['--temporal-baseline', runtime_config.temporal_baseline])
    for word in runtime_config.hidden_words:
        command.extend(['--hidden-word', word])
    return command


def command_preview(payload: dict[str, Any]) -> str:
    payload = resolve_payload(payload)
    runtime_config = RuntimeConfig.from_mapping(payload)
    mode = coerce_mode(runtime_config.mode)
    preview = f'CRAWL {(payload.get("target_specimen") or "").strip()} --depth {runtime_config.depth}'
    if payload.get('ritual_chain'):
        preview += f' --ritual-chain {payload["ritual_chain"]}'
    if mode != 'generic':
        preview += f' --mode {mode}'
    if runtime_config.preset != 'balanced':
        preview += f' --preset {runtime_config.preset}'
    if runtime_config.scope == 'domain':
        preview += ' --scope domain'
    if runtime_config.render_js:
        preview += ' --render-js'
    if runtime_config.archive_seeds:
        preview += ' --wayback'
    if runtime_config.enumerate_subdomains:
        preview += ' --dns'
    if runtime_config.dry_run:
        preview += ' --dry-run'
    if runtime_config.temporal_baseline:
        preview += f' --temporal-baseline {runtime_config.temporal_baseline}'
    if runtime_config.hidden_words:
        preview += f' --hidden-word {runtime_config.hidden_words[0]}'
    return preview.strip()


@dataclass
class CrawlRun:
    run_id: str
    payload: dict[str, Any]
    output_dir: Path
    checkpoint_path: Path
    command: list[str]
    created_at: str = field(default_factory=now_iso)
    started_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    status: str = 'ready'
    status_detail: str = 'TARGET ACQUIRED'
    process: subprocess.Popen[str] | None = None
    exit_code: int | None = None
    stop_requested: bool = False
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=500))
    feed: deque[str] = field(default_factory=lambda: deque(maxlen=250))
    errors: deque[str] = field(default_factory=lambda: deque(maxlen=150))
    lock: threading.Lock = field(default_factory=threading.Lock)
    exports_ready: bool = False
    result_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    queue_snapshot: dict[str, dict[str, Any]] = field(default_factory=default_queue_snapshot)
    robots_metadata: dict[str, Any] = field(default_factory=default_robots_metadata)
    sitemap_metadata: dict[str, Any] = field(default_factory=default_sitemap_metadata)

    def ingest_log(self, raw_line: str) -> None:
        line = strip_ansi(raw_line)
        if not line:
            return
        if line.startswith(WEBUI_EVENT_PREFIX):
            self.ingest_event(line[len(WEBUI_EVENT_PREFIX):])
            return
        with self.lock:
            self.logs.append(line)
            lowered = line.lower()
            if (
                'internal page:' in lowered
                or 'external page:' in lowered
                or 'descending to depth' in lowered
                or 'drained ' in lowered
                or 'subdomain:' in lowered
                or 'harvest summary' in lowered
            ):
                self.feed.append(line)
            if (
                'failed to feed' in lowered
                or 'rejected by the prey' in lowered
                or 'fought back' in lowered
                or 'could not' in lowered
                or 'malformed' in lowered
                or 'disabled' in lowered
            ):
                self.errors.append(line)

    def ingest_event(self, payload: str) -> None:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return
        event_type = event.get('type')
        data = event.get('payload') or {}
        with self.lock:
            if event_type == 'result' and isinstance(data, dict) and data.get('url'):
                self.result_records[str(data['url'])] = {
                    'url': str(data.get('url') or ''),
                    'status_code': data.get('status_code'),
                    'content_type': str(data.get('content_type') or ''),
                    'depth': data.get('depth'),
                    'source_page': str(data.get('source_page') or ''),
                    'discovery_time': int(data.get('discovery_time') or 0),
                    'state': str(data.get('state') or 'pending'),
                    'error_kind': str(data.get('error_kind') or ''),
                    'error_message': str(data.get('error_message') or ''),
                    'source_kind': str(data.get('source_kind') or ''),
                }
            elif event_type == 'queue' and isinstance(data, dict):
                self.queue_snapshot = {
                    name: {
                        'count': int((details or {}).get('count') or 0),
                        'items': [str(item) for item in ((details or {}).get('items') or [])],
                    }
                    for name, details in data.items()
                }
            elif event_type == 'robots' and isinstance(data, dict):
                self.robots_metadata = {
                    'rules': list(data.get('rules') or []),
                    'crawl_delay': data.get('crawl_delay'),
                }
            elif event_type == 'sitemap' and isinstance(data, dict):
                self.sitemap_metadata = {
                    'sitemap_urls': [str(item) for item in (data.get('sitemap_urls') or [])],
                    'queued_urls': [str(item) for item in (data.get('queued_urls') or [])],
                }
            elif event_type == 'error' and isinstance(data, dict):
                message = data.get('message') or 'The rite failed.'
                category = data.get('category')
                url = data.get('url')
                status_code = data.get('status_code')
                parts = [str(message)]
                if category:
                    parts.append(f'category={category}')
                if status_code:
                    parts.append(f'status={status_code}')
                if url:
                    parts.append(f'url={url}')
                self.errors.append(' | '.join(parts))

    def snapshot(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        datasets, stats = collect_run_artifacts(self.output_dir, self.checkpoint_path)
        checkpoint_meta = load_checkpoint_metadata(self.checkpoint_path)
        visible_status = self.status
        if visible_status == 'ready' and self.process:
            visible_status = 'running'
        if visible_status == 'complete' and not any(datasets.values()) and not stats:
            visible_status = 'empty'
        with self.lock:
            logs = list(self.logs)
            feed = list(self.feed)
            errors = list(self.errors)
            result_records = dict(self.result_records)
            queue_snapshot = dict(self.queue_snapshot)
            robots_metadata = dict(self.robots_metadata)
            sitemap_metadata = dict(self.sitemap_metadata)
        return {
            'id': self.run_id,
            'status': visible_status,
            'status_message': STATUS_MESSAGES.get(visible_status, STATUS_MESSAGES['idle']),
            'status_detail': self.status_detail,
            'target_url': self.payload.get('target_url', ''),
            'target_specimen': self.payload.get('target_specimen', self.payload.get('target_url', '')),
            'specimen_type': self.payload.get('specimen', {}).get('type', 'url'),
            'ritual_chain': coerce_ritual_chain(self.payload.get('ritual_chain')),
            'ritual_label': self.payload.get('ritual_label', ''),
            'preset': coerce_preset(self.payload.get('preset')),
            'mode': coerce_mode(self.payload.get('mode')),
            'mode_label': mode_label(self.payload.get('mode')),
            'mode_description': mode_description(self.payload.get('mode')),
            'command_preview': command_preview(self.payload),
            'command': self.command,
            'started_at': self.started_at,
            'ended_at': self.ended_at,
            'output_dir': str(self.output_dir),
            'can_pause': visible_status == 'running',
            'can_resume': visible_status == 'paused',
            'can_stop': visible_status in {'running', 'paused', 'stopping'},
            'logs': logs,
            'feed': feed,
            'errors': errors,
            'queue': queue_snapshot if any(details.get('count') for details in queue_snapshot.values()) else checkpoint_meta['queue'],
            'robots_details': robots_metadata if robots_metadata.get('rules') or robots_metadata.get('crawl_delay') is not None else checkpoint_meta['robots'],
            'sitemap_details': sitemap_metadata if sitemap_metadata.get('sitemap_urls') or sitemap_metadata.get('queued_urls') else checkpoint_meta['sitemap'],
            'result_rows': build_result_rows(
                result_records or checkpoint_meta['results'],
                redirect_lines=datasets.get('redirects', []),
                exports=build_exports(self.output_dir),
            ),
            'summary': build_summary(self.payload, datasets, stats),
            'panels': build_panels(self.payload, datasets, stats),
            'exports': build_exports(self.output_dir),
            'sealed_records': history,
            'is_historical': False,
        }


def collect_run_artifacts(output_dir: Path, checkpoint_path: Path) -> tuple[dict[str, list[str]], dict[str, Any]]:
    datasets = {name: [] for name in DATASET_FILES if name != 'stats'}
    stats: dict[str, Any] = {}
    for name in datasets:
        path = output_dir / f'{name}.txt'
        if path.exists():
            datasets[name] = read_text_lines(path)
    stats_path = output_dir / 'stats.txt'
    if stats_path.exists():
        stats = read_stats(stats_path)

    if any(datasets.values()) or stats or not checkpoint_path.exists():
        return datasets, stats

    try:
        with checkpoint_path.open('r', encoding='utf-8') as handle:
            checkpoint = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return datasets, stats

    for name in datasets:
        values = checkpoint.get(name)
        if isinstance(values, list):
            datasets[name] = [str(item) for item in values]
    if isinstance(checkpoint.get('stats'), dict):
        stats = checkpoint['stats']
    return datasets, stats


def load_checkpoint_metadata(checkpoint_path: Path) -> dict[str, Any]:
    metadata = {
        'queue': default_queue_snapshot(),
        'results': {},
        'robots': default_robots_metadata(),
        'sitemap': default_sitemap_metadata(),
    }
    if not checkpoint_path.exists():
        return metadata
    try:
        with checkpoint_path.open('r', encoding='utf-8') as handle:
            checkpoint = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return metadata

    queue_state = checkpoint.get('queue_state') or {}
    if isinstance(queue_state, dict):
        metadata['queue'] = {
            name: {
                'count': len(values or []),
                'items': [str(item) for item in (values or [])[:12]],
            }
            for name, values in queue_state.items()
        }
    crawl_records = checkpoint.get('crawl_records') or {}
    if isinstance(crawl_records, dict):
        metadata['results'] = crawl_records
    robots_metadata = checkpoint.get('robots_metadata') or {}
    if isinstance(robots_metadata, dict):
        metadata['robots'] = {
            'rules': list(robots_metadata.get('rules') or []),
            'crawl_delay': robots_metadata.get('crawl_delay'),
        }
    sitemap_metadata = checkpoint.get('sitemap_metadata') or {}
    if isinstance(sitemap_metadata, dict):
        metadata['sitemap'] = {
            'sitemap_urls': [str(item) for item in (sitemap_metadata.get('sitemap_urls') or [])],
            'queued_urls': [str(item) for item in (sitemap_metadata.get('queued_urls') or [])],
        }
    return metadata


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_saved_run_payload(output_dir: Path, checkpoint_path: Path, history_entry: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    manifest = read_json_file(output_dir / 'crawl-manifest.json')
    target = manifest.get('target') if isinstance(manifest.get('target'), dict) else {}
    resolved_config = manifest.get('resolved_config') if isinstance(manifest.get('resolved_config'), dict) else {}
    lineage = manifest.get('lineage') if isinstance(manifest.get('lineage'), dict) else {}
    if target:
        payload.update(resolved_config)
        payload.update({
            'target_url': str(target.get('main_url') or ''),
            'target_specimen': str(target.get('main_url') or ''),
            'specimen': target.get('specimen') or {},
            'ritual_chain': str(target.get('ritual_chain') or ''),
            'ritual_label': str(target.get('ritual_label') or ''),
            'preset': str(target.get('preset') or payload.get('preset') or 'balanced'),
            'mode': str(target.get('mode') or payload.get('mode') or 'generic'),
            'temporal_baseline': str(lineage.get('temporal_baseline') or ''),
        })

    checkpoint = read_json_file(checkpoint_path)
    if checkpoint:
        payload.setdefault('target_url', str(checkpoint.get('main_url') or ''))
        payload.setdefault('target_specimen', str(checkpoint.get('specimen_input') or payload.get('target_url') or ''))
        payload.setdefault('specimen', checkpoint.get('specimen_profile') or {})
        payload.setdefault('ritual_chain', str(checkpoint.get('ritual_chain') or ''))
        payload.setdefault('preset', str(checkpoint.get('preset') or payload.get('preset') or 'balanced'))
        payload.setdefault('mode', str(checkpoint.get('mode') or payload.get('mode') or 'generic'))
        payload.setdefault('output_dir', str(checkpoint.get('output_dir') or output_dir))

    if history_entry:
        payload.setdefault('target_url', str(history_entry.get('target_url') or ''))
        payload.setdefault('target_specimen', str(history_entry.get('target_url') or payload.get('target_url') or ''))
        payload.setdefault('mode', str(history_entry.get('mode') or payload.get('mode') or 'generic'))

    payload.setdefault('target_url', '')
    payload.setdefault('target_specimen', payload.get('target_url', ''))
    payload.setdefault('preset', 'balanced')
    payload.setdefault('mode', 'generic')
    return payload


def build_saved_run_snapshot(run_id: str, output_dir: Path, checkpoint_path: Path, history: list[dict[str, Any]], history_entry: dict[str, Any] | None = None) -> dict[str, Any]:
    datasets, stats = collect_run_artifacts(output_dir, checkpoint_path)
    checkpoint_meta = load_checkpoint_metadata(checkpoint_path)
    payload = load_saved_run_payload(output_dir, checkpoint_path, history_entry)
    exports = build_exports(output_dir, run_id=run_id)
    status = str((history_entry or {}).get('status') or ('complete' if any(datasets.values()) or stats else 'empty'))
    return {
        'id': run_id,
        'status': status,
        'status_message': STATUS_MESSAGES.get(status, STATUS_MESSAGES['idle']),
        'status_detail': 'SEALED RECORD REOPENED',
        'target_url': payload.get('target_url', ''),
        'target_specimen': payload.get('target_specimen', payload.get('target_url', '')),
        'specimen_type': payload.get('specimen', {}).get('type', 'url'),
        'ritual_chain': coerce_ritual_chain(payload.get('ritual_chain')),
        'ritual_label': payload.get('ritual_label', ''),
        'preset': coerce_preset(payload.get('preset')),
        'mode': coerce_mode(payload.get('mode')),
        'mode_label': mode_label(payload.get('mode', 'generic')),
        'mode_description': mode_description(payload.get('mode', 'generic')),
        'command_preview': command_preview(payload) if (payload.get('target_specimen') or payload.get('target_url')) else 'CRAWL --sealed-record',
        'command': [],
        'started_at': None,
        'ended_at': (history_entry or {}).get('ended_at'),
        'output_dir': str(output_dir),
        'can_pause': False,
        'can_resume': False,
        'can_stop': False,
        'logs': [],
        'feed': [],
        'errors': [],
        'queue': checkpoint_meta['queue'],
        'robots_details': checkpoint_meta['robots'],
        'sitemap_details': checkpoint_meta['sitemap'],
        'result_rows': build_result_rows(checkpoint_meta['results'], redirect_lines=datasets.get('redirects', []), exports=exports),
        'summary': build_summary(payload, datasets, stats),
        'panels': build_panels(payload, datasets, stats),
        'exports': exports,
        'sealed_records': history,
        'is_historical': True,
    }


def build_result_rows(
    records: dict[str, dict[str, Any]],
    redirect_lines: list[str] | None = None,
    exports: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    redirect_map = parse_redirects(redirect_lines or [])
    export_kinds = [item['kind'] for item in (exports or [])]
    rows = []
    for url, raw in sorted(records.items(), key=lambda item: int((item[1] or {}).get('discovery_time') or 0)):
        raw = raw or {}
        state = str(raw.get('state') or 'pending')
        source_kind = str(raw.get('source_kind') or '')
        related_panel_key, related_panel_title = related_panel_for_row(
            state=state,
            source_kind=source_kind,
            content_type=str(raw.get('content_type') or ''),
        )
        rows.append({
            'url': str(raw.get('url') or url),
            'status_code': raw.get('status_code'),
            'content_type': str(raw.get('content_type') or ''),
            'depth': raw.get('depth'),
            'source_page': str(raw.get('source_page') or ''),
            'discovery_time': int(raw.get('discovery_time') or 0),
            'state': state,
            'error_kind': str(raw.get('error_kind') or ''),
            'error_message': str(raw.get('error_message') or ''),
            'source_kind': source_kind,
            'redirect_chain': redirect_map.get(str(raw.get('url') or url), []),
            'discovery_path': [item for item in (str(raw.get('source_page') or ''), str(raw.get('url') or url)) if item],
            'related_panel_key': related_panel_key,
            'related_panel_title': related_panel_title,
            'export_kinds': export_kinds,
        })
    return rows


def related_panel_for_row(*, state: str, source_kind: str, content_type: str) -> tuple[str, str]:
    lowered_kind = source_kind.lower()
    lowered_type = content_type.lower()
    if state in {'failed', 'skipped'}:
        return 'broken', 'BROKEN GATES'
    if 'script' in lowered_kind or 'javascript' in lowered_type:
        return 'scripts', 'SCRIPT BONES'
    if 'document' in lowered_kind or any(token in lowered_type for token in ('pdf', 'msword', 'officedocument')):
        return 'documents', 'DOCUMENT TOMBS'
    return 'links', 'CRYPT PATHS'


def build_summary(payload: dict[str, Any], datasets: dict[str, list[str]], stats: dict[str, Any]) -> dict[str, Any]:
    mode = coerce_mode(payload.get('mode'))
    summary = {
        'target': payload.get('target_url', ''),
        'target_specimen': payload.get('target_specimen', payload.get('target_url', '')),
        'specimen_type': payload.get('specimen', {}).get('type', 'url'),
        'ritual_chain': coerce_ritual_chain(payload.get('ritual_chain')),
        'ritual_label': payload.get('ritual_label', ''),
        'preset': coerce_preset(payload.get('preset')),
        'mode': mode,
        'mode_label': mode_label(mode),
        'mode_description': mode_description(mode),
        'depth': int(payload.get('depth', 2)),
        'threads': int(payload.get('threads', 4)),
        'visited': int(stats.get('visited', 0) or 0),
        'failures': int(stats.get('failures', len(datasets.get('failed', []))) or 0),
        'links_unearthed': len(datasets.get('internal', [])),
        'relics_found': len(datasets.get('files', [])),
        'mail_sigils': len(filter_mail_sigils(datasets.get('intel', []))),
        'script_bones': len(datasets.get('scripts', [])),
        'document_tombs': len(filter_documents(datasets.get('files', []))),
        'broken_gates': len(datasets.get('failed', [])),
        'source_vitals': stats,
        'summary_cards': build_summary_cards(mode, datasets, stats),
    }
    return summary


def build_summary_cards(mode: str, datasets: dict[str, list[str]], stats: dict[str, Any]) -> list[dict[str, Any]]:
    cards = [
        {'label': 'LINKS', 'value': len(datasets.get('internal', []))},
        {'label': 'RELICS', 'value': len(datasets.get('files', []))},
        {'label': 'MAIL', 'value': len(filter_mail_sigils(datasets.get('intel', [])))},
        {'label': 'OMENS', 'value': int(stats.get('failures', len(datasets.get('failed', []))) or 0)},
    ]
    mode_cards = {
        'document': [
            {'label': 'TOMBS', 'value': len(datasets.get('document_metadata', []))},
            {'label': 'LEAKS', 'value': len(datasets.get('document_leaks', []))},
        ],
        'js-intel': [
            {'label': 'SIGILS', 'value': len(datasets.get('js_intel', []))},
            {'label': 'SCRIPTS', 'value': len(datasets.get('scripts', []))},
        ],
        'forum': [
            {'label': 'THREADS', 'value': len(datasets.get('threads', []))},
            {'label': 'REPLIES', 'value': len([item for item in datasets.get('threads', []) if 'reply_to=' in item])},
        ],
        'geo': [
            {'label': 'EXACT', 'value': len([item for item in datasets.get('locations', []) if 'confidence=exact' in item])},
            {'label': 'WEAK', 'value': len([item for item in datasets.get('locations', []) if 'confidence=weak' in item])},
        ],
        'news': [
            {'label': 'PAGES', 'value': len([item for item in datasets.get('stories', []) if ' relation=page ' in item])},
            {'label': 'MIRRORS', 'value': len([item for item in datasets.get('stories', []) if ' relation=mirror ' in item])},
        ],
        'hidden': [
            {'label': 'SHADOWS', 'value': len(datasets.get('hidden_paths', []))},
            {'label': 'PROBES', 'value': len(datasets.get('hidden_probe_sources', []))},
        ],
        'scam': [
            {'label': 'HEXES', 'value': len(datasets.get('scam_signals', []))},
            {'label': 'RUSES', 'value': count_unique_scam_signal_types(datasets.get('scam_signals', []))},
        ],
        'temporal': [
            {'label': 'DIFFS', 'value': len(datasets.get('temporal_diffs', []))},
            {'label': 'VISITED', 'value': int(stats.get('visited', 0) or 0)},
        ],
    }
    cards.extend(mode_cards.get(mode, [{'label': 'DOCS', 'value': len(filter_documents(datasets.get('files', [])))}, {'label': 'SCRIPTS', 'value': len(datasets.get('scripts', []))}]))
    return cards[:6]


def build_panels(payload: dict[str, Any], datasets: dict[str, list[str]], stats: dict[str, Any]) -> list[dict[str, Any]]:
    mode = coerce_mode(payload.get('mode'))
    failed = datasets.get('failed', [])
    panels = {
        'links': {'key': 'links', 'title': 'CRYPT PATHS', 'count': len(datasets.get('internal', [])), 'items': datasets.get('internal', [])[:TEXT_LIMIT]},
        'mail': {'key': 'mail', 'title': 'MAIL SIGILS', 'count': len(filter_mail_sigils(datasets.get('intel', []))), 'items': filter_mail_sigils(datasets.get('intel', []))[:TEXT_LIMIT]},
        'documents': {'key': 'documents', 'title': 'DOCUMENT TOMBS', 'count': len(filter_documents(datasets.get('files', []))), 'items': filter_documents(datasets.get('files', []))[:TEXT_LIMIT]},
        'relics': {'key': 'relics', 'title': 'RELIC RELIQUARY', 'count': len(datasets.get('files', [])), 'items': datasets.get('files', [])[:TEXT_LIMIT]},
        'scripts': {'key': 'scripts', 'title': 'SCRIPT BONES', 'count': len(datasets.get('scripts', [])), 'items': datasets.get('scripts', [])[:TEXT_LIMIT]},
        'broken': {'key': 'broken', 'title': 'BROKEN GATES', 'count': len(failed), 'items': failed[:TEXT_LIMIT]},
        'forms': {'key': 'forms', 'title': 'RITUAL FORMS', 'count': len(datasets.get('forms', [])), 'items': datasets.get('forms', [])[:TEXT_LIMIT]},
        'vitals': {'key': 'vitals', 'title': 'NIGHT VITALS', 'count': len(stats), 'items': [f'{key}={value}' for key, value in sorted(stats.items())][:TEXT_LIMIT]},
        'document_metadata': {'key': 'document_metadata', 'title': 'PARCHMENT METADATA', 'count': len(datasets.get('document_metadata', [])), 'items': datasets.get('document_metadata', [])[:TEXT_LIMIT]},
        'document_leaks': {'key': 'document_leaks', 'title': 'ARCHIVE LEAKS', 'count': len(datasets.get('document_leaks', [])), 'items': datasets.get('document_leaks', [])[:TEXT_LIMIT]},
        'js_intel': {'key': 'js_intel', 'title': 'ARCANE JS SIGILS', 'count': len(datasets.get('js_intel', [])), 'items': datasets.get('js_intel', [])[:TEXT_LIMIT]},
        'threads': {'key': 'threads', 'title': 'THREAD NECROLOGY', 'count': len(datasets.get('threads', [])), 'items': datasets.get('threads', [])[:TEXT_LIMIT]},
        'locations': {'key': 'locations', 'title': 'BLOOD MAP POINTS', 'count': len(datasets.get('locations', [])), 'items': datasets.get('locations', [])[:TEXT_LIMIT]},
        'stories': {'key': 'stories', 'title': 'MUTATING STORY CHAINS', 'count': len(datasets.get('stories', [])), 'items': datasets.get('stories', [])[:TEXT_LIMIT]},
        'hidden_paths': {'key': 'hidden_paths', 'title': 'SHADOW GATES', 'count': len(datasets.get('hidden_paths', [])), 'items': datasets.get('hidden_paths', [])[:TEXT_LIMIT]},
        'hidden_probe_sources': {'key': 'hidden_probe_sources', 'title': 'SHADOW PROBE SOURCES', 'count': len(datasets.get('hidden_probe_sources', [])), 'items': datasets.get('hidden_probe_sources', [])[:TEXT_LIMIT]},
        'scam_signals': {'key': 'scam_signals', 'title': 'HEXED MERCHANT OMENS', 'count': len(datasets.get('scam_signals', [])), 'items': datasets.get('scam_signals', [])[:TEXT_LIMIT]},
        'temporal_diffs': {'key': 'temporal_diffs', 'title': 'TIME-SLICE OMENS', 'count': len(datasets.get('temporal_diffs', [])), 'items': datasets.get('temporal_diffs', [])[:TEXT_LIMIT]},
        'site_anatomy': {'key': 'site_anatomy', 'title': 'SITE ANATOMY', 'count': len(datasets.get('site_anatomy', [])), 'items': datasets.get('site_anatomy', [])[:TEXT_LIMIT]},
        'mutation_probes': {'key': 'mutation_probes', 'title': 'MUTATION ENGINE', 'count': len(datasets.get('mutation_probes', [])), 'items': datasets.get('mutation_probes', [])[:TEXT_LIMIT]},
        'artifact_genealogy': {'key': 'artifact_genealogy', 'title': 'ARTIFACT GENEALOGY', 'count': len(datasets.get('artifact_genealogy', [])), 'items': datasets.get('artifact_genealogy', [])[:TEXT_LIMIT]},
    }
    mode_layout = {
        'document': ['document_metadata', 'document_leaks', 'artifact_genealogy', 'documents', 'links', 'vitals'],
        'js-intel': ['js_intel', 'mutation_probes', 'scripts', 'links', 'relics', 'vitals'],
        'forum': ['threads', 'links', 'mail', 'vitals'],
        'geo': ['locations', 'links', 'vitals'],
        'news': ['stories', 'links', 'vitals'],
        'hidden': ['hidden_paths', 'hidden_probe_sources', 'links', 'broken', 'vitals'],
        'scam': ['scam_signals', 'links', 'forms', 'vitals'],
        'temporal': ['temporal_diffs', 'artifact_genealogy', 'links', 'vitals'],
        'generic': ['site_anatomy', 'mutation_probes', 'links', 'mail', 'documents', 'relics', 'scripts', 'broken', 'forms', 'vitals'],
    }
    ordered_keys = mode_layout.get(mode, mode_layout['generic'])
    selected = [panels[key] for key in ordered_keys if panels[key]['count'] or key == 'vitals']
    return selected


def build_exports(output_dir: Path, run_id: str | None = None) -> list[dict[str, str]]:
    files = (
        ('json', 'EXPORT JSON', output_dir / 'results.json'),
        ('csv', 'EXPORT CSV', output_dir / 'results.csv'),
        ('autopsy-json', 'AUTOPSY JSON', output_dir / 'autopsy.json'),
        ('autopsy-md', 'AUTOPSY MD', output_dir / 'autopsy.md'),
        ('manifest-json', 'CRAWL MANIFEST', output_dir / 'crawl-manifest.json'),
        ('bundle', 'EXPORT BUNDLE', output_dir / 'sealed-bundle.zip'),
    )
    href_prefix = f'/api/runs/{run_id}/exports' if run_id else '/api/exports'
    return [
        {'kind': kind, 'label': label, 'href': f'{href_prefix}/{kind}'}
        for kind, label, path in files
        if path.exists()
    ]


def ensure_exports(run: CrawlRun) -> None:
    if run.exports_ready:
        return
    datasets, stats = collect_run_artifacts(run.output_dir, run.checkpoint_path)
    runtime_config = RuntimeConfig.from_mapping(run.payload)
    payload = {name: values for name, values in datasets.items() if values}
    if stats:
        payload['stats'] = stats
    if not payload:
        return
    exporter(str(run.output_dir), 'json', payload)
    exporter(str(run.output_dir), 'csv', payload)
    anatomy = build_site_anatomy(run.payload.get('target_url', ''), datasets, {}, run.payload.get('specimen', {}))
    probes = build_mutation_probes(run.payload.get('target_url', ''), datasets)
    run_metadata = build_run_metadata(
        run_id=run.run_id,
        preset=coerce_preset(run.payload.get('preset')),
        mode=coerce_mode(run.payload.get('mode')),
        ritual_chain=coerce_ritual_chain(run.payload.get('ritual_chain')),
        command=run.command,
        runtime_config=runtime_config,
        baseline_source=str(run.payload.get('temporal_baseline') or ''),
        output_dir=str(run.output_dir),
        saved_at=run.ended_at or now_iso(),
    )
    autopsy = build_autopsy(
        specimen=run.payload.get('specimen', {}),
        ritual={
            'ritual_chain': coerce_ritual_chain(run.payload.get('ritual_chain')),
            'label': run.payload.get('ritual_label', ''),
        },
        preset=coerce_preset(run.payload.get('preset')),
        mode=coerce_mode(run.payload.get('mode')),
        datasets=payload,
        stats=stats,
        genealogy={},
        anatomy=anatomy,
        mutation_probes=probes,
        exports=['results.json', 'results.csv', 'autopsy.json', 'autopsy.md', 'sealed-bundle.zip'],
        duration_seconds=float(stats.get('duration_seconds', 0) or 0),
        content_types={},
        run_metadata=run_metadata,
    )
    autopsy_json_path = run.output_dir / 'autopsy.json'
    autopsy_md_path = run.output_dir / 'autopsy.md'
    autopsy_json_path.write_text(json.dumps(autopsy, indent=2, ensure_ascii=False), encoding='utf-8')
    autopsy_md_path.write_text(render_autopsy_markdown(autopsy), encoding='utf-8')
    manifest = build_crawl_manifest(
        specimen=run.payload.get('specimen', {}),
        ritual={
            'ritual_chain': coerce_ritual_chain(run.payload.get('ritual_chain')),
            'label': run.payload.get('ritual_label', ''),
        },
        preset=coerce_preset(run.payload.get('preset')),
        mode=coerce_mode(run.payload.get('mode')),
        command=run.command,
        output_dir=str(run.output_dir),
        main_url=run.payload.get('target_url', ''),
        resolved_config=runtime_config.as_dict(),
        checkpoint_path=str(run.checkpoint_path),
        temporal_baseline=str(run.payload.get('temporal_baseline') or ''),
        run_metadata=run_metadata,
    )
    write_manifest_file(str(run.output_dir), manifest)
    write_structured_snapshot_file(
        str(run.output_dir),
        build_structured_snapshot(
            dataset_names=DATASET_FILES,
            datasets=datasets,
            stats=stats,
            autopsy=autopsy,
            manifest=manifest,
            content_types={},
        ),
    )
    bundle_path = run.output_dir / 'sealed-bundle.zip'
    with zipfile.ZipFile(bundle_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for child in sorted(run.output_dir.iterdir()):
            if child.name == bundle_path.name:
                continue
            archive.write(child, arcname=child.name)
        archive.writestr('crawl-config.json', json.dumps({
            'payload': run.payload,
            'command': run.command,
            'summary': build_summary(run.payload, datasets, stats),
        }, indent=2, ensure_ascii=False))
        archive.writestr('crawl-log.txt', '\n'.join(list(run.logs)))
    run.exports_ready = True


def build_setup_diagnostics(output_dir: Path, proxy: str | None = None) -> dict[str, Any]:
    status = setup_status(output_dir=str(output_dir), proxy=proxy)
    safe_packages = {
        name: _public_check_status(value)
        for name, value in sorted(status['packages'].items())
    }
    safe_output_dir = {
        'path': status['output_dir']['path'],
        'status': 'ok' if status['output_dir']['status'] == 'ok' else 'missing',
        'detail': status['output_dir']['path'] if status['output_dir']['status'] == 'ok' else 'Review the CLI setup check output for write-path remediation.',
    }
    safe_proxy = {
        'status': status['proxy']['status'],
        'detail': status['proxy']['detail'] if status['proxy']['status'] in {'ok', 'not-configured'} else 'Review the CLI setup check output for proxy remediation.',
    }
    checks = [
        {'name': f'package:{name}', 'status': safe_packages[name], 'detail': _public_check_detail(value)}
        for name, value in sorted(status['packages'].items())
    ]
    checks.extend([
        {'name': 'playwright-browser', 'status': _public_check_status(status['playwright_browser']), 'detail': _public_check_detail(status['playwright_browser'])},
        {'name': 'render-smoke', 'status': _public_check_status(status['render_smoke']), 'detail': _public_check_detail(status['render_smoke'])},
        {'name': 'output-dir', 'status': safe_output_dir['status'], 'detail': safe_output_dir['detail']},
        {'name': 'proxy-sanity', 'status': safe_proxy['status'], 'detail': safe_proxy['detail']},
    ])
    issues = [item for item in checks if str(item['status']) not in {'ok', 'not-configured'}]
    return {
        'packages': safe_packages,
        'playwright_browser': _public_check_status(status['playwright_browser']),
        'render_smoke': _public_check_status(status['render_smoke']),
        'output_dir': safe_output_dir,
        'proxy': safe_proxy,
        'install_hint': status['install_hint'],
        'browser_hint': status['browser_hint'],
        'checks': checks,
        'overall_status': 'ok' if not issues else 'issues',
        'status_message': 'FIRST-RUN DIAGNOSTICS CLEAR' if not issues else 'FIRST-RUN DIAGNOSTICS FOUND ISSUES',
    }


def _public_check_status(value: str) -> str:
    return 'ok' if str(value) == 'ok' else 'missing'


def _public_check_detail(value: str) -> str:
    return 'Dependency ready.' if str(value) == 'ok' else 'Review setup-check output in the CLI for exact remediation.'


class CrawlManager:
    def __init__(self, runs_root: Path):
        self.runs_root = runs_root
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.current_run: CrawlRun | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=8)

    def start(self, payload: dict[str, Any]) -> CrawlRun:
        with self._lock:
            if self.current_run and self.current_run.status in {'running', 'paused', 'stopping'}:
                raise RuntimeError('A crawl rite is already in progress.')
            payload = resolve_payload(dict(payload))
            base_run_id = f'{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}-{slugify_target(payload.get("target_url", ""))}-{coerce_mode(payload.get("mode"))}'
            run_id = base_run_id
            suffix = 1
            while (self.runs_root / run_id).exists():
                suffix += 1
                run_id = f'{base_run_id}-{suffix}'
            output_dir = self.runs_root / run_id
            if payload['mode'] == 'temporal' and not payload.get('temporal_baseline'):
                raise ValueError('Temporal mode requires an explicit baseline path.')
            output_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_path = output_dir / 'checkpoint.json'
            command = build_crawl_command(payload, output_dir, checkpoint_path)
            process = subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, 'PYTHONUNBUFFERED': '1', 'VAMPIRIC_WEBUI_EVENTS': '1'},
            )
            run = CrawlRun(
                run_id=run_id,
                payload=payload,
                output_dir=output_dir,
                checkpoint_path=checkpoint_path,
                command=command,
                process=process,
                status='running',
                status_detail='BEGIN CRAWL',
            )
            self.current_run = run
            thread = threading.Thread(target=self._monitor_run, args=(run,), daemon=True)
            thread.start()
            return run

    def _monitor_run(self, run: CrawlRun) -> None:
        assert run.process is not None
        if run.process.stdout is not None:
            for line in iter(run.process.stdout.readline, ''):
                if not line and run.process.poll() is not None:
                    break
                run.ingest_log(line)
        exit_code = run.process.wait()
        with run.lock:
            run.exit_code = exit_code
            run.ended_at = now_iso()
            if run.stop_requested:
                run.status = 'idle'
                run.status_detail = 'RITE HALTED'
            elif exit_code == 0:
                run.status = 'complete'
                run.status_detail = 'CRAWL SEALED'
            else:
                run.status = 'error'
                run.status_detail = 'OMEN DETECTED'
        if run.status == 'complete':
            ensure_exports(run)
        self.history.appendleft({
            'id': run.run_id,
            'target_url': run.payload.get('target_url', ''),
            'mode': coerce_mode(run.payload.get('mode')),
            'ended_at': run.ended_at,
            'status': run.status,
            'status_message': STATUS_MESSAGES.get(run.status, STATUS_MESSAGES['idle']),
            'output_dir': str(run.output_dir),
            'state_href': f'/api/runs/{run.run_id}',
            'exports': build_exports(run.output_dir, run_id=run.run_id),
        })

    def pause(self) -> CrawlRun:
        run = self._active_run()
        if os.name == 'nt' or not hasattr(signal, 'SIGSTOP'):
            raise RuntimeError('Pause descent is not supported on this platform.')
        assert run.process is not None
        run.process.send_signal(signal.SIGSTOP)
        run.status = 'paused'
        run.status_detail = 'PAUSE DESCENT'
        return run

    def resume(self) -> CrawlRun:
        run = self._active_run(allow_paused=True)
        if run.status != 'paused':
            raise RuntimeError('No suspended rite is waiting to resume.')
        if os.name == 'nt' or not hasattr(signal, 'SIGCONT'):
            raise RuntimeError('Resume descent is not supported on this platform.')
        assert run.process is not None
        run.process.send_signal(signal.SIGCONT)
        run.status = 'running'
        run.status_detail = 'DESCENT IN PROGRESS'
        return run

    def stop(self) -> CrawlRun:
        run = self._active_run(allow_paused=True)
        assert run.process is not None
        run.stop_requested = True
        run.status = 'stopping'
        run.status_detail = 'HALT RITE'
        run.process.send_signal(signal.SIGINT)
        return run

    def state(self) -> dict[str, Any]:
        run = self.current_run
        if run is None:
            return {
                'id': None,
                'status': 'idle',
                'status_message': STATUS_MESSAGES['idle'],
                'status_detail': 'Awaiting a target specimen.',
                'target_url': '',
                'target_specimen': '',
                'specimen_type': 'url',
                'ritual_chain': 'domain_necropsy',
                'ritual_label': RITUAL_CHAIN_DEFINITIONS['domain_necropsy']['label'],
                'preset': 'balanced',
                'mode': 'generic',
                'mode_label': mode_label('generic'),
                'mode_description': mode_description('generic'),
                'command_preview': 'CRAWL https://example.com --depth 2',
                'logs': [],
                'feed': [],
                'errors': [],
                'queue': default_queue_snapshot(),
                'robots_details': default_robots_metadata(),
                'sitemap_details': default_sitemap_metadata(),
                'result_rows': [],
                'summary': build_summary({}, {}, {}),
                'panels': build_panels({}, {}, {}),
                'exports': [],
                'sealed_records': list(self.history),
                'is_historical': False,
                'can_pause': False,
                'can_resume': False,
                'can_stop': False,
            }
        if run.status == 'complete':
            ensure_exports(run)
        return run.snapshot(list(self.history))

    def export_path(self, kind: str) -> Path:
        run = self.current_run
        if not run:
            raise FileNotFoundError('No sealed record available.')
        return self.export_path_for_run(run.run_id, kind)

    def run_state(self, run_id: str) -> dict[str, Any]:
        if self.current_run and self.current_run.run_id == run_id:
            if self.current_run.status == 'complete':
                ensure_exports(self.current_run)
            return self.current_run.snapshot(list(self.history))
        history = list(self.history)
        history_entry = next((item for item in history if item.get('id') == run_id), None)
        output_dir = self._run_dir(run_id, history_entry)
        checkpoint_path = output_dir / 'checkpoint.json'
        return build_saved_run_snapshot(run_id, output_dir, checkpoint_path, history, history_entry)

    def export_path_for_run(self, run_id: str, kind: str) -> Path:
        if self.current_run and self.current_run.run_id == run_id:
            run = self.current_run
            if run.status == 'complete':
                ensure_exports(run)
            output_dir = run.output_dir
        else:
            history_entry = next((item for item in self.history if item.get('id') == run_id), None)
            output_dir = self._run_dir(run_id, history_entry)
        mapping = {
            'json': output_dir / 'results.json',
            'csv': output_dir / 'results.csv',
            'autopsy-json': output_dir / 'autopsy.json',
            'autopsy-md': output_dir / 'autopsy.md',
            'manifest-json': output_dir / 'crawl-manifest.json',
            'bundle': output_dir / 'sealed-bundle.zip',
        }
        path = mapping.get(kind)
        if path is None or not path.exists():
            raise FileNotFoundError(kind)
        return path

    def _run_dir(self, run_id: str, history_entry: dict[str, Any] | None = None) -> Path:
        if not re.fullmatch(r'[A-Za-z0-9._-]+', run_id or ''):
            raise FileNotFoundError(run_id)
        candidate = (history_entry or {}).get('output_dir') or (self.runs_root / run_id)
        path = Path(candidate).resolve()
        allowed_root = self.runs_root.resolve()
        if path == allowed_root:
            raise FileNotFoundError(run_id)
        if path.exists() and path.is_dir() and (path.parent == allowed_root or str(path).startswith(str(allowed_root) + os.sep)):
            return path
        fallback = (self.runs_root / run_id).resolve()
        if fallback.exists() and fallback.is_dir() and fallback.parent == allowed_root:
            return fallback
        else:
            raise FileNotFoundError(run_id)

    def _active_run(self, allow_paused: bool = False) -> CrawlRun:
        run = self.current_run
        if not run:
            raise RuntimeError('No active crawl rite exists.')
        allowed = {'running', 'stopping'}
        if allow_paused:
            allowed.add('paused')
        if run.status not in allowed:
            raise RuntimeError('No active crawl rite exists.')
        return run


def create_app(runs_root: Path | None = None) -> Flask:
    app = Flask(__name__)
    manager = CrawlManager(runs_root or RUNS_ROOT)
    app.config['CRAWL_MANAGER'] = manager

    def error_response(message: str, status_code: int, exc: Exception | None = None) -> Any:
        if exc is not None:
            app.logger.warning('%s: %s', message, exc)
        return jsonify({'error': message}), status_code

    @app.get('/')
    def index() -> str:
        return render_template('index.html')

    @app.get('/api/state')
    def state() -> Any:
        return jsonify(app.config['CRAWL_MANAGER'].state())

    @app.post('/api/preview')
    def preview() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            resolved = resolve_payload(payload)
        except ValueError as exc:
            return error_response('The target specimen is malformed.', 400, exc)
        return jsonify({
            'command_preview': command_preview(resolved),
            'resolved': resolved,
            'preset_description': PRESET_DEFINITIONS[coerce_preset(resolved.get('preset'))]['description'],
        })

    @app.route('/api/setup-check', methods=['GET', 'POST'])
    def setup_check() -> Any:
        try:
            diagnostics = build_setup_diagnostics(RUNS_ROOT)
        except Exception as exc:
            return error_response('First-run diagnostics failed.', 500, exc)
        return jsonify(diagnostics)

    @app.post('/api/crawl')
    def start_crawl() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            run = app.config['CRAWL_MANAGER'].start(payload)
        except ValueError as exc:
            return error_response(str(exc) or 'The target specimen is malformed.', 400, exc)
        except RuntimeError as exc:
            return error_response('Another crawl rite is already active.', 409, exc)
        return jsonify(run.snapshot(list(app.config['CRAWL_MANAGER'].history))), 202

    @app.post('/api/crawl/pause')
    def pause_crawl() -> Any:
        try:
            run = app.config['CRAWL_MANAGER'].pause()
        except RuntimeError as exc:
            return error_response('The rite cannot be paused right now.', 409, exc)
        return jsonify(run.snapshot(list(app.config['CRAWL_MANAGER'].history)))

    @app.post('/api/crawl/resume')
    def resume_crawl() -> Any:
        try:
            run = app.config['CRAWL_MANAGER'].resume()
        except RuntimeError as exc:
            return error_response('The rite cannot be resumed right now.', 409, exc)
        return jsonify(run.snapshot(list(app.config['CRAWL_MANAGER'].history)))

    @app.post('/api/crawl/stop')
    def stop_crawl() -> Any:
        try:
            run = app.config['CRAWL_MANAGER'].stop()
        except RuntimeError as exc:
            return error_response('The rite cannot be halted right now.', 409, exc)
        return jsonify(run.snapshot(list(app.config['CRAWL_MANAGER'].history)))

    @app.get('/api/exports/<kind>')
    def export(kind: str) -> Any:
        try:
            path = app.config['CRAWL_MANAGER'].export_path(kind)
        except FileNotFoundError:
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.get('/api/runs/<run_id>')
    def run_state(run_id: str) -> Any:
        try:
            snapshot = app.config['CRAWL_MANAGER'].run_state(run_id)
        except FileNotFoundError:
            abort(404)
        return jsonify(snapshot)

    @app.get('/api/runs/<run_id>/exports/<kind>')
    def run_export(run_id: str, kind: str) -> Any:
        try:
            path = app.config['CRAWL_MANAGER'].export_path_for_run(run_id, kind)
        except FileNotFoundError:
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    return app


app = create_app()


if __name__ == '__main__':
    host = os.environ.get('VAMPIRIC_WEB_HOST', '127.0.0.1')
    port = int(os.environ.get('VAMPIRIC_WEB_PORT', '8080'))
    app.run(host=host, port=port, debug=False)
