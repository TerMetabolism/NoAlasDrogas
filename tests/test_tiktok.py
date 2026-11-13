import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from noalasdrogas import cli
from noalasdrogas.tiktok import MB, TikTok, TikTokError, authorize_url, chunk_plan, code_challenge

UPLOAD_URL = "https://open-upload.tiktokapis.com/video/?upload_id=1&upload_token=x"


def ok(data):
    return httpx.Response(200, json={"data": data, "error": {"code": "ok", "message": ""}})


class FakeTikTok:
    """Simula la API de TikTok y registra las peticiones recibidas."""

    def __init__(self, statuses=("PROCESSING_UPLOAD", "PUBLISH_COMPLETE"), privacy=("SELF_ONLY",)):
        self.requests = []
        self.statuses = list(statuses)
        self.privacy = list(privacy)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v2/oauth/token/":
            form = parse_qs(request.content.decode())
            if form.get("refresh_token") == ["caducado"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired"})
            return httpx.Response(
                200,
                json={
                    "access_token": "act.nuevo",
                    "refresh_token": "rft.nuevo",
                    "expires_in": 7200,
                    "refresh_expires_in": 15552000,
                },
            )
        if path == "/v2/post/publish/creator_info/query/":
            return ok({"creator_username": "canal", "privacy_level_options": self.privacy})
        if path == "/v2/post/publish/video/init/":
            return ok({"publish_id": "v_pub_1", "upload_url": UPLOAD_URL})
        if request.method == "PUT":
            return httpx.Response(201)
        if path == "/v2/post/publish/status/fetch/":
            return ok({"status": self.statuses.pop(0), "fail_reason": "spam_risk"})
        return httpx.Response(404)

    def client(self) -> TikTok:
        return TikTok("key", "secret", http=httpx.Client(transport=httpx.MockTransport(self)))


def test_chunk_plan_follows_tiktok_rules():
    assert chunk_plan(3 * MB) == (3 * MB, 1)
    assert chunk_plan(64 * MB) == (64 * MB, 1)
    # Hasta 64 MB se sube entero aunque se pida un trozo menor.
    assert chunk_plan(50_000_123, 10_000_000) == (50_000_123, 1)
    assert chunk_plan(100 * MB + 123, 10 * MB) == (10 * MB, 10)
    with pytest.raises(TikTokError):
        chunk_plan(0)


def test_authorize_url_uses_hex_sha256_challenge():
    query = parse_qs(urlparse(authorize_url("key", "http://localhost:3455/callback/", "st", "verif")).query)
    assert query["code_challenge"] == [code_challenge("verif")]
    assert len(query["code_challenge"][0]) == 64
    assert query["scope"] == ["video.publish"]
    assert query["code_challenge_method"] == ["S256"]


def test_refresh_returns_rotated_token_and_hides_body_on_error():
    fake = FakeTikTok()
    tokens = fake.client().refresh("rft.viejo")
    assert tokens.refresh_token == "rft.nuevo"
    form = parse_qs(fake.requests[0].content.decode())
    assert form["grant_type"] == ["refresh_token"] and form["client_secret"] == ["secret"]
    with pytest.raises(TikTokError, match="expired"):
        fake.client().refresh("caducado")


def test_publish_small_video_in_one_chunk(tmp_path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x" * 1000)
    fake = FakeTikTok()
    client = fake.client()
    client.refresh("rft")
    publish_id = client.publish_video(video, "hola #fyp", "SELF_ONLY")
    assert client.wait_until_published(publish_id, interval=0)["status"] == "PUBLISH_COMPLETE"

    init = next(r for r in fake.requests if r.url.path.endswith("/video/init/"))
    body = json.loads(init.content)
    assert body["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": 1000,
        "chunk_size": 1000,
        "total_chunk_count": 1,
    }
    assert body["post_info"] == {"title": "hola #fyp", "privacy_level": "SELF_ONLY"}
    assert init.headers["Authorization"] == "Bearer act.nuevo"
    put = next(r for r in fake.requests if r.method == "PUT")
    assert put.headers["Content-Range"] == "bytes 0-999/1000"
    assert put.headers["Content-Type"] == "video/mp4"


def test_large_video_last_chunk_absorbs_remainder(tmp_path, monkeypatch):
    monkeypatch.setattr("noalasdrogas.tiktok.MAX_SINGLE", 100)
    monkeypatch.setattr("noalasdrogas.tiktok.MIN_CHUNK", 10)
    monkeypatch.setattr("noalasdrogas.tiktok.chunk_plan.__defaults__", (100,))
    video = tmp_path / "b.mp4"
    video.write_bytes(bytes(range(256)) + b"z" * 3)  # 259 bytes, trozos de 100
    fake = FakeTikTok()
    client = fake.client()
    client.refresh("rft")
    client.publish_video(video, "", "SELF_ONLY")
    puts = [r for r in fake.requests if r.method == "PUT"]
    assert [r.headers["Content-Range"] for r in puts] == ["bytes 0-99/259", "bytes 100-258/259"]
    assert b"".join(r.content for r in puts) == video.read_bytes()


def test_failed_status_raises_with_reason():
    fake = FakeTikTok(statuses=["FAILED"])
    client = fake.client()
    client.refresh("rft")
    with pytest.raises(TikTokError, match="spam_risk"):
        client.wait_until_published("v_pub_1", interval=0)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    fake = FakeTikTok()
    saved = []
    monkeypatch.setattr(cli, "TikTok", lambda key, secret: fake.client())
    monkeypatch.setattr(cli, "save_refresh_token", saved.append)
    monkeypatch.setattr("noalasdrogas.tiktok.time.sleep", lambda _: None)
    for name in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "valor")
    monkeypatch.delenv("TIKTOK_PRIVACY", raising=False)
    (tmp_path / "queue").mkdir()
    return fake, saved, tmp_path


def run_publish(root):
    cli.main(["publish", "--queue", str(root / "queue"), "--published", str(root / "published")])


def test_cli_publishes_oldest_video_and_moves_it(cli_env):
    fake, saved, root = cli_env
    (root / "queue" / "002.mp4").write_bytes(b"dos")
    (root / "queue" / "001.mp4").write_bytes(b"uno")
    (root / "queue" / "001.txt").write_text("texto del primero\n", encoding="utf-8")
    run_publish(root)

    assert saved == ["valor", "rft.nuevo"]
    init = next(r for r in fake.requests if r.url.path.endswith("/video/init/"))
    assert json.loads(init.content)["post_info"]["title"] == "texto del primero"
    assert sorted(p.name for p in (root / "published").iterdir()) == ["001.mp4", "001.txt"]
    assert [p.name for p in (root / "queue").iterdir()] == ["002.mp4"]


def test_cli_empty_queue_does_not_touch_tokens(cli_env, capsys):
    fake, saved, root = cli_env
    run_publish(root)
    assert saved == [] and fake.requests == []
    assert "vacía" in capsys.readouterr().out


def test_cli_rejects_privacy_not_allowed_but_still_saves_token(cli_env, monkeypatch):
    fake, saved, root = cli_env
    (root / "queue" / "001.mp4").write_bytes(b"uno")
    monkeypatch.setenv("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE")
    with pytest.raises(SystemExit, match="no permitida"):
        run_publish(root)
    assert saved == ["valor", "rft.nuevo"]
    assert (root / "queue" / "001.mp4").exists()


def test_cli_does_not_rotate_token_if_secret_cannot_be_written(cli_env, monkeypatch):
    fake, saved, root = cli_env
    (root / "queue" / "001.mp4").write_bytes(b"uno")

    def fail(_):
        raise OSError("gh no disponible")

    monkeypatch.setattr(cli, "save_refresh_token", fail)
    with pytest.raises(SystemExit, match="GH_PAT"):
        run_publish(root)
    assert fake.requests == []


def test_auth_exchange_checks_state(cli_env, capsys):
    fake, saved, root = cli_env
    with pytest.raises(SystemExit, match="state"):
        cli.main(["auth-exchange", "http://localhost:3455/callback/?code=abc&state=malo"])
    good = cli._derive("state")
    cli.main(["auth-exchange", f"http://localhost:3455/callback/?code=abc&state={good}"])
    assert saved == ["rft.nuevo"]
    form = parse_qs(fake.requests[0].content.decode())
    assert form["code"] == ["abc"] and form["code_verifier"] == [cli._derive("pkce")]
    assert "@canal" in capsys.readouterr().out
