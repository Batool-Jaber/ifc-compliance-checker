"""
admin_dev_server.py
=====================
TEMPORARY dev convenience -- runs ONLY the admin blueprint, without
importing main.py (and therefore without pulling in the heavy
sentence_transformers -> transformers -> torch import chain that's
currently being blocked by a Windows Application Control policy on
this machine -- see the WinError 4551 you hit running app.py).

This lets you keep developing/testing the admin system while that
separate Windows issue gets sorted out with IT / Smart App Control.

Once torch imports cleanly again, go back to `python app.py` as your
normal entry point -- the admin blueprint is registered there too
(via the same init_admin(app) call used below). Nothing about the
admin system itself changes between the two.

Usage:
    python admin_dev_server.py
Then open http://localhost:5000/admin/login
"""

import os

from flask import Flask

from admin import init_admin

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///admin.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

init_admin(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)