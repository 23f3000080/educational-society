from flask import current_app
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

def send_plain_email(to_email, subject, body):
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

    if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
        raise Exception("Email credentials are not set in environment variables")

    msg = MIMEMultipart()
    msg["From"] = EMAIL_HOST_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
        smtp.send_message(msg)


def send_reset_code_email(to_email, reset_code):
    subject = "Your Password Reset Code"

    body = f"""
Hello,

Your password reset code is:

{reset_code}

This code is valid for 10 minutes.

Regards,
Educational Society Team
"""

    send_plain_email(to_email, subject, body)


# ✅ NEW FUNCTION: Send Email OTP
def send_email_verification_otp(to_email, otp):
    subject = "Email Verification OTP"

    body = f"""
Hello,

Your email verification OTP is:

{otp}

⏳ This OTP is valid for 5 minutes.

If you did not request this, please ignore this email.

Regards,
Educational Society Team
"""

    send_plain_email(to_email, subject, body)


def send_course_enrollment_email(to_email, student_name, course_title, enrollment_date=None):
    subject = f"Enrollment Confirmed - {course_title}"
    body = f"""
Hello {student_name or 'Student'},

Your enrollment is confirmed for:
Course: {course_title}
Enrollment date: {enrollment_date or 'N/A'}

You can now access course content, assignments, and tests from your dashboard.

Regards,
Educational Society Team
"""
    send_plain_email(to_email, subject, body)


def send_assignment_added_email(to_email, student_name, course_title, assignment_title, week_title=None, due_date=None):
    subject = f"New Assignment Added - {course_title}"
    body = f"""
Hello {student_name or 'Student'},

A new assignment has been added to your enrolled course.
Course: {course_title}
Week: {week_title or 'N/A'}
Assignment: {assignment_title}
Due date: {due_date or 'Not set'}

Please login to your student dashboard and complete it before the deadline.

Regards,
Educational Society Team
"""
    send_plain_email(to_email, subject, body)


def send_test_created_email(to_email, student_name, course_title, test_title, week_title=None, due_date=None):
    subject = f"New Test Available - {course_title}"
    body = f"""
Hello {student_name or 'Student'},

A new test has been created for your enrolled course.
Course: {course_title}
Week: {week_title or 'General'}
Test: {test_title}
Due date: {due_date or 'Not set'}

Please attempt the test from your Student Tests page before the due date.

Regards,
Educational Society Team
"""
    send_plain_email(to_email, subject, body)


def send_test_result_email(to_email, student_name, course_title, test_title, score=None, max_score=None):
    subject = f"Test Result Update - {test_title}"
    result_line = ""
    if score is not None and max_score is not None:
        result_line = f"Score: {score}/{max_score}"

    body = f"""
Hello {student_name or 'Student'},

Your test result is available.
Course: {course_title or 'N/A'}
Test: {test_title}
{result_line}

Please login to your dashboard to view detailed result analysis.

Regards,
Educational Society Team
"""
    send_plain_email(to_email, subject, body)


def send_week_added_email(to_email, student_name, course_title, week_number, week_title):
    subject = f"New Week Added - {course_title}"
    body = f"""
Hello {student_name or 'Student'},

New content is now available in your enrolled course.
Course: {course_title}
Week: Week {week_number} - {week_title}

Login to your dashboard to access new videos, notes, assignments, and tests.

Regards,
Educational Society Team
"""
    send_plain_email(to_email, subject, body)


def send_query_resolution_email(to_email, person_name, query_status, response_text):
    subject = "Support Query Update"
    body = f"""
Hello {person_name or 'Student'},

Your support query has been updated.
Status: {query_status}

Resolution message:
{response_text}

If you need more help, please raise a new query from the support section.

Regards,
Educational Society Team
"""
    send_plain_email(to_email, subject, body)
