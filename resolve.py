import sys, json, re, time, os, subprocess
from urllib.parse import urlparse, urlencode, urlunparse

def get_api_data(match_id='30724', lang='ar'):
    import urllib.request
    url = f'https://ws.kora-api.top/api/matche/{match_id}/{lang}?t={int(time.time())}'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'API failed: {e}', file=sys.stderr)
        return None

def try_edge_hls(edge_domain, edge, ch, p=12):
    import urllib.request
    url = f'https://{edge}.{edge_domain}/frame.php?ch={ch}&p={p}'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://strm01.vip/',
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode('utf-8', errors='replace')
            m3u8s = re.findall(r'https?://[^"\']+\.m3u8[^"\']*', html)
            if m3u8s:
                return m3u8s[0]
            js_vars = re.findall(r'(?:source|src|url|file)\s*[=:]\s*["\']([^"\']+)["\']', html, re.I)
            for v in js_vars:
                if '.m3u8' in v:
                    return v
    except:
        pass
    return None

def main():
    source_url = sys.argv[1] if len(sys.argv) > 1 else 'https://strm01.vip/?m=30724&lang=ar'
    
    parsed = urlparse(source_url)
    from urllib.parse import parse_qs
    params = parse_qs(parsed.query)
    match_id = params.get('m', ['30724'])[0]
    lang = params.get('lang', ['ar'])[0]
    
    print(f'Resolving match {match_id}...', file=sys.stderr)
    data = get_api_data(match_id, lang)
    
    if data and data.get('channels'):
        channels = data['channels']
        edge_domain = data.get('edge_domain', 'kora-plus.app')
        print(f'Found {len(channels)} channels, edge domain: {edge_domain}', file=sys.stderr)
        
        for ch in channels:
            ch_name = ch.get('ch', '')
            ch_key = ch.get('key', '')
            ch_link = ch.get('link', '')
            ch_type = ch.get('type', '')
            ch_edge = ch.get('edge', '0')
            
            print(f'Trying: {ch.get("server_name", ch_name)} (type={ch_type})', file=sys.stderr)
            
            # Try direct link first
            if ch_link and ('m3u8' in ch_link or '.mp4' in ch_link):
                print(ch_link)
                return
            
            # Try edge URLs
            edges = data.get('edges', [])
            if edges:
                for edge in edges[:3]:
                    hls = try_edge_hls(edge_domain, edge, ch_name)
                    if hls:
                        print(hls)
                        return
    
    # Fallback: try yt-dlp
    print(f'Trying yt-dlp...', file=sys.stderr)
    result = subprocess.run(
        ['yt-dlp', '-g', '--socket-timeout', '15', source_url],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        if lines:
            print(lines[-1])
            return
    
    # Last resort: return the source URL itself
    print(f'Warning: could not resolve stream, using source URL directly', file=sys.stderr)
    print(source_url)

if __name__ == '__main__':
    main()
