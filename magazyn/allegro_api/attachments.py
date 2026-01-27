"""
Załączniki Allegro API - Centrum Wiadomości i Issues API.
"""
import requests

from .core import API_BASE_URL, _request_with_retry


# ============================================================================
# ZALACZNIKI W CENTRUM WIADOMOSCI
# ============================================================================

def download_attachment(access_token: str, attachment_id: str) -> bytes:
    """
    Pobierz załącznik z Centrum Wiadomości Allegro.
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika (z pola attachment.url w wiadomości)
    
    Returns:
        bytes: Zawartość pliku
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "*/*",
    }
    url = f"{API_BASE_URL}/messaging/message-attachments/{attachment_id}"
    response = _request_with_retry(
        requests.get, url, endpoint="download_attachment", headers=headers
    )
    return response.content


def create_attachment_declaration(
    access_token: str, 
    filename: str, 
    size: int
) -> dict:
    """
    Utwórz deklarację załącznika przed jego przesłaniem.
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku (z rozszerzeniem)
        size: Rozmiar pliku w bajtach
    
    Returns:
        dict: Odpowiedź z ID załącznika {"id": "..."}
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
    }
    payload = {
        "filename": filename,
        "size": size,
    }
    url = f"{API_BASE_URL}/messaging/message-attachments"
    response = _request_with_retry(
        requests.post, 
        url, 
        endpoint="create_attachment_declaration", 
        headers=headers, 
        json=payload
    )
    return response.json()


def upload_attachment(
    access_token: str, 
    attachment_id: str, 
    file_content: bytes,
    content_type: str
) -> dict:
    """
    Prześlij załącznik na serwery Allegro.
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika (z create_attachment_declaration)
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME (np. 'image/png', 'application/pdf')
    
    Returns:
        dict: Odpowiedź z ID załącznika {"id": "..."}
    
    Supported content types:
        - image/png
        - image/gif
        - image/bmp
        - image/tiff
        - image/jpeg
        - application/pdf
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": content_type,
    }
    url = f"{API_BASE_URL}/messaging/message-attachments/{attachment_id}"
    response = _request_with_retry(
        requests.put, 
        url, 
        endpoint="upload_attachment", 
        headers=headers, 
        data=file_content
    )
    return response.json()


def upload_attachment_complete(
    access_token: str,
    filename: str,
    file_content: bytes,
    content_type: str
) -> str:
    """
    Pełny proces przesyłania załącznika (deklaracja + upload).
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME
    
    Returns:
        str: ID załącznika gotowego do użycia w wiadomości
    """
    size = len(file_content)
    declaration = create_attachment_declaration(access_token, filename, size)
    attachment_id = declaration["id"]
    
    upload_attachment(access_token, attachment_id, file_content, content_type)
    
    return attachment_id


# ============================================================================
# ZALACZNIKI W DYSKUSJACH I REKLAMACJACH (ISSUES API)
# ============================================================================

def download_issue_attachment(access_token: str, attachment_id: str) -> bytes:
    """
    Pobierz załącznik z dyskusji/reklamacji (Issues API).
    
    Endpoint: GET /sale/issues/attachments/{attachmentId}
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika
    
    Returns:
        bytes: Zawartość pliku
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    url = f"{API_BASE_URL}/sale/issues/attachments/{attachment_id}"
    response = _request_with_retry(
        requests.get, url, endpoint="download_issue_attachment", headers=headers
    )
    return response.content


def create_issue_attachment_declaration(
    access_token: str, 
    filename: str, 
    size: int
) -> dict:
    """
    Utwórz deklarację załącznika dla dyskusji/reklamacji (Issues API).
    
    Endpoint: POST /sale/issues/attachments
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku (z rozszerzeniem)
        size: Rozmiar pliku w bajtach (max 2097152 = 2MB)
    
    Returns:
        dict: Odpowiedź z ID załącznika {"id": "..."}
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
        "Content-Type": "application/vnd.allegro.beta.v1+json",
    }
    payload = {
        "fileName": filename,
        "size": size,
    }
    url = f"{API_BASE_URL}/sale/issues/attachments"
    response = _request_with_retry(
        requests.post, 
        url, 
        endpoint="create_issue_attachment_declaration", 
        headers=headers, 
        json=payload
    )
    return response.json()


def upload_issue_attachment(
    access_token: str, 
    attachment_id: str, 
    file_content: bytes,
    content_type: str
) -> dict:
    """
    Prześlij załącznik do dyskusji/reklamacji (Issues API).
    
    Endpoint: PUT /sale/issues/attachments/{attachmentId}
    
    Args:
        access_token: Token dostępu Allegro
        attachment_id: ID załącznika (z create_issue_attachment_declaration)
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME (np. 'image/png', 'application/pdf')
    
    Returns:
        dict: Odpowiedź (pusta)
    
    Supported content types:
        - image/png
        - image/gif
        - image/bmp
        - image/tiff
        - image/jpeg
        - application/pdf
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.beta.v1+json",
        "Content-Type": content_type,
    }
    url = f"{API_BASE_URL}/sale/issues/attachments/{attachment_id}"
    response = _request_with_retry(
        requests.put, 
        url, 
        endpoint="upload_issue_attachment", 
        headers=headers, 
        data=file_content
    )
    return {}


def upload_issue_attachment_complete(
    access_token: str,
    filename: str,
    file_content: bytes,
    content_type: str
) -> str:
    """
    Pełny proces przesyłania załącznika do dyskusji/reklamacji (Issues API).
    
    Args:
        access_token: Token dostępu Allegro
        filename: Nazwa pliku
        file_content: Zawartość pliku (binarna)
        content_type: Typ MIME
    
    Returns:
        str: ID załącznika gotowego do użycia w wiadomości
    """
    size = len(file_content)
    declaration = create_issue_attachment_declaration(access_token, filename, size)
    attachment_id = declaration["id"]
    
    upload_issue_attachment(access_token, attachment_id, file_content, content_type)
    
    return attachment_id
