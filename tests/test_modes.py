from common import *


class ModeTests(RegressionTestCase):
    def test_mode_helpers_extract_specialized_records(self):
        metadata, leaks = extract_document_records(
            'https://example.com/report.pdf',
            b'%PDF-1.4 /Author (Dracula) /Title (Night Ledger) analyst@example.com C:\\Users\\Vlad\\report.docx',
            'application/pdf',
        )
        self.assertTrue(any('author=Dracula' in item for item in metadata))
        self.assertTrue(any('analyst@example.com' in item for item in leaks))
        self.assertTrue(any('C:\\Users\\Vlad\\report.docx' in item for item in leaks))

        js_records = extract_js_intel(
            'https://example.com/app.js',
            'const betaCheckoutFlag=true; const runtimeConfig={"base":"/api"}; const token="sk_live_1234"; '
            'const view="AdminView"; const gtm="GTM-ABCD12"; const env=process.env.NEXT_PUBLIC_API_URL; '
            'console.error("old stack"); // ancient route retired',
        )
        self.assertTrue(any('feature=betaCheckoutFlag' in item for item in js_records))
        self.assertTrue(any('config=runtimeConfig' in item for item in js_records))
        self.assertTrue(any('view=AdminView' in item for item in js_records))
        self.assertTrue(any('analytics_id=' in item for item in js_records))
        self.assertTrue(any('env_hint=' in item for item in js_records))
        self.assertTrue(any('comment=' in item for item in js_records))

        thread_records = extract_thread_records(
            'https://example.com/thread',
            '<html><title>Night Thread</title><article class="post"><span class="author">CountZero</span>'
            '<blockquote>First omen rises.</blockquote>Reply from the dark.</article></html>',
        )
        self.assertTrue(any('thread=Night Thread' in item for item in thread_records))

        location_records = extract_location_records(
            'https://example.com/geo',
            '<html><head><meta name="geo.position" content="40.7128;-74.0060"></head>'
            '<body>Gathering in New York 40.7128, -74.0060</body></html>',
        )
        self.assertTrue(any('confidence=exact' in item and 'lat=40.7128' in item for item in location_records))
        self.assertTrue(any('confidence=high' in item and 'label=geo.position' in item for item in location_records))
        self.assertTrue(any('confidence=weak' in item and 'label=New York' in item for item in location_records))

        story_records = extract_story_records(
            'https://example.com/news',
            '<html lang="en"><head><title>Vampire bats swarm the wires</title>'
            '<meta property="og:site_name" content="Night Wire">'
            '<meta property="article:published_time" content="2026-05-03T00:15:00Z"></head>'
            '<body>"Witnesses saw sparks in the abbey."<a href="https://mirror.example.net/story">mirror</a></body></html>',
        )
        self.assertTrue(any('story=vampire-bats-swarm-the-wires' in item and 'relation=page' in item for item in story_records))
        self.assertTrue(any('relation=mirror' in item and 'reference=https://mirror.example.net/story' in item for item in story_records))
        self.assertTrue(any('relation=metadata' in item and 'published=2026-05-03T00:15:00Z' in item for item in story_records))

        scam_records = extract_scam_signals(
            'https://example.com/offer',
            '<html><body>Limited time! Only 2 left. Offer ends in 03:00. Crypto only.</body></html>',
        )
        self.assertTrue(any('signal=FAKE_URGENCY' in item for item in scam_records))
        self.assertTrue(any('signal=PRESSURE_PAYMENT' in item for item in scam_records))

        hidden_candidates = build_hidden_candidates(
            'https://example.com',
            {'https://example.com/app'},
            {'https://example.com/static/app.js'},
            {'/api/crypt'},
        )
        self.assertIn('https://example.com/admin', hidden_candidates)
        hidden_records = build_hidden_candidate_records(
            'https://example.com',
            {'https://example.com/app'},
            {'https://example.com/static/app.js'},
            {'/api/crypt'},
            extra_words=('vault',),
        )
        self.assertTrue(any(item['probe'] == 'https://example.com/vault' and item['strategy'] == 'wordlist' for item in hidden_records))
        self.assertTrue(any(item['probe'] == 'https://example.com/app' and item['strategy'] == 'learned' for item in hidden_records))

        diffs = build_temporal_diffs(
            {
                'internal': ['https://example.com/old'],
                'stats': {'visited': 1},
                'artifact_genealogy': {
                    'https://example.com/report.pdf': {'sha256': 'oldhash', 'content_type': 'application/pdf'},
                },
            },
            {
                'internal': ['https://example.com/new'],
                'stats': {'visited': 2},
                'artifact_genealogy': {
                    'https://example.com/report.pdf': {'sha256': 'newhash', 'content_type': 'application/pdf'},
                },
            },
        )
        self.assertTrue(any('change=added value=https://example.com/new' in item for item in diffs))
        self.assertTrue(any('metric=visited before=1 after=2' in item for item in diffs))
        self.assertTrue(any('dataset=artifact_genealogy item=https://example.com/report.pdf field=sha256 before=oldhash after=newhash' in item for item in diffs))


if __name__ == '__main__':
    unittest.main()
