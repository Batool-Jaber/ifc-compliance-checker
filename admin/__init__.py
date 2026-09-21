"""
admin/__init__.py
==================
Assembles the whole admin feature into a single Flask Blueprint, and
exposes `init_admin(app)` as the ONE integration point the main app.py
needs to call.

Route modules (routes/auth.py, conditions.py, proposals.py, users.py,
audit.py, help.py) each attach their routes to `admin_bp` as a side
effect of being imported below -- must stay imported AFTER admin_bp is
defined.
"""

from flask import Blueprint

from admin.extensions import db
from admin.seed import seed_database

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="../templates/admin",
    static_folder=None,  # admin CSS/JS live in the main app's static/ folder
)

# Each import below attaches that module's routes to admin_bp. Must
# stay AFTER admin_bp is defined (see module docstring).
from admin.routes import auth        # noqa: E402,F401
from admin.routes import conditions  # noqa: E402,F401
from admin.routes import proposals   # noqa: E402,F401
from admin.routes import users       # noqa: E402,F401
from admin.routes import audit       # noqa: E402,F401
from admin.routes import help        # noqa: E402,F401  (NEW -- Help Assistant page)


@admin_bp.context_processor
def inject_template_globals():
    """Makes `current_user` and the `Role` enum available in every
    templates/admin/*.html file without passing them explicitly on
    every single render_template() call."""
    from admin.decorators import get_current_user
    from admin.models import Role

    return {"current_user": get_current_user(), "Role": Role}


def init_admin(app) -> None:
    """Wires this package into an existing Flask app. Call once from
    the main app.py, after `app = Flask(__name__)`:

        from admin import init_admin
        init_admin(app)
    """
    db.init_app(app)
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()
        seed_database(app)