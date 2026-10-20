"""Google 访问令牌后台提前刷新：用户请求里不再等换令牌（服务器到 oauth2.googleapis.com 时好时坏）。"""
from datetime import UTC, datetime, timedelta

from google.auth.exceptions import TransportError

from app.llm import google


class FakeCreds:
    def __init__(self, left, failures=0):
        self.token = "t"
        self.expiry = (datetime.now(UTC) + left).replace(tzinfo=None)  # google-auth 用不带时区的 UTC
        self.failures, self.calls = failures, 0

    def refresh(self, request):
        self.calls += 1
        assert isinstance(request, google._QuickRequest)
        if self.failures:
            self.failures -= 1
            raise TransportError("connect timeout")
        self.expiry = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None)


def test_refresh_only_when_close_to_expiry(monkeypatch):
    monkeypatch.setattr(google.time, "sleep", lambda s: None)
    creds = FakeCreds(timedelta(minutes=40))
    monkeypatch.setattr(google, "credentials", lambda: creds)
    assert google.refresh() and creds.calls == 0  # 还早，不换
    creds.expiry = (datetime.now(UTC) + timedelta(minutes=10)).replace(tzinfo=None)
    assert google.refresh() and creds.calls == 1  # 剩不到 15 分钟，提前换


def test_refresh_retries_and_reports(monkeypatch):
    monkeypatch.setattr(google.time, "sleep", lambda s: None)
    creds = FakeCreds(timedelta(minutes=5), failures=2)
    monkeypatch.setattr(google, "credentials", lambda: creds)
    assert google.refresh() and creds.calls == 3  # 连不上时重试，第三次成功
    expired = FakeCreds(timedelta(minutes=-1), failures=5)
    monkeypatch.setattr(google, "credentials", lambda: expired)
    assert google.refresh() is False and expired.calls == 3  # 一直连不上：如实返回不可用


def test_quick_request_caps_timeout(monkeypatch):
    seen = {}

    def fake_call(self, *args, timeout=None, **kwargs):
        seen["timeout"] = timeout

    monkeypatch.setattr(google.Request, "__call__", fake_call)
    google._QuickRequest()(url="https://oauth2.googleapis.com/token", method="POST")
    assert seen["timeout"] == google.REFRESH_TIMEOUT


def test_credentials_are_self_signed(monkeypatch):
    """令牌在本地签发：刷新不需要访问 oauth2.googleapis.com。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt

    # credentials() 必须打开本地签发
    seen = {}

    class Loaded:
        def with_always_use_jwt_access(self, value):
            seen["jwt"] = value
            return self

    monkeypatch.setattr(google, "_credentials_file", lambda: "/tmp/sa.json")
    monkeypatch.setattr(google.service_account.Credentials, "from_service_account_file", lambda path, scopes: Loaded())
    google.credentials.cache_clear()
    try:
        google.credentials()
        assert seen == {"jwt": True}
    finally:
        google.credentials.cache_clear()

    # 本地签发的令牌：刷新时不碰网络
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    creds = google.service_account.Credentials(
        crypt.RSASigner.from_string(pem, "k"), "relay@p.iam.gserviceaccount.com", "https://oauth2.googleapis.com/token",
        scopes=google.SCOPES, always_use_jwt_access=True,
    )

    def no_network(*args, **kwargs):
        raise AssertionError("不应该访问网络")

    monkeypatch.setattr(google.Request, "__call__", no_network)
    creds.refresh(google._QuickRequest())
    assert creds.token and creds.token.count(".") == 2 and google._remaining(creds) > timedelta(minutes=50)
