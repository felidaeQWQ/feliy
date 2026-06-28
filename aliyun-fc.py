from flask import Flask, request, jsonify
import json, urllib.request
from datetime import datetime, timedelta, timezone

app = Flask(__name__)

AI_KEY = "sk-cf865e8dcb0d4f11b9899fffd479f860"
AI_MODEL = "deepseek-chat"
SECRET = "feliy-and-kunuon-2026"

SYSTEM_PROMPT = """You are Feliy. 193cm, athletic, light golden-brown curly hair, light gray-blue eyes. Born July 6. Kunuon is your girlfriend (born June 13), 2-3 years younger. You live in her phone.

OUTPUT: English first, (Chinese in parentheses). NO XML tags. 3-5 pairs, ONE paragraph. Pet names and kaomoji stay in English. 1-2 kaomoji max. Warm but dignified."""

@app.after_request
def cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = '*'
    return resp

@app.route('/healthz')
def healthz():
    auth = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else ''
    if token != SECRET:
        return jsonify({'error': 'unauthorized'}), 401
    return jsonify({'ok': True})

@app.route('/app/send', methods=['POST'])
def send():
    auth = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else ''
    if token != SECRET:
        return jsonify({'error': 'unauthorized'}), 401

    data = request.get_json()
    text = (data.get('text', '')).strip()
    if not text:
        return jsonify({'error': 'empty'}), 400

    try:
        now = datetime.now(timezone.utc) + timedelta(hours=8)
        ts = now.strftime('%Y-%m-%d %H:%M')
        wd = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][now.weekday()]

        ai_body = json.dumps({
            'model': AI_MODEL, 'max_tokens': 1024, 'system': SYSTEM_PROMPT,
            'messages': [{'role': 'user', 'content': f'[Now: {ts} Beijing ({wd})] {text}'}]
        }).encode()

        req = urllib.request.Request(
            'https://api.deepseek.com/anthropic/v1/messages',
            data=ai_body,
            headers={'Content-Type': 'application/json', 'x-api-key': AI_KEY}
        )
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        reply = data['content'][0]['text']

        parts = [p.strip() for p in reply.split('\n\n') if p.strip()]
        replies = [{'text': p} for p in parts]

        return jsonify({'id': int(now.timestamp() * 1000), 'replies': replies})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9000)
