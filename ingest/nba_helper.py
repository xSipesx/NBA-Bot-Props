"""
NBA API Helper — Custom headers and retry logic.
Only used for local runs and bet grading.
"""

import time
import random

CUSTOM_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}

def call_nba_api(endpoint_class, max_retries=3, **kwargs):
    kwargs.setdefault('timeout', 60)
    kwargs['headers'] = CUSTOM_HEADERS
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(random.uniform(0.8, 2.0) * attempt)
            return endpoint_class(**kwargs)
        except Exception as e:
            print(f"    ⚠️  nba_api attempt {attempt}/{max_retries} failed: {e}", flush=True)
            if attempt == max_retries:
                raise
            time.sleep(3 * attempt + random.uniform(0, 2))
