#!/usr/bin/env python3
"""
FRED 탑다운 지표 서버사이드 fetcher
GitHub Actions에서 실행되어 topdown_data.json 생성
"""
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

FRED_API_KEY = os.environ.get('FRED_API_KEY', '')
if not FRED_API_KEY:
    print("ERROR: FRED_API_KEY env not set")
    exit(1)

SERIES_CONFIG = {
    'DGS10': 252,
    'DGS2': 252,
    'PCEPILFE': 36,
    'UNRATE': 13,
    'VIXCLS': 252 * 3,
    'BAA': 252,
    'DTWEXBGS': 252 * 3,
}

def fetch_series(series_id, limit):
    params = urllib.parse.urlencode({
        'series_id': series_id,
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'sort_order': 'desc',
        'limit': limit,
    })
    url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        observations = data.get('observations', [])
        result = []
        for obs in observations:
            v = obs.get('value', '')
            if v in ('.', ''):
                continue
            try:
                result.append({'date': obs['date'], 'value': float(v)})
            except ValueError:
                continue
        return result[::-1]
    except Exception as e:
        print(f"ERROR fetching {series_id}: {e}")
        return []

def main():
    output = {'updated': datetime.now(timezone.utc).isoformat(), 'series': {}}
    for sid, limit in SERIES_CONFIG.items():
        print(f"Fetching {sid}...")
        output['series'][sid] = fetch_series(sid, limit)
        print(f"  Got {len(output['series'][sid])} points")
    with open('topdown_data.json', 'w') as f:
        json.dump(output, f)
    print("Wrote topdown_data.json")

if __name__ == '__main__':
    main()
