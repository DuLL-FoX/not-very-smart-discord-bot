from __future__ import annotations

import os

DEFAULT_DTEK_CHANNEL_ID = int(os.getenv("DTEK_CHANNEL_ID", "1445023003447656678"))

DTEK_REGIONS = {
    "krem": {
        "name": "ДТЕК Київські регіональні електромережі",
        "base_url": "https://www.dtek-krem.com.ua",
        "short_name": "ДТЕК КРЕМ",
        "has_city": True,
    },
    "kem": {
        "name": "ДТЕК Київські електромережі",
        "base_url": "https://www.dtek-kem.com.ua",
        "short_name": "ДТЕК КЕМ",
        "has_city": False,
    },
}

SHUTDOWNS_PATH = "/ua/shutdowns"
AJAX_PATH = "/ua/ajax"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) "
    "Gecko/20100101 Firefox/144.0"
)

STATUS_LABELS = {
    "yes": "Світло є",
    "no": "Світла немає",
    "first": "Немає перші 30 хв.",
    "second": "Немає другі 30 хв.",
    "maybe": "Можливе відключення",
    "mfirst": "Можливе перші 30 хв.",
    "msecond": "Можливе другі 30 хв.",
}

STATUS_MARKERS = {
    "yes": "[+]",
    "no": "[-]",
    "maybe": "[~]",
    "first": "[-]",
    "second": "[-]",
    "mfirst": "[~]",
    "msecond": "[~]",
    "unknown": "[?]",
    "error": "[!]",
}

STATUS_CHARS = {
    "yes": "+",
    "no": "-",
    "maybe": "~",
}
