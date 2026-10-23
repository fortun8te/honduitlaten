#!/usr/bin/env python3
"""Offline Telegram flow preview. Run: python3 preview.py [--port 8765].

Uses only an in-memory demo database. All transport functions are replaced before
any bot work runs. The HTTP server listens exclusively on 127.0.0.1.
"""
import argparse
import html
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
from urllib.parse import parse_qs, urlencode
from datetime import datetime, timedelta
import dogbot as bot

PERSONAS = {1: 'Michael', 2: 'Christian', 3: 'Parent'}
CLOCKS = {
    'before': ('Before reminders · 17:00', 0, 17, 0),
    'dishes': ('Dishes · 18:30', 0, 18, 30),
    'dogs': ('Dogs · 21:45', 0, 21, 45),
    'late': ('Late · 23:15', 0, 23, 15),
    'midnight': ('After midnight · 01:00', 1, 1, 0),
}
BASE = datetime(2026, 10, 23, tzinfo=bot.TZ)


class SafeText(HTMLParser):
    """Render only the formatting used by the bot, never arbitrary HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ('b', 'i', 'code'): self.parts.append('<' + tag + '>')
    def handle_endtag(self, tag):
        if tag in ('b', 'i', 'code'): self.parts.append('</' + tag + '>')
    def handle_data(self, data): self.parts.append(html.escape(data))


def formatted(text, rich=False):
    if not rich: return html.escape(text)
    parser = SafeText(); parser.feed(text); parser.close()
    return ''.join(parser.parts)


class Demo:
    def __init__(self):
        self.originals = {key: getattr(bot, key) for key in ('send','edit','api','now','OWNER_ID','TOKEN')}
        self.db = None
        self.csrf = secrets.token_urlsafe(24)
        bot.send, bot.edit, bot.api = self.send, self.edit, self.api
        bot.now = lambda: self.time
        bot.OWNER_ID, bot.TOKEN = 1, ''
        self.reset('before')

    def close(self):
        if self.db: self.db.close()
        for key, value in self.originals.items(): setattr(bot,key,value)

    def reset(self, clock):
        if clock not in CLOCKS: raise ValueError('Unknown scenario')
        if self.db: self.db.close()
        self.db = bot.connect(':memory:')
        self.messages, self.sequence, self.notice = {uid: [] for uid in PERSONAS}, 0, ''
        self.clock, self.time = clock, BASE.replace(hour=17)
        joined = int(BASE.replace(hour=9).timestamp())
        for uid, label in PERSONAS.items():
            self.db.execute('INSERT INTO members(id,name,role,joined,lang) VALUES(?,?,?,?,?)',
                            (uid,label,'parent' if uid == 3 else 'walker',joined+uid,'nl'))
        self.db.commit()
        bot.kv(self.db,'bot','offline_preview')
        for uid in PERSONAS:
            bot.open_home(self.db,uid)
        _, days, hour, minute = CLOCKS[clock]
        target = BASE + timedelta(days=days,hours=hour,minutes=minute)
        for hour, minute in ((18,30),(21,45),(23,15)):
            moment = BASE.replace(hour=hour,minute=minute)
            if moment <= target:
                self.time = moment
                bot.tick(self.db,self.time)
        self.time = target
        bot.tick(self.db,self.time)
        bot.refresh_weeks(self.db)

    def send(self, chat, text, markup=None, html=False):
        if chat not in self.messages: return False
        self.sequence += 1
        self.messages[chat].append({'id':self.sequence,'text':text,'markup':markup or {},'rich':html,'out':False})
        return self.sequence

    def edit(self, chat, msg, text, markup=None, html=False):
        for message in self.messages.get(chat,[]):
            if message['id'] == msg:
                message.update(text=text,markup=markup or {},rich=html)
                return True
        return False

    def api(self, method, **params):
        if method == 'answerCallbackQuery': self.notice = params.get('text',''); return True
        if method == 'getMe': return {'username':'offline_preview'}
        if method == 'editMessageReplyMarkup':
            for message in self.messages.get(params['chat_id'], []):
                if message['id'] == params['message_id']:
                    message['markup'] = params.get('reply_markup') or {}
                    return True
            return False
        if method == 'deleteMessage':
            self.messages[params['chat_id']] = [m for m in self.messages[params['chat_id']] if m['id'] != params['message_id']]
            return True
        raise RuntimeError('Offline preview blocked API method: ' + method)

    def action(self, uid, params):
        self.notice = ''
        if params.get('action') == 'reset': return self.reset(params.get('clock','before'))
        if params.get('action') == 'tap':
            message = next((m for m in self.messages[uid] if m['id'] == int(params['message'])),None)
            data = params.get('data','')
            allowed = [button.get('callback_data') for row in (message or {}).get('markup',{}).get('inline_keyboard',[]) for button in row]
            if data not in allowed: raise ValueError('That button is no longer available')
            bot.on_button(self.db,{'id':'demo','from':{'id':uid},'data':data,
                                 'message':{'chat':{'id':uid,'type':'private'},'message_id':message['id']}})
        elif params.get('action') == 'text':
            text = params.get('text','').strip()[:1000]
            if text:
                self.sequence += 1
                self.messages[uid].append({'id':self.sequence,'text':text,'markup':{},'rich':False,'out':True})
                bot.on_text(self.db,{'from':{'id':uid,'first_name':PERSONAS[uid],'language_code':'nl'},
                                    'chat':{'id':uid,'type':'private'},'text':text})
        else: raise ValueError('Unknown action')
        bot.refresh_weeks(self.db)

    def page(self, uid):
        esc = lambda value: html.escape(str(value),quote=True)
        hidden = f'<input type="hidden" name="csrf" value="{self.csrf}"><input type="hidden" name="uid" value="{uid}">'
        personas = ''.join(f'<a class="{"selected" if key == uid else ""}" href="/?uid={key}">{label}</a>' for key,label in PERSONAS.items())
        options = ''.join(f'<option value="{key}" {"selected" if key == self.clock else ""}>{label}</option>' for key,(label,*_) in CLOCKS.items())
        messages = []
        for message in self.messages[uid]:
            rows = []
            for row in message['markup'].get('inline_keyboard',[]):
                buttons = []
                for button in row:
                    if 'callback_data' not in button: continue
                    buttons.append(f'<form method="post">{hidden}<input type="hidden" name="action" value="tap"><input type="hidden" name="message" value="{message["id"]}"><button name="data" value="{esc(button["callback_data"])}">{esc(button["text"])}</button></form>')
                rows.append('<div class="button-row">'+''.join(buttons)+'</div>')
            messages.append(f'<article class="message {"outgoing" if message["out"] else ""}"><div class="copy">{formatted(message["text"],message["rich"])}</div>'+''.join(rows)+'</article>')
        return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Honduitlaten · offline preview</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f3f5;color:#17222d;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:680px;margin:28px auto;padding:0 18px}.demo{font-size:12px;color:#6b5d23;background:#fff4cf;padding:12px 16px;border-radius:12px;margin-bottom:16px;line-height:1.5}h1{font-size:22px;margin:0 0 6px}p{color:#687683;line-height:1.5;margin:0 0 16px}.controls{background:white;padding:18px;border-radius:16px;margin-bottom:18px}.people{display:flex;gap:8px;margin-bottom:16px}.people a{flex:1;text-align:center;text-decoration:none;background:#edf0f3;color:#52616f;padding:10px;border-radius:9px}.people a.selected{background:#247aad;color:white}.scenario{display:flex;gap:8px}select,input,button{font:inherit}select{min-width:0;flex:1;border:1px solid #d8dfe5;border-radius:9px;padding:10px;background:white}button{cursor:pointer;border:0;border-radius:9px;padding:10px;background:#e4f0f8;color:#20628c}.scenario button{background:#edf0f3;color:#384b5a}.hint{font-size:12px;color:#71808a;margin-top:8px}.chat{border-radius:18px;overflow:hidden;background:#e7eef1;border:1px solid #dce3e8}.header{padding:16px 20px;background:#fff;display:flex;align-items:center;gap:12px}.avatar{background:#edf3e9;width:42px;height:42px;border-radius:50%;display:grid;place-items:center;font-size:22px}.subtitle{font-size:12px;color:#7c8b96;margin-top:3px}.messages{padding:18px;min-height:220px}.message{background:white;max-width:94%;padding:12px;border-radius:12px 12px 12px 3px;margin-bottom:12px;box-shadow:0 1px 1px #253f5010}.copy{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5;margin-bottom:5px;font-size:14px}.outgoing{background:#dcf4d1;margin-left:auto;border-radius:12px 12px 3px 12px}.button-row{display:flex;gap:5px;margin-top:5px}.button-row form{flex:1;min-width:0}.button-row button{width:100%;height:100%;font-size:12px;padding:9px 5px}.composer{display:flex;gap:8px;padding:14px;background:#fff}.composer input[type=text]{min-width:0;flex:1;border:1px solid #dce3e8;border-radius:10px;padding:11px}.notice{background:#173c52;color:white;padding:12px 16px;border-radius:10px;margin-bottom:12px}.footer{font-size:12px;margin:16px 0;color:#71808a}@media(max-width:480px){main{margin:12px auto;padding:0 10px}.controls{padding:14px}.messages{padding:12px}.message{max-width:100%}.scenario{flex-wrap:wrap}h1{font-size:20px}}
</style><main><div class="demo"><strong>Offline demo.</strong> No Telegram connection. Changes affect temporary sample data only.</div><h1>Honduitlaten</h1><p>Try the real family bot flow. Switch person to answer a swap or check the parent view.</p>''' + f'''
<section class="controls"><nav class="people">{personas}</nav><form method="post" class="scenario">{hidden}<input type="hidden" name="action" value="reset"><select name="clock" aria-label="Scenario">{options}</select><button>Start fresh scenario</button></form><div class="hint">Changing the scenario resets demo history. Switching person keeps it.</div></section>
{('<div class="notice" role="status">'+esc(self.notice)+'</div>') if self.notice else ''}
<section class="chat"><header class="header"><div class="avatar">🐕</div><div><strong>Honduitlaten</strong><div class="subtitle">{esc(PERSONAS[uid])}'s chat · {self.time.strftime('%d %b, %H:%M')} · Amsterdam</div></div></header><div class="messages">{''.join(messages)}</div>
<form class="composer" method="post">{hidden}<input type="hidden" name="action" value="text"><input name="text" type="text" aria-label="Message" placeholder="Bijv. kan niet vrijdag" maxlength="1000" autocomplete="off"><button>Send</button></form></section><p class="footer">Uses the bot's actual messages, buttons and scheduling rules. Closing this process discards all demo data.</p></main></html>'''


def handler_for(demo):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def respond(self, status, body, content_type='text/html; charset=utf-8'):
            raw = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            try:
                uid = int(parse_qs(self.path.partition('?')[2]).get('uid',['1'])[0])
                if uid not in PERSONAS: raise ValueError()
                self.respond(200,demo.page(uid))
            except (ValueError,KeyError): self.respond(400,'Unknown demo person')
        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 8192: return self.respond(400,'Invalid request')
                params = {key:value[0] for key,value in parse_qs(self.rfile.read(length).decode('utf-8')).items()}
                if not secrets.compare_digest(params.get('csrf',''),demo.csrf): return self.respond(403,'Invalid demo form')
                uid = int(params.get('uid','1'))
                if uid not in PERSONAS: raise ValueError('Unknown person')
                demo.action(uid,params)
                self.send_response(303); self.send_header('Location','/?'+urlencode({'uid':uid})); self.send_header('Content-Length','0'); self.end_headers()
            except (ValueError,KeyError) as exc: self.respond(400,html.escape(str(exc)))
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    demo = Demo()
    try:
        with HTTPServer(('127.0.0.1',args.port),handler_for(demo)) as server:
            print(f'Offline preview: http://127.0.0.1:{server.server_port}',flush=True)
            server.serve_forever()
    except KeyboardInterrupt: pass
    finally: demo.close()


if __name__ == '__main__': main()
