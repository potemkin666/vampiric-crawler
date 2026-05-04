"""Global configuration for Vampiric Crawler."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

verbose = False

# Intel domains — external links that count as intel
INTELS = (
    'facebook.com', 'twitter.com', 'github.com', 'linkedin.com',
    'instagram.com', 'youtube.com', 'reddit.com', 'pastebin.com',
    'pinterest.com', 'tumblr.com', 'flickr.com', 'vimeo.com',
    'soundcloud.com', 'medium.com', 'quora.com', 'discord.gg',
    'telegram.me', 't.me', 'twitch.tv', 'tiktok.com',
    's3.amazonaws.com', 'storage.googleapis.com', 'blob.core.windows.net',
)


@dataclass(frozen=True)
class RuntimeConfig:
    """Typed runtime configuration shared across CLI and Web UI flows."""
    depth: int = 2
    threads: int = 4
    delay: float = 0.0
    timeout: float = 8.0
    scope: str = 'host'
    extract_intel: bool = True
    extract_secrets: bool = False
    only_urls: bool = False
    archive_seeds: bool = False
    render_js: bool = False
    respect_robots_delay: bool = False
    enumerate_subdomains: bool = False
    dry_run: bool = False
    preset: str = 'balanced'
    input_kind: str = 'auto'
    ritual_chain: str = ''
    mode: str = 'generic'
    temporal_baseline: str = ''
    scope_allow: tuple[str, ...] = ()
    scope_deny: tuple[str, ...] = ()
    checkpoint: str = ''
    resume: str = ''
    host: str = ''
    domain: str = ''
    verbose: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None = None) -> 'RuntimeConfig':
        raw = raw or {}
        extract_intel = bool(raw.get('extract_intel', not bool(raw.get('only_urls', False))))
        only_urls = bool(raw.get('only_urls', not extract_intel))
        return cls(
            depth=max(1, int(raw.get('depth', 2) or 2)),
            threads=max(1, int(raw.get('threads', 4) or 4)),
            delay=max(0.0, float(raw.get('delay', 0) or 0)),
            timeout=max(1.0, float(raw.get('timeout', 8) or 8)),
            scope='domain' if str(raw.get('scope', 'host') or 'host') == 'domain' else 'host',
            extract_intel=extract_intel,
            extract_secrets=bool(raw.get('extract_secrets', False)),
            only_urls=only_urls,
            archive_seeds=bool(raw.get('archive_seeds', False)),
            render_js=bool(raw.get('render_js', False)),
            respect_robots_delay=bool(raw.get('respect_robots_delay', False)),
            enumerate_subdomains=bool(raw.get('enumerate_subdomains', raw.get('dns', False))),
            dry_run=bool(raw.get('dry_run', False)),
            preset=str(raw.get('preset', 'balanced') or 'balanced'),
            input_kind=str(raw.get('input_kind', 'auto') or 'auto'),
            ritual_chain=str(raw.get('ritual_chain') or ''),
            mode=str(raw.get('mode', 'generic') or 'generic'),
            temporal_baseline=str(raw.get('temporal_baseline') or ''),
            scope_allow=tuple(str(item) for item in (raw.get('scope_allow') or ())),
            scope_deny=tuple(str(item) for item in (raw.get('scope_deny') or ())),
            checkpoint=str(raw.get('checkpoint') or ''),
            resume=str(raw.get('resume') or ''),
            host=str(raw.get('host') or ''),
            domain=str(raw.get('domain') or ''),
            verbose=bool(raw.get('verbose', False)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            'depth': self.depth,
            'threads': self.threads,
            'delay': self.delay,
            'timeout': self.timeout,
            'scope': self.scope,
            'extract_intel': self.extract_intel,
            'extract_secrets': self.extract_secrets,
            'only_urls': self.only_urls,
            'archive_seeds': self.archive_seeds,
            'render_js': self.render_js,
            'respect_robots_delay': self.respect_robots_delay,
            'enumerate_subdomains': self.enumerate_subdomains,
            'dry_run': self.dry_run,
            'preset': self.preset,
            'input_kind': self.input_kind,
            'ritual_chain': self.ritual_chain,
            'mode': self.mode,
            'temporal_baseline': self.temporal_baseline,
            'scope_allow': list(self.scope_allow),
            'scope_deny': list(self.scope_deny),
            'checkpoint': self.checkpoint,
            'resume': self.resume,
            'host': self.host,
            'domain': self.domain,
            'verbose': self.verbose,
        }

    def flags(self) -> dict[str, Any]:
        return {
            'scope': self.scope,
            'depth': self.depth,
            'threads': self.threads,
            'delay': self.delay,
            'timeout': self.timeout,
            'extract_intel': self.extract_intel,
            'extract_secrets': self.extract_secrets,
            'only_urls': self.only_urls,
            'archive_seeds': self.archive_seeds,
            'render_js': self.render_js,
            'respect_robots_delay': self.respect_robots_delay,
            'enumerate_subdomains': self.enumerate_subdomains,
            'dry_run': self.dry_run,
        }
