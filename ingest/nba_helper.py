"""
NBA API Helper — Custom headers and retry logic.

stats.nba.com blocks requests from cloud servers (AWS/GitHub Actions).
This module configures nba_api with browser-like headers and retry logic.
"""

import time
import random

# Custom headers that mimic a real browser — critical for cloud environments
CUSTOM_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Origin': 'https://www.nba.com',
    'Referer': 'https://www.nba.com/',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}


def call_nba_api(endpoint_class, max_retries=3, **kwargs):
    """
    Call an nba_api endpoint with retry logic and custom headers.

    Args:
        endpoint_class: The nba_api endpoint class (e.g., ScoreboardV2)
        max_retries: Number of retries on failure
        **kwargs: Arguments to pass to the endpoint

    Returns:
        The endpoint instance (call .get_data_frames() on it)
    """
    kwargs.setdefault('timeout', 60)  # longer timeout for cloud
    kwargs['headers'] = CUSTOM_HEADERS

    for attempt in range(1, max_retries + 1):
        try:
            # Random delay to avoid rate limiting
            delay = random.uniform(0.8, 2.0) * attempt
            time.sleep(delay)

            result = endpoint_class(**kwargs)
            return result

        except Exception as e:
            print(f"    ⚠️  nba_api attempt {attempt}/{max_retries} failed: {e}")
            if attempt == max_retries:
                raise
            # Exponential backoff
            backoff = 3 * attempt + random.uniform(0, 2)
            print(f"    ⏳ Retrying in {backoff:.0f}s...")
            time.sleep(backoff)
