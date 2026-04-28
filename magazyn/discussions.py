"""
Moduł obsługujący dyskusje i wiadomości Allegro.
Wydzielony z app.py dla lepszej czytelności.
"""
from flask import (
    Blueprint,
    make_response,
    render_template,
    request,
    session,
)

from .auth import login_required
from .services.discussion_attachments import (
    download_discussion_attachment,
    upload_discussion_attachment,
)
from .services.discussion_messages import (
    get_thread_messages_payload,
    send_thread_message_payload,
)
from .services.discussion_threads import (
    build_discussions_context,
    create_local_thread,
    mark_thread_as_read,
)

bp = Blueprint("discussions", __name__)


# =============================================================================
# Routes
# =============================================================================

@bp.route("/discussions")
@login_required
def discussions_list():
    """Display list of all discussions from Allegro."""
    context = build_discussions_context(session.get("username"))
    return render_template("discussions.html", **context)


@bp.route("/discussions/<string:thread_id>/read", methods=["POST"])
@login_required
def mark_as_read(thread_id):
    """Mark thread as read."""
    payload, status_code = mark_thread_as_read(thread_id)
    return payload, status_code


@bp.route("/discussions/<thread_id>")
@login_required
def get_messages(thread_id):
    """
    Pobierz wiadomości dla danego wątku.
    
    DWA TYPY API:
    1. Messaging API (/messaging/threads) - zwykłe wiadomości
    2. Issues API (/sale/issues) - dyskusje (DISPUTE) i reklamacje (CLAIM)
    """
    payload, status_code = get_thread_messages_payload(
        thread_id,
        source=request.args.get("source", "messaging"),
    )
    return payload, status_code


@bp.route("/discussions/create", methods=["POST"])
@login_required
def create_thread():
    """Create a new local discussion thread."""
    payload, status_code = create_local_thread(
        request.get_json(silent=True) or {},
        session["username"],
    )
    return payload, status_code


@bp.route("/discussions/<string:thread_id>/send", methods=["POST"])
@login_required
def send_message(thread_id):
    """
    Wysyła wiadomość do wątku Allegro.
    """
    payload, status_code = send_thread_message_payload(
        thread_id,
        request.get_json(silent=True) or {},
        username=session.get("username", "Ty"),
    )
    return payload, status_code


@bp.route("/discussions/attachments/upload", methods=["POST"])
@login_required
def upload_attachment():
    """
    Przesyła załącznik do Allegro.
    """
    payload, status_code = upload_discussion_attachment(
        request.files.get("file"),
        source=request.form.get("source", "messaging"),
    )
    return payload, status_code


@bp.route("/discussions/attachments/<attachment_id>")
@login_required
def download_attachment(attachment_id):
    """
    Pobiera załącznik z Allegro.
    """
    payload, status_code = download_discussion_attachment(
        attachment_id,
        source=request.args.get("source", "messaging"),
    )
    if status_code != 200:
        return payload, status_code

    response = make_response(payload)
    response.headers["Content-Type"] = "application/octet-stream"
    response.headers["Content-Disposition"] = f'attachment; filename="{attachment_id}"'
    return response
