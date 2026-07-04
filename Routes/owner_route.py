from models import *
from flask import Blueprint, request, jsonify, current_app
from Routes.base_route import token_required, roles_required
from datetime import datetime, timezone
from threading import Thread
from communication.email_sender import send_query_resolution_email, send_notification_email, send_plain_email

owner_bp = Blueprint("owner", __name__)

# --------------- Course Picture Upload Helper ---------------
import os
import uuid
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "uploads/course_pictures"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def save_course_picture(file):
    if not file or file.filename == "":
        return None

    if not allowed_file(file.filename):
        raise ValueError("Invalid file type")

    filename = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_name)

    file.save(filepath)
    return unique_name


def _build_notification_recipients(scope, user_id=None, user_ids=None):
    query = User.query.filter(User.active.is_(True))

    if scope == "single" and user_id:
        query = query.filter(User.id == user_id)
    elif scope == "multiple" and user_ids:
        query = query.filter(User.id.in_(user_ids))

    recipients = []
    seen_emails = set()

    for user in query.with_entities(User.email, User.first_name, User.last_name).all():
        email = (user.email or "").strip()
        if not email or email in seen_emails:
            continue

        seen_emails.add(email)
        full_name = " ".join(
            [part for part in [user.first_name, user.last_name] if part]
        ).strip()
        recipients.append({
            "email": email,
            "name": full_name or "Student"
        })

    return recipients


def _send_notification_emails_async(app, scope, title, message, notif_type="info", user_id=None, user_ids=None):
    try:
        with app.app_context():
            recipients = _build_notification_recipients(scope, user_id=user_id, user_ids=user_ids)

            if not recipients:
                app.logger.info(
                    "No recipients found for notification email dispatch (scope=%s, title=%s)",
                    scope,
                    title,
                )
                return

            for recipient in recipients:
                try:
                    send_notification_email(
                        to_email=recipient["email"],
                        recipient_name=recipient["name"],
                        title=title,
                        message=message,
                        notification_type=notif_type,
                    )
                except Exception as email_error:
                    app.logger.warning(
                        "Notification email failed for %s: %s",
                        recipient["email"],
                        email_error,
                    )
    except Exception as error:
        app.logger.warning("Notification email dispatch failed: %s", error)
    finally:
        with app.app_context():
            db.session.remove()


def _queue_notification_email_dispatch(scope, title, message, notif_type="info", user_id=None, user_ids=None):
    app = current_app._get_current_object()
    worker = Thread(
        target=_send_notification_emails_async,
        args=(app, scope, title, message, notif_type, user_id, user_ids),
        daemon=True,
    )
    worker.start()


def _serialize_subscriber(subscriber):
    return {
        "id": subscriber.id,
        "email": subscriber.email,
        "name": subscriber.name,
        "message": subscriber.message,
        "subscribed_at": subscriber.subscribed_at.isoformat() if subscriber.subscribed_at else None,
    }


def _serialize_management_user(user):
    full_name = " ".join(
        [part for part in [user.first_name, user.last_name] if part]
    ).strip()

    return {
        "id": user.id,
        "user_id": user.user_id,
        "full_name": full_name,
        "email": user.email,
        "mobile_no": user.mobile_no,
        "active": bool(user.active),
        "roles": [role.name for role in user.roles],
        "joining_date": user.joining_date.isoformat() if user.joining_date else None,
    }


def _dedupe_recipients(recipients):
    deduped = []
    seen_emails = set()

    for recipient in recipients:
        email = (recipient.get("email") or "").strip().lower()
        if not email or email in seen_emails:
            continue

        seen_emails.add(email)
        deduped.append({
            "email": email,
            "name": (recipient.get("name") or "Student").strip() or "Student",
        })

    return deduped


def _build_management_email_recipients(audience, user_ids=None):
    user_ids = user_ids or []
    recipients = []

    if audience in {"subscribers", "everyone"}:
        for subscriber in Subscriber.query.order_by(Subscriber.subscribed_at.desc()).all():
            recipients.append({
                "email": subscriber.email,
                "name": subscriber.name or "Subscriber",
            })

    if audience in {"all_users", "everyone"}:
        users = User.query.filter(User.active.is_(True), User.email.isnot(None)).all()
        for user in users:
            full_name = " ".join(
                [part for part in [user.first_name, user.last_name] if part]
            ).strip()
            recipients.append({
                "email": user.email,
                "name": full_name or "Student",
            })

    if audience == "specific_users":
        users = User.query.filter(
            User.active.is_(True),
            User.email.isnot(None),
            User.id.in_(user_ids),
        ).all()
        for user in users:
            full_name = " ".join(
                [part for part in [user.first_name, user.last_name] if part]
            ).strip()
            recipients.append({
                "email": user.email,
                "name": full_name or "Student",
            })

    return _dedupe_recipients(recipients)


def _send_management_email_async(app, audience, subject, body, user_ids=None):
    try:
        with app.app_context():
            recipients = _build_management_email_recipients(audience, user_ids=user_ids)

            for recipient in recipients:
                try:
                    personalized_body = body.replace("{{name}}", recipient["name"])
                    send_plain_email(recipient["email"], subject, personalized_body)
                except Exception as email_error:
                    app.logger.warning(
                        "Management email failed for %s: %s",
                        recipient["email"],
                        email_error,
                    )
    except Exception as error:
        app.logger.warning("Management email dispatch failed: %s", error)
    finally:
        with app.app_context():
            db.session.remove()

#  ---------------------------------------------------------------

# ----------- Notification Management for Owners -----------
# api to create a global notification
def create_global_notification(title, message, type="info"):
    notification = Notification(
        title=title,
        message=message,
        is_global=True,
        type=type
    )
    db.session.add(notification)
    db.session.commit()

@owner_bp.route("/api/create_global_notification", methods=["POST"])
@token_required
@roles_required("admin")
def create_global_notification_route(current_user):
    data = request.get_json() or {}

    title = data.get("title")
    message = data.get("message")
    type = data.get("type", "info")

    if not title or not message:
        return jsonify({"error": "Title and message are required"}), 400

    create_global_notification(title, message, type)
    _queue_notification_email_dispatch("global", title, message, type)

    return jsonify({
        "success": True,
        "message": "Global notification created"
    }), 201

# api to create a notification for a specific user
def create_user_notification(user_id, title, message, type="info"):
    notification = Notification(
        title=title,
        message=message,
        is_global=False,
        type=type
    )
    db.session.add(notification)
    db.session.flush()

    user_notification = UserNotification(
        user_id=user_id,
        notification_id=notification.id
    )

    db.session.add(user_notification)
    db.session.commit()

@owner_bp.route("/api/create_user_notification", methods=["POST"])
@token_required
@roles_required("admin")
def create_user_notification_route(current_user):
    data = request.get_json() or {}

    user_id = data.get("user_id")
    title = data.get("title")
    message = data.get("message")
    type = data.get("type", "info")

    if not user_id or not title or not message:
        return jsonify({"error": "user_id, title, message required"}), 400

    create_user_notification(user_id, title, message, type)
    _queue_notification_email_dispatch("single", title, message, type, user_id=user_id)

    return jsonify({
        "success": True,
        "message": "User notification created"
    }), 201


# api to create notifications for multiple users
def create_multi_user_notification(user_ids, title, message):
    notification = Notification(
        title=title,
        message=message,
        is_global=False
    )
    db.session.add(notification)
    db.session.flush()

    mappings = [
        UserNotification(
            user_id=uid,
            notification_id=notification.id
        )
        for uid in user_ids
    ]

    db.session.bulk_save_objects(mappings)
    db.session.commit()


@owner_bp.route("/api/create_multi_user_notification", methods=["POST"])
@token_required
@roles_required("admin")
def create_multi_user_notification_route(current_user):
    data = request.get_json() or {}

    user_ids = data.get("user_ids")
    title = data.get("title")
    message = data.get("message")

    if not user_ids or not isinstance(user_ids, list):
        return jsonify({"error": "user_ids must be a list"}), 400

    if not title or not message:
        return jsonify({"error": "title and message required"}), 400

    create_multi_user_notification(user_ids, title, message)
    _queue_notification_email_dispatch("multiple", title, message, "info", user_ids=user_ids)

    return jsonify({
        "success": True,
        "message": "Multi-user notification created"
    }), 201


@owner_bp.route("/api/admin/queries", methods=["GET"])
@token_required
@roles_required("admin")
def admin_get_queries(current_user):
    """Admin query inbox with filtering and pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '', type=str).strip()
    status = request.args.get('status', '', type=str).strip().lower()
    issue_type = request.args.get('issue_type', '', type=str).strip().lower()

    query = QueryModel.query

    if search:
        query = query.filter(
            db.or_(
                QueryModel.person_name.ilike(f'%{search}%'),
                QueryModel.email.ilike(f'%{search}%'),
                QueryModel.query_text.ilike(f'%{search}%')
            )
        )

    if status:
        query = query.filter(QueryModel.status.ilike(status))

    if issue_type:
        query = query.filter(QueryModel.issue_type.ilike(issue_type))

    paginated = query.order_by(
        QueryModel.raised_at.desc().nullslast(),
        QueryModel.created_at.desc().nullslast(),
        QueryModel.id.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    queries = []
    for row in paginated.items:
        queries.append({
            "id": row.id,
            "person_name": row.person_name,
            "email": row.email,
            "issue_type": row.issue_type,
            "query_text": row.query_text,
            "raised_at": row.raised_at.isoformat() if row.raised_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "status": row.status,
            "is_resolved": bool(row.is_resolved),
            "response_text": row.response_text,
            "response_at": row.response_at.isoformat() if row.response_at else None,
            "responded_by": row.responded_by
        })

    total_queries = QueryModel.query.count()
    open_queries = QueryModel.query.filter(QueryModel.status.ilike('open')).count()
    in_progress_queries = QueryModel.query.filter(QueryModel.status.ilike('in_progress')).count()
    resolved_queries = QueryModel.query.filter(QueryModel.status.ilike('resolved')).count()

    return jsonify({
        "queries": queries,
        "pagination": {
            "total": paginated.total,
            "pages": paginated.pages,
            "current_page": page,
            "per_page": per_page,
            "has_next": paginated.has_next,
            "has_prev": paginated.has_prev
        },
        "summary": {
            "total_queries": total_queries,
            "open_queries": open_queries,
            "in_progress_queries": in_progress_queries,
            "resolved_queries": resolved_queries
        }
    }), 200


@owner_bp.route("/api/admin/queries/<int:query_id>/resolve", methods=["PUT"])
@token_required
@roles_required("admin")
def admin_resolve_query(current_user, query_id):
    """Resolve or update status of a support query."""
    row = QueryModel.query.get_or_404(query_id)
    data = request.get_json(silent=True) or {}

    response_text = (data.get('response_text') or '').strip()
    new_status = (data.get('status') or 'resolved').strip().lower()

    if not response_text:
        return jsonify({"error": "response_text is required"}), 400

    allowed_statuses = {'open', 'in_progress', 'resolved'}
    if new_status not in allowed_statuses:
        return jsonify({"error": "status must be one of open, in_progress, resolved"}), 400

    row.response_text = response_text
    row.status = new_status
    row.is_resolved = (new_status == 'resolved')
    row.response_at = datetime.now(timezone.utc)

    responder_name = ' '.join(
        [part for part in [getattr(current_user, 'first_name', ''), getattr(current_user, 'last_name', '')] if part]
    ).strip()
    row.responded_by = responder_name or current_user.email

    db.session.commit()

    try:
        send_query_resolution_email(
            to_email=row.email,
            person_name=row.person_name,
            query_status=row.status,
            response_text=row.response_text,
        )
    except Exception as err:
        current_app.logger.warning(f"Query resolution email failed for query_id={row.id}: {err}")

    return jsonify({
        "success": True,
        "message": "Query updated successfully",
        "query": {
            "id": row.id,
            "status": row.status,
            "is_resolved": bool(row.is_resolved),
            "response_text": row.response_text,
            "response_at": row.response_at.isoformat() if row.response_at else None,
            "responded_by": row.responded_by
        }
    }), 200


@owner_bp.route("/api/admin/notifications", methods=["GET"])
@token_required
@roles_required("admin")
def admin_list_notifications(current_user):
    """Get recent notifications for admin monitoring."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    notif_type = request.args.get('type', '', type=str).strip().lower()

    query = Notification.query
    if notif_type:
        query = query.filter(Notification.type.ilike(notif_type))

    paginated = query.order_by(Notification.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    notifications = []
    for n in paginated.items:
        recipient_count = UserNotification.query.filter_by(notification_id=n.id).count()
        notifications.append({
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "type": n.type,
            "is_global": bool(n.is_global),
            "recipient_count": recipient_count,
            "created_at": n.created_at.isoformat() if n.created_at else None
        })

    return jsonify({
        "notifications": notifications,
        "pagination": {
            "total": paginated.total,
            "pages": paginated.pages,
            "current_page": page,
            "per_page": per_page,
            "has_next": paginated.has_next,
            "has_prev": paginated.has_prev
        }
    }), 200


@owner_bp.route("/api/admin/notifications", methods=["POST"])
@token_required
@roles_required("admin")
def admin_create_notification(current_user):
    """Create notification: global, single-user, or multi-user."""
    data = request.get_json(silent=True) or {}

    scope = (data.get('scope') or 'global').strip().lower()
    title = (data.get('title') or '').strip()
    message = (data.get('message') or '').strip()
    notif_type = (data.get('type') or 'info').strip().lower()

    if not title or not message:
        return jsonify({"error": "title and message are required"}), 400

    if scope not in {'global', 'single', 'multiple'}:
        return jsonify({"error": "scope must be global, single, or multiple"}), 400

    notification = Notification(
        title=title,
        message=message,
        type=notif_type,
        is_global=(scope == 'global')
    )
    db.session.add(notification)
    db.session.flush()

    if scope == 'single':
        user_id = data.get('user_id')
        if not user_id:
            db.session.rollback()
            return jsonify({"error": "user_id is required for single scope"}), 400

        db.session.add(UserNotification(user_id=user_id, notification_id=notification.id))

    elif scope == 'multiple':
        user_ids = data.get('user_ids') or []
        if not isinstance(user_ids, list) or not user_ids:
            db.session.rollback()
            return jsonify({"error": "user_ids list is required for multiple scope"}), 400

        for uid in user_ids:
            db.session.add(UserNotification(user_id=uid, notification_id=notification.id))

    db.session.commit()

    if scope == 'global':
        _queue_notification_email_dispatch('global', title, message, notif_type)
    elif scope == 'single':
        _queue_notification_email_dispatch('single', title, message, notif_type, user_id=user_id)
    elif scope == 'multiple':
        _queue_notification_email_dispatch('multiple', title, message, notif_type, user_ids=user_ids)

    return jsonify({
        "success": True,
        "message": "Notification created successfully",
        "notification_id": notification.id
    }), 201


@owner_bp.route("/api/admin/subscribers", methods=["GET"])
@token_required
@roles_required("admin")
def admin_list_subscribers(current_user):
    """List newsletter subscribers for admin management."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    search = request.args.get("search", "", type=str).strip()

    query = Subscriber.query

    if search:
        query = query.filter(
            db.or_(
                Subscriber.email.ilike(f"%{search}%"),
                Subscriber.name.ilike(f"%{search}%"),
            )
        )

    paginated = query.order_by(
        Subscriber.subscribed_at.desc().nullslast(),
        Subscriber.id.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "subscribers": [_serialize_subscriber(item) for item in paginated.items],
        "pagination": {
            "total": paginated.total,
            "pages": paginated.pages,
            "current_page": page,
            "per_page": per_page,
            "has_next": paginated.has_next,
            "has_prev": paginated.has_prev,
        },
        "summary": {
            "total_subscribers": Subscriber.query.count(),
        }
    }), 200


@owner_bp.route("/api/admin/management/recipients", methods=["GET"])
@token_required
@roles_required("admin")
def admin_management_recipients(current_user):
    """Compact recipient data for the management email composer."""
    users = User.query.filter(User.active.is_(True)).order_by(User.joining_date.desc().nullslast()).all()
    subscribers = Subscriber.query.order_by(Subscriber.subscribed_at.desc().nullslast()).all()

    return jsonify({
        "users": [_serialize_management_user(user) for user in users],
        "subscribers": [_serialize_subscriber(subscriber) for subscriber in subscribers],
        "summary": {
            "total_users": len(users),
            "total_subscribers": len(subscribers),
            "total_active_user_emails": len([user for user in users if user.email]),
        }
    }), 200


@owner_bp.route("/api/admin/management/send-email", methods=["POST"])
@token_required
@roles_required("admin")
def admin_send_management_email(current_user):
    """Send plain emails to subscribers, users, selected users, or everyone."""
    data = request.get_json(silent=True) or {}

    audience = (data.get("audience") or "").strip().lower()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    user_ids = data.get("user_ids") or []

    allowed_audiences = {"subscribers", "all_users", "specific_users", "everyone"}
    if audience not in allowed_audiences:
        return jsonify({"error": "audience must be subscribers, all_users, specific_users, or everyone"}), 400

    if not subject or not body:
        return jsonify({"error": "subject and body are required"}), 400

    if audience == "specific_users":
        if not isinstance(user_ids, list) or not user_ids:
            return jsonify({"error": "user_ids list is required for specific_users audience"}), 400

        try:
            user_ids = [int(user_id) for user_id in user_ids]
        except (TypeError, ValueError):
            return jsonify({"error": "user_ids must contain valid user ids"}), 400

    recipients = _build_management_email_recipients(audience, user_ids=user_ids)
    if not recipients:
        return jsonify({"error": "No recipients found for this audience"}), 400

    app = current_app._get_current_object()
    worker = Thread(
        target=_send_management_email_async,
        args=(app, audience, subject, body, user_ids),
        daemon=True,
    )
    worker.start()

    return jsonify({
        "success": True,
        "message": "Email dispatch started",
        "recipient_count": len(recipients),
    }), 202


# api to create course
@owner_bp.route("/api/create_course", methods=["POST"])
@token_required
@roles_required("admin")
def create_course_route(current_user):

    data = request.get_json(silent=True) or request.form
    picture_file = request.files.get("picture")

    course_code = data.get("course_code")
    title = data.get("title")
    class_level = data.get("class_level", "")
    subject = data.get("subject", "")
    description = data.get("description", "")
    duration_months = data.get("duration_months", 0)
    fee = data.get("fee")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    is_active = data.get("is_active", "true").lower() == "true"

    if not course_code or not title or not fee:
        return jsonify({"error": "Course Code, Title, and Fee are required"}), 400

    if Course.query.filter_by(course_code=course_code).first():
        return jsonify({"error": "Course code already exists"}), 409

    picture_name = None
    if picture_file:
        try:
            picture_name = save_course_picture(picture_file)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    course = Course(
        course_code=course_code,
        title=title,
        class_level=class_level,
        subject=subject,
        description=description,
        duration_months=duration_months,
        fee=fee,
        start_date=start_date,
        end_date=end_date,
        is_active=is_active,
        picture=picture_name
    )

    db.session.add(course)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Course created successfully",
        "course_id": course.id
    }), 201

# api to edit course
@owner_bp.route("/api/edit_course/<int:course_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def edit_course_route(current_user, course_id):

    course = Course.query.get(course_id)
    if not course:
        return jsonify({"error": "Course not found"}), 404

    data = request.form
    picture_file = request.files.get("picture")

    course.course_code = data.get("course_code", course.course_code)
    course.title = data.get("title", course.title)
    course.class_level = data.get("class_level", course.class_level)
    course.subject = data.get("subject", course.subject)
    course.description = data.get("description", course.description)
    course.duration_months = data.get("duration_months", course.duration_months)
    course.fee = data.get("fee", course.fee)
    course.start_date = data.get("start_date", course.start_date)
    course.end_date = data.get("end_date", course.end_date)
    course.is_active = data.get("is_active", str(course.is_active)).lower() == "true"

    if picture_file:
        try:
            course.picture = save_course_picture(picture_file)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Course updated successfully"
    }), 200

# api to delete course
@owner_bp.route("/api/delete_course/<int:course_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_course_route(current_user, course_id):
    course = Course.query.get(course_id)
    if not course:
        return jsonify({"error": "Course not found"}), 404

    if course.picture:
        path = os.path.join(UPLOAD_FOLDER, course.picture)
        if os.path.exists(path):
            os.remove(path)

    db.session.delete(course)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Course deleted successfully"
    }), 200


# api to get all courses
@owner_bp.route("/api/courses", methods=["GET"])
@token_required
@roles_required("admin")
def get_all_courses_route(current_user):
    courses = Course.query.all()
    result = []

    for course in courses:
        result.append({
            "id": course.id,
            "course_code": course.course_code,
            "title": course.title,
            "class_level": course.class_level,
            "subject": course.subject,
            "description": course.description,
            "duration_months": course.duration_months,
            "fee": str(course.fee),
            "start_date": course.start_date.isoformat() if course.start_date else None,
            "end_date": course.end_date.isoformat() if course.end_date else None,
            "is_active": course.is_active,
            "picture_url": f"/static/course_pictures/{course.picture}" if course.picture else None
        })

    return jsonify(result), 200

# admin get all subscribers
@owner_bp.route("/api/admin/subscribers", methods=["GET"])
@token_required
@roles_required("admin")
def admin_get_subscribers(current_user):
    subscribers = Subscriber.query.all()
    result = []

    for sub in subscribers:
        result.append({
            "id": sub.id,
            "email": sub.email,
            "name": sub.name,
            "message": sub.message,
            "subscribed_at": sub.subscribed_at.isoformat() if sub.subscribed_at else None
        })

    return jsonify(result), 200

# api to delete subscriber
@owner_bp.route("/api/admin/subscribers/<int:subscriber_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def admin_delete_subscriber(current_user, subscriber_id):
    subscriber = Subscriber.query.get(subscriber_id)
    if not subscriber:
        return jsonify({"error": "Subscriber not found"}), 404

    db.session.delete(subscriber)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Subscriber deleted successfully"
    }), 200
    
# api to edit subscriber
@owner_bp.route("/api/admin/subscribers/<int:subscriber_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def admin_edit_subscriber(current_user, subscriber_id):
    subscriber = Subscriber.query.get(subscriber_id)
    if not subscriber:
        return jsonify({"error": "Subscriber not found"}), 404

    data = request.get_json(silent=True) or {}

    subscriber.email = data.get("email", subscriber.email)
    subscriber.name = data.get("name", subscriber.name)
    subscriber.message = data.get("message", subscriber.message)

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Subscriber updated successfully"
    }), 200 
    
# api to send email to all subscribers or users or specific user
def _normalize_email_recipient(recipient):
    if isinstance(recipient, str):
        email = recipient.strip()
        if not email:
            return None
        return {"email": email, "name": email.split("@")[0] if "@" in email else "Recipient"}

    if isinstance(recipient, dict):
        email = (recipient.get("email") or recipient.get("to") or "").strip()
        if not email:
            return None

        name = (recipient.get("name") or recipient.get("full_name") or "").strip()
        return {"email": email, "name": name or email.split("@")[0] if "@" in email else "Recipient"}

    return None


def _resolve_email_recipients(data):
    recipient_type = (data.get("recipient_type") or "custom").strip().lower()
    user_id = data.get("user_id")
    subscriber_id = data.get("subscriber_id")

    if recipient_type in {"all_subscribers", "subscribers", "subscriber"}:
        recipients = Subscriber.query.with_entities(Subscriber.email, Subscriber.name).all()
        return [
            {"email": (email or "").strip(), "name": (name or "Subscriber").strip() or "Subscriber"}
            for email, name in recipients
            if (email or "").strip()
        ]

    if recipient_type in {"all_users", "users", "user"}:
        recipients = User.query.filter(User.active.is_(True)).with_entities(
            User.email,
            User.first_name,
            User.last_name,
        ).all()
        resolved = []
        seen_emails = set()

        for email, first_name, last_name in recipients:
            email = (email or "").strip()
            if not email or email in seen_emails:
                continue

            seen_emails.add(email)
            name = " ".join([part for part in [first_name, last_name] if part]).strip()
            resolved.append({"email": email, "name": name or "User"})

        return resolved

    if recipient_type in {"specific_user", "single_user", "user_id", "single"}:
        if user_id:
            user = User.query.get(user_id)
            if not user or not (user.email or "").strip():
                return []

            full_name = " ".join([part for part in [user.first_name, user.last_name] if part]).strip()
            return [{"email": user.email.strip(), "name": full_name or "User"}]

        specific_email = (data.get("recipient_email") or data.get("email") or "").strip()
        if specific_email:
            return [{"email": specific_email, "name": data.get("recipient_name") or "User"}]

        return []

    if recipient_type in {"specific_subscriber", "single_subscriber"}:
        if subscriber_id:
            subscriber = Subscriber.query.get(subscriber_id)
            if not subscriber or not (subscriber.email or "").strip():
                return []

            return [{"email": subscriber.email.strip(), "name": (subscriber.name or "Subscriber").strip() or "Subscriber"}]

        specific_email = (data.get("recipient_email") or data.get("email") or "").strip()
        if specific_email:
            return [{"email": specific_email, "name": data.get("recipient_name") or "Subscriber"}]

        return []

    raw_recipients = data.get("recipients") or []
    if not isinstance(raw_recipients, list):
        return []

    resolved = []
    seen_emails = set()
    for recipient in raw_recipients:
        normalized = _normalize_email_recipient(recipient)
        if not normalized:
            continue

        email = normalized["email"]
        if email in seen_emails:
            continue

        seen_emails.add(email)
        resolved.append(normalized)

    return resolved


def _send_bulk_email_async(app, recipients, subject, body):
    try:
        with app.app_context():
            for recipient in recipients:
                try:
                    send_plain_email(recipient["email"], subject, body)
                except Exception as email_error:
                    app.logger.warning(
                        "Admin email failed for %s: %s",
                        recipient["email"],
                        email_error,
                    )
    except Exception as error:
        app.logger.warning("Admin email dispatch failed: %s", error)
    finally:
        with app.app_context():
            db.session.remove()


def _queue_admin_email_dispatch(recipients, subject, body):
    app = current_app._get_current_object()
    worker = Thread(
        target=_send_bulk_email_async,
        args=(app, recipients, subject, body),
        daemon=True,
    )
    worker.start()


# api to send email to all subscribers or users or specific user
@owner_bp.route("/api/admin/send_email", methods=["POST"])
@token_required
@roles_required("admin")
def admin_send_email(current_user):
    data = request.get_json(silent=True) or {}

    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    recipients = _resolve_email_recipients(data)

    if not recipients or not subject or not body:
        return jsonify({"error": "Invalid request data"}), 400

    _queue_admin_email_dispatch(recipients, subject, body)

    return jsonify({
        "success": True,
        "message": "Email queued successfully",
        "recipient_count": len(recipients)
    }), 200
