"""
admin/routes/knowledge.py
==========================
Admin-only knowledge-base management: uploading new Markdown sources
(TWO-STEP: preview with quality warnings, then confirm), plus listing/
editing/deleting sources already uploaded.

UPLOAD (two-step, unchanged from before):
Step 1 (knowledge_upload_preview): admin picks a .md file + split
structure + audience_role + a unique source_name. The file is saved to
a PENDING staging path, chunked, and run through
rag/knowledge_upload.py::analyze_markdown_quality() -- warnings only,
NEVER a hard block (same "system informs, human decides" principle as
the Safe Tester / Building Code Advisory features). Nothing is written
to Chroma or the uploaded_documents table yet.

Step 2 (knowledge_upload_confirm): only reachable from the preview
page. Moves the file from the pending staging path to its permanent
location, upserts its chunks into the unified Chroma collection via
sync_uploaded_markdown(), and records an UploadedDocument row.

MANAGEMENT (NEW):
knowledge_list(): shows every uploaded source (from the
uploaded_documents table), with a form to correct its audience_role
and a delete action.

knowledge_edit_role(): METADATA-ONLY correction. Updates
UploadedDocument.audience_role in the DB AND every one of that
source's chunks in Chroma via rag/vector_db.py::update_audience_role()
-- does NOT re-chunk or touch the file's content in any way. Deliberately
scoped this narrowly: changing the file itself or its split structure
is treated as "delete, then re-upload from scratch" via the existing
upload flow, not a form field here -- keeps this action simple and low-
risk instead of half-duplicating the upload logic.

knowledge_delete(): removes the source's chunks from Chroma
(rag/vector_db.py::delete_source()), deletes the raw .md file from
disk, and deletes the UploadedDocument row. Irreversible -- confirmed
client-side via the shared admin-modal.js confirmation pattern, same
as every other destructive action in this app (Approve, Reject, etc.).
"""

import uuid
from pathlib import Path

from flask import flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from admin import admin_bp
from admin.decorators import get_current_user, role_required
from admin.extensions import db
from admin.models import Role, UploadedDocument
from rag.knowledge_upload import UPLOAD_DIR, analyze_markdown_quality, chunk_uploaded_file, sync_uploaded_markdown
from rag.vector_db import delete_source, update_audience_role

PENDING_DIR = UPLOAD_DIR / "_pending"
PENDING_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@admin_bp.route("/knowledge")
@role_required(Role.ADMIN.value)
def knowledge_list():
    documents = UploadedDocument.query.order_by(UploadedDocument.uploaded_at.desc()).all()
    return render_template("admin/knowledge_list.html", documents=documents)


@admin_bp.route("/knowledge/upload", methods=["GET"])
@role_required(Role.ADMIN.value)
def knowledge_upload_form():
    return render_template("admin/knowledge_upload.html")


@admin_bp.route("/knowledge/upload/preview", methods=["POST"])
@role_required(Role.ADMIN.value)
def knowledge_upload_preview():
    """
    STEP 1. Saves the uploaded file to a PENDING staging path, chunks
    it, runs the quality heuristic, and shows the admin everything
    before anything touches Chroma or the DB.
    """
    file = request.files.get("file")
    source_name = request.form.get("source_name", "").strip()
    split_mode = request.form.get("split_mode", "")
    audience_role = request.form.get("audience_role", "")

    errors = []
    if not file or file.filename == "":
        errors.append("Choose a .md file to upload.")
    elif not file.filename.lower().endswith(".md"):
        errors.append("Only .md (Markdown) files are accepted.")
    if not source_name:
        errors.append("Give this source a name.")
    elif UploadedDocument.query.filter_by(source_name=source_name).first() is not None:
        errors.append(f"A source named '{source_name}' already exists -- choose a different name.")
    if split_mode not in ("single_level", "two_level"):
        errors.append("Choose a split structure.")
    if audience_role not in ("engineer", "admin", "all"):
        errors.append("Choose who this content is for.")

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("admin.knowledge_upload_form"))

    pending_filename = f"{uuid.uuid4().hex}.md"
    pending_path = PENDING_DIR / pending_filename
    file.save(pending_path)

    try:
        chunks = chunk_uploaded_file(pending_path, split_mode)
        analysis = analyze_markdown_quality(chunks)
    except Exception as e:
        pending_path.unlink(missing_ok=True)
        flash(f"Couldn't process this file: {e}", "error")
        return redirect(url_for("admin.knowledge_upload_form"))

    return render_template(
        "admin/knowledge_upload_preview.html",
        pending_filename=pending_filename,
        original_filename=secure_filename(file.filename),
        source_name=source_name,
        split_mode=split_mode,
        audience_role=audience_role,
        warnings=analysis["warnings"],
        stats=analysis["stats"],
        chunk_titles=[c["title"] for c in chunks],
    )


@admin_bp.route("/knowledge/upload/confirm", methods=["POST"])
@role_required(Role.ADMIN.value)
def knowledge_upload_confirm():
    """
    STEP 2. Only reachable from the preview page. Moves the file out of
    staging to its permanent path, upserts its chunks into the unified
    Chroma collection, and records the UploadedDocument row.
    """
    pending_filename = request.form.get("pending_filename", "")
    original_filename = request.form.get("original_filename", "")
    source_name = request.form.get("source_name", "").strip()
    split_mode = request.form.get("split_mode", "")
    audience_role = request.form.get("audience_role", "")

    pending_path = PENDING_DIR / pending_filename
    if not pending_path.exists():
        flash("This upload has expired or was already processed -- start again.", "error")
        return redirect(url_for("admin.knowledge_upload_form"))

    if UploadedDocument.query.filter_by(source_name=source_name).first() is not None:
        pending_path.unlink(missing_ok=True)
        flash(f"A source named '{source_name}' already exists -- choose a different name.", "error")
        return redirect(url_for("admin.knowledge_upload_form"))

    final_path = UPLOAD_DIR / f"{source_name}.md"
    pending_path.rename(final_path)

    try:
        chunk_count = sync_uploaded_markdown(source_name, final_path, split_mode, audience_role)
    except Exception as e:
        flash(f"Failed to add this source to the knowledge base: {e}", "error")
        return redirect(url_for("admin.knowledge_upload_form"))

    db.session.add(UploadedDocument(
        source_name=source_name,
        original_filename=original_filename,
        file_path=str(final_path),
        split_mode=split_mode,
        audience_role=audience_role,
        chunk_count=chunk_count,
        uploaded_by=get_current_user().id,
    ))
    db.session.commit()

    flash(f"'{source_name}' added — {chunk_count} sections are now searchable.", "success")
    return redirect(url_for("admin.knowledge_list"))


@admin_bp.route("/knowledge/upload/cancel", methods=["POST"])
@role_required(Role.ADMIN.value)
def knowledge_upload_cancel():
    """Discards a pending staged upload without touching Chroma or the DB."""
    pending_filename = request.form.get("pending_filename", "")
    pending_path = PENDING_DIR / pending_filename
    pending_path.unlink(missing_ok=True)
    flash("Upload discarded.", "success")
    return redirect(url_for("admin.knowledge_upload_form"))


@admin_bp.route("/knowledge/<int:doc_id>/edit-role", methods=["POST"])
@role_required(Role.ADMIN.value)
def knowledge_edit_role(doc_id):
    """
    METADATA-ONLY correction: updates audience_role on the
    UploadedDocument row AND every one of this source's chunks in
    Chroma. Never touches the file's content, chunking, or anything
    else about it -- see module docstring for why a bigger mistake
    (wrong file, wrong split_mode) is handled via delete + re-upload
    instead of being folded into this same action.
    """
    document = UploadedDocument.query.get_or_404(doc_id)
    new_role = request.form.get("audience_role", "")

    if new_role not in ("engineer", "admin", "all"):
        flash("Choose a valid 'Visible to' value.", "error")
        return redirect(url_for("admin.knowledge_list"))

    updated_count = update_audience_role(document.source_name, new_role)
    document.audience_role = new_role
    db.session.commit()

    flash(f"'{document.source_name}' is now visible to: {new_role} ({updated_count} sections updated).", "success")
    return redirect(url_for("admin.knowledge_list"))


@admin_bp.route("/knowledge/<int:doc_id>/delete", methods=["POST"])
@role_required(Role.ADMIN.value)
def knowledge_delete(doc_id):
    """
    Irreversible: removes this source's chunks from Chroma, deletes its
    raw .md file from disk, and deletes the UploadedDocument row.
    Client-side confirmed via the shared admin-modal.js pattern (see
    templates/admin/knowledge_list.html) -- same as every other
    destructive action in this app.
    """
    document = UploadedDocument.query.get_or_404(doc_id)

    deleted_count = delete_source(document.source_name)
    Path(document.file_path).unlink(missing_ok=True)

    source_name = document.source_name
    db.session.delete(document)
    db.session.commit()

    flash(f"Deleted '{source_name}' — {deleted_count} sections removed from the knowledge base.", "success")
    return redirect(url_for("admin.knowledge_list"))