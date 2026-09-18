import os, bcrypt, mysql.connector
cn=mysql.connector.connect(
    host=os.getenv('BIMA2_DB_HOST','127.0.0.1'),
    port=int(os.getenv('BIMA2_DB_PORT','3306')),
    user=os.getenv('BIMA2_DB_USER','bima2_app'),
    password=os.getenv('BIMA2_DB_PASSWORD'),
    database=os.getenv('BIMA2_DB_NAME','jaes_bima2'))
cur=cn.cursor()
cur.execute("SELECT id FROM roles WHERE name='MasterAdmin'")
role_id=cur.fetchone()[0]
username=os.getenv('BIMA2_ADMIN_USERNAME','Admin')
password=os.getenv('BIMA2_ADMIN_PASSWORD','Admin1234')
ph=bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode()
cur.execute("SELECT id FROM users WHERE username=%s",(username,))
row=cur.fetchone()
if row:
    cur.execute("UPDATE users SET password_hash=%s, role_id=%s, is_active=1, full_name='Master Administrator' WHERE id=%s",(ph,role_id,row[0]))
else:
    cur.execute("INSERT INTO users(username,password_hash,full_name,role_id,is_active) VALUES(%s,%s,'Master Administrator',%s,1)",(username,ph,role_id))
cn.commit(); cur.close(); cn.close()
print('Master Admin ready:', username)
