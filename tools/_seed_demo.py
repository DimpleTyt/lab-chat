import sys
sys.path.insert(0, ".")
from app.db import init_db
from tools.create_user import upsert_user
init_db()
uid, created = upsert_user("demo", "demo1234", "Demo")
print("user", uid, "created" if created else "updated")
