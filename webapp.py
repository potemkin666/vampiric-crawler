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
    build_mutation_probes,
    build_site_anatomy,
    finalize_genealogy,
    render_autopsy_markdown,
)
from core.modes import (
    MODE_DATASET_NAMES,
    MODE_DEFINITIONS,
    PRESET_DEFINITIONS,
    RITUAL_CHAIN_DEFINITIONS,
    coerce_mode,
    coerce_preset,
    coerce_ritual_chain,
)
from core.specimen import apply_preset, classify_specimen, resolve_ritual_plan
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
    return resolved


def build_crawl_command(payload: dict[str, Any], output_dir: Path, checkpoint_path: Path) -> list[str]:
    payload = resolve_payload(payload)
    target_specimen = (payload.get('target_specimen') or '').strip()
    if not target_specimen:
        raise ValueError('TARGET SPECIMEN is required.')

    depth = max(1, min(int(payload.get('depth', 2)), 8))
    threads = max(1, min(int(payload.get('threads', 4)), 32))
    delay = max(0.0, float(payload.get('delay', 0)))
    timeout = max(1.0, float(payload.get('timeout', 8)))
    scope = payload.get('scope', 'host')
    if scope not in ('host', 'domain'):
        raise ValueError('Invalid scope.')
    mode = coerce_mode(payload.get('mode'))

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
        str(payload.get('input_kind', 'auto')),
        '--checkpoint',
        str(checkpoint_path),
        '-o',
        str(output_dir),
        '-v',
    ]

    if payload.get('respect_robots_delay'):
        command.append('--respect-robots-delay')
    if payload.get('render_js'):
        command.append('--render-js')
    if payload.get('enumerate_subdomains'):
        command.append('--dns')
    if payload.get('archive_seeds'):
        command.append('--wayback')
    if payload.get('extract_secrets'):
        command.append('--keys')
    if not payload.get('extract_intel', True):
        command.append('--only-urls')
    if payload.get('dry_run'):
        command.append('--dry-run')
    if payload.get('temporal_baseline'):
        command.extend(['--temporal-baseline', str(payload['temporal_baseline'])])
    return command


def command_preview(payload: dict[str, Any]) -> str:
    payload = resolve_payload(payload)
    mode = coerce_mode(payload.get('mode'))
    preview = f'CRAWL {(payload.get("target_specimen") or "").strip()} --depth {int(payload.get("depth", 2))}'
    if payload.get('ritual_chain'):
        preview += f' --ritual-chain {payload["ritual_chain"]}'
    if mode != 'generic':
        preview += f' --mode {mode}'
    if payload.get('preset', 'balanced') != 'balanced':
        preview += f' --preset {payload["preset"]}'
    if payload.get('scope', 'host') == 'domain':
        preview += ' --scope domain'
    if payload.get('render_js'):
        preview += ' --render-js'
    if payload.get('archive_seeds'):
        preview += ' --wayback'
    if payload.get('enumerate_subdomains'):
        preview += ' --dns'
    if payload.get('dry_run'):
        preview += ' --dry-run'
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
            'result_rows': build_result_rows(result_records or checkpoint_meta['results']),
            'summary': build_summary(self.payload, datasets, stats),
            'panels': build_panels(self.payload, datasets, stats),
            'exports': build_exports(self.output_dir),
            'sealed_records': history,
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


def build_result_rows(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for url, raw in sorted(records.items(), key=lambda item: int((item[1] or {}).get('discovery_time') or 0)):
        raw = raw or {}
        rows.append({
            'url': str(raw.get('url') or url),
            'status_code': raw.get('status_code'),
            'content_type': str(raw.get('content_type') or ''),
            'depth': raw.get('depth'),
            'source_page': str(raw.get('source_page') or ''),
            'discovery_time': int(raw.get('discovery_time') or 0),
            'state': str(raw.get('state') or 'pending'),
            'error_kind': str(raw.get('error_kind') or ''),
            'error_message': str(raw.get('error_message') or ''),
            'source_kind': str(raw.get('source_kind') or ''),
        })
    return rows


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
            {'label': 'PLACES', 'value': len(datasets.get('locations', []))},
            {'label': 'MAP', 'value': len([item for item in datasets.get('locations', []) if 'lat=' in item and 'lon=' in item])},
        ],
        'news': [
            {'label': 'STORIES', 'value': len([item for item in datasets.get('stories', []) if ' title=' in item])},
            {'label': 'REFS', 'value': len([item for item in datasets.get('stories', []) if 'reference=' in item])},
        ],
        'hidden': [
            {'label': 'SHADOWS', 'value': len(datasets.get('hidden_paths', []))},
            {'label': 'ENDPTS', 'value': len(datasets.get('endpoints', []))},
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
        'hidden': ['hidden_paths', 'links', 'broken', 'vitals'],
        'scam': ['scam_signals', 'links', 'forms', 'vitals'],
        'temporal': ['temporal_diffs', 'artifact_genealogy', 'links', 'vitals'],
        'generic': ['site_anatomy', 'mutation_probes', 'links', 'mail', 'documents', 'relics', 'scripts', 'broken', 'forms', 'vitals'],
    }
    ordered_keys = mode_layout.get(mode, mode_layout['generic'])
    selected = [panels[key] for key in ordered_keys if panels[key]['count'] or key == 'vitals']
    return selected


def build_exports(output_dir: Path) -> list[dict[str, str]]:
    files = (
        ('json', 'EXPORT JSON', output_dir / 'results.json'),
        ('csv', 'EXPORT CSV', output_dir / 'results.csv'),
        ('autopsy-json', 'AUTOPSY JSON', output_dir / 'autopsy.json'),
        ('autopsy-md', 'AUTOPSY MD', output_dir / 'autopsy.md'),
        ('bundle', 'EXPORT BUNDLE', output_dir / 'sealed-bundle.zip'),
    )
    return [
        {'kind': kind, 'label': label, 'href': f'/api/exports/{kind}'}
        for kind, label, path in files
        if path.exists()
    ]


def ensure_exports(run: CrawlRun) -> None:
    if run.exports_ready:
        return
    datasets, stats = collect_run_artifacts(run.output_dir, run.checkpoint_path)
    payload = {name: values for name, values in datasets.items() if values}
    if stats:
        payload['stats'] = stats
    if not payload:
        return
    exporter(str(run.output_dir), 'json', payload)
    exporter(str(run.output_dir), 'csv', payload)
    anatomy = build_site_anatomy(run.payload.get('target_url', ''), datasets, {}, run.payload.get('specimen', {}))
    probes = build_mutation_probes(run.payload.get('target_url', ''), datasets)
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
    )
    autopsy_json_path = run.output_dir / 'autopsy.json'
    autopsy_md_path = run.output_dir / 'autopsy.md'
    autopsy_json_path.write_text(json.dumps(autopsy, indent=2, ensure_ascii=False), encoding='utf-8')
    autopsy_md_path.write_text(render_autopsy_markdown(autopsy), encoding='utf-8')
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
                baseline = self._latest_baseline(payload.get('target_url', ''), exclude_dir=output_dir)
                if baseline is not None:
                    payload['temporal_baseline'] = str(baseline.resolve())
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

    def _latest_baseline(self, target_url: str, exclude_dir: Path | None = None) -> Path | None:
        target_slug = slugify_target(target_url)
        candidates = []
        for entry in self.runs_root.iterdir():
            if not entry.is_dir() or target_slug not in entry.name:
                continue
            if exclude_dir is not None and entry == exclude_dir:
                continue
            if self.current_run and entry == self.current_run.output_dir:
                continue
            candidates.append(entry)
        return sorted(candidates)[-1] if candidates else None

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
        if run.status == 'complete':
            ensure_exports(run)
        mapping = {
            'json': run.output_dir / 'results.json',
            'csv': run.output_dir / 'results.csv',
            'autopsy-json': run.output_dir / 'autopsy.json',
            'autopsy-md': run.output_dir / 'autopsy.md',
            'bundle': run.output_dir / 'sealed-bundle.zip',
        }
        path = mapping.get(kind)
        if path is None or not path.exists():
            raise FileNotFoundError(kind)
        return path

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

    @app.post('/api/crawl')
    def start_crawl() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            run = app.config['CRAWL_MANAGER'].start(payload)
        except ValueError as exc:
            return error_response('The target specimen is malformed.', 400, exc)
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

    return app


app = create_app()


if __name__ == '__main__':
    host = os.environ.get('VAMPIRIC_WEB_HOST', '127.0.0.1')
    port = int(os.environ.get('VAMPIRIC_WEB_PORT', '8080'))
    app.run(host=host, port=port, debug=False)
