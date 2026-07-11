import os
import requests
from flask import Flask, Response, request

app = Flask(__name__)

# --- আপনার এক্সট্রিম সার্ভার ডিটেইলস ---
XTREAM_HOST = "http://tickstar1.xyz:8080"
USERNAME = "25711345"
PASSWORD = "late8airline"
# --------------------------------------

@app.route('/')
def home():
    host = request.host_url.rstrip('/')
    return f"""
    <html>
        <head><title>Xtream Proxy Server</title></head>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Xtream API-to-M3U8 Proxy Server (XC-API Based)</h2>
            <p>আপনার এক্সট্রিম এপিআই সমর্থিত প্লেলিস্ট সার্ভারটি সফলভাবে চালু হয়েছে।</p>
            <h3>আপনার প্লেলিস্ট লিঙ্ক (M3U8):</h3>
            <code style="background: #f4f4f4; padding: 10px; display: block; word-break: break-all;">
                {host}/playlist.m3u
            </code>
            <p style="color: gray; margin-top: 20px;">এই লিঙ্কটি কপি করে আপনার আইপিটিভি প্লেয়ারে ব্যবহার করুন।</p>
        </body>
    </html>
    """

@app.route('/playlist.m3u')
def playlist():
    # ১. এক্সট্রিম এপিআই থেকে ক্যাটাগরি তালিকা এবং চ্যানেল তালিকা নিয়ে আসা হচ্ছে
    cat_url = f"{XTREAM_HOST}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_live_categories"
    stream_url = f"{XTREAM_HOST}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_live_streams"
    
    try:
        # ক্যাটাগরি ডিকশনারি তৈরি করা
        cat_response = requests.get(cat_url, timeout=15)
        categories = {}
        if cat_response.status_code == 200:
            for cat in cat_response.json():
                cat_id = str(cat.get('category_id'))
                cat_name = cat.get('category_name')
                categories[cat_id] = cat_name

        # চ্যানেল তালিকা ডাউনলোড করা
        stream_response = requests.get(stream_url, timeout=20)
        if stream_response.status_code != 200:
            return f"Failed to fetch streams from Xtream API. Status: {stream_response.status_code}", 500
            
        streams = stream_response.json()
        
        # রিয়েল-টাইম .m3u8 ভিত্তিক প্লেলিস্ট জেনারেশন
        m3u_content = "#EXTM3U\n"
        for stream in streams:
            name = stream.get('name')
            stream_id = stream.get('stream_id')
            logo = stream.get('stream_icon') or ""
            cat_id = str(stream.get('category_id'))
            category_name = categories.get(cat_id, "General")
            
            if name and stream_id:
                # এক্সট্রিম কোডস-এর আসল সরাসরি .m3u8 লিঙ্ক ফর্মুলা
                play_url = f"{XTREAM_HOST}/live/{USERNAME}/{PASSWORD}/{stream_id}.m3u8"
                m3u_content += f'#EXTINF:-1 tvg-logo="{logo}" group-title="{category_name}",{name}\n{play_url}\n'
        
        return Response(m3u_content, mimetype='text/plain')
        
    except Exception as e:
        return f"Error generating playlist: {str(e)}", 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
