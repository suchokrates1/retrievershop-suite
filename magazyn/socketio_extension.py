"""WebSocket extension for real-time discussions."""
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request, session
from functools import wraps

socketio = SocketIO(cors_allowed_origins="*")


def authenticated_only(f):
    """Decorator to ensure user is authenticated."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'username' not in session:
            return False
        return f(*args, **kwargs)
    return wrapped


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    username = session.get('username', 'anonymous')
    if username == 'anonymous':
        return False  # reject unauthenticated connections
    print(f'[SocketIO] User {username} connected')
    emit('connected', {'username': username})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    username = session.get('username', 'anonymous')
    print(f'[SocketIO] User {username} disconnected')


@socketio.on('join_thread')
@authenticated_only
def handle_join_thread(data):
    """User joins a thread room."""
    thread_id = data.get('thread_id')
    if thread_id:
        join_room(thread_id)
        username = session.get('username')
        print(f'[SocketIO] {username} joined thread {thread_id}')


@socketio.on('leave_thread')
@authenticated_only
def handle_leave_thread(data):
    """User leaves a thread room."""
    thread_id = data.get('thread_id')
    if thread_id:
        leave_room(thread_id)
        username = session.get('username')
        print(f'[SocketIO] {username} left thread {thread_id}')


@socketio.on('typing')
@authenticated_only
def handle_typing(data):
    """Broadcast typing indicator to other users in thread."""
    thread_id = data.get('thread_id')
    is_typing = data.get('is_typing', False)
    if thread_id:
        username = session.get('username')
        emit('user_typing', {
            'username': username,
            'is_typing': is_typing
        }, room=thread_id, skip_sid=request.sid)


def broadcast_new_message(thread_id, message_payload):
    """
    Emit new message to all users in thread room.
    
    Args:
        thread_id: The thread identifier
        message_payload: Dict containing message data
    """
    socketio.emit('message_received', {
        'thread_id': thread_id,
        'message': message_payload
    }, room=thread_id)


def broadcast_thread_update(thread_id, thread_payload):
    """
    Emit thread metadata update.
    
    Args:
        thread_id: The thread identifier
        thread_payload: Dict containing thread metadata
    """
    socketio.emit('thread_updated', {
        'thread_id': thread_id,
        'thread': thread_payload
    }, to=thread_id)
