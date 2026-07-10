import os
import re
import time
import urllib.parse
import requests
from flask import Flask, Response, request, redirect
from concurrent.futures import ThreadPoolExecutor

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

PLAYLIST_CACHE = None
CACHE_TIMESTAMP = 0
CACHE_DURATION = 1800  # ৩০ মিনিট ক্যাশ থাকবে

def clean_redirect_url(url):
    """সাধারণ ক্লিনিং (ব্যাকআপের জন্য)"""
    if not url:
        return ""
    cleaned = re.sub(r'^(auto|ffrt|ffmpeg|rtmp|mp4)\s+', '', url, flags=re.IGNORECASE).strip()
    cleaned = cleaned.replace('\\', '/')
    cleaned = re.sub(r'^(https?:)/+', r'\1//', cleaned)
    return cleaned

def get_session():
    handshake_url = f"{PORTAL_URL}?type=stb&action=handshake&js=&token=&mac={MAC_ADDRESS}"
    try:
        response = requests.get(handshake_url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            token = data.get('js', {}).get('token', '')
            
            # সেট-কুকি থেকে শুধুমাত্র সেশন আইডি (PHPSESSID=xxxx) অংশটি ফিল্টার করা
            set_cookie = response.headers.get('Set-Cookie', '')
            cookie_val = ""
            if set_cookie:
                match = re.search(r'([a-zA-Z0-9_-]+=[a-zA-Z0-9_-]+)', set_cookie)
                if match:
                    cookie_val = match.group(1)
            
            return token, cookie_val
    except Exception:
        pass
    return None, None

def get_playable_link(token, cookie, cmd_url):
    # safe='' দিয়ে সব স্ল্যাশ ও ক্যারেক্টারকে প্রপারলি এনকোড করা হচ্ছে
    encoded_cmd = urllib.parse.quote(cmd_url, safe='')
    # টোকেন ইউআরএল প্যারামিটার হিসেবেও পাঠানো হচ্ছে
    url = f"{PORTAL_URL}?type=itv&action=create_link&cmd={encoded_cmd}&token={token}&series=&forced_tmp_link=1"
    
    session_headers = headers.copy()
    session_headers['Authorization'] = f'Bearer {token}'
    if cookie:
        session_headers['Cookie'] = f"mac={MAC_ADDRESS}; {cookie}"
        
    try:
        response = requests.get(url, headers=session_headers, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            js_val = res_data.get('js', '')
            if isinstance(js_val, dict):
                return js_val.get('cmd', '') or js_val.get('url', '') or ''
            return str(js_val)
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
        response = requests.get(url, headers=session_headers, timeout=10)
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
            response = requests.get(url, headers=session_headers, timeout=10)
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

def fetch_genre_m3u(genre, token, cookie, host_url):
    genre_id = genre.get('id')
    genre_title = genre.get('title') or genre.get('name') or "General"
    
    if not genre_id or genre_title.strip().lower() in ['all', 'all channels', 'all tv']:
        return ""

    channels = get_channels_by_genre(token, cookie, genre_id)
    m3u_part = ""
    for ch in channels:
        name = ch.get('name', 'Unknown')
        cmd = ch.get('cmd', '')
        logo = ch.get('logo', '')
        
        if cmd:
            encoded_cmd = urllib.parse.quote(cmd, safe='')
            proxy_play_url = f"{host_url}/play?cmd={encoded_cmd}"
            m3u_part += f'#EXTINF:-1 tvg-logo="{logo}" group-title="{genre_title}",{name}\n{proxy_play_url}\n'
    return m3u_part

def extract_channel_id(cmd):
    """কমান্ড ইউআরএল থেকে চ্যানেল আইডি এক্সট্র্যাক্ট করা"""
    match = re.search(r'channelId=(\d+)', cmd)
    if match:
        return match.group(1)
    match2 = re.search(r'/(\d+)(\.ts|\.m3u8|$)', cmd)
    if match2:
        return match2.group(1)
    return None

@app.route('/')
def home():
    host = request.host_url.rstrip('/')
    return f"""
    <html>
        <head><title>IPTV Proxy Server</title></head>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>IPTV MAC-to-M3U8 Proxy Server (Formula-Based)</h2>
            <p>আপনার রিয়েল-টাইম টাইমার সমর্থিত প্রক্সি সার্ভারটি সফলভাবে চালু হয়েছে।</p>
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
    global PLAYLIST_CACHE, CACHE_TIMESTAMP
    current_time = time.time()

    if PLAYLIST_CACHE and (current_time - CACHE_TIMESTAMP < CACHE_DURATION):
        return Response(PLAYLIST_CACHE, mimetype='text/plain')

    token, cookie = get_session()
    if not token:
        return "Authentication with portal failed.", 500

    genres = get_genres(token, cookie)
    if not genres:
        return "Could not fetch genres.", 500

    host_url = request.host_url.rstrip('/')

    m3u_parts = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_genre_m3u, genre, token, cookie, host_url) for genre in genres]
        for future in futures:
            try:
                m3u_parts.append(future.result())
            except Exception:
                pass

    m3u_content = "#EXTM3U\n" + "".join(m3u_parts)

    PLAYLIST_CACHE = m3u_content
    CACHE_TIMESTAMP = current_time

    return Response(m3u_content, mimetype='text/plain')

@app.route('/play')
def play():
    cmd = request.args.get('cmd')
    if not cmd:
        return "Missing cmd parameter.", 400

    channel_id = extract_channel_id(cmd)
    if not channel_id:
        return "Invalid channel ID.", 400

    token, cookie = get_session()
    if not token:
        return "Failed to authenticate session.", 500

    playable_url = get_playable_link(token, cookie, cmd)

    # যদি সেশন লিঙ্ক পাওয়া যায়, তবে সেখান থেকে SN_xxxx টোকেন নিয়ে সরাসরি ফর্মুলা ভিত্তিক .m3u8 লিঙ্ক তৈরি করা হবে
    if playable_url:
        match = re.search(r'(SN_\d+)', playable_url)
        if match:
            sn_token = match.group(1)
            # আপনার সেই শতভাগ সফল .m3u8 ফর্মুলা লিঙ্ক জেনারেশন
            final_m3u8_url = f"http://tv.cloudcdn.me/live/{MAC_ADDRESS}/{sn_token}/{channel_id}.m3u8"
            return redirect(final_m3u8_url, code=302)

    # ব্যর্থ হলে ব্যাকআপ হিসেবে মূল লিঙ্কটি (.ts হিসেবেই) ওপেন হবে
    fallback_url = clean_redirect_url(cmd)
    return redirect(fallback_url, code=302)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
