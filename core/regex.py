"""Regex patterns used by Vampiric Crawler."""
import re

# Href / src / action attributes
rhref = re.compile(r'(href|src|action|data-src)\s*=\s*(["\'])(.*?)\2', re.I)

# Script src tags
rscript = re.compile(r'(<script.*?src\s*=\s*)(["\'])(.*?)\2', re.I)

# API / token entropy strings (base64-ish, hex strings ≥20 chars)
rentropy = re.compile(r'["\']([a-zA-Z0-9+/=_\-]{20,})["\']')

# High-value secret patterns  (name, compiled pattern)
rsecrets = [
    ('AWS_ACCESS_KEY_ID',
     re.compile(r'\b(A3T[A-Z0-9]|AKIA|AGPA|AIDA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}\b')),
    ('GITHUB_TOKEN',
     re.compile(r'\b(gh[pousr]_[A-Za-z0-9_]{36,255})\b')),
    ('SLACK_TOKEN',
     re.compile(r'\b(xox[baprs]-[A-Za-z0-9-]{10,200})\b')),
    ('STRIPE_LIVE_SECRET',
     re.compile(r'\b(sk_live_[0-9a-zA-Z]{16,})\b')),
    ('GOOGLE_API_KEY',
     re.compile(r'\b(AIza[0-9A-Za-z\-_]{35})\b')),
    ('JSON_WEB_TOKEN',
     re.compile(r'\b(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+)\b')),
    ('PRIVATE_KEY',
     re.compile(r'(-----BEGIN [A-Z ]+PRIVATE KEY-----)')),
]

# JS endpoint paths
rendpoint = re.compile(
    r'(?:"|\')'
    r'((?:[a-zA-Z]{1,10}://|//)[^"\']{1,200}|(?:/|\.\./|\./)[^"\'><,;| *()(%%$^/\\\[\]][^"\'><,;|]*|'
    r'[a-zA-Z0-9_\-/]{1,}/[a-zA-Z0-9_\-/]{1,}\.(?:[a-zA-Z]{1,4}|action)\b'
    r'(?:[?|#][^"|\']{0,})?)(?:"|\')'
)

# Intel patterns  (name, compiled pattern)
rintels = [
    ('EMAIL',
     re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')),
    ('PHONE',
     re.compile(r'\b(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b')),
    ('IP_ADDRESS',
     re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
    ('AWS_BUCKET',
     re.compile(r'[a-z0-9\-\.]{3,63}\.s3(?:[\-a-z0-9]+)?\.amazonaws\.com', re.I)),
    ('AWS_BUCKET_URI',
     re.compile(r's3://[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]', re.I)),
    ('GCP_BUCKET',
     re.compile(r'storage\.googleapis\.com/[a-zA-Z0-9_\-\.]+', re.I)),
    ('AZURE_BLOB',
     re.compile(r'https?://[a-z0-9\-]+\.blob\.core\.windows\.net/[^\s"\']+', re.I)),
    ('CREDIT_CARD',
     re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b')),
    ('SOCIAL_SECURITY',
     re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
    ('BITCOIN',
     re.compile(r'\b[13][a-zA-HJ-NP-Z0-9]{25,34}\b')),
    ('GITHUB',
     re.compile(r'github\.com/[a-zA-Z0-9_\-]+', re.I)),
    ('FACEBOOK',
     re.compile(r'facebook\.com/[a-zA-Z0-9.\-]+', re.I)),
    ('INSTAGRAM',
     re.compile(r'instagram\.com/[a-zA-Z0-9._]+', re.I)),
    ('REDDIT',
     re.compile(r'reddit\.com/(?:u|user)/[a-zA-Z0-9_\-]+', re.I)),
    ('TWITTER',
     re.compile(r'twitter\.com/[a-zA-Z0-9_]{1,15}(?:[^a-zA-Z0-9_/]|$)', re.I)),
    ('DISCORD_INVITE',
     re.compile(r'(?:discord\.gg|discord(?:app)?\.com/invite)/[a-zA-Z0-9]+', re.I)),
    ('TELEGRAM',
     re.compile(r'(?:t\.me|telegram\.me)/[a-zA-Z0-9_]+', re.I)),
    ('PASTEBIN',
     re.compile(r'pastebin\.com/[a-zA-Z0-9]+', re.I)),
    ('LINKEDIN',
     re.compile(r'linkedin\.com/in/[a-zA-Z0-9_\-]+', re.I)),
    ('YOUTUBE',
     re.compile(r'youtube\.com/(?:@|channel/|c/)[a-zA-Z0-9_\-]+', re.I)),
]
