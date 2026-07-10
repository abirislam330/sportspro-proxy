import os
import re
import time
import urllib.parse
import requests
from flask import Flask, Response, request, redirect, jsonify
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# --- এখানে আপনার পোর্টাল এবং ম্যাক অ্যাড্রেস দিন ---
PORTAL_URL = 'http://tv.cloudcdn.me/portal.php'
MAC_ADDRESS = '00:1A:79:31:34:0E'
# -----------------------------------------------

USER_AGENT = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 sb.gxt.r3 Safari/533.3'

headers = {
    'User-Agent': USER_AGENT,
    'Referer': PORTAL_URL.rsplit('/', 1)[0] if '/' in PORTAL_URL else PORTAL_URL,
    'X-User-MAC': MAC_ADDRESS
}

PLAYLIST_CACHE = None
CACHE_TIMESTAMP = 0
CACHE_DURATION = 1800

# সেশন ক্লায়েন্ট তৈরি করা
session_client = requests.Session()
session_client.headers.update(headers)
# সেশন কুকি মেমোরিতে পার্মানেন্টলি ম্যাক সেট করা
session_client.cookies.set('mac', MAC_ADDRESS, domain='tv.cloudcdn.me')

ACTIVE_TOKEN = None
GLOBAL_SN_TOKEN = None  # মেমোরিতে সেভ থাকা সেশন টোকেন (SN_xxxx)

def clean_redirect_url(url):
    if not url:
        return ""
    cleaned = re.sub(r'^(auto|ffrt|ffmpeg|rtmp|mp4)\s+', '', url, flags=re.IGNORECASE).strip()
    cleaned = cleaned.replace('\\', '/')
    cleaned = re.sub(r'^(https?:)/+', r'\1//', cleaned)
    return cleaned

def get_session():
    global ACTIVE_TOKEN
    handshake_url = f"{PORTAL_URL}?type=stb&action=handshake&js=&token=&mac={MAC_ADDRESS}"
    try:
        response = session_client.get(handshake_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            token = data.get('js', {}).get('token', '')
            ACTIVE_TOKEN = token
            session_client.headers.update({'Authorization': f'Bearer {token}'})
            
            # সেশন সম্পূর্ণ সচল করতে প্রোফাইল ভিউ সম্পূর্ণ করা হচ্ছে
            profile_url = f"{PORTAL_URL}?type=stb&action=get_profile"
            session_client.get(profile_url, timeout=10)
            
            return token
    except Exception:
        pass
    return None

def get_playable_link(token, cmd_url):
    # ডাটাবেজ ম্যাচিংয়ের জন্য uid এবং deviceMac কেটে ক্লিন করা হচ্ছে
    clean_cmd = re.sub(r'&uid=\d+', '', cmd_url)
    clean_cmd = re.sub(r'&deviceMac=[a-zA-Z0-9:]+', '', clean_cmd)
    
    encoded_cmd = urllib.parse.quote(clean_cmd, safe='')
    
    # টাইপ ১: স্ট্যান্ডার্ড (itv)
    url_itv = f"{PORTAL_URL}?type=itv&action=create_link&cmd={encoded_cmd}&token={token}&series=&forced_tmp_link=1"
    try:
        response = session_client.get(url_itv, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            js_val = res_data.get('js', '')
            if js_val and "not authorized" not in str(js_val).lower():
                if isinstance(js_val, dict):
                    return js_val.get('cmd', '') or js_val.get('url', '') or ''
                return str(js_val)
    except Exception:
        pass
        
    # টাইপ ২: মিনিস্ট্রা স্ট্যান্ডার্ড (stb)
    url_stb = f"{PORTAL_URL}?type=stb&action=create_link&cmd={encoded_cmd}&token={token}&series=&forced_tmp_link=1"
    try:
        response = session_client.get(url_stb, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            js_val = res_data.get('js', '')
            if js_val and "not authorized" not in str(js_val).lower():
                if isinstance(js_val, dict):
                    return js_val.get('cmd', '') or js_val.get('url', '') or ''
                return str(js_val)
    except Exception:
        pass
        
    return None

def get_genres(token):
    url = f"{PORTAL_URL}?type=itv&action=get_genres"
    try:
        response = session_client.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('js', [])
    except Exception:
        pass
    return []

def get_channels_by_genre(token, genre_id):
    all_channels = []
    page = 1
    while True:
        url = f"{PORTAL_URL}?type=itv&action=get_ordered_list&genre={genre_id}&force_ch_link_check=&fav=0&sortby=number&hd=0&p={page}"
        try:
            response = session_client.get(url, timeout=10)
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

def fetch_genre_m3u(genre, token, host_url):
    genre_id = genre.get('id')
    genre_title = genre.get('title') or genre.get('name') or "General"
    
    if not genre_id or genre_title.strip().lower() in ['all', 'all channels', 'all tv']:
        return ""

    channels = get_channels_by_genre(token, genre_id)
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
            <h2>IPTV MAC-to-M3U8 Proxy Server (Session-Based)</h2>
            <p>আপনার সেশন ও কুকি সমর্থিত প্রক্সি সার্ভারটি সফলভাবে চালু হয়েছে।</p>
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
    global PLAYLIST_CACHE, CACHE_TIMESTAMP, GLOBAL_SN_TOKEN
    current_time = time.time()

    if PLAYLIST_CACHE and (current_time - CACHE_TIMESTAMP < CACHE_DURATION):
        return Response(PLAYLIST_CACHE, mimetype='text/plain')

    token = get_session()
    if not token:
        return "Authentication with portal failed.", 500

    genres = get_genres(token)
    if not genres:
        return "Could not fetch genres.", 500

    host_url = request.host_url.rstrip('/')

    # ক্যাশ তৈরির সময়েই প্রথম ক্যাটাগরির প্রথম চ্যানেলের লিঙ্ক দিয়ে অ্যাক্টিভ SN_xxxx টোকেনটি তুলে নেওয়া হচ্ছে
    print("Pre-fetching active session token...")
    for genre in genres:
        genre_id = genre.get('id')
        if genre_id:
            sample_channels = get_channels_by_genre(token, genre_id)
            if sample_channels and len(sample_channels) > 0:
                sample_cmd = sample_channels[0].get('cmd', '')
                if sample_cmd:
                    playable = get_playable_link(token, sample_cmd)
                    if playable:
                        match = re.search(r'(SN_\d+)', playable)
                        if match:
                            GLOBAL_SN_TOKEN = match.group(1)
                            print(f"Global SN Token Cached: {GLOBAL_SN_TOKEN}")
                            break
            time.sleep(0.3)

    m3u_parts = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_genre_m3u, genre, token, host_url) for genre in genres]
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
    global GLOBAL_SN_TOKEN
    cmd = request.args.get('cmd')
    if not cmd:
        return "Missing cmd parameter.", 400

    channel_id = extract_channel_id(cmd)
    if not channel_id:
        return "Invalid channel ID.", 400

    # যদি মেমোরিতে সেশন টোকেন থাকে, তবে কোনো এপিআই রিকোয়েস্ট ছাড়াই সরাসরি ১ মিলি-সেকেন্ডে রিডাইরেক্ট হবে
    if GLOBAL_SN_TOKEN:
        final_m3u8_url = f"http://tv.cloudcdn.me/live/{MAC_ADDRESS}/{GLOBAL_SN_TOKEN}/{channel_id}.m3u8"
        return redirect(final_m3u8_url, code=302)

    # যদি টোকেন না থাকে, তবে একবার সেশন রিস্টার্ট করে টোকেন সংগ্রহের ট্রাই করবে
    token = get_session()
    if token:
        playable_url = get_playable_link(token, cmd)
        if playable_url:
            match = re.search(r'(SN_\d+)', playable_url)
            if match:
                GLOBAL_SN_TOKEN = match.group(1)
                final_m3u8_url = f"http://tv.cloudcdn.me/live/{MAC_ADDRESS}/{GLOBAL_SN_TOKEN}/{channel_id}.m3u8"
                return redirect(final_m3u8_url, code=302)

    fallback_url = clean_redirect_url(cmd)
    return redirect(fallback_url, code=302)

@app.route('/debug')
def debug():
    cmd = request.args.get('cmd')
    if not cmd:
        return "Please add cmd in URL. Example: /debug?cmd=auto...", 400
        
    token = get_session()
    if not token:
        return jsonify({"error": "Handshake failed", "token": token}), 500
        
    clean_cmd = re.sub(r'&uid=\d+', '', cmd)
    clean_cmd = re.sub(r'&deviceMac=[a-zA-Z0-9:]+', '', clean_cmd)
    encoded_cmd = urllib.parse.quote(clean_cmd, safe='')
    url = f"{PORTAL_URL}?type=itv&action=create_link&cmd={encoded_cmd}&token={token}&series=&forced_tmp_link=1"
    
    try:
        response = session_client.get(url, timeout=10)
        cookies_saved = session_client.cookies.get_dict()
        return jsonify({
            "portal_status_code": response.status_code,
            "portal_response_raw": response.text,
            "extracted_token": token,
            "session_cookies_active": cookies_saved,
            "api_request_url": url
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
