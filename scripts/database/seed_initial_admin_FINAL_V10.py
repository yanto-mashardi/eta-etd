import os
import bcrypt
import mysql.connector

required = ["BIMA2_DB_PASSWORD", "BIMA2_ADMIN_PASSWORD"]
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit("Environment variable wajib belum diset: " + ", ".join(missing))

cn = mysql.connector.connect(
    host=os.getenv("BIMA2_DB_HOST", "127.0.0.1"),
    port=int(os.getenv("BIMA2_DB_PORT", "3306")),
    user=os.getenv("BIMA2_DB_USER", "root"),
    password=os.environ["BIMA2_DB_PASSWORD"],
    database=os.getenv("BIMA2_DB_NAME", "jaes_bima2"),
)
cur = cn.cursor()
cur.execute("SELECT id FROM roles WHERE name='MasterAdmin'")
role = cur.fetchone()
if not role:
    raise SystemExit("Role MasterAdmin belum tersedia. Jalankan seed_roles_permissions.sql terlebih dahulu.")

role_id = role[0]
username = os.getenv("BIMA2_ADMIN_USERNAME", "Admin")
password = os.environ["BIMA2_ADMIN_PASSWORD"]
password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

cur.execute("SELECT id FROM users WHERE username=%s", (username,))
row = cur.fetchone()
if row:
    cur.execute(
        "UPDATE users SET password_hash=%s,role_id=%s,is_active=1,full_name='Master Administrator' WHERE id=%s",
        (password_hash, role_id, row[0]),
    )
    action = "UPDATED"
else:
    cur.execute(
        "INSERT INTO users(username,password_hash,full_name,role_id,is_active) VALUES(%s,%s,'Master Administrator',%s,1)",
        (username, password_hash, role_id),
    )
    action = "CREATED"

cn.commit()
cur.close()
cn.close()
print(f"Master Admin {action}: {username}")
