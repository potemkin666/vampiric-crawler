"""Regex patterns used by Vampiric Crawler."""
import re

# Href / src / action attributes
rhref = re.compile(r'(href|src|action|data-src)\s*=\s*(["\'])(.*?)\2', re.I)

# Script src tags
rscript = re.compile(r'(<script.*?src\s*=\s*)(["\'])(.*?)\2', re.I)

# API / token entropy strings (base64-ish, hex strings ≥20 chars)
rentropy = re.compile(r'["\']([a-zA-Z0-9+/=_\-]{20,})["\']')

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
    ('GCP_BUCKET',
     re.compile(r'storage\.googleapis\.com/[a-zA-Z0-9_\-\.]+', re.I)),
    ('CREDIT_CARD',
     re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b')),
    ('SOCIAL_SECURITY',
     re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
    ('BITCOIN',
     re.compile(r'\b[13][a-zA-HJ-NP-Z0-9]{25,34}\b')),
    ('GITHUB',
     re.compile(r'github\.com/[a-zA-Z0-9_\-]+', re.I)),
    ('TWITTER',
     re.compile(r'twitter\.com/[a-zA-Z0-9_]{1,15}(?:[^a-zA-Z0-9_/]|$)', re.I)),
    ('LINKEDIN',
     re.compile(r'linkedin\.com/in/[a-zA-Z0-9_\-]+', re.I)),
]
