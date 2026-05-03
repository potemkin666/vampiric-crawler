"""Export crawl results to JSON or CSV formats."""
import csv
import json
import os


def exporter(output_dir, fmt, datasets):
    """Write *datasets* to a file inside *output_dir* in *fmt* format."""
    if fmt == 'json':
        fpath = os.path.join(output_dir, 'results.json')
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(datasets, f, indent=2, ensure_ascii=False)
        print(f'  Exported JSON → {fpath}')

    elif fmt == 'csv':
        fpath = os.path.join(output_dir, 'results.csv')
        with open(fpath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['category', 'value'])
            for category, items in datasets.items():
                if isinstance(items, dict):
                    for key, value in sorted(items.items()):
                        writer.writerow([category, f'{key}={value}'])
                else:
                    for item in items:
                        writer.writerow([category, item])
        print(f'  Exported CSV  → {fpath}')
