from markupsafe import escape
import flask
from flask_socketio import SocketIO, send, emit, join_room, leave_room
import sys
import psycopg2 as p
import json
import time
import hashlib as hl
import uuid

# load config file
with open('non_git_stuff/l.json', 'r') as j:
    d = json.load(j)
conn = p.connect(host='localhost', database='chat', user=d['user'], password=d['password'])
cur = conn.cursor()
app = flask.Flask(__name__)
app.secret_key = d['secret_key']
socketio = SocketIO(app, logger=True, engineio_logger=True)
guests = set()
# number of messages to load when initializing a chat room
DEFAULT_PAST = 10
# number of accounts that can be generated per ip address per day
ACC_PER_IP_PER_DAY_LIM = 100
# maximum acceptable length for usernames
NAME_LEN_LIM = 40

# return list of n messages from MESSAGE table
def fetch_messages(n):
    cur.execute('select CONTENT, USERNAME from MESSAGE order by ID desc;')
    stuff = cur.fetchmany(n)
    stuff.reverse()
    return stuff

# store message in MESSAGE table
def store_message(username, message):
    cur.execute('insert into MESSAGE (content, username) values (%s, %s);', (message, username))
    conn.commit()

# produce list of IDs associated with an IP. There should only be 1 or 0 IDs per IP address. 
def ip_to_id(ip):
    cur.execute('select ID from ID_IP where IP=%s;', (ip,))
    return cur.fetchall()

# return True if IP address is permitted to make an account. Return False otherwise. 
def can_create(ip):
    _id = ip_to_id(ip)
    # check if IP has been registered in ID_IP table
    if len(_id) < 1: 
        # generate unique ID if IP does not exist in ID_IP table and return True
        cur.execute('insert into ID_IP values (gen_random_uuid(), %s)', (ip,))
        conn.commit()
        return True 
    # check how many accounts are associated with the IP. 
    cur.execute('select COUNT(*) from ACCOUNT where IPID=%s', (_id[0][0],))
    r = cur.fetchall()[0][0]
    # return False if sign up limit exceeded
    if r >= ACC_PER_IP_PER_DAY_LIM:
        return False
    # return True otherwise
    return True

# return timestamp in GMT and YYYY-MM-DD HH:MM:SS format
def get_gmtime():
    b = time.gmtime(time.time())
    return f'{b[0]}-{b[1]}-{b[2]} {b[3]}:{b[4]}:{b[5]}'

# return True if account with username exists, otherwise return False
def check_acc_exists(username): 
    cur.execute('select COUNT(*) from ACCOUNT where USERNAME=%s', (username,))
    if cur.fetchall()[0][0] > 0: return True
    return False

def validate_username(username):
    alphanumeric = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890'
    if username == '' or \
       username[0] not in alphanumeric or \
       len(username) > NAME_LEN_LIM: return False
    return True

# Attempt to create an account for given username, password, and ip
def create_account(username, password, ip):
    # return False if username does not meet requirements
    if not validate_username(username): return False

    # generate salt and store in `slt`
    slt = str(uuid.uuid4())
    # create new account and return True
    h = hl.sha256(f'{password}{slt}'.encode()).hexdigest()
    args = (username, h, get_gmtime(), ip_to_id(ip)[0][0], slt)
    cur.execute('insert into ACCOUNT values (DEFAULT, %s, %s, %s, %s, %s)', args)
    conn.commit()
    return True

# Attempt to login client given a username and password
def account_login(username, password):
    cur.execute('select PASSWORD, SALT from ACCOUNT where USERNAME=%s;', (username,))
    h, s = cur.fetchall()[0]
    match = hl.sha256(f'{password}{s}'.encode()).hexdigest() == h
    if match: return True
    return False

@app.route("/")
def login():
    return flask.render_template('login.html', error=escape(flask.request.args.get('error', '')))

@app.route('/disclaimer')
def disclaimer():
    return flask.render_template('disclaimer.html')

@app.route('/login_post', methods=['POST'])
def verify():
    data, ip = flask.request.form, flask.request.remote_addr
    err = False
    if not check_acc_exists(username = data['username']):
        if not can_create(ip): err='account_creation_limit_reached'
        elif not create_account(username = data['username'], password = data['password'], ip = ip): err='invalid_username'
    else: 
        if not account_login(username = data['username'], password = data['password']): err='invalid_password'
    if err: return flask.redirect(flask.url_for('login', error=err, ulim=NAME_LEN_LIM))
    flask.session['username'] = data['username']
    flask.session['password'] = data['password']
    return flask.redirect(flask.url_for('chat'))

@app.route('/login_guest')
def guest_login():
    username = f'Guest{len(guests)}'
    guests.add(len(guests))
    flask.session['username'] = username
    return flask.redirect(flask.url_for('chat', guest='True'))

@app.route('/chat')
def chat():
    return flask.render_template('chat.html')

@socketio.on('join')
def onjoin(data):
    join_room(data['room'])
    username = flask.session.get('username', None)
    if username == None:
        emit('redirect', {'url' : flask.url_for('guest_login')})
    j_msgs = fetch_messages(DEFAULT_PAST)
    for msg in j_msgs:
        emit('receivemsg', {'message' : f'{msg[1]}: {msg[0]}'})
    msg = f'@{username} joined the room #{data["room"]}'
    emit('login', {'message' : msg})
    print(msg)

@socketio.on('chatmsg')
def delivermsg(data):
    username = flask.session['username']
    msg = f'{username}: {data["message"]}'
    store_message(username = username, message = data['message'])
    socketio.emit('receivemsg', {'message': msg}, to='chat')
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
