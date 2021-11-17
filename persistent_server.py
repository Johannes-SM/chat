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
cur.execute('set time zone "UTC"')
conn.commit()
app = flask.Flask(__name__)
app.secret_key = d['secret_key']
socketio = SocketIO(app, logger=True, engineio_logger=True)
guests = set()
# number of messages to load when initializing a chat room
DEFAULT_PAST = 100
# number of accounts that can be generated per ip address per day
ACC_PER_IP_PER_DAY_LIM = 100
# maximum acceptable length for usernames
NAME_LEN_LIM = 40
MSG_LEN_LIM = 1500
# period in seconds
PERIOD = 5
RATE_LIMIT = 4
# seconds in a day
SEC_DAY = 60 * 60 * 24
CMD_PREFIX = '/'

# return list of n messages from MESSAGE table
def fetch_messages(n, rev=True):
    cur.execute('select CONTENT, USERNAME from MESSAGE order by ID desc;')
    stuff = cur.fetchmany(n)
    conn.commit()
    if rev: stuff.reverse()
    return stuff

# store message in MESSAGE table
def store_message(username, message):
    values = (message, username)
    print('\n store_message', values)
    cur.execute('insert into MESSAGE (content, username, date_sent) values (%s, %s, NOW());', values)
    conn.commit()

# produce list of IDs associated with an IP. There should only be 1 or 0 IDs per IP address. 
def ip_to_id(ip):
    cur.execute('select ID from ID_IP where IP=%s;', (ip,))
    conn.commit()
    return cur.fetchall()

# register IP in ID_IP table
def make_ipid(ip):
    # return if IP already registed in ID_IP table
    if len(ip_to_id(ip)) > 0:
        return
    cur.execute('insert into ID_IP values (gen_random_uuid(), %s)', (ip,))
    conn.commit()

# return True if IP address is permitted to make an account. Return False otherwise. 
def can_create(ip):
    _id = ip_to_id(ip)
    # check if IP has been registered in ID_IP table
    if len(_id) < 1: 
        # return True if IP has not been registered in ID_IP table
        return True 
    # check how many accounts are associated with the IP. 
    values = (_id[0][0], SEC_DAY)
    cur.execute('select COUNT(*) from ACCOUNT where IPID=%s and extract(epoch from NOW()-DATE_CREATED)<=%s', values)
    r = cur.fetchall()[0][0]
    conn.commit()
    print('\n\n', r)
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
    conn.commit()
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

    # register IP in ID_IP table
    make_ipid(ip)
    # generate salt and store in `slt`
    slt = str(uuid.uuid4())
    # create new account and return True
    h = hl.sha256(f'{password}{slt}'.encode()).hexdigest()
    args = (username, h, ip_to_id(ip)[0][0], slt)
    cur.execute('insert into ACCOUNT values (DEFAULT, %s, %s, NOW(), %s, %s, DEFAULT)', args)
    conn.commit()
    return True

# Attempt to login client given a username and password
def account_login(username, password):
    cur.execute('select PASSWORD, SALT from ACCOUNT where USERNAME=%s;', (username,))
    conn.commit()
    h, s = cur.fetchall()[0]
    match = hl.sha256(f'{password}{s}'.encode()).hexdigest() == h
    if match: return True
    return False

def check_spam(username):
    values = (username, PERIOD)
    cur.execute('select (extract(epoch from NOW())-SEC_SENT) from MESSAGE \
                 where USERNAME=%s and (extract(epoch from NOW())-SEC_SENT)<=%s \
                 and (extract(epoch from NOW())-SEC_SENT)>0 \
                 order by ID asc', values)
    conn.commit()
    a = cur.fetchall()
    print('\n', a)
    return a

def cmd_parse(cmd):
    invalid_cmd_msg = 'Invalid command'
    args = cmd.split(' ')
    if args[0] not in ['swag']: return invalid_cmd_msg
    else: return f'{args[0]} is a valid command'

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
        emit('receivemsg', {'msg_content': msg[0], 'msg_sender': msg[1]})
    msg = f'@{username} joined the room #{data["room"]}'
    emit('login', {'message' : msg})

@socketio.on('chatmsg')
def delivermsg(data):
    if data['message'][0] == CMD_PREFIX:
        notif = cmd_parse(data['message'][1::])
        emit('notification', {'type': 'command', 'notif': notif, 'msg_content': data['message']})
        return
    username = flask.session['username']
    a = check_spam(username)
    if len(a) > RATE_LIMIT: 
        emit('notification', {'type' : 'spam', \
             'notif' : f'wait {PERIOD-a[0][0]} before sending another message', 'msg_content' : data['message']})
        return
    if len(data['message']) > MSG_LEN_LIM: 
        data['message'] = data['message'][0:MSG_LEN_LIM]
    msg = data['message']
    store_message(username = username, message = data['message'])
    socketio.emit('receivemsg', {'msg_content': msg, 'msg_sender': username}, to='chat')

@socketio.on('request_history')
def deliver_history(data):
    n, req_num = data['n'], data['req_num']
    j_msgs = fetch_messages(n+req_num, rev=False)[n::]
    emit('receive_history', {'messages' : j_msgs})

if __name__ == '__main__':
    args = {sys.argv[i]:sys.argv[i+1] for i in range(len(sys.argv)) if sys.argv[i][0:2] == '--'}
    debug = args.get('--debug', False) == 'True'
    host = args.get('--host', None)
    port = int(args.get('--port', 80))
    key = args.get('--keyfile', None)
    cert = args.get('--certfile', None)
    print(f'DEBUG: {debug}\nHOST: {host}\nPORT: {port}\nKEYFILE: {key}\nCERTFILE: {cert}')
    socketio.run(app, debug=debug, host=host, port=port, keyfile=key, certfile=cert)
