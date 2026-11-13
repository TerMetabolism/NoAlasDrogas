"""Cliente mínimo de la Content Posting API de TikTok (publicación directa).

Referencia: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

API = "https://open.tiktokapis.com"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES = "video.publish"
JSON_HEADERS = {"Content-Type": "application/json; charset=UTF-8"}

MB = 1024 * 1024
MIN_CHUNK = 5 * MB
MAX_SINGLE = 64 * MB
DEFAULT_CHUNK = 10 * MB

MIME_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


class TikTokError(RuntimeError):
    pass


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int


def code_challenge(code_verifier: str) -> str:
    # TikTok pide el SHA256 en hexadecimal (no base64url) para apps de escritorio.
    return hashlib.sha256(code_verifier.encode()).hexdigest()


def authorize_url(client_key: str, redirect_uri: str, state: str, code_verifier: str) -> str:
    query = {
        "client_key": client_key,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def chunk_plan(video_size: int, chunk_size: int = DEFAULT_CHUNK) -> tuple[int, int]:
    """Devuelve (chunk_size, total_chunk_count) según las reglas de TikTok.

    Los vídeos de hasta 64 MB se suben enteros. Los mayores se trocean y el
    último trozo absorbe los bytes sobrantes.
    """
    if video_size <= 0:
        raise TikTokError("El vídeo está vacío")
    if video_size <= MAX_SINGLE:
        return video_size, 1
    if not MIN_CHUNK <= chunk_size <= MAX_SINGLE:
        raise TikTokError("chunk_size debe estar entre 5 MB y 64 MB")
    return chunk_size, video_size // chunk_size


class TikTok:
    def __init__(self, client_key: str, client_secret: str, http: httpx.Client | None = None):
        self.client_key = client_key
        self.client_secret = client_secret
        self.http = http or httpx.Client(timeout=120)
        self.access_token: str | None = None

    # --- OAuth -----------------------------------------------------------

    def _token_request(self, form: dict[str, str]) -> Tokens:
        form = {"client_key": self.client_key, "client_secret": self.client_secret, **form}
        response = self.http.post(f"{API}/v2/oauth/token/", data=form)
        body = response.json()
        if response.status_code != 200 or "access_token" not in body:
            # No se vuelca el cuerpo completo: puede contener tokens.
            reason = body.get("error_description") or body.get("error") or response.status_code
            raise TikTokError(f"TikTok rechazó la petición de token: {reason}")
        self.access_token = body["access_token"]
        return Tokens(
            access_token=body["access_token"],
            refresh_token=body["refresh_token"],
            expires_in=int(body.get("expires_in", 0)),
            refresh_expires_in=int(body.get("refresh_expires_in", 0)),
        )

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> Tokens:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )

    def refresh(self, refresh_token: str) -> Tokens:
        """Renueva el acceso. El refresh_token devuelto SUSTITUYE al enviado."""
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    # --- Publicación -----------------------------------------------------

    def _api(self, path: str, payload: dict | None = None) -> dict:
        if not self.access_token:
            raise TikTokError("Falta el token de acceso; llama antes a refresh()")
        headers = {"Authorization": f"Bearer {self.access_token}", **JSON_HEADERS}
        response = self.http.post(f"{API}{path}", headers=headers, json=payload or {})
        body = response.json()
        error = body.get("error") or {}
        if response.status_code != 200 or error.get("code") != "ok":
            raise TikTokError(
                f"{path}: {error.get('code', response.status_code)} - {error.get('message', '')}"
            )
        return body["data"]

    def creator_info(self) -> dict:
        return self._api("/v2/post/publish/creator_info/query/")

    def publish_video(self, video: Path, title: str, privacy_level: str) -> str:
        """Sube el vídeo y devuelve el publish_id para consultar su estado."""
        size = video.stat().st_size
        chunk_size, chunk_count = chunk_plan(size)
        mime = MIME_TYPES.get(video.suffix.lower())
        if mime is None:
            raise TikTokError(f"Formato no admitido: {video.suffix} (usa .mp4, .mov o .webm)")

        data = self._api(
            "/v2/post/publish/video/init/",
            {
                "post_info": {"title": title, "privacy_level": privacy_level},
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": chunk_count,
                },
            },
        )
        with video.open("rb") as handle:
            for index in range(chunk_count):
                first = index * chunk_size
                last = size - 1 if index == chunk_count - 1 else first + chunk_size - 1
                handle.seek(first)
                chunk = handle.read(last - first + 1)
                response = self.http.put(
                    data["upload_url"],
                    content=chunk,
                    headers={
                        "Content-Type": mime,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {first}-{last}/{size}",
                    },
                )
                if response.status_code not in (200, 201, 206):
                    raise TikTokError(f"Fallo al subir el trozo {index + 1}: HTTP {response.status_code}")
        return data["publish_id"]

    def wait_until_published(self, publish_id: str, timeout: float = 600, interval: float = 10) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            data = self._api("/v2/post/publish/status/fetch/", {"publish_id": publish_id})
            if data["status"] == "PUBLISH_COMPLETE":
                return data
            if data["status"] == "FAILED":
                raise TikTokError(f"TikTok rechazó la publicación: {data.get('fail_reason', 'sin motivo')}")
            if time.monotonic() >= deadline:
                raise TikTokError(f"Sin confirmación tras {timeout:.0f} s (estado: {data['status']})")
            time.sleep(interval)
