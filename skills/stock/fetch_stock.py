#!/usr/bin/env python3
"""
Stock data fetcher — uses stooq.com (reliable, no auth, global).
All markets: HK, US, A-share (CN).

Symbol formats for stooq:
  HK:  9988.hk   (no leading zeros needed)
  US:  baba.us   (lowercase ticker)
  CN:  600519.cn or 000001.cn

Usage:
  python3 fetch_stock.py hk 9988
  python3 fetch_stock.py cn 600519
  python3 fetch_stock.py us BABA
"""
import sys, json, os, time
import requests
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def get_stooq_symbol(market, symbol):
    market = market.lower()
    symbol = symbol.lower()
    if market == 'hk':
        return f'{symbol}.hk'
    elif market == 'cn':
        return f'{symbol}.cn'
    elif market == 'us':
        return f'{symbol}.us'
    raise ValueError(f'Unknown market: {market}')


def fetch_stooq(market, symbol, days=90):
    stooq_sym = get_stooq_symbol(market, symbol)
    end = datetime.today().strftime('%Y%m%d')
    start = (datetime.today() - timedelta(days=days)).strftime('%Y%m%d')
    url = f'https://stooq.com/q/d/l/?s={stooq_sym}&d1={start}&d2={end}&i=d'

    s = requests.Session()
    s.trust_env = False  # ignore system proxy env vars
    s.headers['User-Agent'] = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )

    last_err = None
    for attempt in range(4):
        try:
            r = s.get(url, timeout=12)
            r.raise_for_status()
            lines = r.text.strip().split('\n')
            if len(lines) < 2 or 'No data' in r.text or lines[0].strip() == '':
                raise ValueError(f'No data returned for {stooq_sym}. Check symbol.')
            # Parse CSV: Date,Open,High,Low,Close,Volume
            rows = []
            for line in lines[1:]:  # skip header
                parts = line.strip().split(',')
                if len(parts) < 5:
                    continue
                try:
                    rows.append({
                        'date': parts[0],
                        'open': float(parts[1]),
                        'high': float(parts[2]),
                        'low': float(parts[3]),
                        'close': float(parts[4]),
                        'vol': float(parts[5]) if len(parts) > 5 and parts[5] else 0.0,
                    })
                except ValueError:
                    continue
            # Compute pct and chg
            for i, row in enumerate(rows):
                if i == 0:
                    row['pct'] = 0.0
                    row['chg'] = 0.0
                else:
                    prev = rows[i-1]['close']
                    row['pct'] = round((row['close'] - prev) / prev * 100, 4) if prev else 0.0
                    row['chg'] = round(row['close'] - prev, 4)
            return rows
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))

    raise last_err


def main():
    if len(sys.argv) < 3:
        print(json.dumps({'error': 'Usage: fetch_stock.py <hk|cn|us> <SYMBOL>'}))
        sys.exit(1)

    market = sys.argv[1].lower()
    symbol = sys.argv[2]

    try:
        rows = fetch_stooq(market, symbol)
        print(json.dumps(rows[-21:], ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
