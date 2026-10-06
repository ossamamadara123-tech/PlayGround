import urllib.request, json
url = 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=30&page=1&sparkline=true&price_change_percentage=1h,24h,7d'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req, timeout=25) as r:
    data = json.loads(r.read().decode())
print(f'Got {len(data)} coins from CoinGecko')
for c in data[:5]:
    print(f'  {c["id"]}: {c["name"]} ({c["symbol"]}) = ${c["current_price"]}')