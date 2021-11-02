from markupsafe import escape
import flask
from flask_socketio import SocketIO, send, emit, join_room, leave_room
import sys

app = flask.Flask(__name__)
socketio = SocketIO(app, logger=True, engineio_logger=True)
guests = set()

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
    token, user = len(guests)+100, f'Guest{len(guests)}'
    msg = f'@{user} joined the room #{data["room"]}'
    emit('login', {'token' : token, 'user' : user, 'message' : msg})
    guests.add(len(guests))
    print(msg)

@socketio.on('chatmsg')
def delivermsg(data):
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
