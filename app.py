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
            <h2>Xtream-to-M3U8 Proxy Server</h2>
            <p>আপনার সার্ভারটি সফলভাবে চালু হয়েছে।</p>
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
    # সরাসরি এক্সট্রিম সার্ভার থেকে m3u8 আউটপুটের প্লেলিস্ট সংগ্রহ করা হচ্ছে
    url = f"{XTREAM_HOST}/get.php?username={USERNAME}&password={PASSWORD}&output=m3u8"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 200:
            # প্লেলিস্টের ডাটা সরাসরি প্লেয়ারে রিটার্ন করা হচ্ছে
            return Response(response.text, mimetype='text/plain')
        else:
            return f"Failed to fetch playlist from Xtream server. Status: {response.status_code}", 500
    except Exception as e:
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
