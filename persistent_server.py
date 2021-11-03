from markupsafe import escape
import flask
from flask_socketio import SocketIO, send, emit, join_room, leave_room
import sys
import psycopg2 as p

conn = p.connect(host='localhost', database='chat', user='flask_user', password='flask_password')
cur = conn.cursor()
app = flask.Flask(__name__)
socketio = SocketIO(app, logger=True, engineio_logger=True)
guests = set()

def fetch_messages():
    cur.execute('select CONTENT, USERNAME from MESSAGE;')
    return cur.fetchall()

def store_message(data):
    cur.execute('insert into MESSAGE (content, username) values (%s, %s)', (data["message"], f'Guest{data["token"]-100}'))
    conn.commit()

@app.route("/")
def login():
    return flask.render_template('login.html', error=escape(flask.request.args.get('error', '')))

@app.route('/login_post', methods=['POST'])
def verify():
    return flask.redirect(flask.url_for('login', error='invalid_credentials'))

@app.route('/login_guest')
def guest_login():
    return flask.redirect(flask.url_for('chat', guest='True'))

@app.route('/chat')
def chat():
    if flask.request.args.get('guest', 'False') == 'True':
        return flask.render_template('chat.html')
    else: 
        return flask.redirect(flask.url_for('login'))

@socketio.on('join')
def onjoin(data):
    join_room(data['room'])

    past = fetch_messages()
    for m in past:
        content, username = m
        emit('receivemsg', f'{username}: {content}')
        
    token, user = len(guests)+100, f'Guest{len(guests)}'
    msg = f'@{user} joined the room #{data["room"]}'
    emit('login', {'token' : token, 'user' : user, 'message' : msg})
    guests.add(len(guests))
    print(msg)

@socketio.on('chatmsg')
def delivermsg(data):
    store_message(data)
    msg = f'Guest{data["token"]-100}: {data["message"]}'
    socketio.emit('receivemsg', msg, to='chat')
    print(msg)

if __name__ == '__main__':
    args = {sys.argv[i]:sys.argv[i+1] for i in range(len(sys.argv)) if sys.argv[i][0:2] == '--'}
    debug = args.get('--debug', False) == 'True'
    host = args.get('--host', None)
    port = int(args.get('--port', 80))
    key = args.get('--keyfile', None)
    cert = args.get('--certfile', None)
    print(f'DEBUG: {debug}\nHOST: {host}\nPORT: {port}\nKEYFILE: {key}\nCERTFILE: {cert}')
    socketio.run(app, debug=debug, host=host, port=port, keyfile=key, certfile=cert)
