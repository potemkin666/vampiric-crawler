"""Checkpoint persistence for long crawler runs."""
import json
import os
import tempfile
import time


CHECKPOINT_VERSION = 1


DATASET_NAMES = (
    'files', 'forms', 'intel', 'robots', 'custom', 'failed', 'skipped',
    'redirects', 'internal', 'scripts', 'external', 'fuzzable',
    'endpoints', 'keys', 'processed', 'bad_scripts', 'bad_intel',
)


def save_checkpoint(path, payload):
    """Atomically write *payload* as a JSON checkpoint to *path*."""
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(directory, exist_ok=True)
    document = {
        'version': CHECKPOINT_VERSION,
        'saved_at': time.time(),
    }
    document.update(payload)
    handle, temp_path = tempfile.mkstemp(prefix='.vampire-checkpoint-', suffix='.json', dir=directory)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, indent=2, sort_keys=True, ensure_ascii=False)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def load_checkpoint(path):
    """Load and return a checkpoint dict from *path*."""
    with open(path, 'r', encoding='utf-8') as stream:
        payload = json.load(stream)
    version = payload.get('version')
    if version != CHECKPOINT_VERSION:
        raise ValueError('Unsupported checkpoint version: {}'.format(version))
    return payload


def normalize_checkpoint_sets(payload):
    """Return restored set-based crawler state from a checkpoint payload."""
    restored = {}
    for name in DATASET_NAMES:
        values = payload.get(name, [])
        if name == 'bad_intel':
            normalized = set()
            for item in values:
                if not isinstance(item, (list, tuple)) or len(item) != 3:
                    continue
                match, intel_name, url = item
                if isinstance(match, list):
                    match = tuple(match)
                normalized.add((match, intel_name, url))
            restored[name] = normalized
        else:
            restored[name] = set(values or [])
    return restored
