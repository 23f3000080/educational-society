from sqlalchemy import func

from models import *
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from Routes.base_route import token_required, roles_required
from sqlalchemy.orm import aliased
from zoneinfo import ZoneInfo
import razorpay
from dotenv import load_dotenv
import os
from flask_security.utils import hash_password, verify_password
from communication.email_sender import send_course_enrollment_email

load_dotenv()

user_bp = Blueprint("user", __name__)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
IST = ZoneInfo("Asia/Kolkata")


def _serialize_user_profile(user):
    return {
        "id": user.id,
        "user_id": user.user_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "mobile_no": user.mobile_no,
        "alternate_mobile_no": user.alternate_mobile_no,
        "country": user.country,
        "state": user.state,
        "city": user.city,
        "location": user.location,
        "pincode": user.pincode,
        "gender": user.gender,
        "dob": user.dob.isoformat() if user.dob else None,
        "parent_name": user.parent_name,
        "parent_relation": user.parent_relation,
        "mode_of_communication": user.mode_of_communication,
        "joining_date": user.joining_date.isoformat() if user.joining_date else None,
        "is_email_verified": bool(user.is_email_verified),
        "is_mobile_verified": bool(user.is_mobile_verified),
        "profile_picture": user.profile_picture,
    }

# Helper to convert UTC to IST
def to_ist(utc_dt):
    if utc_dt is None:
        return None
    # IST is UTC + 5:30
    return (utc_dt + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

def get_user_notifications(user_id):
    """
    Fetch all notifications for a user:
    - Global notifications (everyone)
    - User-specific notifications
    """

    # 1️⃣ Global notifications with is_read if exists
    global_notifications = db.session.query(
        Notification,
        UserNotification.is_read
    ).outerjoin(
        UserNotification,
        (UserNotification.notification_id == Notification.id) &
        (UserNotification.user_id == user_id)
    ).filter(
        Notification.is_global == True
    ).all()

    # 2️⃣ User-specific notifications
    user_notifications = db.session.query(
        Notification,
        UserNotification.is_read
    ).join(
        UserNotification
    ).filter(
        UserNotification.user_id == user_id,
        Notification.is_global == False
    ).all()

    # Combine both
    return global_notifications + user_notifications


def _normalize_text(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _parse_selected_option_ids(raw_value):
    if isinstance(raw_value, list):
        return [str(v).strip() for v in raw_value if str(v).strip()]
    if isinstance(raw_value, str):
        return [v.strip() for v in raw_value.split(',') if v.strip()]
    return []


def _to_ist_aware(dt_value):
    if not dt_value:
        return None

    # Stored naive due_date is treated as IST local time.
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=IST)

    return dt_value.astimezone(IST)


def _score_mcq(question, selected_option_id):
    if selected_option_id is None:
        return 0.0, False

    correct_option = QuestionOption.query.filter_by(
        question_id=question.id,
        is_correct=True
    ).first()

    is_correct = bool(correct_option and str(correct_option.id) == str(selected_option_id))
    return (float(question.marks) if is_correct else 0.0), is_correct


def _score_multiple_select(question, selected_option_ids):
    selected_ids = {str(v) for v in _parse_selected_option_ids(selected_option_ids)}
    correct_ids = {
        str(opt.id)
        for opt in QuestionOption.query.filter_by(question_id=question.id, is_correct=True).all()
    }

    if not correct_ids:
        return 0.0, False

    correct_selected = len(selected_ids & correct_ids)
    incorrect_selected = len(selected_ids - correct_ids)

    # Real-world partial marking: reward correct picks, penalize wrong picks.
    ratio = (correct_selected - incorrect_selected) / len(correct_ids)
    earned = max(0.0, ratio * float(question.marks))
    earned = round(earned, 2)
    is_fully_correct = selected_ids == correct_ids

    return earned, is_fully_correct


def _score_fill_blank(question, text_answer):
    normalized = _normalize_text(text_answer)
    if not normalized:
        return 0.0, False

    valid_answers = {
        _normalize_text(row.correct_answer)
        for row in FillBlankAnswer.query.filter_by(question_id=question.id).all()
        if row.correct_answer
    }

    is_correct = normalized in valid_answers if valid_answers else False
    return (float(question.marks) if is_correct else 0.0), is_correct


@user_bp.route("/api/student/profile", methods=["GET"])
@token_required
@roles_required("user", "admin")
def fetch_student_profile(current_user):
    return jsonify(_serialize_user_profile(current_user)), 200


@user_bp.route("/api/student/profile", methods=["PUT"])
@token_required
@roles_required("user", "admin")
def update_student_profile(current_user):
    data = request.get_json(silent=True) or {}
    previous_mobile_no = current_user.mobile_no

    updatable_fields = [
        "first_name",
        "last_name",
        "mobile_no",
        "alternate_mobile_no",
        "country",
        "state",
        "city",
        "location",
        "pincode",
        "gender",
        "parent_name",
        "parent_relation",
        "mode_of_communication",
    ]

    for field in updatable_fields:
        if field in data:
            value = data.get(field)
            setattr(current_user, field, value.strip() if isinstance(value, str) else value)

    if "mobile_no" in data:
        updated_mobile = (current_user.mobile_no or "").strip()
        old_mobile = (previous_mobile_no or "").strip()
        if updated_mobile != old_mobile:
            current_user.is_mobile_verified = False

    if "dob" in data:
        dob_value = data.get("dob")
        if dob_value in (None, ""):
            current_user.dob = None
        else:
            try:
                current_user.dob = datetime.strptime(str(dob_value), "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Invalid dob format. Use YYYY-MM-DD"}), 400

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Profile updated successfully",
        "profile": _serialize_user_profile(current_user),
    }), 200


@user_bp.route("/api/student/change-password", methods=["POST"])
@token_required
@roles_required("user", "admin")
def change_student_password(current_user):
    data = request.get_json(silent=True) or {}
    current_password = (data.get("current_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()
    confirm_password = (data.get("confirm_password") or "").strip()

    if not current_password or not new_password or not confirm_password:
        return jsonify({"error": "current_password, new_password, and confirm_password are required"}), 400

    if not verify_password(current_password, current_user.password):
        return jsonify({"error": "Current password is incorrect"}), 400

    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters long"}), 400

    if new_password != confirm_password:
        return jsonify({"error": "New password and confirm password do not match"}), 400

    if verify_password(new_password, current_user.password):
        return jsonify({"error": "New password must be different from current password"}), 400

    current_user.password = hash_password(new_password)
    db.session.commit()

    return jsonify({"message": "Password updated successfully"}), 200

# API to fetch notifications
@user_bp.route("/api/notifications/<int:user_id>", methods=["GET"])
@token_required
@roles_required("user", "admin")
def fetch_notifications(current_user, user_id):
    notifications = get_user_notifications(user_id)

    result = []
    for notification, is_read in notifications:
        result.append({
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "type": notification.type,
            "is_global": notification.is_global,
            "created_at": to_ist(notification.created_at),
            "is_read": bool(is_read) if is_read is not None else False
        })

    # Optional: sort by newest first
    result.sort(key=lambda x: x["created_at"], reverse=True)

    return jsonify(result), 200

def mark_notification_read(user_id, notification_id):
    # fetch the notification first
    notification = Notification.query.get(notification_id)
    if not notification:
        return jsonify({"error": "Invalid notification ID"}), 404

    # check if this notification belongs to this user or is global
    if not notification.is_global:
        # must have a mapping in UserNotification
        mapping = UserNotification.query.filter_by(
            user_id=user_id,
            notification_id=notification_id
        ).first()
        if not mapping:
            # this notification does NOT belong to this user
            return jsonify({"error": "Notification does not belong to user"}), 403

    # now mark as read
    record = UserNotification.query.filter_by(
        user_id=user_id,
        notification_id=notification_id
    ).first()

    if not record:
        # only create record if notification is global
        if notification.is_global:
            record = UserNotification(
                user_id=user_id,
                notification_id=notification_id,
                is_read=True,
                read_at=datetime.now(timezone.utc)
            )
            db.session.add(record)
    else:
        record.is_read = True
        record.read_at = datetime.now(timezone.utc)

    db.session.commit()
    return jsonify({"message": "Notification marked as read"}), 200

# api to mark notification as read
@user_bp.route("/api/notifications/mark_read", methods=["POST"])
@token_required
@roles_required("user", "admin")
def mark_notification_as_read_route(current_user):
    data = request.get_json()
    user_id = data.get("user_id")
    notification_id = data.get("notification_id")

    if not user_id or not notification_id:
        return jsonify({"message": "user_id and notification_id are required"}), 400

    response = mark_notification_read(user_id, notification_id)
    # show mark_notification_read response

    return response

# API to fetch courses for student
@user_bp.route("/api/student/courses", methods=["GET"])
@token_required
@roles_required("user")
def fetch_courses(current_user):

    courses = Course.query.filter_by(is_active=True).all()
    enrollments = Enrollment.query.filter_by(student_id=current_user.id).all()
    enrollment_map = {e.course_id: e for e in enrollments}

    result = []

    for course in courses:
        enrollment = enrollment_map.get(course.id)

        result.append({
            "id": course.id,
            "title": course.title,
            "subject": course.subject,
            "duration_months": course.duration_months,
            "class_level": course.class_level,
            "course_code": course.course_code,
            "fee": float(course.fee),
            "description": course.description,
            "picture_url":course.picture if course.picture else None
            ,
            "is_enrolled": enrollment is not None,
            "payment_status": enrollment.payment_status if enrollment else None
        })

    return jsonify(result), 200


# API to fetch enrolled & paid courses for student
@user_bp.route("/api/my-courses", methods=["GET"])
@token_required
@roles_required("user")
def fetch_enrolled_paid_courses(current_user):

    enrolled_courses = (
        db.session.query(Course, Enrollment)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .filter(
            Enrollment.student_id == current_user.id,
            Enrollment.payment_status == "paid",
            Enrollment.enrollment_status == "active",
            Course.is_active == True
        )
        .all()
    )

    result = []
    # course progress for enrolled courses

    for course, enrollment in enrolled_courses:

        total_videos = db.session.query(func.count(Video.id))\
            .join(Week, Week.id == Video.week_id)\
            .filter(Week.course_id == course.id).scalar()

        total_notes = db.session.query(func.count(Note.id))\
            .join(Week, Week.id == Note.week_id)\
            .filter(Week.course_id == course.id).scalar()

        total_assignments = db.session.query(func.count(Assignment.id))\
            .filter(Assignment.course_id == course.id).scalar()

        total_items = total_videos + total_notes + total_assignments

        completed_items = db.session.query(func.count(CourseProgress.id)).filter(
            CourseProgress.student_id == current_user.id,
            CourseProgress.course_id == course.id,
            CourseProgress.completed == True
        ).scalar()

        progress_percent = 0
        if total_items > 0:
            progress_percent = round((completed_items / total_items) * 100, 2)

        result.append({
            "course_id": course.id,
            "title": course.title,
            "course_code": course.course_code,
            "class_level": course.class_level,
            "subject": course.subject,
            "description": course.description,
            "duration_months": course.duration_months,
            "fee": float(course.fee),
            "enrollment_date": enrollment.enrollment_date,
            "payment_status": enrollment.payment_status,
            "progress_percent": progress_percent,
            "total_items": total_items,
            "completed_items": completed_items
        })

    return jsonify(result), 200

# api to fetch course details with course id
@user_bp.route("/api/course/<int:course_id>", methods=["GET"])
@token_required
@roles_required("user")
def fetch_course_details(current_user, course_id):
    print(f"Fetching details for course_id: {course_id}")  # ✅ debug log
    course = Course.query.filter_by(id=course_id, is_active=True).first()
    if not course:
        return jsonify({"error": "Course not found"}), 404

    course = {
        "id": course.id,
        "course_code": course.course_code,
        "title": course.title,
        "subject": course.subject,
        "duration_months": course.duration_months,
        "start_date": course.start_date,
        "end_date": course.end_date,
        "is_active": course.is_active,
        "class_level": course.class_level,
        "course_code": course.course_code,
        "fee": float(course.fee),
        "description": course.description,
        "picture_url": (course.picture if course.picture else None
        )
    }
    return jsonify({
        "course": course,
        "message": "Course details fetched successfully"
    }), 200

@user_bp.route("/api/create-payment", methods=["POST"])
@token_required
@roles_required("user")
def create_payment(current_user):

    data = request.json
    course_id = data.get("course_id")

    course = Course.query.get(course_id)

    if not course:
        return jsonify({"error": "Course not found"}), 404
    
    existing = Enrollment.query.filter_by(student_id=current_user.id,
                course_id=course_id
            ).first()

    if existing:
        return jsonify({"error": "You are already enrolled in this course"}), 400

    amount = int(course.fee * 100)  # Razorpay uses paise

    order = razorpay_client.order.create({
        "amount": amount,
        "currency": "INR",
        "payment_capture": 1
    })

    return jsonify({
        "order_id": order["id"],
        "amount": amount,
        "key": RAZORPAY_KEY_ID,
        "course_id": course.id
    })

@user_bp.route("/api/verify-payment", methods=["POST"])
@token_required
@roles_required("user")
def verify_payment(current_user):

    data = request.json

    payment_id = data.get("razorpay_payment_id")
    order_id = data.get("razorpay_order_id")
    signature = data.get("razorpay_signature")
    course_id = data.get("course_id")

    course = Course.query.get(course_id)

    try:

        razorpay_client.utility.verify_payment_signature({
            "razorpay_payment_id": payment_id,
            "razorpay_order_id": order_id,
            "razorpay_signature": signature
        })

        enrollment = Enrollment(
            student_id=current_user.id,
            course_id=course_id,
            payment_id=payment_id,
            payment_status="paid"
        )

        db.session.add(enrollment)
        db.session.commit()

        try:
            student_name = " ".join(
                [part for part in [current_user.first_name, current_user.last_name] if part]
            ).strip() or "Student"
            enrollment_date = enrollment.enrollment_date.isoformat() if enrollment.enrollment_date else None
            send_course_enrollment_email(
                to_email=current_user.email,
                student_name=student_name,
                course_title=course.title,
                # send enrollment date in IST format

                enrollment_date=to_ist(enrollment.enrollment_date) if enrollment.enrollment_date else None,
            )
        except Exception as err:
            current_app.logger.warning(f"Enrollment email failed for user_id={current_user.id}: {err}")

        return jsonify({
            "message": "Payment verified. Course enrolled successfully."
        })

    except:

        return jsonify({"error": "Payment verification failed"}), 400

# api to check user enrollment status for a course
@user_bp.route("/api/enrollment-status/<int:course_id>", methods=["GET"])
@token_required
@roles_required("user")
def check_enrollment_status(current_user, course_id):
    """Check if user is enrolled in a course"""
    
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=course_id
    ).first()
    
    if not enrollment:
        return jsonify({
            "enrolled": False,
            "message": "Not enrolled"
        })
    
    return jsonify({
        "enrolled": True,
        "payment_status": enrollment.payment_status,
        "enrollment_status": enrollment.enrollment_status,
        "enrollment_date": enrollment.enrollment_date.isoformat() if enrollment.enrollment_date else None
    }), 200

@user_bp.route("/api/courses/<int:course_id>", methods=["GET"])
@token_required
@roles_required("user")
def get_course(current_user, course_id):
    """Get course details"""
    course = Course.query.get_or_404(course_id)
    
    # Check enrollment
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        enrollment_status='active'
    ).first()
    
    if not enrollment:
        return jsonify({"error": "Not enrolled in this course"}), 403
    
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
        "is_active": course.is_active
    })

@user_bp.route("/api/courses/<int:course_id>/weeks", methods=["GET"])
@token_required
@roles_required("user")
def get_course_weeks(current_user, course_id):
    """Get all weeks with their videos, assignments, and notes for a course"""
    # Check enrollment
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        enrollment_status='active'
    ).first()
    
    if not enrollment:
        return jsonify({"error": "Not enrolled in this course"}), 403
    
    weeks = Week.query.filter_by(course_id=course_id).order_by(Week.week_number).all()
    
    result = []
    for week in weeks:
        week_data = {
            "id": week.id,
            "week_number": week.week_number,
            "title": week.title,
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
                "order_index": video.order_index
            })
        
        # Get assignments
        for assignment in week.assignments:
            week_data["assignments"].append({
                "id": assignment.id,
                "title": assignment.title,
                "description": assignment.description,
                "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
                # "total_points": assignment.total_points
            })
        
        # Get notes
        for note in week.notes:
            week_data["notes"].append({
                "id": note.id,
                "title": note.title,
                "file_url": note.file_url,
                "description": note.description
            })
        
        result.append(week_data)
    
    return jsonify(result)

@user_bp.route("/api/assignments/<int:assignment_id>/questions", methods=["GET"])
@token_required
@roles_required("user")
def get_assignment_questions(current_user, assignment_id):
    """Get all questions for an assignment"""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Check enrollment in the course
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=assignment.course_id,
        enrollment_status='active'
    ).first()
    
    if not enrollment:
        return jsonify({"error": "Not enrolled in this course"}), 403

    latest_submission = AssignmentSubmission.query.filter_by(
        assignment_id=assignment_id,
        student_id=current_user.id
    ).order_by(AssignmentSubmission.submitted_at.desc(), AssignmentSubmission.id.desc()).first()

    now_ist = datetime.now(IST)
    due_date = _to_ist_aware(assignment.due_date)
    can_view_answers = False

    if due_date:
        can_view_answers = now_ist >= due_date
    
    questions = Question.query.filter_by(assignment_id=assignment_id).order_by(Question.order_index).all()
    question_ids = [q.id for q in questions]

    student_answers = {}
    if question_ids:
        answer_rows = StudentAnswer.query.filter(
            StudentAnswer.student_id == current_user.id,
            StudentAnswer.question_id.in_(question_ids)
        ).order_by(StudentAnswer.created_at.desc(), StudentAnswer.id.desc()).all()

        # Keep latest answer per question in case historical duplicate rows exist.
        for row in answer_rows:
            if row.question_id not in student_answers:
                student_answers[row.question_id] = row
    
    result = []
    for q in questions:
        question_data = {
            "id": q.id,
            "question_text": q.question_text,
            "question_type": q.question_type,
            "marks": q.marks,
            "options": [],
            "student_answer": None,
            "earned_marks": None,
            "is_correct": None
        }

        answer_row = student_answers.get(q.id)

        if answer_row:
            if q.question_type == 'mcq':
                question_data["student_answer"] = {
                    "selected_option_id": answer_row.selected_option_id
                }
            elif q.question_type == 'multiple_select':
                selected_ids = _parse_selected_option_ids(answer_row.text_answer)
                question_data["student_answer"] = {
                    "selected_option_ids": selected_ids
                }
            elif q.question_type == 'fill_blank':
                question_data["student_answer"] = {
                    "text_answer": answer_row.text_answer or ''
                }

        if can_view_answers:
            earned_marks = 0.0
            is_correct = False

            if answer_row:
                if q.question_type == 'mcq':
                    earned_marks, is_correct = _score_mcq(q, answer_row.selected_option_id)
                elif q.question_type == 'multiple_select':
                    earned_marks, is_correct = _score_multiple_select(q, answer_row.text_answer)
                elif q.question_type == 'fill_blank':
                    earned_marks, is_correct = _score_fill_blank(q, answer_row.text_answer)

            question_data["earned_marks"] = earned_marks
            question_data["is_correct"] = is_correct
        
        # Get options for MCQ and multiple select
        if q.question_type in ['mcq', 'multiple_select']:
            for opt in q.options:
                question_data["options"].append({
                    "id": opt.id,
                    "option_text": opt.option_text,
                    # Expose correctness only after due date is over.
                    "is_correct": opt.is_correct if can_view_answers else None
                })

        if q.question_type == 'fill_blank':
            if can_view_answers:
                valid_answers = [
                    answer.correct_answer
                    for answer in q.blank_answers
                    if answer.correct_answer
                ]
                question_data["correct_answers"] = valid_answers
            else:
                question_data["correct_answers"] = []
        
        question_data["can_view_answer"] = can_view_answers
        result.append(question_data)
    
    return jsonify({
        "questions": result,
        "latest_submission_at": (
            _to_ist_aware(latest_submission.submitted_at).isoformat()
            if latest_submission and latest_submission.submitted_at
            else None
        )
    })

@user_bp.route("/api/submit-assignment", methods=["POST"])
@token_required
@roles_required("user")
def submit_assignment(current_user):
    """Submit assignment answers"""
    data = request.get_json()
    
    assignment_id = data.get("assignment_id")
    answers = data.get("answers", [])  # List of answers
    
    assignment = Assignment.query.get_or_404(assignment_id)
    
    due_date = _to_ist_aware(assignment.due_date)
    if due_date and datetime.now(IST) > due_date:
            return jsonify({"error": "Assignment due date is over"}), 400

    # Check previous submission status after due-date validation.
    existing = AssignmentSubmission.query.filter_by(
        assignment_id=assignment_id,
        student_id=current_user.id
    ).first()

    is_resubmission = existing is not None

    if is_resubmission:
        existing.submitted_at = datetime.now(timezone.utc)

        # Replace previous answers for this assignment with the latest attempt.
        question_ids = [
            row.id
            for row in Question.query.with_entities(Question.id).filter_by(assignment_id=assignment_id).all()
        ]
        if question_ids:
            StudentAnswer.query.filter(
                StudentAnswer.student_id == current_user.id,
                StudentAnswer.question_id.in_(question_ids)
            ).delete(synchronize_session=False)
    else:
        # Create first submission record.
        submission = AssignmentSubmission(
            assignment_id=assignment_id,
            student_id=current_user.id,
            submitted_at=datetime.now(timezone.utc)
        )
        db.session.add(submission)
        db.session.flush()
    
    total_points = 0
    earned_points = 0
    
    # Process each answer
    for answer_data in answers:
        question = Question.query.get(answer_data['question_id'])
        if not question or question.assignment_id != assignment_id:
            continue

        total_points += question.marks
        
        student_answer = StudentAnswer(
            student_id=current_user.id,
            question_id=question.id
        )
        
        # Handle different question types
        if question.question_type == 'mcq':
            selected_option_id = answer_data.get('selected_option_id')
            student_answer.selected_option_id = selected_option_id

            earned_marks, _ = _score_mcq(question, selected_option_id)
            earned_points += earned_marks
        
        elif question.question_type == 'multiple_select':
            selected_option_ids = _parse_selected_option_ids(answer_data.get('selected_option_ids', []))
            # Store as JSON or create multiple records
            # For simplicity, storing as comma-separated string in text_answer
            student_answer.text_answer = ','.join(map(str, selected_option_ids))

            earned_marks, _ = _score_multiple_select(question, selected_option_ids)
            earned_points += earned_marks
        
        elif question.question_type == 'fill_blank':
            text_answer = answer_data.get('text_answer', '')
            student_answer.text_answer = text_answer

            earned_marks, _ = _score_fill_blank(question, text_answer)
            earned_points += earned_marks
        
        db.session.add(student_answer)
    
    # Mark assignment as completed in progress (id-based key used by frontend)
    content_key = f"assignment_{assignment.id}"
    existing_progress = CourseProgress.query.filter_by(
        student_id=current_user.id,
        course_id=assignment.course_id,
        content_key=content_key
    ).first()

    if not existing_progress:
        progress = CourseProgress(
            student_id=current_user.id,
            course_id=assignment.course_id,
            content_type='assignment',
            content_key=content_key,
            completed=True
        )
        db.session.add(progress)
    
    db.session.commit()
    
    return jsonify({
        "message": "Assignment updated successfully" if is_resubmission else "Assignment submitted successfully",
        "score": round(float(earned_points), 2),
        "total": total_points,
        "submitted_at": datetime.now(IST).isoformat()
    }), 200

@user_bp.route("/api/progress/complete", methods=["POST"])
@token_required
@roles_required("user")
def mark_content_completed(current_user):
    """Mark a content item (video/assignment/note) as completed"""
    data = request.get_json()
    
    course_id = data.get("course_id")
    content_type = data.get("content_type")  # video / assignment
    content_key = data.get("content_key")
    
    if not course_id or not content_key:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Check enrollment
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        enrollment_status='active'
    ).first()
    
    if not enrollment:
        return jsonify({"error": "User not enrolled in this course"}), 403
    
    # Check if already completed
    progress = CourseProgress.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        content_key=content_key
    ).first()
    
    if progress:
        return jsonify({"message": "Already completed"}), 200
    
    progress = CourseProgress(
        student_id=current_user.id,
        course_id=course_id,
        content_type=content_type,
        content_key=content_key,
        completed=True
        # completed_at=datetime.now(timezone.utc)
    )
    
    db.session.add(progress)
    db.session.commit()
    
    return jsonify({
        "message": "Content marked as completed"
    }), 200

@user_bp.route("/api/course-progress/<int:course_id>", methods=["POST"])
@token_required
@roles_required("user")
def get_course_progress(current_user, course_id):
    """Get overall course progress percentage"""
    data = request.get_json()
    total_content = data.get("total_content", 0)
    
    # Check enrollment
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        enrollment_status='active'
    ).first()
    
    if not enrollment:
        return jsonify({"error": "User not enrolled"}), 403
    
    # Completed content count
    completed_count = CourseProgress.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        completed=True
    ).count()
    
    progress_percentage = 0
    if total_content > 0:
        progress_percentage = round((completed_count / total_content) * 100, 2)
    
    return jsonify({
        "completed": completed_count,
        "total": total_content,
        "progress": progress_percentage
    }), 200


@user_bp.route("/api/course-progress/<int:course_id>/completed", methods=["GET"])
@token_required
@roles_required("user")
def get_completed_items(current_user, course_id):
    """Get all completed items for a course"""
    
    # Check enrollment
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        enrollment_status='active'
    ).first()
    
    if not enrollment:
        return jsonify({"error": "User not enrolled"}), 403
    
    # Get all completed progress items
    completed_items = CourseProgress.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        completed=True
    ).all()
    
    items = []
    for item in completed_items:
        items.append({
            "content_type": item.content_type,
            "content_key": item.content_key
        })
    
    return jsonify(items), 200


@user_bp.route("/api/course-full/<int:course_id>", methods=["GET"])
@token_required
@roles_required("user")
def get_full_course_data(current_user, course_id):
    """Single API to get full course data"""

    # ✅ Check enrollment
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        enrollment_status='active'
    ).first()

    if not enrollment:
        return jsonify({"error": "Not enrolled in this course"}), 403

    # ✅ Get course
    course = Course.query.get_or_404(course_id)

    # ---------------------------
    # 📦 COURSE DATA
    # ---------------------------
    course_data = {
        "id": course.id,
        "title": course.title,
        "subject": course.subject,
        "description": course.description,
        "duration_months": course.duration_months,
        "class_level": course.class_level,
        "picture": course.picture
    }

    # ---------------------------
    # 📚 WEEKS + CONTENT
    # ---------------------------
    weeks = Week.query.filter_by(course_id=course_id).order_by(Week.week_number).all()

    weeks_data = []
    total_items = 0

    for week in weeks:
        week_obj = {
            "id": week.id,
            "week_number": week.week_number,
            "title": week.title,
            "videos": [],
            "assignments": [],
            "notes": []
        }

        # 🎥 Videos
        for video in week.videos:
            week_obj["videos"].append({
                "id": video.id,
                "title": video.title,
                "url": video.url,
                "duration": video.duration
            })
            total_items += 1

        # 📝 Assignments
        for assignment in week.assignments:
            week_obj["assignments"].append({
                "id": assignment.id,
                "title": assignment.title,
                "description": assignment.description,
                "due_date": assignment.due_date.isoformat() if assignment.due_date else None
            })
            total_items += 1

        # 📄 Notes
        for note in week.notes:
            week_obj["notes"].append({
                "id": note.id,
                "title": note.title,
                "file_url": note.file_url,
                "description": note.description
            })
            total_items += 1

        weeks_data.append(week_obj)

    # ---------------------------
    # 📊 PROGRESS
    # ---------------------------
    completed_items = CourseProgress.query.filter_by(
        student_id=current_user.id,
        course_id=course_id,
        completed=True
    ).all()

    completed_list = [item.content_key for item in completed_items]

    completed_count = len(completed_list)

    progress_percent = 0
    if total_items > 0:
        progress_percent = round((completed_count / total_items) * 100, 2)

    # ---------------------------
    # ✅ FINAL RESPONSE
    # ---------------------------
    return jsonify({
        "course": course_data,
        "weeks": weeks_data,
        "progress": {
            "completed": completed_count,
            "total": total_items,
            "progress": progress_percent
        },
        "completed_items": completed_list
    }), 200