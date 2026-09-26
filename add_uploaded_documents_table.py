from app import app
from admin.extensions import db

with app.app_context():
    db.create_all()  # SQLAlchemy ينشئ بس الجداول الناقصة، ما يلمس الموجود
    print("Done — uploaded_documents table added, existing data untouched.")