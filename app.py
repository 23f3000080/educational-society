from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_security import Security, SQLAlchemyUserDatastore
from flask_security.utils import hash_password
from datetime import datetime
import uuid
from flask_cors import CORS
import pytz
from flask_migrate import Migrate

# Import routes, config, and models
from Routes.base_route import base_bp
from Routes.user_route import user_bp
from Routes.owner_route import owner_bp
from Routes.admin_course_routes import admin_course_bp
from Routes.admin_assignment_routes import admin_assignment_bp
from Routes.admin_test_routes import admin_test_bp
from Routes.student_test_routes import student_test_bp
from Routes.chatbot_routes import chatbot_bp
from config import LocalDevelopmentConfig
from models import db, User, Role


load_dotenv()

# Setup user datastore
user_datastore = SQLAlchemyUserDatastore(db, User, Role)


def create_app():
    app = Flask(__name__)
    app.config.from_object(LocalDevelopmentConfig)
    CORS(app)

    db.init_app(app)
    migrate = Migrate(app, db)

    # Setup Flask-Security-Too
    Security(app, user_datastore)

    with app.app_context():
        db.create_all()
        app.register_blueprint(base_bp)
        app.register_blueprint(user_bp)
        app.register_blueprint(owner_bp)
        app.register_blueprint(admin_course_bp)
        app.register_blueprint(admin_assignment_bp)
        app.register_blueprint(admin_test_bp)
        app.register_blueprint(student_test_bp)
        app.register_blueprint(chatbot_bp)
        setup_default_users(user_datastore)

    return app


def setup_default_users(user_datastore):
    """Ensure roles and default users exist"""

    # Create roles if they don't exist
    for role_name, role_desc in [("admin", "Administrator role"), ("user", "Normal user role")]:
        if not user_datastore.find_role(role_name):
            user_datastore.create_role(name=role_name, description=role_desc)

    db.session.commit()

    itz = pytz.timezone("Asia/Kolkata")
    current_time = datetime.now(itz)

    # Create admin user if not exists
    if not user_datastore.find_user(email="ankitkumar7768523@gmail.com"):
        admin_user = user_datastore.create_user(
            email="ankitkumar7768523@gmail.com",
            fs_uniquifier=str(uuid.uuid4()),
            user_id="ADM001",
            password=hash_password("12345"),
            first_name="Admin",
            last_name="Jha",
            mobile_no="9999999999",
            country="India",
            state="Bihar",
            city="Patna",
            joining_date=current_time,
            active=True
        )
        user_datastore.add_role_to_user(admin_user, "admin")

    # Create normal user if not exists
    if not user_datastore.find_user(email="user@gmail.com"):
        normal_user = user_datastore.create_user(
            email="user@gmail.com",
            fs_uniquifier=str(uuid.uuid4()),
            user_id="USER01",
            password=hash_password("1234"),
            first_name="User",
            last_name="Jha",
            mobile_no="8888888888",
            country="India",
            state="Bihar",
            city="Patna",
            joining_date=current_time,
            active=True
        )
        user_datastore.add_role_to_user(normal_user, "user")

    db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
