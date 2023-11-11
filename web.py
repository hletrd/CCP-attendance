from flask import Flask, render_template, request, session, abort, redirect, Response

import datetime
import re
import random
import string
import secrets

import qrcode
import base64
from io import BytesIO

import pymysql.cursors

app = Flask(__name__)

db_user = '' #database username
db_pass = '' #database password
password = '' #login password
url = 'https://vmo.snu.ac.kr:5001'

app.secret_key = secrets.token_hex()

conn_mariadb = lambda host, user, password, database: pymysql.connect(host=host, user=user, password=password, database=database, cursorclass=pymysql.cursors.DictCursor)

def randstr(length=10):
  return ''.join(random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits, k=length))

@app.route('/qrcode', methods=['GET', 'POST'])
def showqr():
  if 'auth' not in session:
    if request.method == 'GET':
      return render_template('auth.html')
    else:
      if request.form.get('password') == password:
        session['auth'] = True
      else:
        return render_template('auth.html')
  code = makeqr()
  today = datetime.datetime.now().strftime("%-m월 %-d일")
  sql = "DELETE FROM `tokens` WHERE `token` NOT IN (SELECT `token` FROM `attend` GROUP BY `token`);"
  conn = conn_mariadb('localhost', db_user, db_pass, 'ccp')
  cursor = conn.cursor()
  cursor.execute(sql)
  conn.commit()
  cursor.close()
  conn.close()
  return render_template('qrcode.html', data={'qrcode': code, 'now': today})

def makeqr():
  conn = conn_mariadb('localhost', db_user, db_pass, 'ccp')
  cursor = conn.cursor()
  if 'token' not in session:
    token = randstr(10)
    session['token'] = token
    sql = "INSERT INTO `tokens` SET `token`=%s, `datetime`=NOW();"
    cursor.execute(sql, (token,))
    conn.commit()
  else:
    token = session['token']
    sql = "SELECT * FROM `tokens` WHERE `token`=%s AND `datetime` >= DATE_SUB(NOW(), INTERVAL 3 SECOND);"
    cursor.execute(sql, (token,))
    result = cursor.fetchone()
    if result == None: #reissue a token
      token = randstr(10)
      session['token'] = token
      sql = "INSERT INTO `tokens` SET `token`=%s, `datetime`=NOW();"
      cursor.execute(sql, (token,))
      conn.commit()
  cursor.close()
  conn.close()
  qr = qrcode.QRCode(
    version=None,
    error_correction=qrcode.constants.ERROR_CORRECT_Q,
    box_size=1,
    border=2,
  )
  qr.add_data(url + '/?token=' + token)
  qr.make(fit=True)
  img = qr.make_image(fill_color="black", back_color="white")
  buffered = BytesIO()
  img.save(buffered)
  img = 'data:image/png;base64,' + str(base64.b64encode(buffered.getvalue()), 'ascii')
  return img

@app.route('/qrget')
def serveqr():
  if 'auth' not in session:
    abort(404)
  return makeqr()

@app.route('/count')
def count():
  if 'auth' not in session:
    abort(404)
  else:
    token = request.form.get('token', '')
    conn = conn_mariadb('localhost', db_user, db_pass, 'ccp')
    cursor = conn.cursor()
    sql = "SELECT COUNT(*) FROM `attend` WHERE `datetime` >= DATE_SUB(NOW(), INTERVAL 3 HOUR);"
    cursor.execute(sql)
    result = cursor.fetchone()
    return str(result['COUNT(*)'])

@app.route('/list')
def list_unattend():
  if 'auth' not in session:
    abort(404)
  else:
    attended_students = {}
    conn = conn_mariadb('localhost', db_user, db_pass, 'ccp')
    cursor = conn.cursor()
    sql = "SELECT `name`,`number` FROM `attend` WHERE `attend`.`datetime` >= DATE_SUB(NOW(), INTERVAL 3 HOUR);"
    cursor.execute(sql)
    result = cursor.fetchall()
    for i in result:
      attended_students[i['number']] = 1
    sql = "SELECT `name`,`number` FROM `students`;"
    cursor.execute(sql)
    result = cursor.fetchall()
    response = ''
    students = []
    for i in result:
      if i['number'] not in attended_students:
        if len(i['name']) > 3:
          name = i['name'][0] + '*' + i['name'][2] + ('*'*(len(i['name'])-3))
        elif len(i['name']) == 3:
          name = i['name'][0] + '*' + i['name'][2]
        elif len(i['name']) == 2:
          name = i['name'][0] + '*'
        else:
          name = '*'
        students.append(name)
    response = ', '.join(students)
    return response

@app.route('/result', methods=['GET', 'POST'])
def attend_result():
  if 'auth' not in session:
    if request.method == 'GET':
      return render_template('auth.html')
    else:
      if request.form.get('password') == password:
        session['auth'] = True
      else:
        return render_template('auth.html')
  if request.args.get('date', '') != '':
    date = datetime.datetime.strptime(datetime.datetime.now().strftime("%Y")+'-'+request.args.get('date', ''), '%Y-%m-%d')
  else:
    date = datetime.datetime.now()
  token = request.form.get('token', '')
  conn = conn_mariadb('localhost', db_user, db_pass, 'ccp')
  cursor = conn.cursor()
  sql = "SELECT `name`,`number`,`attend`.`datetime` AS `adatetime`,`scanned`,`ip`,`ua`,`session`,`tokens`.`datetime` AS `tdatetime` FROM `attend` LEFT JOIN `tokens` ON `attend`.`token`=`tokens`.`token` WHERE `attend`.`datetime` >= DATE_SUB('" + date.strftime("%Y-%m-%d %H:%M:%S") + "', INTERVAL 24 HOUR);"
  cursor.execute(sql)
  sessions = {}
  attended_students = {}
  result = cursor.fetchall()
  response = '이름,학번,시각,QR코드 스캔 시각,IP,세션,QR코드 발급 시각,비고\n'
  sessionid_seq = 0
  for i in result:
    if i['session'] in sessions:
      sessionid = sessions[i['session']]
    else:
      sessionid = sessionid_seq
      sessions[i['session']] = sessionid
      sessionid_seq += 1
    attended_students[i['number']] = 1
    response += i['name'] + ','
    response += i['number'] + ','
    response += i['adatetime'].strftime("%Y-%m-%d %H:%M:%S") + ','
    try:
      response += i['scanned'].strftime("%Y-%m-%d %H:%M:%S") + ','
    except:
      response += ','
    response += i['ip'] + ','
    response += str(sessionid) + ','
    try:
      response += i['tdatetime'].strftime("%Y-%m-%d %H:%M:%S")  + ',,'
    except AttributeError:
      response += ',,'
    response += '\n'
  sql = "SELECT `name`,`number` FROM `students`;"
  cursor.execute(sql)
  result = cursor.fetchall()
  for i in result:
    if i['number'] not in attended_students:
      response += i['name'] + ','
      response += i['number'] + ','
      response += ',,,,결석\n'
  return Response(response, mimetype='text/plain', headers={"Content-Disposition":"attachment; filename=attendance_" + date.strftime("%m-%d") + ".txt"})

@app.route('/', methods=['GET', 'POST'])
def index():
  today = datetime.datetime.now().strftime("%-m월 %-d일")
  if request.args.get('token', '') != '':
    session['usertoken'] = request.args.get('token', '')
    return redirect('/')
  if request.method == 'POST':
    csrf = request.form.get('csrf', '')
    name = request.form.get('name', '')
    number = request.form.get('number', '')
    timestamp = request.form.get('timestamp', '')
    if 'usertoken' in session:
      token = session['usertoken']
    else:
      token = request.form.get('token', '')
    with conn_mariadb('localhost', db_user, db_pass, 'ccp') as conn:
      cursor = conn.cursor()
      sql = "SELECT * FROM `tokens` WHERE `token`=%s AND `datetime` >= DATE_SUB(NOW(), INTERVAL 5 MINUTE);"
      cursor.execute(sql, (token,))
      result = cursor.fetchone()
      if 'csrf' not in session or session['csrf'] != csrf or re.fullmatch(r'[가-힣]{2,10}', name) == None or re.fullmatch(r'20[12][0-9]-[129][0-9]{4}', number) == None or 'key' not in session or re.fullmatch(r'[0-9]{10}', timestamp) == None: #or result == None
        if 'csrf' not in session or session['csrf'] != csrf:
          message = 'CSRF 토큰 오류'
        if re.fullmatch(r'[가-힣]{2,10}', name) == None or re.fullmatch(r'20[12][0-9]-[129][0-9]{4}', number) == None:
          message = '이름 또는 학번 오류'
        #if result == None: #Currently not checking QR code validity
        #  message = '유효하지 않은 링크'
        if re.fullmatch(r'[0-9]{10}', timestamp) == None:
          message = '유효하지 않은 링크'
        if 'key' not in session:
          message = '세션 만료'
        session['csrf'] = randstr(10)
        return render_template('index.html', data={'now': today, 'token': token, 'name': name, 'number': number, 'csrf': session['csrf'], 'alert_type': 'warning', 'alert': '출석 체크에 실패했습니다: ' + message})
      ip = request.remote_addr
      ua = request.headers.get('User-Agent')
      timestamp = datetime.datetime.fromtimestamp(int(timestamp))
      sql = "SELECT * FROM `students` WHERE `name`=%s AND `number`=%s;"
      cursor.execute(sql, (name, number))
      result = cursor.fetchone()
      if result == None:
        session['csrf'] = randstr(10)
        conn.commit()
        return render_template('index.html', data={'now': today, 'token': token, 'name': name, 'number': number, 'csrf': session['csrf'], 'alert_type': 'warning', 'alert': '사용자 정보가 잘못되었습니다.'})
      sql = "SELECT * FROM `attend` WHERE `name`=%s AND `number`=%s AND `datetime` >= DATE_SUB(NOW(), INTERVAL 3 HOUR);"
      cursor.execute(sql, (name, number))
      result = cursor.fetchone()
      if result != None:
        session['csrf'] = randstr(10)
        conn.commit()
        return render_template('index.html', data={'now': today, 'token': token, 'name': name, 'number': number, 'csrf': session['csrf'], 'alert_type': 'warning', 'alert': '출석 기록이 이미 존재합니다.'})
      sql = "INSERT INTO `attend` SET `name`=%s, `number`=%s, `datetime`=NOW(), `scanned`=%s, `ip`=%s, `ua`=%s, `session`=%s, `token`=%s;"
      cursor.execute(sql, (name, number, timestamp, ip, ua, session['key'], token))
      conn.commit()
      return render_template('index.html', data={'now': today, 'token': request.args.get('token') or '', 'name': name, 'number': number, 'csrf': session['csrf'], 'alert_type': 'primary', 'alert': '출석 체크에 성공했습니다.'})
  if 'key' not in session:
    session['key'] = randstr(10)
  usertoken = None
  session['csrf'] = randstr(10)
  if 'usertoken' in session:
    usertoken = session['usertoken']
  return render_template('index.html', data={'now': today, 'token': usertoken or '', 'csrf': session['csrf']})

if __name__ == "__main__":
  app.run(host='0.0.0.0', port=5001, debug=True)