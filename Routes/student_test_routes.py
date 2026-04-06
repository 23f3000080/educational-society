from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import random

from models import (
    db,
    Course,
    Enrollment,
    Test,
    TestQuestion,
    TestQuestionOption,
    TestFillBlankAnswer,
    TestSubmission,
)
from Routes.base_route import token_required, roles_required
from communication.email_sender import send_test_result_email

student_test_bp = Blueprint('student_test', __name__)
IST = ZoneInfo('Asia/Kolkata')


def _now_ist():
    return datetime.now(IST)


def _to_ist_aware(dt_value):
    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=IST)
    return dt_value.astimezone(IST)


def _to_ist_iso(dt_value):
    aware = _to_ist_aware(dt_value)
    return aware.isoformat() if aware else None


def _enrolled_course_ids(current_user):
    enrollments = Enrollment.query.filter_by(
        student_id=current_user.id,
        payment_status='paid',
        enrollment_status='active'
    ).all()
    return {enrollment.course_id for enrollment in enrollments}


def _test_attempts_used(test_id, student_id):
    return TestSubmission.query.filter_by(test_id=test_id, student_id=student_id).count()


def _test_schedule_state(test):
    current_time = _now_ist()
    start_at = _to_ist_aware(test.start_at)
    due_date = _to_ist_aware(test.due_date)

    if not test.is_active:
        return 'inactive'

    if start_at and current_time < start_at:
        return 'upcoming'

    if due_date and current_time > due_date:
        return 'expired'

    return 'active'


def _serialize_test(test, current_user=None):
    course = Course.query.get(test.course_id) if test.course_id else None
    week = test.week if test.week_id else None
    attempts_used = _test_attempts_used(test.id, current_user.id) if current_user else 0
    max_attempts = test.max_attempts or 1
    remaining_attempts = max(0, max_attempts - attempts_used)
    schedule_state = _test_schedule_state(test)

    return {
        'id': test.id,
        'title': test.title,
        'description': test.description,
        'course_id': test.course_id,
        'course_title': course.title if course else None,
        'course_code': course.course_code if course else None,
        'week_id': test.week_id,
        'week_number': week.week_number if week else None,
        'week_title': week.title if week else None,
        'test_scope': test.test_scope,
        'duration_minutes': test.duration_minutes or 60,
        'start_at': _to_ist_iso(test.start_at),
        'due_date': _to_ist_iso(test.due_date),
        'total_marks': test.total_marks or 0,
        'max_attempts': max_attempts,
        'passcode_required': bool(test.passcode),
        'shuffle_questions': bool(test.shuffle_questions),
        'shuffle_options': bool(test.shuffle_options),
        'require_fullscreen': bool(test.require_fullscreen),
        'prevent_tab_switch': bool(test.prevent_tab_switch),
        'is_active': bool(test.is_active),
        'schedule_state': schedule_state,
        'attempts_used': attempts_used,
        'remaining_attempts': remaining_attempts,
        'can_attempt': schedule_state == 'active' and remaining_attempts > 0
    }


def _serialize_question(question, shuffle_options=False):
    payload = {
        'id': question.id,
        'question_text': question.question_text,
        'question_type': question.question_type,
        'marks': question.marks,
        'order_index': question.order_index,
        'options': []
    }

    if question.question_type in ['mcq', 'multiple_select']:
        options = list(TestQuestionOption.query.filter_by(question_id=question.id).order_by(TestQuestionOption.id).all())
        if shuffle_options:
            random.shuffle(options)

        payload['options'] = [
            {
                'id': option.id,
                'option_text': option.option_text
            }
            for option in options
        ]

    return payload


def _parse_answers(payload):
    answers = payload.get('answers', [])
    if isinstance(answers, dict):
        answers = list(answers.values())
    if not isinstance(answers, list):
        return []
    return answers


def _normalize_answers_payload(answers_json):
    if not answers_json:
        return []

    try:
        parsed = json.loads(answers_json)
    except (ValueError, TypeError):
        return []

    if isinstance(parsed, dict):
        return list(parsed.values())
    if isinstance(parsed, list):
        return parsed
    return []


def _build_submission_question_details(test_id, submission):
    answers_payload = _normalize_answers_payload(submission.answers_json)
    answers_map = {
        str(item.get('question_id')): item
        for item in answers_payload
        if isinstance(item, dict) and item.get('question_id') is not None
    }

    questions = TestQuestion.query.filter_by(test_id=test_id).order_by(TestQuestion.order_index, TestQuestion.id).all()
    details = []

    for index, question in enumerate(questions, start=1):
        answer_item = answers_map.get(str(question.id), {})
        selected_answer = None
        correct_answer = None
        is_correct = False
        earned_marks = 0.0
        options_payload = []

        if question.question_type == 'mcq':
            options = TestQuestionOption.query.filter_by(question_id=question.id).order_by(TestQuestionOption.id).all()
            selected_option_id = answer_item.get('selected_option_id')
            correct_option = next((opt for opt in options if opt.is_correct), None)
            selected_option = next((opt for opt in options if str(opt.id) == str(selected_option_id)), None)

            selected_answer = selected_option.option_text if selected_option else None
            correct_answer = correct_option.option_text if correct_option else None
            is_correct = bool(correct_option and selected_option and correct_option.id == selected_option.id)
            earned_marks = float(question.marks or 0) if is_correct else 0.0

            options_payload = [
                {
                    'id': opt.id,
                    'option_text': opt.option_text,
                    'is_correct': bool(opt.is_correct),
                    'is_selected': bool(selected_option and selected_option.id == opt.id)
                }
                for opt in options
            ]

        elif question.question_type == 'multiple_select':
            options = TestQuestionOption.query.filter_by(question_id=question.id).order_by(TestQuestionOption.id).all()
            selected_ids = {
                str(item).strip()
                for item in (answer_item.get('selected_option_ids') or [])
                if str(item).strip()
            }

            selected_texts = [opt.option_text for opt in options if str(opt.id) in selected_ids]
            correct_texts = [opt.option_text for opt in options if opt.is_correct]

            selected_answer = selected_texts
            correct_answer = correct_texts
            earned_marks, is_correct = _score_multiple_select(question, answer_item.get('selected_option_ids') or [])

            options_payload = [
                {
                    'id': opt.id,
                    'option_text': opt.option_text,
                    'is_correct': bool(opt.is_correct),
                    'is_selected': str(opt.id) in selected_ids
                }
                for opt in options
            ]

        elif question.question_type == 'fill_blank':
            entered_text = (answer_item.get('text_answer') or '').strip()
            valid_answers = [
                (row.correct_answer or '').strip()
                for row in TestFillBlankAnswer.query.filter_by(question_id=question.id).all()
                if (row.correct_answer or '').strip()
            ]
            selected_answer = entered_text or None
            correct_answer = valid_answers
            normalized_entered = entered_text.lower()
            is_correct = bool(normalized_entered and normalized_entered in {ans.lower() for ans in valid_answers})
            earned_marks = float(question.marks or 0) if is_correct else 0.0

        details.append({
            'question_id': question.id,
            'question_no': index,
            'question_text': question.question_text,
            'question_type': question.question_type,
            'marks': float(question.marks or 0),
            'earned_marks': round(float(earned_marks), 2),
            'is_correct': bool(is_correct),
            'selected_answer': selected_answer,
            'correct_answer': correct_answer,
            'options': options_payload
        })

    return details


def _score_mcq(question, selected_option_id):
    if selected_option_id in (None, ''):
        return 0.0, False

    correct_option = TestQuestionOption.query.filter_by(question_id=question.id, is_correct=True).first()
    is_correct = bool(correct_option and str(correct_option.id) == str(selected_option_id))
    return (float(question.marks) if is_correct else 0.0), is_correct


def _score_multiple_select(question, selected_option_ids):
    selected_ids = {str(item).strip() for item in (selected_option_ids or []) if str(item).strip()}
    correct_ids = {
        str(option.id)
        for option in TestQuestionOption.query.filter_by(question_id=question.id, is_correct=True).all()
    }

    if not correct_ids:
        return 0.0, False

    correct_selected = len(selected_ids & correct_ids)
    incorrect_selected = len(selected_ids - correct_ids)
    ratio = (correct_selected - incorrect_selected) / len(correct_ids)
    earned = max(0.0, ratio * float(question.marks))
    return round(earned, 2), selected_ids == correct_ids


def _score_fill_blank(question, text_answer):
    normalized = (text_answer or '').strip().lower()
    if not normalized:
        return 0.0, False

    valid_answers = {
        (answer.correct_answer or '').strip().lower()
        for answer in TestFillBlankAnswer.query.filter_by(question_id=question.id).all()
        if answer.correct_answer
    }

    is_correct = normalized in valid_answers if valid_answers else False
    return (float(question.marks) if is_correct else 0.0), is_correct


def _get_accessible_tests(current_user):
    course_ids = _enrolled_course_ids(current_user)
    if not course_ids:
        return []

    tests = Test.query.filter(
        Test.course_id.in_(course_ids),
        Test.is_active.is_(True)
    ).order_by(Test.created_at.desc()).all()

    return tests


@student_test_bp.route('/api/student/tests', methods=['GET'])
@token_required
@roles_required('user')
def list_student_tests(current_user):
    tests = _get_accessible_tests(current_user)
    result = [_serialize_test(test, current_user=current_user) for test in tests]
    return jsonify(result), 200


@student_test_bp.route('/api/student/tests/<int:test_id>/access', methods=['POST'])
@token_required
@roles_required('user')
def access_student_test(current_user, test_id):
    test = Test.query.get_or_404(test_id)

    if test.course_id not in _enrolled_course_ids(current_user):
        return jsonify({'error': 'You are not enrolled in the course for this test'}), 403

    schedule_state = _test_schedule_state(test)
    if schedule_state == 'inactive':
        return jsonify({'error': 'This test is inactive'}), 400
    if schedule_state == 'upcoming':
        return jsonify({'error': 'This test has not started yet'}), 400
    if schedule_state == 'expired':
        return jsonify({'error': 'This test has expired'}), 400

    attempts_used = _test_attempts_used(test.id, current_user.id)
    if attempts_used >= (test.max_attempts or 1):
        return jsonify({'error': 'You have used all allowed attempts for this test'}), 400

    data = request.get_json(silent=True) or {}
    expected_passcode = (test.passcode or '').strip()
    provided_passcode = (data.get('passcode') or '').strip()

    if expected_passcode and provided_passcode != expected_passcode:
        return jsonify({'error': 'Invalid test passcode'}), 403

    questions = TestQuestion.query.filter_by(test_id=test.id).order_by(TestQuestion.order_index, TestQuestion.id).all()
    questions_payload = [_serialize_question(question, shuffle_options=bool(test.shuffle_options)) for question in questions]
    if test.shuffle_questions:
        random.shuffle(questions_payload)

    return jsonify({
        'test': _serialize_test(test, current_user=current_user),
        'questions': questions_payload,
        'security': {
            'passcode_required': bool(test.passcode),
            'require_fullscreen': bool(test.require_fullscreen),
            'prevent_tab_switch': bool(test.prevent_tab_switch),
            'shuffle_questions': bool(test.shuffle_questions),
            'shuffle_options': bool(test.shuffle_options),
            'max_attempts': test.max_attempts or 1
        }
    }), 200


@student_test_bp.route('/api/student/tests/<int:test_id>/submit', methods=['POST'])
@token_required
@roles_required('user')
def submit_student_test(current_user, test_id):
    test = Test.query.get_or_404(test_id)

    if test.course_id not in _enrolled_course_ids(current_user):
        return jsonify({'error': 'You are not enrolled in the course for this test'}), 403

    schedule_state = _test_schedule_state(test)
    if schedule_state != 'active':
        return jsonify({'error': 'This test is not available for submission'}), 400

    attempts_used = _test_attempts_used(test.id, current_user.id)
    if attempts_used >= (test.max_attempts or 1):
        return jsonify({'error': 'You have used all allowed attempts for this test'}), 400

    data = request.get_json(silent=True) or {}
    expected_passcode = (test.passcode or '').strip()
    provided_passcode = (data.get('passcode') or '').strip()
    if expected_passcode and provided_passcode != expected_passcode:
        return jsonify({'error': 'Invalid test passcode'}), 403

    answers = _parse_answers(data)
    answers_map = {str(item.get('question_id')): item for item in answers if item.get('question_id') is not None}

    questions = TestQuestion.query.filter_by(test_id=test.id).order_by(TestQuestion.order_index, TestQuestion.id).all()
    scored_questions = []
    total_score = 0.0
    total_max_score = 0.0

    for question in questions:
        answer = answers_map.get(str(question.id), {})
        earned = 0.0
        is_correct = False

        if question.question_type == 'mcq':
            earned, is_correct = _score_mcq(question, answer.get('selected_option_id'))
        elif question.question_type == 'multiple_select':
            earned, is_correct = _score_multiple_select(question, answer.get('selected_option_ids') or answer.get('selected_option_id'))
        elif question.question_type == 'fill_blank':
            earned, is_correct = _score_fill_blank(question, answer.get('text_answer'))

        total_score += earned
        total_max_score += float(question.marks or 0)

        scored_questions.append({
            'question_id': question.id,
            'earned_marks': earned,
            'max_marks': float(question.marks or 0),
            'is_correct': is_correct
        })

    attempt_no = attempts_used + 1
    now = datetime.now(timezone.utc)
    submission = TestSubmission(
        test_id=test.id,
        student_id=current_user.id,
        attempt_no=attempt_no,
        status='submitted',
        score=round(total_score, 2),
        max_score=round(total_max_score, 2),
        answers_json=json.dumps(answers, ensure_ascii=False),
        started_at=now,
        submitted_at=now,
        ended_at=now
    )

    db.session.add(submission)
    db.session.commit()

    try:
        course = Course.query.get(test.course_id) if test.course_id else None
        student_name = " ".join([part for part in [current_user.first_name, current_user.last_name] if part]).strip() or "Student"
        send_test_result_email(
            to_email=current_user.email,
            student_name=student_name,
            course_title=course.title if course else f"Course #{test.course_id}",
            test_title=test.title,
            score=round(total_score, 2),
            max_score=round(total_max_score, 2),
        )
    except Exception as err:
        current_app.logger.warning(
            f"Test result email failed for test_id={test_id}, student_id={current_user.id}: {err}"
        )

    return jsonify({
        'message': 'Test submitted successfully',
        'submission': {
            'id': submission.id,
            'test_id': submission.test_id,
            'attempt_no': submission.attempt_no,
            'score': submission.score,
            'max_score': submission.max_score,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None
        },
        'breakdown': scored_questions
    }), 201


@student_test_bp.route('/api/student/tests/<int:test_id>/results', methods=['GET'])
@token_required
@roles_required('user')
def get_student_test_results(current_user, test_id):
    test = Test.query.get_or_404(test_id)

    if test.course_id not in _enrolled_course_ids(current_user):
        return jsonify({'error': 'You are not enrolled in the course for this test'}), 403

    if _test_schedule_state(test) != 'expired':
        return jsonify({'error': 'Results will be available after test due date passes'}), 400

    submissions = TestSubmission.query.filter_by(test_id=test_id, student_id=current_user.id).order_by(TestSubmission.attempt_no.desc(), TestSubmission.submitted_at.desc()).all()
    result_items = [
        {
            'submission_id': submission.id,
            'attempt_no': submission.attempt_no,
            'status': submission.status,
            'score': float(submission.score or 0),
            'max_score': float(submission.max_score or 0),
            'percentage': round((float(submission.score or 0) / float(submission.max_score or 0)) * 100, 2) if float(submission.max_score or 0) > 0 else 0.0,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None
        }
        for submission in submissions
    ]

    return jsonify({
        'test': _serialize_test(test, current_user=current_user),
        'results': result_items
    }), 200


@student_test_bp.route('/api/student/tests/<int:test_id>/results/<int:submission_id>', methods=['GET'])
@token_required
@roles_required('user')
def get_student_test_result_detail(current_user, test_id, submission_id):
    test = Test.query.get_or_404(test_id)

    if test.course_id not in _enrolled_course_ids(current_user):
        return jsonify({'error': 'You are not enrolled in the course for this test'}), 403

    if _test_schedule_state(test) != 'expired':
        return jsonify({'error': 'Results will be available after test due date passes'}), 400

    submission = TestSubmission.query.filter_by(id=submission_id, test_id=test_id, student_id=current_user.id).first_or_404()
    questions = _build_submission_question_details(test_id, submission)

    max_score = float(submission.max_score or 0)
    score = float(submission.score or 0)

    return jsonify({
        'test': _serialize_test(test, current_user=current_user),
        'submission': {
            'submission_id': submission.id,
            'attempt_no': submission.attempt_no,
            'status': submission.status,
            'score': score,
            'max_score': max_score,
            'percentage': round((score / max_score) * 100, 2) if max_score > 0 else 0.0,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None
        },
        'questions': questions
    }), 200
