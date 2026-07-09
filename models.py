from flask_sqlalchemy import SQLAlchemy
from flask_security import UserMixin, RoleMixin
from datetime import datetime, timezone

db = SQLAlchemy()


# -------------------------
# USER & AUTH MODELS
# -------------------------

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(8), unique=True, nullable=False)

    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50))

    email = db.Column(db.String(150), unique=True, nullable=False)
    is_email_verified = db.Column(db.Boolean, default=False)

    fs_uniquifier = db.Column(db.String(64), unique=True, nullable=False)

    mobile_no = db.Column(db.String(15))
    alternate_mobile_no = db.Column(db.String(15))

    is_mobile_verified = db.Column(db.Boolean, default=False)

    password = db.Column(db.String(200), nullable=False)

    country = db.Column(db.String(50), default='India')
    state = db.Column(db.String(50))
    city = db.Column(db.String(50))
    location = db.Column(db.String(100))
    pincode = db.Column(db.String(10))

    gender = db.Column(db.String(10))
    dob = db.Column(db.Date)

    id_card_type = db.Column(db.String(50))
    id_no = db.Column(db.String(50))

    parent_name = db.Column(db.String(100))
    parent_relation = db.Column(db.String(100))

    mode_of_communication = db.Column(db.String(50))

    joining_date = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    active = db.Column(db.Boolean, nullable=False)

    profile_picture = db.Column(db.String(200))

    reset_code = db.Column(db.String(6))
    reset_code_expiry = db.Column(db.DateTime)

    roles = db.relationship(
        'Role',
        secondary='users_roles',
        backref=db.backref('users', lazy=True)
    )


class Role(db.Model, RoleMixin):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))


class UsersRoles(db.Model):
    __tablename__ = "users_roles"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"))
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id', ondelete="CASCADE"))


# -------------------------
# QUERY MODEL
# -------------------------

class QueryModel(db.Model):
    __tablename__ = 'queries'

    id = db.Column(db.Integer, primary_key=True)

    person_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    issue_type = db.Column(db.String(100), nullable=True)

    query_text = db.Column(db.String(1000), nullable=False)

    raised_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    is_resolved = db.Column(db.Boolean, default=False)

    status = db.Column(db.String(50), default='open')

    response_text = db.Column(db.String(1000))
    response_at = db.Column(db.DateTime)

    responded_by = db.Column(db.String(100))


# -------------------------
# EMAIL OTP
# -------------------------

class EmailOTP(db.Model):
    __tablename__ = "email_otps"

    id = db.Column(db.Integer, primary_key=True)

    email = db.Column(db.String(255), nullable=False)

    otp = db.Column(db.String(6), nullable=False)

    expires_at = db.Column(db.DateTime, nullable=False)


class MobileOTP(db.Model):
    __tablename__ = "mobile_otps"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=False)

    mobile_no = db.Column(db.String(15), nullable=False)

    otp = db.Column(db.String(6), nullable=False)

    expires_at = db.Column(db.DateTime, nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    user = db.relationship('User', backref=db.backref('mobile_otps', lazy=True, cascade="all, delete-orphan"))


# -------------------------
# NOTIFICATIONS
# -------------------------

class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(255), nullable=False)

    message = db.Column(db.Text, nullable=False)

    type = db.Column(db.String(50))

    is_global = db.Column(db.Boolean, default=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )


class UserNotification(db.Model):
    __tablename__ = "user_notifications"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    notification_id = db.Column(
        db.Integer,
        db.ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False
    )

    is_read = db.Column(db.Boolean, default=False)

    read_at = db.Column(db.DateTime)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    user = db.relationship("User", backref=db.backref("notifications", lazy=True, cascade="all, delete-orphan"))

    notification = db.relationship("Notification")


# -------------------------
# COURSE SYSTEM
# -------------------------

class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)

    course_code = db.Column(db.String(20), unique=True, nullable=False)

    title = db.Column(db.String(150), nullable=False)

    class_level = db.Column(db.String(50))
    subject = db.Column(db.String(100))

    description = db.Column(db.Text)

    duration_months = db.Column(db.Integer)

    fee = db.Column(db.Numeric(10, 2), nullable=False)

    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)

    is_active = db.Column(db.Boolean, default=True)

    picture = db.Column(db.String(255))

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )


class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))

    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"))

    payment_id = db.Column(db.String(120))

    payment_status = db.Column(db.String(20), default="pending")

    enrollment_status = db.Column(db.String(20), default="active")

    enrollment_date = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    student = db.relationship("User", backref=db.backref("enrollments", lazy=True, cascade="all, delete-orphan"))

    course = db.relationship("Course", backref=db.backref("enrollments", lazy=True, cascade="all, delete-orphan"))


# -------------------------
# COURSE STRUCTURE
# -------------------------

class Week(db.Model):
    __tablename__ = "weeks"

    id = db.Column(db.Integer, primary_key=True)

    course_id = db.Column(db.Integer, db.ForeignKey('courses.id', ondelete="CASCADE"))

    week_number = db.Column(db.Integer)

    title = db.Column(db.String(200))
    description = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    course = db.relationship("Course", backref=db.backref("weeks", lazy=True, cascade="all, delete-orphan"))


class Video(db.Model):
    __tablename__ = "videos"

    id = db.Column(db.Integer, primary_key=True)

    week_id = db.Column(db.Integer, db.ForeignKey('weeks.id', ondelete="CASCADE"))

    title = db.Column(db.String(200))

    video_key = db.Column(db.String(50))

    url = db.Column(db.String(500))

    duration = db.Column(db.Integer)

    order_index = db.Column(db.Integer, default=0)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    week = db.relationship("Week", backref=db.backref("videos", lazy=True, cascade="all, delete-orphan"))


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)

    week_id = db.Column(db.Integer, db.ForeignKey('weeks.id', ondelete="CASCADE"))

    title = db.Column(db.String(200))

    file_url = db.Column(db.String(500))

    description = db.Column(db.Text)

    order_index = db.Column(db.Integer, default=0)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    week = db.relationship("Week", backref=db.backref("notes", lazy=True, cascade="all, delete-orphan"))


# -------------------------
# ASSIGNMENT
# -------------------------

class Assignment(db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)

    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"))
    week_id = db.Column(db.Integer, db.ForeignKey("weeks.id", ondelete="CASCADE"))

    title = db.Column(db.String(150))

    description = db.Column(db.Text)

    due_date = db.Column(db.DateTime)
    total_points = db.Column(db.Integer)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    order_index = db.Column(db.Integer, default=0)

    course = db.relationship("Course", backref=db.backref("assignments", lazy=True, cascade="all, delete-orphan"))
    week = db.relationship("Week", backref=db.backref("assignments", lazy=True, cascade="all, delete-orphan"))


# -------------------------
# TEST SYSTEM
# -------------------------

class Test(db.Model):
    __tablename__ = "tests"

    id = db.Column(db.Integer, primary_key=True)

    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"))
    week_id = db.Column(db.Integer, db.ForeignKey("weeks.id", ondelete="CASCADE"))

    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)

    test_scope = db.Column(db.String(20), default='week')
    # week | full_length

    duration_minutes = db.Column(db.Integer, default=60)
    start_at = db.Column(db.DateTime)
    due_date = db.Column(db.DateTime)
    total_marks = db.Column(db.Integer, default=0)

    max_attempts = db.Column(db.Integer, default=1)
    passcode = db.Column(db.String(40))
    shuffle_questions = db.Column(db.Boolean, default=True)
    shuffle_options = db.Column(db.Boolean, default=True)
    require_fullscreen = db.Column(db.Boolean, default=True)
    prevent_tab_switch = db.Column(db.Boolean, default=True)

    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    course = db.relationship("Course", backref=db.backref("tests", lazy=True, cascade="all, delete-orphan"))
    week = db.relationship("Week", backref=db.backref("tests", lazy=True, cascade="all, delete-orphan"))


class TestQuestion(db.Model):
    __tablename__ = "test_questions"

    id = db.Column(db.Integer, primary_key=True)

    test_id = db.Column(
        db.Integer,
        db.ForeignKey("tests.id", ondelete="CASCADE")
    )

    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20))
    marks = db.Column(db.Integer, default=1)
    order_index = db.Column(db.Integer, default=0)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    test = db.relationship("Test", backref=db.backref("questions", lazy=True, cascade="all, delete-orphan"))


class TestQuestionOption(db.Model):
    __tablename__ = "test_question_options"

    id = db.Column(db.Integer, primary_key=True)

    question_id = db.Column(
        db.Integer,
        db.ForeignKey("test_questions.id", ondelete="CASCADE")
    )

    option_text = db.Column(db.String(500))
    is_correct = db.Column(db.Boolean, default=False)

    question = db.relationship("TestQuestion", backref=db.backref("options", lazy=True, cascade="all, delete-orphan"))


class TestFillBlankAnswer(db.Model):
    __tablename__ = "test_fill_blank_answers"

    id = db.Column(db.Integer, primary_key=True)

    question_id = db.Column(
        db.Integer,
        db.ForeignKey("test_questions.id", ondelete="CASCADE")
    )

    correct_answer = db.Column(db.String(255))

    question = db.relationship("TestQuestion", backref=db.backref("blank_answers", lazy=True, cascade="all, delete-orphan"))


class TestSubmission(db.Model):
    __tablename__ = "test_submissions"

    id = db.Column(db.Integer, primary_key=True)

    test_id = db.Column(db.Integer, db.ForeignKey("tests.id", ondelete="CASCADE"))
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))

    attempt_no = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default="submitted")
    score = db.Column(db.Float, default=0)
    max_score = db.Column(db.Float, default=0)

    answers_json = db.Column(db.Text)

    started_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    submitted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    ended_at = db.Column(db.DateTime(timezone=True))

    test = db.relationship("Test", backref=db.backref("submissions", lazy=True, cascade="all, delete-orphan"))
    student = db.relationship("User")


# -------------------------
# QUESTION SYSTEM
# -------------------------

class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)

    assignment_id = db.Column(
        db.Integer,
        db.ForeignKey("assignments.id", ondelete="CASCADE")
    )

    question_text = db.Column(db.Text, nullable=False)

    question_type = db.Column(db.String(20))
    # mcq
    # multiple_select
    # fill_blank

    marks = db.Column(db.Integer, default=1)

    order_index = db.Column(db.Integer, default=0)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    assignment = db.relationship("Assignment", backref=db.backref("questions", lazy=True, cascade="all, delete-orphan"))


class QuestionOption(db.Model):
    __tablename__ = "question_options"

    id = db.Column(db.Integer, primary_key=True)

    question_id = db.Column(
        db.Integer,
        db.ForeignKey("questions.id", ondelete="CASCADE")
    )

    option_text = db.Column(db.String(500))

    is_correct = db.Column(db.Boolean, default=False)

    question = db.relationship("Question", backref=db.backref("options", lazy=True, cascade="all, delete-orphan"))


class FillBlankAnswer(db.Model):
    __tablename__ = "fill_blank_answers"

    id = db.Column(db.Integer, primary_key=True)

    question_id = db.Column(
        db.Integer,
        db.ForeignKey("questions.id", ondelete="CASCADE")
    )

    correct_answer = db.Column(db.String(255))

    question = db.relationship("Question", backref=db.backref("blank_answers", lazy=True, cascade="all, delete-orphan"))


# -------------------------
# STUDENT ANSWERS
# -------------------------

class StudentAnswer(db.Model):
    __tablename__ = "student_answers"

    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))

    question_id = db.Column(db.Integer, db.ForeignKey("questions.id", ondelete="CASCADE"))

    selected_option_id = db.Column(
        db.Integer,
        db.ForeignKey("question_options.id", ondelete="CASCADE")
    )

    text_answer = db.Column(db.String(500))

    marks_obtained = db.Column(db.Float, default=0.0)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    student = db.relationship("User", backref=db.backref("answers", lazy=True, cascade="all, delete-orphan"))

    question = db.relationship("Question")

    option = db.relationship("QuestionOption")

class AssignmentSubmission(db.Model):
    __tablename__ = "assignment_submissions"

    id = db.Column(db.Integer, primary_key=True)

    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id", ondelete="CASCADE"))
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))

    submitted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    
    score = db.Column(db.Float, default=0.0)
    total_possible = db.Column(db.Float, default=0.0)
    percentage = db.Column(db.Float, default=0.0)
    is_graded = db.Column(db.Boolean, default=False)
    graded_at = db.Column(db.DateTime(timezone=True))
    graded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    assignment = db.relationship("Assignment", backref=db.backref("submissions", lazy=True, cascade="all, delete-orphan"))
    
    # FIX: Explicitly add the foreign key constraint here as well
    student = db.relationship("User", foreign_keys=[student_id])
    
    grader = db.relationship("User", foreign_keys=[graded_by])



# -------------------------
# COURSE PROGRESS
# -------------------------

class CourseProgress(db.Model):
    __tablename__ = "course_progress"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"))
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id', ondelete="CASCADE"))
    content_type = db.Column(db.String(50))
    content_key = db.Column(db.String(100))
    completed = db.Column(db.Boolean, default=False)
    # completed_at = db.Column(db.DateTime)
    student = db.relationship("User", backref=db.backref("course_progress", lazy=True, cascade="all, delete-orphan"))
    course = db.relationship("Course", backref=db.backref("course_progress", lazy=True, cascade="all, delete-orphan"))

# live class model
class LiveClass(db.Model):
    __tablename__ = "live_classes"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    start_time = db.Column(db.DateTime(timezone=True), nullable=False)
    end_time = db.Column(db.DateTime(timezone=True), nullable=False)

    meeting_link = db.Column(db.String(500))
    instructor_name = db.Column(db.String(100))
    status = db.Column(db.String(30), default="Scheduled") # Scheduled | Live | Completed | Cancelled

    message = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    course = db.relationship("Course", backref=db.backref("live_classes", lazy=True, cascade="all, delete-orphan"))

# subscribe models
class Subscriber(db.Model):
    __tablename__ = "subscribers"

    id = db.Column(db.Integer, primary_key=True)

    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    message = db.Column(db.String(1000), nullable=True)

    subscribed_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    
# certificates table
class Certificate(db.Model):
    __tablename__ = "certificates"

    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"))
    course_code = db.Column(db.String(20), nullable=False)
    duration_months = db.Column(db.Integer, nullable=True)
    completion_date = db.Column(db.Date, nullable=True)
    grade = db.Column(db.String(10), nullable=True)
    project_title = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    instructor_name = db.Column(db.String(100), nullable=True)
    certificate_number = db.Column(db.String(50), unique=True, nullable=False)
    

    verification_token = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default="verified")  # verified | revoked | expired

    issued_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    student = db.relationship("User", backref=db.backref("certificates", lazy=True, cascade="all, delete-orphan"))
    course = db.relationship("Course", backref=db.backref("certificates", lazy=True, cascade="all, delete-orphan"))