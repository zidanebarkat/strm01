import sys, json, re, urllib.request, asyncio
from urllib.parse import urlparse, parse_qs

API_URL = 'https://ws.kora-api.top/api/matche/{mid}/{lang}?t={t}'

def get_api_data(match_id, lang='ar'):
    url = API_URL.format(mid=match_id, lang=lang, t=int(__import__('time').time()))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except:
        return None

def find_hls_in_html(html):
    urls = set()
    for m in re.finditer(r'https?://[^"\' <>]+\.m3u8[^"\' <>]*', html):
        urls.add(m.group(0))
    for m in re.finditer(r'"(https?://[^"]+)"', html):
        u = m.group(1)
        if '.m3u8' in u:
            urls.add(u)
    return urls

async def playwright_extract(source_url):
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            hls_urls = set()
            page.on('request', lambda r: hls_urls.add(r.url) if '.m3u8' in r.url.lower() else None)
            try:
                await page.goto(source_url, wait_until='domcontentloaded', timeout=25000)
                await page.wait_for_timeout(12000)
                html = await page.content()
                hls_urls |= find_hls_in_html(html)
            except:
                pass
            await browser.close()
            for u in sorted(hls_urls):
                if '.m3u8' in u.lower():
                    return u
            return hls_urls and list(hls_urls)[0] or None
    except:
        return None

def main():
    source_url = sys.argv[1] if len(sys.argv) > 1 else 'https://strm01.vip/?m=30724&lang=ar'
    params = parse_qs(urlparse(source_url).query)
    match_id = params.get('m', ['30724'])[0]
    lang = params.get('lang', ['ar'])[0]
    
    # Try API first
    data = get_api_data(match_id, lang)
    if data and data.get('channels'):
        for ch in data['channels']:
            link = ch.get('link', '') or ''
            if '.m3u8' in link:
                print(link); return
        # Try edge URLs with API
        edges = data.get('edges', [])
        edge_domain = data.get('edge_domain', 'kora-plus.app')
        for edge in edges[:3]:
            for ch in data['channels']:
                ch_name = ch.get('ch', '')
                url = f'https://{edge}.{edge_domain}/frame.php?ch={ch_name}'
                try:
                    req = urllib.request.Request(url, headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Referer': source_url,
                    })
                    with urllib.request.urlopen(req, timeout=8) as r:
                        html = r.read().decode('utf-8', errors='replace')
                        found = find_hls_in_html(html)
                        for u in found:
                            if '.m3u8' in u:
                                print(u); return
                except:
                    pass
    
    # Try Playwright
    hls = asyncio.run(playwright_extract(source_url))
    if hls:
        print(hls); return
    
    # Fallback: return source URL
    print(source_url)

if __name__ == '__main__':
    main()
