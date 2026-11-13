"""Órdenes de línea de comandos: auth-url, auth-exchange y publish."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .tiktok import TikTok, TikTokError, authorize_url

REDIRECT_URI = "http://localhost:3455/callback/"
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}
REFRESH_SECRET = "TIKTOK_REFRESH_TOKEN"


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Falta la variable {name}")
    return value


def _derive(label: str) -> str:
    # El verificador PKCE y el state deben sobrevivir entre dos ejecuciones
    # separadas del workflow, así que se derivan del client_secret.
    return hmac.new(env("TIKTOK_CLIENT_SECRET").encode(), label.encode(), hashlib.sha256).hexdigest()


def save_refresh_token(token: str) -> None:
    """Guarda el nuevo refresh token como secreto del repo (TikTok lo rota en cada uso)."""
    repo = env("GITHUB_REPOSITORY")
    subprocess.run(
        ["gh", "secret", "set", REFRESH_SECRET, "--repo", repo],
        input=token,
        text=True,
        check=True,
    )


def next_video(queue: Path) -> Path | None:
    videos = sorted(p for p in queue.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
    return videos[0] if videos else None


def caption_for(video: Path) -> str:
    sidecar = video.with_suffix(".txt")
    return sidecar.read_text(encoding="utf-8").strip() if sidecar.exists() else ""


def cmd_auth_url(_: argparse.Namespace) -> None:
    print(authorize_url(env("TIKTOK_CLIENT_KEY"), REDIRECT_URI, _derive("state"), _derive("pkce")))


def cmd_auth_exchange(args: argparse.Namespace) -> None:
    query = parse_qs(urlparse(args.callback_url.strip()).query)
    if "code" not in query:
        sys.exit("La URL pegada no contiene el parámetro 'code'")
    if not hmac.compare_digest(query.get("state", [""])[0], _derive("state")):
        sys.exit("El parámetro 'state' no coincide; repite la autorización desde el principio")
    client = TikTok(env("TIKTOK_CLIENT_KEY"), env("TIKTOK_CLIENT_SECRET"))
    tokens = client.exchange_code(query["code"][0], REDIRECT_URI, _derive("pkce"))
    save_refresh_token(tokens.refresh_token)
    info = client.creator_info()
    print(f"Autorizado como @{info.get('creator_username')}")
    print(f"Privacidad permitida: {', '.join(info.get('privacy_level_options', []))}")


def cmd_publish(args: argparse.Namespace) -> None:
    queue, done = Path(args.queue), Path(args.published)
    video = next_video(queue)
    if video is None:
        print("La cola está vacía; no hay nada que publicar.")
        return

    client = TikTok(env("TIKTOK_CLIENT_KEY"), env("TIKTOK_CLIENT_SECRET"))
    tokens = client.refresh(env(REFRESH_SECRET))
    # Antes que nada: si esto no se guarda, la siguiente ejecución no podrá autenticarse.
    save_refresh_token(tokens.refresh_token)

    privacy = os.environ.get("TIKTOK_PRIVACY", "").strip() or "SELF_ONLY"
    allowed = client.creator_info().get("privacy_level_options", [])
    if privacy not in allowed:
        sys.exit(f"Privacidad '{privacy}' no permitida para esta cuenta. Opciones: {', '.join(allowed)}")

    publish_id = client.publish_video(video, caption_for(video), privacy)
    client.wait_until_published(publish_id)
    print(f"Publicado {video.name} ({privacy})")

    done.mkdir(parents=True, exist_ok=True)
    for path in (video, video.with_suffix(".txt")):
        if path.exists():
            path.rename(done / path.name)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="noalasdrogas")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth-url", help="Muestra la URL para autorizar la app en TikTok").set_defaults(func=cmd_auth_url)
    exchange = sub.add_parser("auth-exchange", help="Canjea la URL de retorno por los tokens")
    exchange.add_argument("callback_url")
    exchange.set_defaults(func=cmd_auth_exchange)
    publish = sub.add_parser("publish", help="Publica el siguiente vídeo de la cola")
    publish.add_argument("--queue", default="queue")
    publish.add_argument("--published", default="published")
    publish.set_defaults(func=cmd_publish)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except TikTokError as error:
        sys.exit(f"Error de TikTok: {error}")


if __name__ == "__main__":
    main()
