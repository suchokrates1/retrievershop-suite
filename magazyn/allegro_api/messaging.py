"""
Wiadomości i dyskusje Allegro API.
"""
import logging
from typing import Optional

import requests

from .core import API_BASE_URL, _request_with_retry


def fetch_discussions(access_token: str) -> dict:
    """Pobierz wszystkie dyskusje z Allegro używając access tokenu."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
    }
    url = f"{API_BASE_URL}/sale/issues"

    all_issues = []
    offset = 0
    limit = 20

    while True:
        params = {"offset": offset, "limit": limit, "status": "DISPUTE_ONGOING"}
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="discussions",
            headers=headers,
            params=params,
        )
        data = response.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)

        if not issues or len(issues) < limit:
            break
        offset += limit

    return {"issues": all_issues}


def fetch_message_threads(access_token: str) -> dict:
    """Pobierz wszystkie wątki wiadomości z Allegro."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    url = f"{API_BASE_URL}/messaging/threads"

    all_threads = []
    offset = 0
    limit = 20

    while True:
        params = {"offset": offset, "limit": limit}
        response = _request_with_retry(
            requests.get,
            url,
            endpoint="message_threads",
            headers=headers,
            params=params,
        )
        data = response.json()
        threads = data.get("threads", [])
        all_threads.extend(threads)

        if not threads or len(threads) < limit:
            break
        offset += limit

    return {"threads": all_threads}


def fetch_discussion_issues(access_token: str, limit: int = 100) -> dict:
    """Pobierz wszystkie sprawy dyskusji (reklamacje i spory) z Allegro."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
    }
    
    all_issues = []
    offset = 0
    page_limit = min(limit, 100)  # API max is 100
    
    while True:
        params = {"offset": offset, "limit": page_limit}
        url = f"{API_BASE_URL}/sale/issues"
        response = _request_with_retry(
            requests.get, url, endpoint="discussion_issues", headers=headers, params=params
        )
        data = response.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)
        
        if not issues or len(issues) < page_limit or len(all_issues) >= limit:
            break
        offset += page_limit
    
    return {"issues": all_issues[:limit]}


def fetch_discussion_chat(access_token: str, issue_id: str, limit: int = 100) -> dict:
    """
    Pobierz wiadomości z dyskusji lub reklamacji (Issues API).
    
    Endpoint: GET /sale/issues/{issueId}/chat
    
    Args:
        access_token: Token dostępu Allegro
        issue_id: ID dyskusji/reklamacji
        limit: Maksymalna liczba wiadomości (1-100, Issues API akceptuje do 100)
    
    Returns:
        dict: {"chat": [...]} - wiadomości w kolejności od najnowszej do najstarszej
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
    }
    params = {"limit": min(limit, 100)}
    url = f"{API_BASE_URL}/sale/issues/{issue_id}/chat"
    response = _request_with_retry(
        requests.get, url, endpoint="discussion_chat", headers=headers, params=params
    )
    data = response.json()
    logging.info(
        f"[DEBUG] fetch_discussion_chat({issue_id}): keys={list(data.keys())}, "
        f"message_count={len(data.get('chat', []))}"
    )
    return data


def fetch_thread_messages(access_token: str, thread_id: str, limit: int = 20) -> dict:
    """
    Pobierz wiadomości dla konkretnego wątku.
    
    UWAGA: Messaging API akceptuje maksymalnie limit=20!
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    params = {"limit": min(limit, 20)}
    url = f"{API_BASE_URL}/messaging/threads/{thread_id}/messages"
    response = _request_with_retry(
        requests.get, url, endpoint="thread_messages", headers=headers, params=params
    )
    data = response.json()
    logging.info(
        f"[DEBUG] fetch_thread_messages({thread_id}): keys={list(data.keys())}, "
        f"message_count={len(data.get('messages', []))}"
    )
    return data


def send_thread_message(
    access_token: str, 
    thread_id: str, 
    text: str, 
    attachment_ids: Optional[list] = None
) -> dict:
    """
    Wyślij wiadomość do wątku w Centrum Wiadomości Allegro.
    
    Args:
        access_token: Token dostępu Allegro
        thread_id: ID wątku
        text: Treść wiadomości (do 2000 znaków)
        attachment_ids: Lista ID załączników (opcjonalne)
    
    Returns:
        dict: Odpowiedź API z danymi wysłanej wiadomości
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }
    
    payload = {"text": text}
    
    if attachment_ids:
        payload["attachments"] = [{"id": aid} for aid in attachment_ids]
    else:
        payload["attachments"] = []
    
    url = f"{API_BASE_URL}/messaging/threads/{thread_id}/messages"
    response = _request_with_retry(
        requests.post, url, endpoint="send_thread_message", headers=headers, json=payload
    )
    return response.json()


def send_discussion_message(
    access_token: str, 
    issue_id: str, 
    text: str,
    attachment_ids: Optional[list] = None
) -> dict:
    """
    Wyślij wiadomość do dyskusji lub reklamacji (Issues API).
    
    Args:
        access_token: Token dostępu Allegro
        issue_id: ID dyskusji/reklamacji
        text: Treść wiadomości
        attachment_ids: Lista ID załączników (opcjonalne)
    
    Returns:
        dict: Odpowiedź API z danymi wysłanej wiadomości
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
        "Content-Type": "application/vnd.allegro.beta.v1+json",
    }
    
    payload = {
        "text": text,
        "type": "REGULAR"
    }
    
    if attachment_ids:
        payload["attachments"] = [{"id": aid} for aid in attachment_ids]
    
    url = f"{API_BASE_URL}/sale/issues/{issue_id}/message"
    response = _request_with_retry(
        requests.post,
        url,
        endpoint="send_discussion_message",
        headers=headers,
        json=payload,
    )
    return response.json()
