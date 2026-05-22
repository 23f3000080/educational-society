from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from models import *

from Routes.base_route import token_required, roles_required
from live_socket.rooms import get_room_snapshot


admin_live_class_management_bp = Blueprint(
    'admin_live_class_management',
    __name__
)

IST = ZoneInfo("Asia/Kolkata")
ALLOWED_LIVE_CLASS_STATUSES = {"Scheduled", "Live", "Completed", "Cancelled"}


def _room_id_for(live_class_id):
    return f"LC-{live_class_id}"


def _serialize_live_class(live_class):
    course = live_class.course or Course.query.get(live_class.course_id)
    room_snapshot = get_room_snapshot(live_class.id)

    return {
        'id': live_class.id,
        'course_id': live_class.course_id,
        'course_title': course.title if course else None,
        'room_id': _room_id_for(live_class.id),
        'title': live_class.title,
        'description': live_class.description,
        'start_time': live_class.start_time.isoformat() if live_class.start_time else None,
        'end_time': live_class.end_time.isoformat() if live_class.end_time else None,
        'meeting_link': live_class.meeting_link,
        'instructor_name': live_class.instructor_name,
        'status': live_class.status,
        'message': live_class.message,
        'participant_count': room_snapshot['participant_count'],
        'created_at': live_class.created_at.isoformat() if live_class.created_at else None,
        'updated_at': live_class.updated_at.isoformat() if live_class.updated_at else None,
    }


def _student_access_course_ids(user_id):
    return [
        enrollment.course_id
        for enrollment in Enrollment.query.filter_by(
            student_id=user_id,
            payment_status='paid',
            enrollment_status='active'
        ).all()
    ]


def _can_access_live_class(current_user, live_class):
    user_roles = {role.name for role in current_user.roles}
    if 'admin' in user_roles:
        return True

    if live_class.status == 'Cancelled':
        return False

    return live_class.course_id in set(_student_access_course_ids(current_user.id))


@admin_live_class_management_bp.route('/api/admin/live-classes', methods=['POST'])
@token_required
@roles_required('admin')
def create_live_class(current_user):

    try:
        data = request.get_json()

        required_fields = [
            'course_id',
            'title',
            'start_time',
            'end_time'
        ]

        # Validate required fields
        missing_fields = [
            field for field in required_fields
            if field not in data
        ]

        if missing_fields:
            return jsonify({
                'success': False,
                'message': f'Missing fields: {", ".join(missing_fields)}'
            }), 400

        course_id = data['course_id']
        title = data['title']
        description = data.get('description', '')
        meeting_link = data.get('meeting_link')
        instructor_name = data.get('instructor_name')
        message = data.get('message')
        status = data.get('status', 'Scheduled')
        if status not in ALLOWED_LIVE_CLASS_STATUSES:
            status = 'Scheduled'

        # Validate course exists
        course = Course.query.get(course_id)

        if not course:
            return jsonify({
                'success': False,
                'message': 'Course not found'
            }), 404

        # Parse datetime
        try:
            start_time = datetime.fromisoformat(
                data['start_time']
            )

            # Add timezone if missing
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=IST)

            start_time = start_time.astimezone(timezone.utc)
            
            end_time = datetime.fromisoformat(
                data['end_time']
            )
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=IST)
            end_time = end_time.astimezone(timezone.utc)

        except Exception:
            return jsonify({
                'success': False,
                'message': 'Invalid start_time format. Use ISO format.'
            }), 400


        # Create live class
        live_class = LiveClass(
            course_id=course_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            meeting_link=meeting_link,
            instructor_name=instructor_name,
            message=message,
            status=status
        )

        db.session.add(live_class)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Live class created successfully',
            'live_class': _serialize_live_class(live_class)
        }), 201

    except Exception as e:

        db.session.rollback()

        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
        
@admin_live_class_management_bp.route('/api/admin/live-classes/<int:live_class_id>', methods=['PUT'])
@token_required
@roles_required('admin')
def update_live_class(current_user, live_class_id):
    
    try:
        data = request.get_json()

        live_class = LiveClass.query.get(live_class_id)

        if not live_class:
            return jsonify({
                'success': False,
                'message': 'Live class not found'
            }), 404

        # Update fields if provided
        if 'course_id' in data:
            course = Course.query.get(data['course_id'])
            if not course:
                return jsonify({
                    'success': False,
                    'message': 'Course not found'
                }), 404
            live_class.course_id = data['course_id']

        if 'title' in data:
            live_class.title = data['title']

        if 'description' in data:
            live_class.description = data['description']

        if 'meeting_link' in data:
            live_class.meeting_link = data['meeting_link']

        if 'instructor_name' in data:
            live_class.instructor_name = data['instructor_name']

        if 'message' in data:
            live_class.message = data['message']

        if 'status' in data:
            live_class.status = data['status'] if data['status'] in ALLOWED_LIVE_CLASS_STATUSES else live_class.status

        # Update start_time and end_time together
        if 'start_time' in data and 'end_time' in data:
            try:
                start_time = datetime.fromisoformat(
                    data['start_time']
                )

                # Add timezone if missing
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=IST)

                start_time = start_time.astimezone(timezone.utc)
                
                end_time = datetime.fromisoformat(
                    data['end_time']
                )
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=IST)
                end_time = end_time.astimezone(timezone.utc)

                live_class.start_time = start_time
                live_class.end_time = end_time

            except Exception:
                return jsonify({
                    'success': False,
                    'message': 'Invalid datetime format. Use ISO format.'
                }), 400

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Live class updated successfully',
            'live_class': _serialize_live_class(live_class)
        }), 200
    except Exception as e:

        db.session.rollback()

        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
        
@admin_live_class_management_bp.route('/api/admin/live-classes/<int:live_class_id>', methods=['DELETE'])
@token_required
@roles_required('admin')
def delete_live_class(current_user, live_class_id):
    
    try:
        live_class = LiveClass.query.get(live_class_id)

        if not live_class:
            return jsonify({
                'success': False,
                'message': 'Live class not found'
            }), 404

        db.session.delete(live_class)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Live class deleted successfully'
        }), 200

    except Exception as e:

        db.session.rollback()

        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@admin_live_class_management_bp.route('/api/admin/live-classes', methods=['GET'])
@token_required
@roles_required('admin')
def list_live_classes(current_user):
    """Return paginated list of live classes. Query params: page, per_page"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 100, type=int)

        query = LiveClass.query.order_by(LiveClass.start_time.desc())

        paginated = query.paginate(page=page, per_page=per_page, error_out=False)

        items = [_serialize_live_class(lc) for lc in paginated.items]

        return jsonify({
            'live_classes': items,
            'pagination': {
                'total': paginated.total,
                'pages': paginated.pages,
                'current_page': page,
                'per_page': per_page,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_live_class_management_bp.route('/api/admin/live-classes/<int:live_class_id>', methods=['GET'])
@token_required
@roles_required('admin')
def get_live_class(current_user, live_class_id):
    try:
        lc = LiveClass.query.get(live_class_id)
        if not lc:
            return jsonify({'success': False, 'message': 'Live class not found'}), 404

        return jsonify({'live_class': _serialize_live_class(lc)}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_live_class_management_bp.route('/api/student/live-classes', methods=['GET'])
@token_required
@roles_required('user', 'admin')
def list_student_live_classes(current_user):
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        query = LiveClass.query.join(Course)
        if 'admin' not in {role.name for role in current_user.roles}:
            course_ids = _student_access_course_ids(current_user.id)
            if not course_ids:
                return jsonify({'live_classes': [], 'pagination': {'total': 0, 'pages': 0, 'current_page': page, 'per_page': per_page, 'has_next': False, 'has_prev': False}}), 200
            query = query.filter(LiveClass.course_id.in_(course_ids))

        query = query.order_by(LiveClass.start_time.desc())
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'live_classes': [_serialize_live_class(live) for live in paginated.items],
            'pagination': {
                'total': paginated.total,
                'pages': paginated.pages,
                'current_page': page,
                'per_page': per_page,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_live_class_management_bp.route('/api/live-classes/<int:live_class_id>/access', methods=['GET'])
@token_required
@roles_required('user', 'admin')
def get_live_class_access(current_user, live_class_id):
    try:
        live_class = LiveClass.query.get(live_class_id)
        if not live_class:
            return jsonify({'success': False, 'message': 'Live class not found'}), 404

        allowed = _can_access_live_class(current_user, live_class)
        if not allowed:
            return jsonify({'success': False, 'message': 'You are not enrolled in this course'}), 403

        return jsonify({
            'success': True,
            'can_join': live_class.status in {'Scheduled', 'Live'},
            'live_class': _serialize_live_class(live_class),
            'room': {
                'room_id': _room_id_for(live_class.id),
                'participant_count': get_room_snapshot(live_class.id)['participant_count']
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500