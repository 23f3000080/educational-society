from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from models import Enrollment, db, Test, TestQuestion, TestQuestionOption, TestFillBlankAnswer, TestSubmission, Course, Week, User
from Routes.base_route import token_required, roles_required
from communication.email_sender import send_test_created_email

admin_test_bp = Blueprint('admin_test', __name__)
IST = ZoneInfo('Asia/Kolkata')


def _now_ist():
    return datetime.now(IST)


def _to_ist_aware(dt_value):
    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=IST)
    return dt_value.astimezone(IST)


def _parse_iso_datetime(value, field_name):
    if value in (None, ''):
        return None, None

    try:
        return datetime.fromisoformat(value), None
    except ValueError:
        return None, f'Invalid {field_name} format'


def _serialize_test(test, include_relations=False):
    course = Course.query.get(test.course_id) if include_relations and test.course_id else None
    week = Week.query.get(test.week_id) if include_relations and test.week_id else None

    return {
        'id': test.id,
        'title': test.title,
        'description': test.description,
        'course_id': test.course_id,
        'course_title': course.title if course else None,
        'week_id': test.week_id,
        'week_number': week.week_number if week else None,
        'week_title': week.title if week else None,
        'test_scope': test.test_scope,
        'duration_minutes': test.duration_minutes,
        'start_at': test.start_at.isoformat() if test.start_at else None,
        'due_date': test.due_date.isoformat() if test.due_date else None,
        'total_marks': test.total_marks,
        'total_points': test.total_marks,
        'max_attempts': test.max_attempts,
        'passcode_enabled': bool(test.passcode),
        'shuffle_questions': bool(test.shuffle_questions),
        'shuffle_options': bool(test.shuffle_options),
        'require_fullscreen': bool(test.require_fullscreen),
        'prevent_tab_switch': bool(test.prevent_tab_switch),
        'is_active': bool(test.is_active),
        'created_at': test.created_at.isoformat() if test.created_at else None,
        'updated_at': test.updated_at.isoformat() if test.updated_at else None
    }


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
    earned = max(0.0, ratio * float(question.marks or 0))
    return round(earned, 2), selected_ids == correct_ids


def _build_submission_details(test_id, submission):
    answers_payload = _normalize_answers_payload(submission.answers_json)
    answers_map = {
        str(item.get('question_id')): item
        for item in answers_payload
        if isinstance(item, dict) and item.get('question_id') is not None
    }

    question_rows = TestQuestion.query.filter_by(test_id=test_id).order_by(TestQuestion.order_index, TestQuestion.id).all()

    details = []
    for index, question in enumerate(question_rows, start=1):
        answer_item = answers_map.get(str(question.id), {})
        selected_answer = None
        correct_answer = None
        is_correct = False
        earned_marks = 0.0

        if question.question_type == 'mcq':
            options = TestQuestionOption.query.filter_by(question_id=question.id).order_by(TestQuestionOption.id).all()
            selected_id = answer_item.get('selected_option_id')
            selected_option = next((opt for opt in options if str(opt.id) == str(selected_id)), None)
            correct_option = next((opt for opt in options if opt.is_correct), None)

            selected_answer = selected_option.option_text if selected_option else None
            correct_answer = correct_option.option_text if correct_option else None
            is_correct = bool(correct_option and selected_option and correct_option.id == selected_option.id)
            earned_marks = float(question.marks or 0) if is_correct else 0.0

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

        else:
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
            'correct_answer': correct_answer
        })

    return details


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


@admin_test_bp.route('/api/admin/tests', methods=['GET'])
@token_required
@roles_required('admin')
def get_all_tests(current_user):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '', type=str).strip()
    course_id = request.args.get('course_id', type=int)
    week_id = request.args.get('week_id', type=int)
    status = request.args.get('status', '', type=str).strip().lower()

    query = Test.query

    if search:
        query = query.filter(
            db.or_(
                Test.title.ilike(f'%{search}%'),
                Test.description.ilike(f'%{search}%')
            )
        )

    if course_id:
        query = query.filter(Test.course_id == course_id)

    if week_id:
        query = query.filter(Test.week_id == week_id)

    now = _now_ist()
    if status == 'active':
        query = query.filter(db.or_(Test.due_date.is_(None), Test.due_date >= now.replace(tzinfo=None)))
    elif status == 'expired':
        query = query.filter(Test.due_date.is_not(None), Test.due_date < now.replace(tzinfo=None))

    paginated = query.order_by(Test.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    tests = []
    for test in paginated.items:
        question_count = TestQuestion.query.filter_by(test_id=test.id).count()
        submission_count = TestSubmission.query.filter_by(test_id=test.id).count()

        due_status = 'no_due_date'
        if test.due_date:
            due_status = 'expired' if _to_ist_aware(test.due_date) < now else 'active'
        payload = _serialize_test(test, include_relations=True)
        payload.update({
            'question_count': question_count,
            'submission_count': submission_count,
            'due_status': due_status
        })
        tests.append(payload)

    total_tests = Test.query.count()
    active_tests = Test.query.filter(db.or_(Test.due_date.is_(None), Test.due_date >= now)).count()
    expired_tests = Test.query.filter(Test.due_date.is_not(None), Test.due_date < now).count()
    total_submissions = TestSubmission.query.count()

    return jsonify({
        'tests': tests,
        'pagination': {
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page,
            'per_page': per_page,
            'has_next': paginated.has_next,
            'has_prev': paginated.has_prev
        },
        'summary': {
            'total_tests': total_tests,
            'active_tests': active_tests,
            'expired_tests': expired_tests,
            'total_submissions': total_submissions
        }
    }), 200


@admin_test_bp.route('/api/admin/tests', methods=['POST'])
@token_required
@roles_required('admin')
def create_test(current_user):
    data = request.get_json(silent=True) or {}

    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'title is required'}), 400

    test_scope = (data.get('test_scope') or 'week').strip().lower()
    if test_scope not in ('week', 'full_length'):
        return jsonify({'error': 'test_scope must be week or full_length'}), 400

    course_id = data.get('course_id')
    week_id = data.get('week_id')

    if test_scope == 'week' and not week_id:
        return jsonify({'error': 'week_id is required for week scope tests'}), 400

    start_at, start_err = _parse_iso_datetime(data.get('start_at'), 'start_at')
    if start_err:
        return jsonify({'error': start_err}), 400

    due_date, due_err = _parse_iso_datetime(data.get('due_date'), 'due_date')
    if due_err:
        return jsonify({'error': due_err}), 400

    if start_at and due_date and due_date <= start_at:
        return jsonify({'error': 'due_date must be after start_at'}), 400

    duration_minutes = int(data.get('duration_minutes', 60) or 60)
    max_attempts = int(data.get('max_attempts', 1) or 1)
    if duration_minutes < 1:
        return jsonify({'error': 'duration_minutes must be at least 1'}), 400
    if max_attempts < 1:
        return jsonify({'error': 'max_attempts must be at least 1'}), 400

    test = Test(
        course_id=course_id,
        week_id=week_id if test_scope == 'week' else None,
        title=title,
        description=data.get('description', ''),
        test_scope=test_scope,
        duration_minutes=duration_minutes,
        start_at=start_at,
        due_date=due_date,
        total_marks=data.get('total_marks', data.get('total_points', 0)),
        max_attempts=max_attempts,
        passcode=(data.get('passcode') or '').strip() or None,
        shuffle_questions=bool(data.get('shuffle_questions', True)),
        shuffle_options=bool(data.get('shuffle_options', True)),
        require_fullscreen=bool(data.get('require_fullscreen', True)),
        prevent_tab_switch=bool(data.get('prevent_tab_switch', True)),
        is_active=bool(data.get('is_active', True))
    )

    db.session.add(test)
    db.session.commit()

    course = Course.query.get(test.course_id) if test.course_id else None
    week = Week.query.get(test.week_id) if test.week_id else None
    students = _get_active_paid_students_for_course(test.course_id) if test.course_id else []

    for student in students:
        try:
            student_name = " ".join([part for part in [student.first_name, student.last_name] if part]).strip() or "Student"
            due_date = test.due_date.isoformat() if test.due_date else None
            send_test_created_email(
                to_email=student.email,
                student_name=student_name,
                course_title=course.title if course else f"Course #{test.course_id}",
                test_title=test.title,
                week_title=week.title if week else None,
                # send due date in IST format
                due_date=_to_ist_aware(test.due_date).isoformat() if test.due_date else None,
            )
        except Exception as err:
            current_app.logger.warning(
                f"Test creation email failed for test_id={test.id}, user_id={student.id}: {err}"
            )

    return jsonify({'message': 'Test created successfully', 'id': test.id, 'test': _serialize_test(test, include_relations=True)}), 201


@admin_test_bp.route('/api/admin/tests/<int:test_id>', methods=['GET'])
@token_required
@roles_required('admin')
def get_test(current_user, test_id):
    test = Test.query.get_or_404(test_id)
    return jsonify(_serialize_test(test, include_relations=True)), 200


@admin_test_bp.route('/api/admin/tests/<int:test_id>', methods=['PUT'])
@token_required
@roles_required('admin')
def update_test(current_user, test_id):
    test = Test.query.get_or_404(test_id)
    data = request.get_json(silent=True) or {}

    test_scope = (data.get('test_scope') or test.test_scope or 'week').strip().lower()
    if test_scope not in ('week', 'full_length'):
        return jsonify({'error': 'test_scope must be week or full_length'}), 400
    test.test_scope = test_scope

    if 'title' in data:
        test.title = data.get('title')
    if 'description' in data:
        test.description = data.get('description')
    if 'course_id' in data and data.get('course_id'):
        test.course_id = data.get('course_id')
    if test_scope == 'week':
        if 'week_id' in data and data.get('week_id'):
            test.week_id = data.get('week_id')
        elif not test.week_id:
            return jsonify({'error': 'week_id is required for week scope tests'}), 400
    else:
        test.week_id = None

    if 'duration_minutes' in data:
        duration_minutes = int(data.get('duration_minutes') or 0)
        if duration_minutes < 1:
            return jsonify({'error': 'duration_minutes must be at least 1'}), 400
        test.duration_minutes = duration_minutes

    if 'total_marks' in data:
        test.total_marks = data.get('total_marks')
    elif 'total_points' in data:
        test.total_marks = data.get('total_points')

    if 'max_attempts' in data:
        max_attempts = int(data.get('max_attempts') or 0)
        if max_attempts < 1:
            return jsonify({'error': 'max_attempts must be at least 1'}), 400
        test.max_attempts = max_attempts

    if 'passcode' in data:
        test.passcode = (data.get('passcode') or '').strip() or None

    if 'shuffle_questions' in data:
        test.shuffle_questions = bool(data.get('shuffle_questions'))

    if 'shuffle_options' in data:
        test.shuffle_options = bool(data.get('shuffle_options'))

    if 'require_fullscreen' in data:
        test.require_fullscreen = bool(data.get('require_fullscreen'))

    if 'prevent_tab_switch' in data:
        test.prevent_tab_switch = bool(data.get('prevent_tab_switch'))
    if 'is_active' in data:
        test.is_active = bool(data.get('is_active'))

    if 'start_at' in data:
        start_at, start_err = _parse_iso_datetime(data.get('start_at'), 'start_at')
        if start_err:
            return jsonify({'error': start_err}), 400
        test.start_at = start_at

    if 'due_date' in data:
        due_date, due_err = _parse_iso_datetime(data.get('due_date'), 'due_date')
        if due_err:
            return jsonify({'error': due_err}), 400
        test.due_date = due_date

    if test.start_at and test.due_date and test.due_date <= test.start_at:
        return jsonify({'error': 'due_date must be after start_at'}), 400

    db.session.commit()
    return jsonify({'message': 'Test updated successfully', 'test': _serialize_test(test, include_relations=True)}), 200


@admin_test_bp.route('/api/admin/tests/<int:test_id>', methods=['DELETE'])
@token_required
@roles_required('admin')
def delete_test(current_user, test_id):
    test = Test.query.get_or_404(test_id)
    db.session.delete(test)
    db.session.commit()
    return jsonify({'message': 'Test deleted successfully'}), 200


@admin_test_bp.route('/api/admin/tests/<int:test_id>/questions', methods=['GET'])
@token_required
@roles_required('admin')
def get_test_questions(current_user, test_id):
    Test.query.get_or_404(test_id)

    questions = []
    rows = TestQuestion.query.filter_by(test_id=test_id).order_by(TestQuestion.order_index, TestQuestion.id).all()
    for q in rows:
        item = {
            'id': q.id,
            'question_text': q.question_text,
            'question_type': q.question_type,
            'marks': q.marks,
            'order_index': q.order_index,
            'options': [],
            'correct_answer': None
        }

        if q.question_type in ['mcq', 'multiple_select']:
            options = TestQuestionOption.query.filter_by(question_id=q.id).order_by(TestQuestionOption.id).all()
            for opt in options:
                item['options'].append({
                    'id': opt.id,
                    'option_text': opt.option_text,
                    'is_correct': opt.is_correct
                })
        elif q.question_type == 'fill_blank':
            fill_blank = TestFillBlankAnswer.query.filter_by(question_id=q.id).first()
            if fill_blank:
                item['correct_answer'] = fill_blank.correct_answer

        questions.append(item)

    return jsonify(questions), 200


@admin_test_bp.route('/api/admin/tests/<int:test_id>/questions', methods=['POST'])
@token_required
@roles_required('admin')
def create_test_question(current_user, test_id):
    Test.query.get_or_404(test_id)
    data = request.get_json(silent=True) or {}

    if not data.get('question_text'):
        return jsonify({'error': 'Question text is required'}), 400

    if data.get('question_type') not in ['mcq', 'fill_blank', 'multiple_select']:
        return jsonify({'error': 'Invalid question type'}), 400

    max_order = db.session.query(db.func.max(TestQuestion.order_index)).filter_by(test_id=test_id).scalar() or -1

    question = TestQuestion(
        test_id=test_id,
        question_text=data.get('question_text'),
        question_type=data.get('question_type'),
        marks=data.get('marks', 10),
        order_index=data.get('order_index', max_order + 1)
    )
    db.session.add(question)
    db.session.flush()

    if question.question_type in ['mcq', 'multiple_select']:
        options_data = data.get('options', [])
        if not options_data:
            return jsonify({'error': 'Options are required for this question type'}), 400

        correct_count = sum(1 for opt in options_data if opt.get('is_correct'))
        if question.question_type == 'mcq' and correct_count != 1:
            return jsonify({'error': 'MCQ must have exactly one correct option'}), 400
        if question.question_type == 'multiple_select' and correct_count < 1:
            return jsonify({'error': 'Multiple Select must have at least one correct option'}), 400

        for opt_data in options_data:
            if not opt_data.get('option_text'):
                return jsonify({'error': 'Option text is required'}), 400
            db.session.add(TestQuestionOption(
                question_id=question.id,
                option_text=opt_data.get('option_text'),
                is_correct=bool(opt_data.get('is_correct', False))
            ))

    elif question.question_type == 'fill_blank':
        correct_answer = (data.get('correct_answer') or '').strip()
        if not correct_answer:
            return jsonify({'error': 'Correct answer is required for fill in blank'}), 400

        db.session.add(TestFillBlankAnswer(
            question_id=question.id,
            correct_answer=correct_answer
        ))

    update_test_total_marks(test_id)
    db.session.commit()

    return jsonify({'message': 'Question created successfully', 'question_id': question.id}), 201


@admin_test_bp.route('/api/admin/test-questions/<int:question_id>', methods=['PUT'])
@token_required
@roles_required('admin')
def update_test_question(current_user, question_id):
    question = TestQuestion.query.get_or_404(question_id)
    data = request.get_json(silent=True) or {}

    question.question_text = data.get('question_text', question.question_text)
    question.marks = data.get('marks', question.marks)
    question.order_index = data.get('order_index', question.order_index)

    if question.question_type in ['mcq', 'multiple_select'] and data.get('options'):
        options_data = data.get('options')
        correct_count = sum(1 for opt in options_data if opt.get('is_correct'))

        if question.question_type == 'mcq' and correct_count != 1:
            return jsonify({'error': 'MCQ must have exactly one correct option'}), 400
        if question.question_type == 'multiple_select' and correct_count < 1:
            return jsonify({'error': 'Multiple Select must have at least one correct option'}), 400

        TestQuestionOption.query.filter_by(question_id=question_id).delete()
        for opt_data in options_data:
            db.session.add(TestQuestionOption(
                question_id=question.id,
                option_text=opt_data.get('option_text'),
                is_correct=bool(opt_data.get('is_correct', False))
            ))

    elif question.question_type == 'fill_blank' and data.get('correct_answer') is not None:
        answer_text = (data.get('correct_answer') or '').strip()
        existing = TestFillBlankAnswer.query.filter_by(question_id=question_id).first()
        if existing:
            existing.correct_answer = answer_text
        else:
            db.session.add(TestFillBlankAnswer(question_id=question_id, correct_answer=answer_text))

    update_test_total_marks(question.test_id)
    db.session.commit()

    return jsonify({'message': 'Question updated successfully'}), 200


@admin_test_bp.route('/api/admin/test-questions/<int:question_id>', methods=['DELETE'])
@token_required
@roles_required('admin')
def delete_test_question(current_user, question_id):
    question = TestQuestion.query.get_or_404(question_id)
    test_id = question.test_id

    db.session.delete(question)
    update_test_total_marks(test_id)

    remaining = TestQuestion.query.filter_by(test_id=test_id).order_by(TestQuestion.order_index).all()
    for index, row in enumerate(remaining):
        row.order_index = index

    db.session.commit()
    return jsonify({'message': 'Question deleted successfully'}), 200


@admin_test_bp.route('/api/admin/tests/<int:test_id>/bulk-questions', methods=['POST'])
@token_required
@roles_required('admin')
def create_bulk_test_questions(current_user, test_id):
    Test.query.get_or_404(test_id)
    data = request.get_json(silent=True) or {}
    questions_data = data.get('questions', [])

    if not questions_data:
        return jsonify({'error': 'No questions provided'}), 400

    created_questions = []
    errors = []
    max_order = db.session.query(db.func.max(TestQuestion.order_index)).filter_by(test_id=test_id).scalar() or -1

    for index, q_data in enumerate(questions_data):
        try:
            if not q_data.get('question_text'):
                errors.append(f'Question {index + 1}: Question text is required')
                continue

            if q_data.get('question_type') not in ['mcq', 'fill_blank', 'multiple_select']:
                errors.append(f'Question {index + 1}: Invalid question type')
                continue

            question = TestQuestion(
                test_id=test_id,
                question_text=q_data.get('question_text'),
                question_type=q_data.get('question_type'),
                marks=q_data.get('marks', 10),
                order_index=max_order + index + 1
            )
            db.session.add(question)
            db.session.flush()

            if question.question_type in ['mcq', 'multiple_select']:
                options_data = q_data.get('options', [])
                if not options_data:
                    errors.append(f'Question {index + 1}: Options are required')
                    db.session.rollback()
                    continue

                correct_count = sum(1 for opt in options_data if opt.get('is_correct'))
                if question.question_type == 'mcq' and correct_count != 1:
                    errors.append(f'Question {index + 1}: MCQ must have exactly one correct answer')
                    db.session.rollback()
                    continue
                if question.question_type == 'multiple_select' and correct_count < 1:
                    errors.append(f'Question {index + 1}: Multiple Select must have at least one correct answer')
                    db.session.rollback()
                    continue

                for opt_data in options_data:
                    if not opt_data.get('option_text'):
                        errors.append(f'Question {index + 1}: Option text is required')
                        db.session.rollback()
                        continue
                    db.session.add(TestQuestionOption(
                        question_id=question.id,
                        option_text=opt_data.get('option_text'),
                        is_correct=bool(opt_data.get('is_correct', False))
                    ))

            elif question.question_type == 'fill_blank':
                answer_text = (q_data.get('correct_answer') or '').strip()
                if not answer_text:
                    errors.append(f'Question {index + 1}: Correct answer is required')
                    db.session.rollback()
                    continue
                db.session.add(TestFillBlankAnswer(question_id=question.id, correct_answer=answer_text))

            created_questions.append({
                'id': question.id,
                'question_text': question.question_text,
                'question_type': question.question_type
            })
        except Exception as err:
            errors.append(f'Question {index + 1}: {str(err)}')
            db.session.rollback()

    if created_questions:
        update_test_total_marks(test_id)
        db.session.commit()

    return jsonify({
        'message': f'Successfully created {len(created_questions)} questions',
        'created_questions': created_questions,
        'errors': errors
    }), 201 if created_questions else 400


@admin_test_bp.route('/api/admin/tests/<int:test_id>/reorder-questions', methods=['POST'])
@token_required
@roles_required('admin')
def reorder_test_questions(current_user, test_id):
    data = request.get_json(silent=True) or {}
    question_order = data.get('question_order', [])

    if not question_order:
        return jsonify({'error': 'No question order provided'}), 400

    for order_data in question_order:
        question_id = order_data.get('id')
        new_order = order_data.get('order_index')

        if question_id is not None and new_order is not None:
            question = TestQuestion.query.filter_by(id=question_id, test_id=test_id).first()
            if question:
                question.order_index = new_order

    db.session.commit()
    return jsonify({'message': 'Questions reordered successfully'}), 200


def update_test_total_marks(test_id):
    total = db.session.query(db.func.sum(TestQuestion.marks)).filter_by(test_id=test_id).scalar() or 0
    test = Test.query.get(test_id)
    if test:
        test.total_marks = total
    return total


@admin_test_bp.route('/api/admin/tests/<int:test_id>/results', methods=['GET'])
@token_required
@roles_required('admin')
def get_test_results(current_user, test_id):
    test = Test.query.get_or_404(test_id)
    submissions = TestSubmission.query.filter_by(test_id=test_id).order_by(TestSubmission.submitted_at.desc(), TestSubmission.id.desc()).all()

    results = []
    for submission in submissions:
        student = submission.student or User.query.get(submission.student_id)
        max_score = float(submission.max_score or 0)
        score = float(submission.score or 0)
        percentage = round((score / max_score) * 100, 2) if max_score > 0 else 0.0

        results.append({
            'submission_id': submission.id,
            'student_id': submission.student_id,
            'student_name': f"{(student.first_name or '').strip()} {(student.last_name or '').strip()}".strip() if student else f'Student #{submission.student_id}',
            'student_email': student.email if student else None,
            'attempt_no': submission.attempt_no,
            'status': submission.status,
            'score': score,
            'max_score': max_score,
            'percentage': percentage,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None
        })

    avg_score = 0.0
    if results:
        avg_score = round(sum(item['percentage'] for item in results) / len(results), 2)

    return jsonify({
        'test': _serialize_test(test, include_relations=True),
        'summary': {
            'total_submissions': len(results),
            'average_percentage': avg_score
        },
        'results': results
    }), 200


@admin_test_bp.route('/api/admin/tests/<int:test_id>/results/<int:submission_id>', methods=['GET'])
@token_required
@roles_required('admin')
def get_test_submission_result(current_user, test_id, submission_id):
    test = Test.query.get_or_404(test_id)
    submission = TestSubmission.query.filter_by(id=submission_id, test_id=test_id).first_or_404()
    student = submission.student or User.query.get(submission.student_id)

    details = _build_submission_details(test_id, submission)

    max_score = float(submission.max_score or 0)
    score = float(submission.score or 0)
    percentage = round((score / max_score) * 100, 2) if max_score > 0 else 0.0

    return jsonify({
        'test': _serialize_test(test, include_relations=True),
        'submission': {
            'submission_id': submission.id,
            'student_id': submission.student_id,
            'student_name': f"{(student.first_name or '').strip()} {(student.last_name or '').strip()}".strip() if student else f'Student #{submission.student_id}',
            'student_email': student.email if student else None,
            'attempt_no': submission.attempt_no,
            'status': submission.status,
            'score': score,
            'max_score': max_score,
            'percentage': percentage,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None
        },
        'questions': details
    }), 200
