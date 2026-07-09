# admin_assignment_routes.py

from flask import Blueprint, request, jsonify
from flask_cors import cross_origin
from datetime import datetime
from models import db, Assignment, Question, QuestionOption, FillBlankAnswer, Course, Week, AssignmentSubmission, StudentAnswer, User
from Routes.base_route import token_required, roles_required

admin_assignment_bp = Blueprint('admin_assignment', __name__)

# ==================== ASSIGNMENT MANAGEMENT ====================

@admin_assignment_bp.route("/api/admin/assignments", methods=["GET"])
@token_required
@roles_required("admin")
def get_all_assignments(current_user):
    """Get all assignments with pagination, filtering, and summary stats."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '', type=str).strip()
    course_id = request.args.get('course_id', type=int)
    week_id = request.args.get('week_id', type=int)
    status = request.args.get('status', '', type=str).strip().lower()

    query = Assignment.query

    if search:
        query = query.filter(
            db.or_(
                Assignment.title.ilike(f'%{search}%'),
                Assignment.description.ilike(f'%{search}%')
            )
        )

    if course_id:
        query = query.filter(Assignment.course_id == course_id)

    if week_id:
        query = query.filter(Assignment.week_id == week_id)

    now = datetime.utcnow()
    if status == 'active':
        query = query.filter(db.or_(Assignment.due_date.is_(None), Assignment.due_date >= now))
    elif status == 'expired':
        query = query.filter(Assignment.due_date.is_not(None), Assignment.due_date < now)

    paginated = query.order_by(Assignment.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    assignments = []
    for assignment in paginated.items:
        question_count = Question.query.filter_by(assignment_id=assignment.id).count()
        submission_count = AssignmentSubmission.query.filter_by(assignment_id=assignment.id).count()

        course = Course.query.get(assignment.course_id)
        week = Week.query.get(assignment.week_id)

        due_status = 'no_due_date'
        if assignment.due_date:
            due_status = 'expired' if assignment.due_date < now else 'active'

        assignments.append({
            "id": assignment.id,
            "title": assignment.title,
            "description": assignment.description,
            "order_index": assignment.order_index,
            "course_id": assignment.course_id,
            "course_title": course.title if course else None,
            "week_id": assignment.week_id,
            "week_number": week.week_number if week else None,
            "week_title": week.title if week else None,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "total_points": assignment.total_points,
            "question_count": question_count,
            "submission_count": submission_count,
            "due_status": due_status,
            "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
            "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None
        })

    total_assignments = Assignment.query.count()
    active_assignments = Assignment.query.filter(db.or_(Assignment.due_date.is_(None), Assignment.due_date >= now)).count()
    expired_assignments = Assignment.query.filter(Assignment.due_date.is_not(None), Assignment.due_date < now).count()
    total_submissions = AssignmentSubmission.query.count()

    return jsonify({
        "assignments": assignments,
        "pagination": {
            "total": paginated.total,
            "pages": paginated.pages,
            "current_page": page,
            "per_page": per_page,
            "has_next": paginated.has_next,
            "has_prev": paginated.has_prev
        },
        "summary": {
            "total_assignments": total_assignments,
            "active_assignments": active_assignments,
            "expired_assignments": expired_assignments,
            "total_submissions": total_submissions
        }
    }), 200

@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>", methods=["GET"])
@token_required
@roles_required("admin")
def get_assignment(current_user, assignment_id):
    """Get assignment details by ID"""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Get course and week info
    course = Course.query.get(assignment.course_id)
    week = Week.query.get(assignment.week_id)
    
    return jsonify({
        "id": assignment.id,
        "title": assignment.title,
        "description": assignment.description,
        "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
        "total_points": assignment.total_points,
        "order_index": assignment.order_index,
        "course_id": assignment.course_id,
        "course_title": course.title if course else None,
        "week_id": assignment.week_id,
        "week_number": week.week_number if week else None,
        "week_title": week.title if week else None,
        "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
        "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None
    }), 200


@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>/questions", methods=["GET"])
@token_required
@roles_required("admin")
def get_assignment_questions(current_user, assignment_id):
    """Get all questions for an assignment with their options and correct answers"""
    Assignment.query.get_or_404(assignment_id)

    questions = []
    ordered_questions = Question.query.filter_by(assignment_id=assignment_id).order_by(Question.order_index, Question.id).all()

    for q in ordered_questions:
        question_data = {
            "id": q.id,
            "question_text": q.question_text,
            "question_type": q.question_type,
            "marks": q.marks,
            "order_index": q.order_index,
            "options": [],
            "correct_answer": None
        }
        
        # Get options for MCQ and multiple select
        if q.question_type in ['mcq', 'multiple_select']:
            options = QuestionOption.query.filter_by(question_id=q.id).order_by(QuestionOption.id).all()
            for opt in options:
                question_data["options"].append({
                    "id": opt.id,
                    "option_text": opt.option_text,
                    "is_correct": opt.is_correct
                })
        
        # For fill in blank, get correct answer
        elif q.question_type == 'fill_blank':
            fill_blank = FillBlankAnswer.query.filter_by(question_id=q.id).first()
            if fill_blank:
                question_data["correct_answer"] = fill_blank.correct_answer
        
        questions.append(question_data)
    
    return jsonify(questions), 200


@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>/questions", methods=["POST"])
@token_required
@roles_required("admin")
def create_question(current_user, assignment_id):
    """Create a new question for an assignment"""
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json()
    
    # Validate required fields
    if not data.get('question_text'):
        return jsonify({"error": "Question text is required"}), 400
    
    if not data.get('question_type'):
        return jsonify({"error": "Question type is required"}), 400
    
    if data['question_type'] not in ['mcq', 'fill_blank', 'multiple_select']:
        return jsonify({"error": "Invalid question type"}), 400
    
    # Get the next order index
    max_order = db.session.query(db.func.max(Question.order_index)).filter_by(
        assignment_id=assignment_id
    ).scalar() or -1
    
    question = Question(
        assignment_id=assignment_id,
        question_text=data['question_text'],
        question_type=data['question_type'],
        marks=data.get('marks', 10),
        order_index=data.get('order_index', max_order + 1)
    )
    
    db.session.add(question)
    db.session.flush()  # Get the question ID
    
    # Handle options for MCQ and multiple select
    if data['question_type'] in ['mcq', 'multiple_select']:
        options_data = data.get('options', [])
        print("Options Data:", options_data)  # Debugging line
        if not options_data:
            return jsonify({"error": "Options are required for MCQ/Multiple Select questions"}), 400
        
        # For MCQ, ensure exactly one correct answer
        if data['question_type'] == 'mcq':
            correct_count = sum(1 for opt in options_data if opt.get('is_correct'))
            if correct_count != 1:
                return jsonify({"error": "MCQ questions must have exactly one correct answer"}), 400
        
        # For Multiple Select, ensure at least one correct answer
        elif data['question_type'] == 'multiple_select':
            correct_count = sum(1 for opt in options_data if opt.get('is_correct'))
            if correct_count < 1:
                return jsonify({"error": "Multiple Select questions must have at least one correct answer"}), 400
        
        for opt_data in options_data:
            if not opt_data.get('option_text'):
                return jsonify({"error": "Option text is required for all options"}), 400
            
            option = QuestionOption(
                question_id=question.id,
                option_text=opt_data['option_text'],
                is_correct=opt_data.get('is_correct', False)
            )
            db.session.add(option)
    
    # Handle fill in blank
    elif data['question_type'] == 'fill_blank':
        correct_answer = data.get('correct_answer')
        if not correct_answer:
            return jsonify({"error": "Correct answer is required for fill in blank questions"}), 400
        
        fill_blank = FillBlankAnswer(
            question_id=question.id,
            correct_answer=correct_answer.strip()
        )
        db.session.add(fill_blank)
    
    # Update assignment total points
    update_assignment_total_points(assignment_id)
    
    db.session.commit()
    
    return jsonify({
        "message": "Question created successfully",
        "question_id": question.id
    }), 201


@admin_assignment_bp.route("/api/admin/questions/<int:question_id>", methods=["PUT"])
@token_required
@roles_required("admin")
def update_question(current_user, question_id):
    """Update a question"""
    question = Question.query.get_or_404(question_id)
    data = request.get_json()
    
    # Update basic fields
    question.question_text = data.get('question_text', question.question_text)
    question.marks = data.get('marks', question.marks)
    question.order_index = data.get('order_index', question.order_index)
    
    # Handle options update for MCQ/Multiple Select
    if question.question_type in ['mcq', 'multiple_select'] and data.get('options'):
        # Validate options
        options_data = data['options']
        
        # For MCQ, ensure exactly one correct answer
        if question.question_type == 'mcq':
            correct_count = sum(1 for opt in options_data if opt.get('is_correct'))
            if correct_count != 1:
                return jsonify({"error": "MCQ questions must have exactly one correct answer"}), 400
        
        # For Multiple Select, ensure at least one correct answer
        elif question.question_type == 'multiple_select':
            correct_count = sum(1 for opt in options_data if opt.get('is_correct'))
            if correct_count < 1:
                return jsonify({"error": "Multiple Select questions must have at least one correct answer"}), 400
        
        # Delete existing options
        QuestionOption.query.filter_by(question_id=question_id).delete()
        
        # Add new options
        for opt_data in options_data:
            if not opt_data.get('option_text'):
                return jsonify({"error": "Option text is required for all options"}), 400
            
            option = QuestionOption(
                question_id=question_id,
                option_text=opt_data['option_text'],
                is_correct=opt_data.get('is_correct', False)
            )
            db.session.add(option)
    
    # Update fill in blank
    elif question.question_type == 'fill_blank' and data.get('correct_answer') is not None:
        correct_answer = data['correct_answer'].strip()
        
        fill_blank = FillBlankAnswer.query.filter_by(question_id=question_id).first()
        if fill_blank:
            fill_blank.correct_answer = correct_answer
        else:
            fill_blank = FillBlankAnswer(
                question_id=question_id,
                correct_answer=correct_answer
            )
            db.session.add(fill_blank)
    
    # Update assignment total points
    update_assignment_total_points(question.assignment_id)
    
    db.session.commit()
    
    return jsonify({"message": "Question updated successfully"}), 200


@admin_assignment_bp.route("/api/admin/questions/<int:question_id>", methods=["DELETE"])
@token_required
@roles_required("admin")
def delete_question(current_user, question_id):
    """Delete a question"""
    question = Question.query.get_or_404(question_id)
    assignment_id = question.assignment_id
    
    # Delete related records (cascade should handle this if set in models)
    db.session.delete(question)
    
    # Update assignment total points
    update_assignment_total_points(assignment_id)
    
    # Reorder remaining questions
    remaining_questions = Question.query.filter_by(assignment_id=assignment_id).order_by(Question.order_index).all()
    for index, q in enumerate(remaining_questions):
        q.order_index = index
    
    db.session.commit()
    
    return jsonify({"message": "Question deleted successfully"}), 200


@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>/bulk-questions", methods=["POST"])
@token_required
@roles_required("admin")
def create_bulk_questions(current_user, assignment_id):
    """Create multiple questions at once for an assignment"""
    assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json()
    
    questions_data = data.get('questions', [])
    
    if not questions_data:
        return jsonify({"error": "No questions provided"}), 400
    
    created_questions = []
    errors = []
    
    # Get current max order
    max_order = db.session.query(db.func.max(Question.order_index)).filter_by(
        assignment_id=assignment_id
    ).scalar() or -1
    
    for index, q_data in enumerate(questions_data):
        try:
            # Validate required fields
            if not q_data.get('question_text'):
                errors.append(f"Question {index + 1}: Question text is required")
                continue
            
            if not q_data.get('question_type'):
                errors.append(f"Question {index + 1}: Question type is required")
                continue
            
            if q_data['question_type'] not in ['mcq', 'fill_blank', 'multiple_select']:
                errors.append(f"Question {index + 1}: Invalid question type")
                continue
            
            question = Question(
                assignment_id=assignment_id,
                question_text=q_data['question_text'],
                question_type=q_data['question_type'],
                marks=q_data.get('marks', 10),
                order_index=max_order + index + 1
            )
            
            db.session.add(question)
            db.session.flush()
            
            # Handle options for MCQ and multiple select
            if q_data['question_type'] in ['mcq', 'multiple_select']:
                options_data = q_data.get('options', [])
                
                if not options_data:
                    errors.append(f"Question {index + 1}: Options are required")
                    db.session.rollback()
                    continue
                
                # Validate correct answers count
                correct_count = sum(1 for opt in options_data if opt.get('is_correct'))
                
                if q_data['question_type'] == 'mcq' and correct_count != 1:
                    errors.append(f"Question {index + 1}: MCQ must have exactly one correct answer")
                    db.session.rollback()
                    continue
                
                if q_data['question_type'] == 'multiple_select' and correct_count < 1:
                    errors.append(f"Question {index + 1}: Multiple Select must have at least one correct answer")
                    db.session.rollback()
                    continue
                
                for opt_data in options_data:
                    if not opt_data.get('option_text'):
                        errors.append(f"Question {index + 1}: Option text is required")
                        db.session.rollback()
                        continue
                    
                    option = QuestionOption(
                        question_id=question.id,
                        option_text=opt_data['option_text'],
                        is_correct=opt_data.get('is_correct', False)
                    )
                    db.session.add(option)
            
            # Handle fill in blank
            elif q_data['question_type'] == 'fill_blank':
                correct_answer = q_data.get('correct_answer')
                if not correct_answer:
                    errors.append(f"Question {index + 1}: Correct answer is required")
                    db.session.rollback()
                    continue
                
                fill_blank = FillBlankAnswer(
                    question_id=question.id,
                    correct_answer=correct_answer.strip()
                )
                db.session.add(fill_blank)
            
            created_questions.append({
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type
            })
            
        except Exception as e:
            errors.append(f"Question {index + 1}: {str(e)}")
            db.session.rollback()
    
    # Update assignment total points
    if created_questions:
        update_assignment_total_points(assignment_id)
        db.session.commit()
    
    return jsonify({
        "message": f"Successfully created {len(created_questions)} questions",
        "created_questions": created_questions,
        "errors": errors
    }), 201 if created_questions else 400


@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>/reorder-questions", methods=["POST"])
@token_required
@roles_required("admin")
def reorder_questions(current_user, assignment_id):
    """Reorder questions within an assignment"""
    data = request.get_json()
    question_order = data.get('question_order', [])
    
    if not question_order:
        return jsonify({"error": "No question order provided"}), 400
    
    for order_data in question_order:
        question_id = order_data.get('id')
        new_order = order_data.get('order_index')
        
        if question_id and new_order is not None:
            question = Question.query.filter_by(
                id=question_id,
                assignment_id=assignment_id
            ).first()
            
            if question:
                question.order_index = new_order
    
    db.session.commit()
    
    return jsonify({"message": "Questions reordered successfully"}), 200


@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>/stats", methods=["GET"])
@token_required
@roles_required("admin")
def get_assignment_stats(current_user, assignment_id):
    """Get statistics for an assignment"""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    questions = Question.query.filter_by(assignment_id=assignment_id).all()
    
    mcq_count = sum(1 for q in questions if q.question_type == 'mcq')
    multiple_select_count = sum(1 for q in questions if q.question_type == 'multiple_select')
    fill_blank_count = sum(1 for q in questions if q.question_type == 'fill_blank')
    total_marks = sum(q.marks for q in questions)
    
    # Get submission stats
    from models import AssignmentSubmission
    submissions = AssignmentSubmission.query.filter_by(assignment_id=assignment_id).all()
    
    submitted_count = len(submissions)
    avg_score = 0
    if submissions:
        avg_score = sum(s.score for s in submissions if s.score) / len(submissions)
    
    return jsonify({
        "total_questions": len(questions),
        "mcq_count": mcq_count,
        "multiple_select_count": multiple_select_count,
        "fill_blank_count": fill_blank_count,
        "total_marks": total_marks,
        "submitted_count": submitted_count,
        "average_score": round(avg_score, 2) if avg_score else 0,
        "completion_rate": round((submitted_count / assignment.course.enrollments.count()) * 100, 2) if assignment.course.enrollments.count() > 0 else 0
    }), 200


@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>/submissions", methods=["GET"])
@token_required
@roles_required("admin")
def get_assignment_submissions(current_user, assignment_id):
    return _build_assignment_submissions_payload(assignment_id)


# Helper function to update assignment total points
def update_assignment_total_points(assignment_id):
    """Calculate and update the total points for an assignment"""
    total = db.session.query(db.func.sum(Question.marks)).filter_by(
        assignment_id=assignment_id
    ).scalar() or 0
    
    assignment = Assignment.query.get(assignment_id)
    if assignment:
        assignment.total_points = total
    
    return total


# Optional: Clone assignment (useful for creating similar assignments)
@admin_assignment_bp.route("/api/admin/assignments/<int:assignment_id>/clone", methods=["POST"])
@token_required
@roles_required("admin")
def clone_assignment(current_user, assignment_id):
    """Clone an existing assignment with all its questions"""
    source_assignment = Assignment.query.get_or_404(assignment_id)
    data = request.get_json()
    
    new_title = data.get('title', f"{source_assignment.title} (Copy)")
    
    # Create new assignment
    new_assignment = Assignment(
        course_id=source_assignment.course_id,
        week_id=source_assignment.week_id,
        title=new_title,
        description=source_assignment.description,
        due_date=source_assignment.due_date,
        total_points=source_assignment.total_points
    )
    
    db.session.add(new_assignment)
    db.session.flush()
    
    # Clone all questions
    source_questions = Question.query.filter_by(assignment_id=source_assignment.id).order_by(Question.order_index, Question.id).all()

    for source_question in source_questions:
        new_question = Question(
            assignment_id=new_assignment.id,
            question_text=source_question.question_text,
            question_type=source_question.question_type,
            marks=source_question.marks,
            order_index=source_question.order_index
        )
        
        db.session.add(new_question)
        db.session.flush()
        
        # Clone options for MCQ/Multiple Select
        if source_question.question_type in ['mcq', 'multiple_select']:
            source_options = QuestionOption.query.filter_by(question_id=source_question.id).order_by(QuestionOption.id).all()
            for opt in source_options:
                new_option = QuestionOption(
                    question_id=new_question.id,
                    option_text=opt.option_text,
                    is_correct=opt.is_correct
                )
                db.session.add(new_option)
        
        # Clone fill in blank answer
        elif source_question.question_type == 'fill_blank':
            fill_blank = FillBlankAnswer.query.filter_by(question_id=source_question.id).first()
            if fill_blank:
                new_fill_blank = FillBlankAnswer(
                    question_id=new_question.id,
                    correct_answer=fill_blank.correct_answer
                )
                db.session.add(new_fill_blank)
    
    db.session.commit()
    
    return jsonify({
        "message": "Assignment cloned successfully",
        "new_assignment_id": new_assignment.id,
        "new_assignment_title": new_assignment.title
    }), 201
    
# -------------------------
# GET ASSIGNMENT SUBMISSIONS WITH ANSWERS
# -------------------------


def _build_assignment_submissions_payload(assignment_id):
    """Build the admin submissions payload with per-question answers."""
    assignment = Assignment.query.get_or_404(assignment_id)

    submissions = AssignmentSubmission.query.filter_by(
        assignment_id=assignment_id
    ).order_by(
        AssignmentSubmission.submitted_at.desc(),
        AssignmentSubmission.id.desc()
    ).all()

    questions = Question.query.filter_by(
        assignment_id=assignment_id
    ).order_by(Question.order_index, Question.id).all()

    result = []

    for submission in submissions:
        student = User.query.get(submission.student_id)
        student_id = student.id if student else submission.student_id
        student_name = "Unknown"
        student_email = None

        if student:
            name_parts = [student.first_name, student.last_name]
            student_name = " ".join(part for part in name_parts if part).strip() or "Unknown"
            student_email = student.email

        questions_data = []
        total_marks = 0
        obtained_marks = 0

        for question in questions:
            student_answer = StudentAnswer.query.filter_by(
                student_id=student_id,
                question_id=question.id
            ).order_by(StudentAnswer.created_at.desc(), StudentAnswer.id.desc()).first()

            correct_answer = None
            if question.question_type in ['mcq', 'multiple_select']:
                options = QuestionOption.query.filter_by(question_id=question.id).all()
                correct_options = [opt for opt in options if opt.is_correct]
                correct_answer = [opt.id for opt in correct_options]
            elif question.question_type == 'fill_blank':
                blank_answers = FillBlankAnswer.query.filter_by(question_id=question.id).all()
                correct_answer = [ans.correct_answer for ans in blank_answers]

            student_selected = None
            if student_answer:
                if question.question_type == 'mcq':
                    student_selected = [student_answer.selected_option_id] if student_answer.selected_option_id else []
                elif question.question_type == 'multiple_select':
                    student_selected = [student_answer.selected_option_id] if student_answer.selected_option_id else []
                elif question.question_type == 'fill_blank':
                    student_selected = [student_answer.text_answer] if student_answer.text_answer else []

            marks_obtained = float(student_answer.marks_obtained) if student_answer and student_answer.marks_obtained is not None else 0
            if student_answer and student_answer.selected_option_id:
                option = QuestionOption.query.get(student_answer.selected_option_id)
                if option and option.is_correct:
                    marks_obtained = question.marks
            elif student_answer and student_answer.text_answer:
                blank_answers = FillBlankAnswer.query.filter_by(question_id=question.id).all()
                for answer in blank_answers:
                    if answer.correct_answer and answer.correct_answer.lower().strip() == student_answer.text_answer.lower().strip():
                        marks_obtained = question.marks
                        break

            total_marks += question.marks
            obtained_marks += marks_obtained

            questions_data.append({
                'question_id': question.id,
                'question_text': question.question_text,
                'question_type': question.question_type,
                'marks': question.marks,
                'correct_answer': correct_answer,
                'student_answer': student_selected,
                'marks_obtained': marks_obtained,
                'is_correct': marks_obtained == question.marks if marks_obtained > 0 else False
            })

        result.append({
            'submission_id': submission.id,
            'student_id': student_id,
            'student_name': student_name,
            'student_email': student_email,
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None,
            'total_marks': total_marks,
            'obtained_marks': obtained_marks,
            'percentage': (obtained_marks / total_marks * 100) if total_marks > 0 else 0,
            'questions': questions_data,
            'score': submission.score,
            'is_graded': submission.is_graded,
            'graded_at': submission.graded_at.isoformat() if submission.graded_at else None
        })

    return jsonify({
        'success': True,
        'assignment_id': assignment_id,
        'assignment_title': assignment.title,
        'submissions': result
    }), 200

@admin_assignment_bp.route('/<int:assignment_id>/submissions', methods=['GET'])
@token_required
@roles_required('admin')
def get_assignment_submissions_with_answers(assignment_id):
    """
    Fetch all student submissions for an assignment with their answers
    Returns: student info, answers for each question, correct answers, marks obtained
    """
    try:
        return _build_assignment_submissions_payload(assignment_id)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# -------------------------
# UPDATE STUDENT ANSWER SCORE
# -------------------------

@admin_assignment_bp.route('/<int:assignment_id>/submissions/<int:submission_id>/question/<int:question_id>', methods=['PUT'])
@token_required
def update_question_score(current_user, assignment_id, submission_id, question_id):
    """
    Admin can edit score and mark answer correct/incorrect
    """
    try:
        data = request.get_json()
        marks_obtained = data.get('marks_obtained')
        is_correct = data.get('is_correct')
        selected_option_id = data.get('selected_option_id')
        text_answer = data.get('text_answer')
        
        # Validate input
        if marks_obtained is None:
            return jsonify({'success': False, 'error': 'Marks obtained is required'}), 400
        
        # Find the submission
        submission = AssignmentSubmission.query.get_or_404(submission_id)
        
        # Find the question
        question = Question.query.get_or_404(question_id)
        
        # Find or create student answer
        student_answer = StudentAnswer.query.filter_by(
            student_id=submission.student_id,
            question_id=question_id
        ).first()
        
        if not student_answer:
            student_answer = StudentAnswer(
                student_id=submission.student_id,
                question_id=question_id
            )
            db.session.add(student_answer)
        
        # Update based on question type
        if question.question_type in ['mcq', 'multiple_select']:
            if selected_option_id:
                student_answer.selected_option_id = selected_option_id
        elif question.question_type == 'fill_blank':
            if text_answer:
                student_answer.text_answer = text_answer

        student_answer.marks_obtained = float(marks_obtained)

        assignment_questions = Question.query.filter_by(assignment_id=assignment_id).all()
        total_marks = 0.0
        obtained_marks = 0.0

        for assignment_question in assignment_questions:
            total_marks += assignment_question.marks or 0
            answer = StudentAnswer.query.filter_by(
                student_id=submission.student_id,
                question_id=assignment_question.id
            ).first()

            if answer and answer.marks_obtained is not None:
                obtained_marks += float(answer.marks_obtained)
            elif answer and answer.selected_option_id:
                option = QuestionOption.query.get(answer.selected_option_id)
                if option and option.is_correct:
                    obtained_marks += assignment_question.marks or 0
            elif answer and answer.text_answer:
                blank_answers = FillBlankAnswer.query.filter_by(question_id=assignment_question.id).all()
                for blank in blank_answers:
                    if blank.correct_answer and blank.correct_answer.lower().strip() == answer.text_answer.lower().strip():
                        obtained_marks += assignment_question.marks or 0
                        break

        submission.score = obtained_marks
        submission.total_possible = total_marks
        submission.percentage = (obtained_marks / total_marks * 100) if total_marks > 0 else 0
        submission.is_graded = True
        submission.graded_at = datetime.utcnow()
        submission.graded_by = current_user.id
        
        # You might want to store marks in a separate table
        # For now, we'll assume marks are stored in a mark field
        # Add a marks_obtained field to StudentAnswer or create a separate table
        
        # If you have a marks field in StudentAnswer
        # student_answer.marks_obtained = marks_obtained
        
        db.session.commit()
        
        # Recalculate total marks for this student
        total_marks = calculate_student_total_marks(submission.student_id, assignment_id)
        
        return jsonify({
            'success': True,
            'message': 'Question score updated successfully',
            'student_id': submission.student_id,
            'question_id': question_id,
            'marks_obtained': marks_obtained,
            'total_marks': total_marks,
            'submission_score': submission.score,
            'percentage': submission.percentage,
            'is_graded': submission.is_graded,
            'graded_at': submission.graded_at.isoformat() if submission.graded_at else None
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# -------------------------
# BULK UPDATE SUBMISSION GRADES
# -------------------------

@admin_assignment_bp.route('/<int:assignment_id>/submissions/bulk-update', methods=['PUT'])
@token_required
def bulk_update_submissions(current_user, assignment_id):
    """
    Bulk update scores for all questions in a submission
    """
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        question_scores = data.get('question_scores', [])
        
        submission = AssignmentSubmission.query.get_or_404(submission_id)
        
        for score_data in question_scores:
            question_id = score_data.get('question_id')
            marks_obtained = score_data.get('marks_obtained')
            
            student_answer = StudentAnswer.query.filter_by(
                student_id=submission.student_id,
                question_id=question_id
            ).first()
            
            if student_answer:
                student_answer.marks_obtained = float(marks_obtained or 0)
        
        db.session.commit()
        
        assignment_questions = Question.query.filter_by(assignment_id=assignment_id).all()
        total_marks = sum(question.marks or 0 for question in assignment_questions)
        obtained_marks = calculate_student_total_marks(submission.student_id, assignment_id)

        submission.score = obtained_marks
        submission.total_possible = total_marks
        submission.percentage = (obtained_marks / total_marks * 100) if total_marks > 0 else 0
        submission.is_graded = True
        submission.graded_at = datetime.utcnow()
        
        return jsonify({
            'success': True,
            'message': 'Bulk update completed',
            'total_marks': total_marks,
            'submission_score': obtained_marks,
            'percentage': submission.percentage,
            'is_graded': submission.is_graded
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# -------------------------
# HELPER FUNCTION
# -------------------------

def calculate_student_total_marks(student_id, assignment_id):
    """Calculate total marks obtained by a student for an assignment"""
    student_answers = StudentAnswer.query.filter_by(student_id=student_id).all()
    total_marks = 0
    
    for answer in student_answers:
        question = Question.query.get(answer.question_id)
        if question and question.assignment_id == assignment_id:
            if answer.marks_obtained is not None:
                total_marks += float(answer.marks_obtained)
            elif answer.selected_option_id:
                option = QuestionOption.query.get(answer.selected_option_id)
                if option and option.is_correct:
                    total_marks += question.marks
            elif answer.text_answer:
                blank_answers = FillBlankAnswer.query.filter_by(question_id=question.id).all()
                for blank in blank_answers:
                    if blank.correct_answer.lower().strip() == answer.text_answer.lower().strip():
                        total_marks += question.marks
                        break
    
    return total_marks

# -------------------------
# GET SUBMISSION DETAIL FOR A SPECIFIC STUDENT
# -------------------------

@admin_assignment_bp.route('/<int:assignment_id>/student/<int:student_id>/submission', methods=['GET'])
@token_required
def get_student_submission(assignment_id, student_id):
    """
    Get a specific student's submission for an assignment
    """
    try:
        submission = AssignmentSubmission.query.filter_by(
            assignment_id=assignment_id,
            student_id=student_id
        ).first_or_404()
        
        questions = Question.query.filter_by(assignment_id=assignment_id).all()
        
        questions_data = []
        total_marks = 0
        obtained_marks = 0
        
        for question in questions:
            student_answer = StudentAnswer.query.filter_by(
                student_id=student_id,
                question_id=question.id
            ).first()
            
            # Similar logic as above
            correct_answer = None
            student_selected = None
            marks_obtained = 0
            
            if question.question_type == 'mcq':
                options = QuestionOption.query.filter_by(question_id=question.id).all()
                correct_options = [opt for opt in options if opt.is_correct]
                correct_answer = [opt.id for opt in correct_options]
                
                if student_answer and student_answer.selected_option_id:
                    student_selected = [student_answer.selected_option_id]
                    option = QuestionOption.query.get(student_answer.selected_option_id)
                    if option and option.is_correct:
                        marks_obtained = question.marks
                        
            elif question.question_type == 'fill_blank':
                blank_answers = FillBlankAnswer.query.filter_by(question_id=question.id).all()
                correct_answer = [ans.correct_answer for ans in blank_answers]
                
                if student_answer and student_answer.text_answer:
                    student_selected = [student_answer.text_answer]
                    for blank in blank_answers:
                        if blank.correct_answer.lower().strip() == student_answer.text_answer.lower().strip():
                            marks_obtained = question.marks
                            break
            
            total_marks += question.marks
            obtained_marks += marks_obtained
            
            questions_data.append({
                'question_id': question.id,
                'question_text': question.question_text,
                'question_type': question.question_type,
                'marks': question.marks,
                'correct_answer': correct_answer,
                'student_answer': student_selected,
                'marks_obtained': marks_obtained,
                'is_correct': marks_obtained == question.marks if marks_obtained > 0 else False
            })
        
        return jsonify({
            'success': True,
            'student_id': student_id,
            'submission_id': submission.id,
            'submitted_at': submission.submitted_at.isoformat(),
            'total_marks': total_marks,
            'obtained_marks': obtained_marks,
            'percentage': (obtained_marks / total_marks * 100) if total_marks > 0 else 0,
            'questions': questions_data
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# -------------------------
# EXPORT SUBMISSIONS AS CSV
# -------------------------

@admin_assignment_bp.route('/<int:assignment_id>/submissions/export', methods=['GET'])
@token_required
def export_submissions_csv(assignment_id):
    """
    Export all submissions as CSV
    """
    try:
        import csv
        from io import StringIO
        
        assignment = Assignment.query.get_or_404(assignment_id)
        submissions = AssignmentSubmission.query.filter_by(assignment_id=assignment_id).all()
        
        # Create CSV
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        header = ['Student ID', 'Student Name', 'Student Email', 'Submitted At', 'Total Marks', 'Obtained Marks', 'Percentage']
        
        # Get all questions for columns
        questions = Question.query.filter_by(assignment_id=assignment_id).order_by(Question.order_index).all()
        for q in questions:
            header.append(f'Q{q.order_index+1} (Marks)')
            header.append(f'Q{q.order_index+1} (Correct)')
        
        writer.writerow(header)
        
        # Write data for each submission
        for submission in submissions:
            student = User.query.get(submission.student_id)
            row = [
                student.id,
                f"{student.first_name} {student.last_name or ''}",
                student.email,
                submission.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
            ]
            
            # Calculate marks and add question details
            total_marks = 0
            obtained_marks = 0
            
            for question in questions:
                student_answer = StudentAnswer.query.filter_by(
                    student_id=student.id,
                    question_id=question.id
                ).first()
                
                marks = 0
                is_correct = 'No'
                
                if student_answer:
                    if question.question_type == 'mcq':
                        option = QuestionOption.query.get(student_answer.selected_option_id)
                        if option and option.is_correct:
                            marks = question.marks
                            is_correct = 'Yes'
                    elif question.question_type == 'fill_blank':
                        blank_answers = FillBlankAnswer.query.filter_by(question_id=question.id).all()
                        for blank in blank_answers:
                            if blank.correct_answer.lower().strip() == student_answer.text_answer.lower().strip():
                                marks = question.marks
                                is_correct = 'Yes'
                                break
                
                total_marks += question.marks
                obtained_marks += marks
                row.extend([marks, is_correct])
            
            row.extend([
                total_marks,
                obtained_marks,
                f"{(obtained_marks/total_marks*100):.2f}%" if total_marks > 0 else '0%'
            ])
            
            writer.writerow(row)
        
        # Create response
        response = jsonify({
            'success': True,
            'csv_data': output.getvalue(),
            'filename': f"assignment_{assignment_id}_submissions.csv"
        })
        
        return response, 200
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500