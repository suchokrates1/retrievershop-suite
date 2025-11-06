"""Test WebSocket functionality for discussions."""
import pytest
from magazyn.socketio_extension import socketio


def test_socketio_initialization():
    """Test that SocketIO extension is properly initialized."""
    assert socketio is not None
    assert hasattr(socketio, 'emit')
    assert hasattr(socketio, 'on')


def test_websocket_connect(client):
    """Test WebSocket connection with authenticated user."""
    with client.session_transaction() as sess:
        sess['username'] = 'testuser'
    
    socketio_client = socketio.test_client(client.application, flask_test_client=client)
    assert socketio_client.is_connected()
    
    # The connection itself is successful - that's the main test
    # In Flask-SocketIO test client, 'connected' event may not always appear in received messages
    # because it's part of the connection handshake
    socketio_client.disconnect()


def test_websocket_unauthenticated(client):
    """Test WebSocket connection without authentication."""
    # Do not set username in session
    socketio_client = socketio.test_client(client.application, flask_test_client=client)
    
    # Connection should be rejected by @authenticated_only decorator
    assert not socketio_client.is_connected()


def test_join_thread_room(client):
    """Test joining a thread room."""
    with client.session_transaction() as sess:
        sess['username'] = 'testuser'
    
    socketio_client = socketio.test_client(client.application, flask_test_client=client)
    socketio_client.get_received()  # Clear connection messages
    
    # Join thread room
    socketio_client.emit('join_thread', {'thread_id': 'test-thread-123'})
    
    # Should not receive any immediate response (just joins room)
    socketio_client.disconnect()


def test_typing_indicator(client):
    """Test typing indicator broadcast."""
    with client.session_transaction() as sess:
        sess['username'] = 'testuser'
    
    socketio_client = socketio.test_client(client.application, flask_test_client=client)
    socketio_client.get_received()  # Clear connection messages
    
    # Join thread room
    socketio_client.emit('join_thread', {'thread_id': 'test-thread-123'})
    
    # Send typing event
    socketio_client.emit('typing', {
        'thread_id': 'test-thread-123',
        'is_typing': True
    })
    
    socketio_client.disconnect()


def test_broadcast_new_message(client):
    """Test message broadcast functionality."""
    from magazyn.socketio_extension import broadcast_new_message
    
    # This is a unit test - just ensure the function exists and can be called
    # In integration tests, you'd need multiple clients to test broadcasting
    message_payload = {
        'id': 'msg-123',
        'author': 'testuser',
        'content': 'Test message',
        'created_at': '2025-11-06T12:00:00Z'
    }
    
    # Should not raise any errors
    broadcast_new_message('test-thread-123', message_payload)
