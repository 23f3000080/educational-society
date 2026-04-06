from models import *
from flask import Blueprint, request, jsonify, current_app
from Routes.base_route import token_required, roles_required
from datetime import datetime, timezone
from communication.email_sender import send_query_resolution_email

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

    return jsonify({
        "success": True,
        "message": "Notification created successfully",
        "notification_id": notification.id
    }), 201


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