"""Thread-pool executor for Vampiric Crawler (inspired by Photon's flash)."""
from concurrent.futures import ThreadPoolExecutor, as_completed


def flash(func, urls, thread_count):
    """Call *func* concurrently for each item in *urls*."""
    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = {executor.submit(func, url): url for url in urls}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass
