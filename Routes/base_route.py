from flask import Blueprint, request, jsonify
from models import *
from flask_security.utils import hash_password, verify_password
import uuid, random, string
import pytz
from datetime import datetime, timedelta
from communication.email_sender import send_reset_code_email, send_email_verification_otp
import jwt
from functools import wraps
from flask import current_app

base_bp = Blueprint("base", __name__)
IST = pytz.timezone("Asia/Kolkata")


def to_ist_iso(dt_value):
    if not dt_value:
        return None

    if dt_value.tzinfo is None:
        dt_value = pytz.utc.localize(dt_value)

    return dt_value.astimezone(IST).isoformat()

# Unique user_id generator
def generate_unique_user_id():
    while True:
        user_id = 'ST' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        existing_user_id = User.query.filter_by(user_id=user_id).first()
        
        if not existing_user_id:
            return user_id
        
# JWT generation
def generate_jwt(user, remember_me=False):
    expiry = timedelta(days=7) if remember_me else timedelta(hours=24)

    payload = {
        "user_id": user.id,
        "email": user.email,
        "role": user.roles[0].name if user.roles else "user",
        "exp": datetime.now(pytz.utc) + expiry
    }

    # print("Generating JWT with payload:", payload)
    return jwt.encode(
        payload,
        current_app.config["SECRET_KEY"],
        algorithm="HS256"
    )

# Token required decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        # print("AUTH HEADER RECEIVED:", auth_header)

        if not auth_header:
            return jsonify({"error": "Token missing"}), 401

        # Extract token from "Bearer <token>" format
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        else:
            token = auth_header  # raw token

        try:
            payload = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"]
            )

            current_user = User.query.get(payload["user_id"])

            if not current_user:
                return jsonify({"error": "User not found"}), 401

            if not current_user.active:
                return jsonify({"error": "Account suspended"}), 403

        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        return f(current_user, *args, **kwargs)

    return decorated


# Roles required decorator
def roles_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapped(current_user, *args, **kwargs):
            # Extract role names
            user_roles = [role.name for role in current_user.roles]

            if not set(user_roles).intersection(allowed_roles):
                return jsonify({
                    "error": "You do not have permission to access this resource"
                }), 403

            return f(current_user, *args, **kwargs)

        return wrapped
    return decorator

@base_bp.route('/api/auth/register', methods=['POST'])
def register_user():
    data = request.get_json(silent=True)
    # validate fields are empty or null
    if not data:
        return jsonify({"error": "Invalid or missing JSON"}), 400

    for key, value in data.items():
        if not value:
            return jsonify({"error": f"Field '{key}' is required"}), 400
    
    # check email verified or not
    verified = EmailOTP.query.filter_by(email=data.get("email")).first()
    if verified:
        return jsonify({"error": "Please verify your email first"}), 400


    # Validate password length
    if len(data.get("password", "")) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400
    
    # validate password and confirm password
    if data.get("password") != data.get("confirmPassword"):
        return jsonify({"error": "Passwords do not match"}), 400
    
    # validate user exist or not
    existing_user = User.query.filter_by(email=data.get("email")).first()
    if existing_user:
        return jsonify({"error": "* User already exists *"}), 400
    
    # add user in database
    first_name = data.get("fullName").split(" ")[0]
    # last name from 1 to end
    last_name = " ".join(data.get("fullName").split(" ")[1:]) if len(data.get("fullName").split(" ")) > 1 else ""
    hashed_password = hash_password(data.get("password"))

    user_id = generate_unique_user_id()

    # datetime
    itz = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(itz)

    new_user = User(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        email=data.get("email"),
        password=hashed_password,
        is_email_verified=False,
        fs_uniquifier=str(uuid.uuid4()),
        is_mobile_verified=False,
        country="N/A",
        joining_date=current_time,
        active=True,
    )
    db.session.add(new_user)
    db.session.commit()
    # create userrole
    user_id = User.query.filter_by(email=data.get("email")).first().id
    user_role = UsersRoles(user_id=user_id, role_id=2)  # 2 is the role_id for 'user'
    db.session.add(user_role)
    db.session.commit()

    return jsonify({
        "message": "Registration successful! Redirecting to login...",
    }), 200

@base_bp.route("/api/auth/send-email-otp", methods=["POST"])
def send_email_otp_route():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required"}), 400

    otp = str(random.randint(100000, 999999))
    expiry_time = datetime.now() + timedelta(minutes=5)

    EmailOTP.query.filter_by(email=email).delete()

    db.session.add(
        EmailOTP(email=email, otp=otp, expires_at=expiry_time)
    )
    db.session.commit()

    send_email_verification_otp(
        to_email=email,
        otp=otp
    )

    return jsonify({"message": "OTP sent to your email (valid for 5 minutes)"}), 200



@base_bp.route("/api/auth/verify-email-otp", methods=["POST"])
def verify_email_otp():
    data = request.get_json()
    email = data.get("email")
    otp = data.get("otp")

    record = EmailOTP.query.filter_by(email=email, otp=otp).first()

    if not record:
        return jsonify({"error": "Invalid OTP"}), 400

    if datetime.now() > record.expires_at:
        db.session.delete(record)
        db.session.commit()
        return jsonify({"error": "OTP expired. Please resend OTP"}), 400

    db.session.delete(record)
    db.session.commit()

    return jsonify({"message": "Email verified successfully"}), 200


@base_bp.route("/api/auth/send-mobile-otp", methods=["POST"])
@token_required
@roles_required("user", "admin")
def send_mobile_otp_route(current_user):
    data = request.get_json(silent=True) or {}
    mobile_no = (data.get("mobile_no") or current_user.mobile_no or "").strip()

    if not mobile_no:
        return jsonify({"error": "Mobile number is required"}), 400

    otp = str(random.randint(100000, 999999))
    expiry_time = datetime.now() + timedelta(minutes=5)

    MobileOTP.query.filter_by(user_id=current_user.id, mobile_no=mobile_no).delete()
    db.session.add(
        MobileOTP(
            user_id=current_user.id,
            mobile_no=mobile_no,
            otp=otp,
            expires_at=expiry_time
        )
    )
    db.session.commit()

    response = {"message": "OTP stored for mobile verification (valid for 5 minutes)"}
    if current_app.debug:
        response["dev_otp"] = otp

    return jsonify(response), 200


@base_bp.route("/api/auth/verify-mobile-otp", methods=["POST"])
@token_required
@roles_required("user", "admin")
def verify_mobile_otp_route(current_user):
    data = request.get_json(silent=True) or {}
    mobile_no = (data.get("mobile_no") or current_user.mobile_no or "").strip()
    otp = str(data.get("otp", "")).strip()

    if not mobile_no or not otp:
        return jsonify({"error": "mobile_no and otp are required"}), 400

    record = MobileOTP.query.filter_by(
        user_id=current_user.id,
        mobile_no=mobile_no,
        otp=otp
    ).order_by(MobileOTP.id.desc()).first()

    if not record:
        return jsonify({"error": "Invalid OTP"}), 400

    if datetime.now() > record.expires_at:
        MobileOTP.query.filter_by(user_id=current_user.id, mobile_no=mobile_no).delete()
        db.session.commit()
        return jsonify({"error": "OTP expired. Please resend OTP"}), 400

    current_user.mobile_no = mobile_no
    current_user.is_mobile_verified = True

    MobileOTP.query.filter_by(user_id=current_user.id, mobile_no=mobile_no).delete()
    db.session.commit()

    return jsonify({"message": "Mobile number verified successfully"}), 200

# API for login
@base_bp.route('/api/auth/login', methods=['POST'])
def login_user():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Invalid or missing JSON"}), 400

    email = data.get("email")
    password = data.get("password")
    remember_me = data.get("rememberMe", False)

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = User.query.filter_by(email=email).first()

    if not user:
        return jsonify({"error": "Invalid email"}), 401

    if not verify_password(password, user.password):
        return jsonify({"error": "Invalid password"}), 401

    # check if user active
    if not user.active:
        return jsonify({"error": "You are suspended! Please contact Admin."}), 403

    # ✅ extract role name safely
    role_name = user.roles[0].name if user.roles else "user"

    # ✅ apply mapping rule
    role = "student" if role_name == "user" else role_name

    user_data = {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "user_id": user.user_id,
        "role": role,            # ✅ string only
        "email": user.email
    }

    token = generate_jwt(user, remember_me)

    return jsonify({
        "success": True,
        "message": "Login successful!",
        "user": user_data,
        "token": token
    }), 200


# API for Google Login
@base_bp.route('/api/auth/google-login', methods=['POST'])
def google_login():
    """Handle Google OAuth login - creates session for existing Google users"""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    
    data = request.get_json(silent=True)
    
    if not data or not data.get("token"):
        return jsonify({"error": "Google token is required"}), 400
    
    try:
        # Verify Google token
        idinfo = id_token.verify_oauth2_token(
            data.get("token"),
            google_requests.Request()
        )
        
        # Token is valid, get user info
        google_email = idinfo.get("email")
        google_id = idinfo.get("sub")
        first_name = idinfo.get("given_name", "")
        last_name = idinfo.get("family_name", "")
        
        if not google_email:
            return jsonify({"error": "Unable to get email from Google"}), 400
        
        # Find user by email
        user = User.query.filter_by(email=google_email).first()
        
        if not user:
            return jsonify({"error": "User not found. Please sign up first."}), 404
        
        # check if user active
        if not user.active:
            return jsonify({"error": "You are suspended! Please contact Admin."}), 403
        
        # Generate JWT token
        role_name = user.roles[0].name if user.roles else "user"
        role = "student" if role_name == "user" else role_name
        
        user_data = {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "user_id": user.user_id,
            "role": role,
            "email": user.email
        }
        
        token = generate_jwt(user, remember_me=True)
        
        return jsonify({
            "success": True,
            "message": "Google login successful!",
            "user": user_data,
            "token": token
        }), 200
        
    except ValueError as e:
        return jsonify({"error": f"Invalid Google token: {str(e)}"}), 401


# API for Google Sign Up
@base_bp.route('/api/auth/google-signup', methods=['POST'])
def google_signup():
    """Handle Google OAuth signup - creates new account for Google users"""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    
    data = request.get_json(silent=True)
    
    if not data or not data.get("token"):
        return jsonify({"error": "Google token is required"}), 400
    
    try:
        # Verify Google token
        idinfo = id_token.verify_oauth2_token(
            data.get("token"),
            google_requests.Request()
        )
        
        # Token is valid, get user info
        google_email = idinfo.get("email")
        google_id = idinfo.get("sub")
        first_name = idinfo.get("given_name", "")
        last_name = idinfo.get("family_name", "")
        
        if not google_email:
            return jsonify({"error": "Unable to get email from Google"}), 400
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=google_email).first()
        
        if existing_user:
            return jsonify({"error": "User with this email already exists. Please login instead."}), 409
        
        # Create new user with Google ID as password (never used, but required field)
        user = User(
            email=google_email,
            first_name=first_name,
            last_name=last_name,
            password=hash_password(google_id + "google_oauth"),  # Hash Google ID for security
            user_id=generate_unique_user_id(),
            is_email_verified=True,  # Google email is verified by Google
            fs_uniquifier=str(uuid.uuid4()),
            active=True
        )
        
        # Assign default 'student' role
        user_role = Role.query.filter_by(name='user').first()
        if user_role:
            user.roles.append(user_role)
        
        db.session.add(user)
        db.session.commit()
        
        # Generate JWT token
        role = "student"  # New users are students
        
        user_data = {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "user_id": user.user_id,
            "role": role,
            "email": user.email
        }
        
        token = generate_jwt(user, remember_me=True)
        
        return jsonify({
            "success": True,
            "message": "Google signup successful! Account created.",
            "user": user_data,
            "token": token
        }), 201
        
    except ValueError as e:
        return jsonify({"error": f"Invalid Google token: {str(e)}"}), 401
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Signup failed: {str(e)}"}), 500


# API for forgot password
@base_bp.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "Email not found"}), 404

    reset_code = ''.join(random.choices(string.digits, k=6))
    expiry_time = datetime.now() + timedelta(minutes=10)

    user.reset_code = reset_code
    user.reset_code_expiry = expiry_time
    db.session.commit()

    print(f"Reset code for {user.email}: {reset_code}")  # For debugging purposes
    # send email here
    send_reset_code_email(user.email, reset_code)

    return jsonify({
        "message": "Reset code sent to email"
    }), 200


@base_bp.route('/api/auth/verify-reset-code', methods=['POST'])
def verify_reset_code():
    data = request.get_json(silent=True)

    email = data.get("email")
    code = data.get("code")

    if not email or not code:
        return jsonify({"error": "Email and code required"}), 400

    user = User.query.filter_by(email=email).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    if user.reset_code != code:
        return jsonify({"error": "Invalid reset code"}), 400

    if datetime.now() > user.reset_code_expiry:
        return jsonify({"error": "Reset code expired"}), 400

    return jsonify({
        "message": "Code verified. Proceed to reset password"
    }), 200


@base_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True)

    email = data.get("email")
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")

    if not all([email, new_password, confirm_password]):
        return jsonify({"error": "All fields required"}), 400

    if new_password != confirm_password:
        return jsonify({"error": "Passwords do not match"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.password = hash_password(new_password)
    user.reset_code = None
    user.reset_code_expiry = None

    db.session.commit()

    return jsonify({
        "message": "Password reset successful"
    }), 200

# contactus API
@base_bp.route('/api/contactus', methods=['POST'])
def contact_us():
    data = request.get_json(silent=True)

    name = data.get("name")
    email = data.get("email")
    issue_type = data.get("issue_type")
    message = data.get("message")

    if not all([name, email, issue_type, message]):
        return jsonify({"error": "All fields required"}), 400

    allowed_issue_types = {"admission", "fees", "technical", "course", "other"}
    issue_type_normalized = str(issue_type).strip().lower()
    if issue_type_normalized not in allowed_issue_types:
        return jsonify({"error": "Invalid issue type"}), 400

    name = str(name).strip()
    email = str(email).strip().lower()
    message = str(message).strip()

    if not all([name, email, message]):
        return jsonify({"error": "All fields required"}), 400

    new_message = QueryModel(
        person_name=name,
        email=email,
        issue_type=issue_type_normalized,
        query_text=message,
        raised_at=datetime.now(timezone.utc)
    )
    db.session.add(new_message)
    db.session.commit()

    return jsonify({
        "message": "Your message has been received. We'll get back to you soon!"
    }), 200

# api to check query status using user email
@base_bp.route('/api/query-status', methods=['POST'])
def query_status():
    data = request.get_json(silent=True)

    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required"}), 400

    messages = QueryModel.query.filter_by(email=email).all()

    if not messages:
        return jsonify({"error": "No queries found for this email"}), 404

    response_data = []
    for msg in messages:
        response_data.append({
            "id": msg.id,
            "name": msg.person_name,
            "email": msg.email,
            "issue_type": msg.issue_type,
            "query": msg.query_text,
            "raised_at": to_ist_iso(msg.raised_at),
            "response": msg.response_text,
            "status": msg.status,
            "response_at": to_ist_iso(msg.response_at),
            "response_date": to_ist_iso(msg.response_at),
            "responded_by": msg.responded_by

        })

    return jsonify({
        "queries": response_data
    }), 200

# API to get and set subscriber emails
@base_bp.route('/api/subscribers', methods=['GET', 'POST'])
def add_subscribers():
    if request.method == 'POST':
        data = request.get_json(silent=True)
        email = data.get("email")

        if not email:
            return jsonify({"error": "Email is required"}), 400

        existing_subscriber = Subscriber.query.filter_by(email=email).first()
        if existing_subscriber:
            return jsonify({"error": "You are already subscribed"}), 400

        new_subscriber = Subscriber(email=email)
        db.session.add(new_subscriber)
        db.session.commit()

        # response with a cachy message

        return jsonify({"message": "You’re in! Thanks for joining us."}), 200
    else:
        # something went wrong message
        return jsonify({"error": "Invalid request"}), 400