import os
import re
import urllib.parse
import requests
from flask import Flask, Response, request, redirect

app = Flask(__name__)

# --- এখানে আপনার পোর্টাল এবং ম্যাক অ্যাড্রেস দিন ---
PORTAL_URL = 'http://tv.cloudcdn.me/portal.php'
MAC_ADDRESS = '00:1A:79:31:34:0E'
# -----------------------------------------------

USER_AGENT = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 sb.gxt.r3 Safari/533.3'

headers = {
    'User-Agent': USER_AGENT,
    'Cookie': f'mac={MAC_ADDRESS}',
    'Referer': PORTAL_URL.rsplit('/', 1)[0] if '/' in PORTAL_URL else PORTAL_URL,
    'X-User-MAC': MAC_ADDRESS
}

def get_session():
    handshake_url = f"{PORTAL_URL}?type=stb&action=handshake&js=&token=&mac={MAC_ADDRESS}"
    try:
        response = requests.get(handshake_url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            token = data.get('js', {}).get('token', '')
            cookie = response.headers.get('Set-Cookie', '')
            return token, cookie
    except Exception:
        pass
    return None, None

def get_playable_link(token, cookie, cmd_url):
    url = f"{PORTAL_URL}?type=itv&action=create_link&cmd={urllib.parse.quote(cmd_url)}&series=&forced_tmp_link=1"
    session_headers = headers.copy()
    session_headers['Authorization'] = f'Bearer {token}'
    if cookie:
        session_headers['Cookie'] = f"mac={MAC_ADDRESS}; {cookie}"
        
    try:
        response = requests.get(url, headers=session_headers, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            return res_data.get('js', '')
    except Exception:
        pass
    return None

def get_genres(token, cookie):
    url = f"{PORTAL_URL}?type=itv&action=get_genres"
    session_headers = headers.copy()
    session_headers['Authorization'] = f'Bearer {token}'
    if cookie:
        session_headers['Cookie'] = f"mac={MAC_ADDRESS}; {cookie}"
    try:
        response = requests.get(url, headers=session_headers, timeout=15)
        if response.status_code == 200:
            return response.json().get('js', [])
    except Exception:
        pass
    return []

def get_channels_by_genre(token, cookie, genre_id):
    all_channels = []
    page = 1
    while True:
        url = f"{PORTAL_URL}?type=itv&action=get_ordered_list&genre={genre_id}&force_ch_link_check=&fav=0&sortby=number&hd=0&p={page}"
        session_headers = headers.copy()
        session_headers['Authorization'] = f'Bearer {token}'
        if cookie:
            session_headers['Cookie'] = f"mac={MAC_ADDRESS}; {cookie}"
            
        try:
            response = requests.get(url, headers=session_headers, timeout=15)
            if response.status_code != 200:
                break
            js_data = response.json().get('js', {})
            if isinstance(js_data, list):
                if len(js_data) == 0:
                    break
                all_channels.extend(js_data)
                break
            channels_on_page = js_data.get('data', [])
            if not channels_on_page:
                break
            all_channels.extend(channels_on_page)
            total_items = int(js_data.get('total_items') or 0)
            max_rows = int(js_data.get('max_rows') or 14)
            if len(all_channels) >= total_items or len(channels_on_page) < max_rows:
                break
            page += 1
        except Exception:
            break
    return all_channels

@app.route('/')
def home():
    host = request.host_url.rstrip('/')
    return f"""
    <html>
        <head><title>IPTV Proxy Server</title></head>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>IPTV MAC-to-M3U8 Proxy Server</h2>
            <p>আপনার সার্ভারটি সফলভাবে চালু হয়েছে।</p>
            <h3>আপনার প্লেলিস্ট লিঙ্ক (M3U):</h3>
            <code style="background: #f4f4f4; padding: 10px; display: block; word-break: break-all;">
                {host}/playlist.m3u
            </code>
            <p style="color: gray; margin-top: 20px;">এই লিঙ্কটি কপি করে আপনার আইপিটিভি প্লেয়ারে ব্যবহার করুন।</p>
        </body>
    </html>
    """

@app.route('/playlist.m3u')
def playlist():
    token, cookie = get_session()
    if not token:
        return "Authentication with portal failed.", 500

    genres = get_genres(token, cookie)
    if not genres:
        return "Could not fetch genres.", 500

    m3u_content = "#EXTM3U\n"
    host_url = request.host_url.rstrip('/')

    for genre in genres:
        genre_id = genre.get('id')
        genre_title = genre.get('title') or genre.get('name') or "General"
        
        if not genre_id or genre_title.strip().lower() in ['all', 'all channels', 'all tv']:
            continue

        channels = get_channels_by_genre(token, cookie, genre_id)
        for ch in channels:
            name = ch.get('name', 'Unknown')
            cmd = ch.get('cmd', '')
            logo = ch.get('logo', '')
            
            if cmd:
                encoded_cmd = urllib.parse.quote(cmd)
                proxy_play_url = f"{host_url}/play?cmd={encoded_cmd}"
                m3u_content += f'#EXTINF:-1 tvg-logo="{logo}" group-title="{genre_title}",{name}\n{proxy_play_url}\n'

    return Response(m3u_content, mimetype='text/plain')

@app.route('/play')
def play():
    cmd = request.args.get('cmd')
    if not cmd:
        return "Missing cmd parameter.", 400

    token, cookie = get_session()
    if not token:
        return "Failed to authenticate session.", 500

    playable_url = get_playable_link(token, cookie, cmd)

    if playable_url and playable_url.startswith('http'):
        return redirect(playable_url, code=302)
    else:
        fallback_url = cmd.replace('ffrt ', '').replace('ffmpeg ', '').replace('auto ', '').strip().replace('\\', '/')
        return redirect(fallback_url, code=302)

if __name__ == '__main__':
    # Render পোর্ট নির্ধারণ করার জন্য এনভায়রনমেন্ট ভেরিয়েবল রিড করা হচ্ছে
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
