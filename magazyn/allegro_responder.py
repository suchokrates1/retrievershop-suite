from sqlalchemy.orm import Session
from . import allegro_api
from .models import AllegroRepliedThread, AllegroRepliedDiscussion
from .settings_store import settings_store
from .db import get_session
import logging

logger = logging.getLogger(__name__)

def process_new_messages(access_token: str):
    """
    Fetches new messages from Allegro, and if autoresponder is enabled,
    sends an automated reply to each new message.
    """
    if not settings_store.get("ALLEGRO_AUTORESPONDER_ENABLED"):
        return

    try:
        threads = allegro_api.fetch_message_threads(access_token)
        with get_session() as db:
            for thread in threads.get("threads", []):
                if not thread.get("read"):
                    thread_id = thread["id"]
                    if not db.query(AllegroRepliedThread).filter_by(thread_id=thread_id).first():
                        message = settings_store.get("ALLEGRO_AUTORESPONDER_MESSAGE")
                        allegro_api.send_thread_message(access_token, thread_id, message)
                        db.add(AllegroRepliedThread(thread_id=thread_id))
                        db.commit()
                        logger.info(f"Auto-reply sent to thread {thread_id}")
    except Exception as e:
        logger.error(f"Failed to process new messages: {e}")

def process_new_discussions(access_token: str):
    """
    Fetches new discussions from Allegro, and if autoresponder is enabled,
    sends an automated reply to each new discussion.
    """
    if not settings_store.get("ALLEGRO_AUTORESPONDER_ENABLED"):
        return

    try:
        discussions = allegro_api.fetch_discussions(access_token)
        with get_session() as db:
            for discussion in discussions.get("disputes", []):
                discussion_id = discussion["id"]
                if not db.query(AllegroRepliedDiscussion).filter_by(discussion_id=discussion_id).first():
                    message = settings_store.get("ALLEGRO_AUTORESPONDER_MESSAGE")
                    allegro_api.send_discussion_message(access_token, discussion_id, message)
                    db.add(AllegroRepliedDiscussion(discussion_id=discussion_id))
                    db.commit()
                    logger.info(f"Auto-reply sent to discussion {discussion_id}")
    except Exception as e:
        logger.error(f"Failed to process new discussions: {e}")
