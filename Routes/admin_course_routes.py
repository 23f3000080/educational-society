# admin_course_routes.py

from flask import Blueprint, request, jsonify, current_app
from flask_cors import cross_origin
from datetime import datetime, timezone
from models import *
from Routes.base_route import token_required, roles_required
from flask_security.utils import hash_password
import uuid
import random
import string
from zoneinfo import ZoneInfo
from communication.email_sender import send_assignment_added_email, send_week_added_email

admin_course_bp = Blueprint('admin_course', __name__)
IST = ZoneInfo("Asia/Kolkata")


def _to_ist_iso(dt_value):
    if not dt_value:
        return None

    # Legacy rows may be naive in DB; treat them as UTC before converting to IST.
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)

    return dt_value.astimezone(IST).isoformat()


def _generate_unique_user_id(prefix):
    """Generate unique 8-char IDs like ST1234AB or AD98XY76."""
    safe_prefix = (prefix or 'ST')[:2].upper()
    alphabet = string.ascii_uppercase + string.digits

    while True:
        candidate = safe_prefix + ''.join(random.choices(alphabet, k=6))
        if not User.query.filter_by(user_id=candidate).first():
            return candidate


def _get_active_paid_students_for_course(course_id):
    return (
        db.session.query(User)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(
            Enrollment.course_id == course_id,
            Enrollment.payment_status == 'paid',
            Enrollment.enrollment_status == 'active',
            User.email.isnot(None),
        )
        .all()
    )


@admin_course_bp.route("/api/admin/users", methods=["POST"])
@token_required
@roles_required("admin")
def create_admin_user(current_user):
    """Allow admins to create student/admin accounts from users panel."""
    data = request.get_json(silent=True) or {}

    full_name = (data.get('full_name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()
    role_name = (data.get('role') or 'user').strip().lower()
    mobile_no = (data.get('mobile_no') or '').strip()

    if not full_name or not email or not password or not confirm_password:
        return jsonify({"error": "full_name, email, password and confirm_password are required"}), 400

    if role_name not in ('user', 'admin'):
        return jsonify({"error": "role must be either 'user' or 'admin'"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400

    if password != confirm_password:
        return jsonify({"error": "Password and confirm password do not match"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email is already registered"}), 400

    if mobile_no and User.query.filter_by(mobile_no=mobile_no).first():
        return jsonify({"error": "Mobile number is already used by another user"}), 400

    name_parts = full_name.split()
    first_name = name_parts[0]
    last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''

    role = Role.query.filter_by(name=role_name).first()
    if not role:
        return jsonify({"error": f"Role '{role_name}' is not configured"}), 400

    user_id = _generate_unique_user_id('AD' if role_name == 'admin' else 'ST')

    new_user = User(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=hash_password(password),
        fs_uniquifier=str(uuid.uuid4()),
        mobile_no=mobile_no or None,
        is_email_verified=False,
        is_mobile_verified=False,
        country='India',
        joining_date=datetime.now(timezone.utc),
        active=True
    )
    new_user.roles.append(role)

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "message": f"{role_name.title()} account created successfully",
        "user": {
            "id": new_user.id,
            "user_id": new_user.user_id,
            "full_name": ' '.join([part for part in [new_user.first_name, new_user.last_name] if part]).strip(),
            "email": new_user.email,
            "mobile_no": new_user.mobile_no,
            "roles": [r.name for r in new_user.roles],
            "joining_date": _to_ist_iso(new_user.joining_date)
        }
    }), 201


@admin_course_bp.route("/api/admin/users", methods=["GET"])
@token_required
@roles_required("admin")
def get_all_users(current_user):
    """Get all users for admin panel with filters and pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '', type=str).strip()
    role_filter = request.args.get('role', '', type=str).strip().lower()
    email_verified = request.args.get('email_verified', '', type=str).strip().lower()
    mobile_verified = request.args.get('mobile_verified', '', type=str).strip().lower()

    query = User.query

    if search:
        query = query.filter(
            db.or_(
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
                User.user_id.ilike(f'%{search}%'),
                User.mobile_no.ilike(f'%{search}%')
            )
        )

    if role_filter:
        query = query.join(User.roles).filter(Role.name == role_filter)

    if email_verified in ('true', 'false'):
        query = query.filter(User.is_email_verified.is_(email_verified == 'true'))

    if mobile_verified in ('true', 'false'):
        query = query.filter(User.is_mobile_verified.is_(mobile_verified == 'true'))

    paginated = query.order_by(User.joining_date.desc().nullslast(), User.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    users = []
    for user in paginated.items:
        full_name = ' '.join([part for part in [user.first_name, user.last_name] if part]).strip()
        role_names = [role.name for role in user.roles]

        users.append({
            "id": user.id,
            "user_id": user.user_id,
            "full_name": full_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "mobile_no": user.mobile_no,
            "alternate_mobile_no": user.alternate_mobile_no,
            "gender": user.gender,
            "dob": user.dob.isoformat() if user.dob else None,
            "country": user.country,
            "state": user.state,
            "city": user.city,
            "location": user.location,
            "pincode": user.pincode,
            "parent_name": user.parent_name,
            "parent_relation": user.parent_relation,
            "mode_of_communication": user.mode_of_communication,
            "is_email_verified": bool(user.is_email_verified),
            "is_mobile_verified": bool(user.is_mobile_verified),
            "active": bool(user.active),
            "roles": role_names,
            "profile_picture": user.profile_picture,
            "joining_date": _to_ist_iso(user.joining_date),
            "enrollments_count": len(user.enrollments),
            "active_enrollments_count": len([e for e in user.enrollments if e.enrollment_status == 'active'])
        })

    total_users = User.query.count()
    total_admins = User.query.join(User.roles).filter(Role.name == 'admin').count()
    total_students = User.query.join(User.roles).filter(Role.name == 'user').count()
    verified_emails = User.query.filter(User.is_email_verified.is_(True)).count()
    verified_mobiles = User.query.filter(User.is_mobile_verified.is_(True)).count()

    return jsonify({
        "users": users,
        "pagination": {
            "total": paginated.total,
            "pages": paginated.pages,
            "current_page": page,
            "per_page": per_page,
            "has_next": paginated.has_next,
            "has_prev": paginated.has_prev
        },
        "summary": {
            "total_users": total_users,
            "total_admins": total_admins,
            "total_students": total_students,
            "verified_emails": verified_emails,
            "verified_mobiles": verified_mobiles
        }
    }), 200


@admin_course_bp.route("/api/admin/users/<int:user_id>/insights", methods=["GET"])
@token_required
@roles_required("admin")
def get_user_insights(current_user, user_id):
    """Get deep user study insights for admin monitoring."""
    user = User.query.get_or_404(user_id)

    enrollments = Enrollment.query.filter_by(student_id=user_id).all()
    enrollment_course_ids = [en.course_id for en in enrollments]

    total_enrollments = len(enrollments)
    active_enrollments = len([en for en in enrollments if en.enrollment_status == 'active'])

    total_assignments = 0
    submitted_assignments = 0
    total_content_items = 0
    completed_content_items = 0

    course_breakdown = []

    for enrollment in enrollments:
        course = enrollment.course
        if not course:
            continue

        videos_count = db.session.query(db.func.count(Video.id))\
            .join(Week, Week.id == Video.week_id)\
            .filter(Week.course_id == course.id)\
            .scalar() or 0

        notes_count = db.session.query(db.func.count(Note.id))\
            .join(Week, Week.id == Note.week_id)\
            .filter(Week.course_id == course.id)\
            .scalar() or 0

        assignments_count = Assignment.query.filter_by(course_id=course.id).count()

        completed_items = CourseProgress.query.filter_by(
            student_id=user_id,
            course_id=course.id,
            completed=True
        ).count()

        submitted_for_course = db.session.query(db.func.count(db.distinct(AssignmentSubmission.assignment_id)))\
            .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)\
            .filter(
                AssignmentSubmission.student_id == user_id,
                Assignment.course_id == course.id
            )\
            .scalar() or 0

        total_items = videos_count + notes_count + assignments_count
        progress_percent = round((completed_items / total_items) * 100, 2) if total_items else 0

        total_assignments += assignments_count
        submitted_assignments += submitted_for_course
        total_content_items += total_items
        completed_content_items += completed_items

        last_submission = db.session.query(AssignmentSubmission)\
            .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)\
            .filter(
                AssignmentSubmission.student_id == user_id,
                Assignment.course_id == course.id
            )\
            .order_by(AssignmentSubmission.submitted_at.desc())\
            .first()

        course_breakdown.append({
            "course_id": course.id,
            "course_title": course.title,
            "course_code": course.course_code,
            "enrollment_status": enrollment.enrollment_status,
            "payment_status": enrollment.payment_status,
            "enrollment_date": _to_ist_iso(enrollment.enrollment_date),
            "videos_count": videos_count,
            "notes_count": notes_count,
            "assignments_count": assignments_count,
            "submitted_assignments_count": submitted_for_course,
            "pending_assignments_count": max(assignments_count - submitted_for_course, 0),
            "total_items": total_items,
            "completed_items": completed_items,
            "progress_percent": progress_percent,
            "last_submission_at": _to_ist_iso(last_submission.submitted_at if last_submission else None)
        })

    content_track_rows = db.session.query(
        CourseProgress.content_type,
        db.func.count(CourseProgress.id)
    ).filter(
        CourseProgress.student_id == user_id,
        CourseProgress.completed.is_(True)
    ).group_by(CourseProgress.content_type).all()

    content_track = {
        (row[0] or 'other'): row[1]
        for row in content_track_rows
    }

    recent_submissions_query = db.session.query(
        AssignmentSubmission,
        Assignment.title,
        Course.title
    ).join(
        Assignment, Assignment.id == AssignmentSubmission.assignment_id
    ).join(
        Course, Course.id == Assignment.course_id
    ).filter(
        AssignmentSubmission.student_id == user_id
    ).order_by(
        AssignmentSubmission.submitted_at.desc()
    ).limit(15).all()

    recent_submissions = []
    for submission, assignment_title, course_title in recent_submissions_query:
        recent_submissions.append({
            "submission_id": submission.id,
            "assignment_id": submission.assignment_id,
            "assignment_title": assignment_title,
            "course_title": course_title,
            "submitted_at": _to_ist_iso(submission.submitted_at)
        })

    overall_progress = round((completed_content_items / total_content_items) * 100, 2) if total_content_items else 0

    return jsonify({
        "user": {
            "id": user.id,
            "user_id": user.user_id,
            "full_name": ' '.join([part for part in [user.first_name, user.last_name] if part]).strip(),
            "email": user.email,
            "mobile_no": user.mobile_no,
            "active": bool(user.active),
            "is_email_verified": bool(user.is_email_verified),
            "is_mobile_verified": bool(user.is_mobile_verified),
            "joining_date": _to_ist_iso(user.joining_date),
            "roles": [role.name for role in user.roles]
        },
        "summary": {
            "total_enrollments": total_enrollments,
            "active_enrollments": active_enrollments,
            "total_assignments": total_assignments,
            "submitted_assignments": submitted_assignments,
            "pending_assignments": max(total_assignments - submitted_assignments, 0),
            "total_content_items": total_content_items,
            "completed_content_items": completed_content_items,
            "overall_progress_percent": overall_progress
        },
        "study_track": content_track,
        "courses": course_breakdown,
        "recent_submissions": recent_submissions
    }), 200


@admin_course_bp.route("/api/admin/users/<int:user_id>/status", methods=["PUT"])
@token_required
@roles_required("admin")
def update_user_status(current_user, user_id):
    """Allow admin to activate/deactivate a user account."""
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    if "active" not in data:
        return jsonify({"error": "'active' boolean field is required"}), 400

    target_active = bool(data.get("active"))

    if current_user.id == user.id and not target_active:
        return jsonify({"error": "You cannot deactivate your own account"}), 400

    user.active = target_active
    db.session.commit()

    return jsonify({
        "message": "User activated successfully" if target_active else "User made inactive successfully",
        "user": {
            "id": user.id,
            "active": bool(user.active)
        }
    }), 200


@admin_course_bp.route("/api/admin/users/<int:user_id>/verification", methods=["PUT"])
@token_required
@roles_required("admin")
def update_user_verification(current_user, user_id):
    """Allow admin to verify user email/mobile status from insights panel."""
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    if "is_email_verified" not in data and "is_mobile_verified" not in data:
        return jsonify({"error": "Provide at least one of is_email_verified or is_mobile_verified"}), 400

    def _parse_bool(value, field_name):
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("true", "1"):
                return True, None
            if normalized in ("false", "0"):
                return False, None
        return None, f"{field_name} must be a boolean"

    if "is_email_verified" in data:
        parsed_email, email_error = _parse_bool(data.get("is_email_verified"), "is_email_verified")
        if email_error:
            return jsonify({"error": email_error}), 400
        user.is_email_verified = parsed_email

    if "is_mobile_verified" in data:
        parsed_mobile, mobile_error = _parse_bool(data.get("is_mobile_verified"), "is_mobile_verified")
        if mobile_error:
            return jsonify({"error": mobile_error}), 400
        user.is_mobile_verified = parsed_mobile

    db.session.commit()

    return jsonify({
        "message": "Verification status updated successfully",
        "user": {
            "id": user.id,
            "is_email_verified": bool(user.is_email_verified),
            "is_mobile_verified": bool(user.is_mobile_verified)
        }
    }), 200

# ==================== COURSE MANAGEMENT ====================

@admin_course_bp.route("/api/admin/courses", methods=["GET"])
@token_required
@roles_required("admin")
def get_all_courses(current_user):
    """Get all courses with pagination and search"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '', type=str)
    is_active = request.args.get('is_active', None, type=str)
    
    query = Course.query
    
    if search:
        query = query.filter(
            db.or_(
                Course.title.ilike(f'%{search}%'),
                Course.course_code.ilike(f'%{search}%'),
                Course.subject.ilike(f'%{search}%')
            )
        )

    if is_active is not None:
        status = is_active.lower()
        if status in ('true', '1'):
            query = query.filter(Course.is_active.is_(True))
        elif status in ('false', '0'):
            query = query.filter(Course.is_active.is_(False))
    
    paginated = query.order_by(Course.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    courses = []
    for course in paginated.items:
        courses.append({
            "id": course.id,
            "course_code": course.course_code,
            "title": course.title,
            "class_level": course.class_level,
            "subject": course.subject,
            "description": course.description,
            "duration_months": course.duration_months,
            "fee": float(course.fee) if course.fee else 0,
            "start_date": course.start_date.isoformat() if course.start_date else None,
            "end_date": course.end_date.isoformat() if course.end_date else None,
            "picture": course.picture,
            "is_active": course.is_active,
            "weeks_count": len(course.weeks),
            "created_at": course.created_at.isoformat() if course.created_at else None
        })
    
    return jsonify({
        "courses": courses,
        "total": paginated.total,
        "pages": paginated.pages,
        "current_page": page
    }), 200

@admin_course_bp.route("/api/admin/courses", methods=["POST"])
@token_required
@roles_required("admin")
def create_course(current_user):
    """Create a new course"""
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['title', 'course_code', 'class_level', 'subject']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400
    
    # Check if course code already exists
    existing = Course.query.filter_by(course_code=data['course_code']).first()
    if existing:
        return jsonify({"error": "Course code already exists"}), 400
    
    course = Course(
        course_code=data['course_code'],
        title=data['title'],
        class_level=data['class_level'],
        subject=data['subject'],
        description=data.get('description', ''),
        duration_months=data.get('duration_months'),
        fee=data.get('fee'),
        start_date=datetime.fromisoformat(data['start_date']) if data.get('start_date') else None,
        end_date=datetime.fromisoformat(data['end_date']) if data.get('end_date') else None,
        picture=data.get('picture'),
        is_active=data.get('is_active', True)
    )
    
    db.session.add(course)
    db.session.commit()
    
    return jsonify({
        "message": "Course created successfully",
        "course": {
            "id": course.id,
            "title": course.title,
            "course_code": course.course_code
        }
    }), 201

@admin_course_bp.route("/api/admin/courses/<int:course_id>", methods=["GET"])
@token_required
@roles_required("admin")
def get_course(current_user, course_id):
    """Get a single course with all details"""
    course = Course.query.get_or_404(course_id)
    
    # Get weeks with their content
    weeks = []
    for week in course.weeks:
        weeks.append({
            "id": week.id,
            "week_number": week.week_number,
            "title": week.title,
            "videos_count": len(week.videos),
            "assignments_count": len(week.assignments),
            "notes_count": len(week.notes),
            "created_at": week.created_at.isoformat() if week.created_at else None
        })
    
    return jsonify({
        "id": course.id,
        "course_code": course.course_code,
        "title": course.title,
        "class_level": course.class_level,
        "subject": course.subject,
        "description": course.description,
        "duration_months": course.duration_months,
        "fee": float(course.fee) if course.fee else 0,
        "start_date": course.start_date.isoformat() if course.start_date else None,
        "end_date": course.end_date.isoformat() if course.end_date else None,
        "picture": course.picture,
        "is_active": course.is_active,
        "weeks": weeks,
        "created_at": course.created_at.isoformat() if course.created_at else None
    }), 200

@admin_course_bp.route("/api/admin/courses/<int:course_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def update_course(current_user, course_id):
    """Update a course"""
    course = Course.query.get_or_404(course_id)
    data = request.get_json()
    
    # Check if course code is being changed and if it already exists
    if data.get('course_code') and data['course_code'] != course.course_code:
        existing = Course.query.filter_by(course_code=data['course_code']).first()
        if existing:
            return jsonify({"error": "Course code already exists"}), 400
    
    # Update fields
    course.course_code = data.get('course_code', course.course_code)
    course.title = data.get('title', course.title)
    course.class_level = data.get('class_level', course.class_level)
    course.subject = data.get('subject', course.subject)
    course.description = data.get('description', course.description)
    course.duration_months = data.get('duration_months', course.duration_months)
    course.fee = data.get('fee', course.fee)
    course.start_date = datetime.fromisoformat(data['start_date']) if data.get('start_date') else course.start_date
    course.end_date = datetime.fromisoformat(data['end_date']) if data.get('end_date') else course.end_date
    course.picture = data.get('picture', course.picture)
    course.is_active = data.get('is_active', course.is_active)
    
    db.session.commit()
    
    return jsonify({"message": "Course updated successfully"}), 200

@admin_course_bp.route("/api/admin/courses/<int:course_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_course(current_user, course_id):
    """Delete a course"""
    course = Course.query.get_or_404(course_id)
    
    # Check if course has any enrollments
    if course.enrollments and len(course.enrollments) > 0:
        return jsonify({"error": "Cannot delete course with enrolled students"}), 400
    
    db.session.delete(course)
    db.session.commit()
    
    return jsonify({"message": "Course deleted successfully"}), 200


# ==================== WEEK MANAGEMENT ====================

@admin_course_bp.route("/api/admin/courses/<int:course_id>/weeks", methods=["GET"])
@token_required
@roles_required("admin")
def get_course_weeks(current_user, course_id):
    """Get all weeks for a course with full details"""
    course = Course.query.get_or_404(course_id)
    
    weeks = []
    for week in course.weeks:
        week_data = {
            "id": week.id,
            "week_number": week.week_number,
            "title": week.title,
            "description": week.description,
            "videos": [],
            "assignments": [],
            "notes": []
        }
        
        # Get videos
        for video in week.videos:
            week_data["videos"].append({
                "id": video.id,
                "title": video.title,
                "video_key": video.video_key,
                "url": video.url,
                "duration": video.duration,
                "order_index": video.order_index,
                "created_at": video.created_at.isoformat() if video.created_at else None
            })
        
        # Get assignments
        for assignment in week.assignments:
            week_data["assignments"].append({
                "id": assignment.id,
                "title": assignment.title,
                "description": assignment.description,
                "total_points": assignment.total_points,
                "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
                "created_at": assignment.created_at.isoformat() if assignment.created_at else None
            })
        
        # Get notes
        for note in week.notes:
            week_data["notes"].append({
                "id": note.id,
                "title": note.title,
                "file_url": note.file_url,
                "description": note.description,
                "created_at": note.created_at.isoformat() if note.created_at else None
            })
        
        weeks.append(week_data)
        print(week_data)
    
    return jsonify(weeks), 200

@admin_course_bp.route("/api/admin/courses/<int:course_id>/weeks", methods=["POST"])
@token_required
@roles_required("admin")
def create_week(current_user, course_id):
    """Create a new week for a course"""
    course = Course.query.get_or_404(course_id)
    data = request.get_json()
    
    # Validate required fields
    if not data.get('week_number'):
        return jsonify({"error": "Week number is required"}), 400
    
    if not data.get('title'):
        return jsonify({"error": "Title is required"}), 400
    
    # Check if week number already exists for this course
    existing = Week.query.filter_by(
        course_id=course_id,
        week_number=data['week_number']
    ).first()
    
    if existing:
        return jsonify({"error": f"Week {data['week_number']} already exists for this course"}), 400
    
    week = Week(
        course_id=course_id,
        week_number=data['week_number'],
        title=data['title'],
        description=data.get('description', '')
    )
    
    db.session.add(week)
    db.session.commit()

    students = _get_active_paid_students_for_course(course_id)
    for student in students:
        try:
            student_name = " ".join([part for part in [student.first_name, student.last_name] if part]).strip() or "Student"
            send_week_added_email(
                to_email=student.email,
                student_name=student_name,
                course_title=course.title,
                week_number=week.week_number,
                week_title=week.title,
            )
        except Exception as err:
            current_app.logger.warning(
                f"Week notification email failed for course_id={course_id}, user_id={student.id}: {err}"
            )
    
    return jsonify({
        "message": "Week created successfully",
        "week": {
            "id": week.id,
            "week_number": week.week_number,
            "title": week.title
        }
    }), 201

@admin_course_bp.route("/api/admin/weeks/<int:week_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def update_week(current_user, week_id):
    """Update a week"""
    week = Week.query.get_or_404(week_id)
    data = request.get_json(silent=True) or {}

    if not data:
        return jsonify({"error": "No update data provided"}), 400
    
    # Check if week number is being changed and if it conflicts
    if data.get('week_number') and data['week_number'] != week.week_number:
        existing = Week.query.filter_by(
            course_id=week.course_id,
            week_number=data['week_number']
        ).first()
        if existing:
            return jsonify({"error": f"Week {data['week_number']} already exists for this course"}), 400
    
    week.week_number = data.get('week_number', week.week_number)
    week.title = data.get('title', week.title)
    week.description = data.get('description', week.description)
    
    db.session.commit()
    
    return jsonify({"message": "Week updated successfully"}), 200

@admin_course_bp.route("/api/admin/weeks/<int:week_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_week(current_user, week_id):
    """Delete a week"""
    week = Week.query.get_or_404(week_id)
    
    # Check if week has content
    if week.videos or week.assignments or week.notes:
        return jsonify({"error": "Cannot delete week with existing content. Delete content first."}), 400
    
    db.session.delete(week)
    db.session.commit()
    
    return jsonify({"message": "Week deleted successfully"}), 200


# ==================== VIDEO MANAGEMENT ====================

@admin_course_bp.route("/api/admin/weeks/<int:week_id>/videos", methods=["POST"])
@token_required
@roles_required("admin")
def create_video(current_user, week_id):
    """Create a new video for a week"""
    week = Week.query.get_or_404(week_id)
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['title', 'url']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400
    
    # Generate unique video key
    video_key = str(uuid.uuid4())[:8]
    
    video = Video(
        week_id=week_id,
        title=data['title'],
        video_key=video_key,
        url=data['url'],
        duration=data.get('duration'),
        order_index=data.get('order_index', 0)
    )
    
    db.session.add(video)
    db.session.commit()
    
    return jsonify({
        "message": "Video created successfully",
        "video": {
            "id": video.id,
            "title": video.title,
            "video_key": video.video_key,
            "url": video.url,
            "duration": video.duration,
            "order_index": video.order_index
        }
    }), 201

@admin_course_bp.route("/api/admin/videos/<int:video_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def update_video(current_user, video_id):
    """Update a video"""
    video = Video.query.get_or_404(video_id)
    data = request.get_json()
    
    video.title = data.get('title', video.title)
    video.url = data.get('url', video.url)
    video.duration = data.get('duration', video.duration)
    video.order_index = data.get('order_index', video.order_index)
    
    db.session.commit()
    
    return jsonify({"message": "Video updated successfully"}), 200

@admin_course_bp.route("/api/admin/videos/<int:video_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_video(current_user, video_id):
    """Delete a video"""
    video = Video.query.get_or_404(video_id)
    db.session.delete(video)
    db.session.commit()
    
    return jsonify({"message": "Video deleted successfully"}), 200


# ==================== ASSIGNMENT MANAGEMENT ====================

@admin_course_bp.route("/api/admin/weeks/<int:week_id>/assignments", methods=["POST"])
@token_required
@roles_required("admin")
def create_assignment(current_user, week_id):
    """Create a new assignment for a week"""
    week = Week.query.get_or_404(week_id)
    data = request.get_json()
    
    # Validate required fields
    if not data.get('title'):
        return jsonify({"error": "Title is required"}), 400
    
    assignment = Assignment(
        course_id=week.course_id,
        week_id=week_id,
        title=data['title'],
        description=data.get('description', ''),
        total_points=data.get('total_points', 0),
        due_date=datetime.fromisoformat(data['due_date']) if data.get('due_date') else None
    )
    
    db.session.add(assignment)
    db.session.commit()

    course = Course.query.get(week.course_id)
    students = _get_active_paid_students_for_course(week.course_id)
    for student in students:
        try:
            student_name = " ".join([part for part in [student.first_name, student.last_name] if part]).strip() or "Student"
            due_date = assignment.due_date.isoformat() if assignment.due_date else None
            send_assignment_added_email(
                to_email=student.email,
                student_name=student_name,
                course_title=course.title if course else f"Course #{week.course_id}",
                assignment_title=assignment.title,
                week_title=week.title,
                due_date=due_date,
            )
        except Exception as err:
            current_app.logger.warning(
                f"Assignment notification email failed for week_id={week_id}, user_id={student.id}: {err}"
            )
    
    return jsonify({
        "message": "Assignment created successfully",
        "assignment": {
            "id": assignment.id,
            "title": assignment.title,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "total_points": assignment.total_points
        }
    }), 201

@admin_course_bp.route("/api/admin/assignments/<int:assignment_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def update_assignment(current_user, assignment_id):
    """Update an assignment"""
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json()
    
    assignment.title = data.get('title', assignment.title)
    assignment.description = data.get('description', assignment.description)
    assignment.due_date = datetime.fromisoformat(data['due_date']) if data.get('due_date') else assignment.due_date
    assignment.total_points = data.get('total_points', assignment.total_points)
    
    db.session.commit()
    
    return jsonify({"message": "Assignment updated successfully"}), 200

@admin_course_bp.route("/api/admin/assignments/<int:assignment_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_assignment(current_user, assignment_id):
    """Delete an assignment"""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Check if there are submissions
    if assignment.submissions:
        return jsonify({"error": "Cannot delete assignment with student submissions"}), 400
    
    db.session.delete(assignment)
    db.session.commit()
    
    return jsonify({"message": "Assignment deleted successfully"}), 200


# ==================== NOTE MANAGEMENT ====================

@admin_course_bp.route("/api/admin/weeks/<int:week_id>/notes", methods=["POST"])
@token_required
@roles_required("admin")
def create_note(current_user, week_id):
    """Create a new note for a week"""
    week = Week.query.get_or_404(week_id)
    data = request.get_json()
    
    # Validate required fields
    if not data.get('title'):
        return jsonify({"error": "Title is required"}), 400
    
    if not data.get('file_url'):
        return jsonify({"error": "File URL is required"}), 400
    
    note = Note(
        week_id=week_id,
        title=data['title'],
        file_url=data['file_url'],
        description=data.get('description', '')
    )
    
    db.session.add(note)
    db.session.commit()
    
    return jsonify({
        "message": "Note created successfully",
        "note": {
            "id": note.id,
            "title": note.title,
            "file_url": note.file_url,
            "description": note.description
        }
    }), 201

@admin_course_bp.route("/api/admin/notes/<int:note_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def update_note(current_user, note_id):
    """Update a note"""
    note = Note.query.get_or_404(note_id)
    data = request.get_json()
    
    note.title = data.get('title', note.title)
    note.file_url = data.get('file_url', note.file_url)
    note.description = data.get('description', note.description)
    
    db.session.commit()
    
    return jsonify({"message": "Note updated successfully"}), 200

@admin_course_bp.route("/api/admin/notes/<int:note_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_note(current_user, note_id):
    """Delete a note"""
    note = Note.query.get_or_404(note_id)
    db.session.delete(note)
    db.session.commit()
    
    return jsonify({"message": "Note deleted successfully"}), 200


@admin_course_bp.route("/api/admin/weeks/<int:week_id>/reorder-videos", methods=["POST"])
@token_required
@roles_required("admin")
def reorder_videos(current_user, week_id):
    """Reorder videos within a week"""
    data = request.get_json()
    video_order = data.get('video_order', [])
    
    for index, video_id in enumerate(video_order):
        video = Video.query.get(video_id)
        if video and video.week_id == week_id:
            video.order_index = index
    
    db.session.commit()
    
    return jsonify({"message": "Videos reordered successfully"}), 200