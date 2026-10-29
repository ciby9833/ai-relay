from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    secret_key: str
    database_url: str = "postgresql+asyncpg://relay:relay@localhost:54329/relay"
    frontend_url: str = "http://localhost:5173"
    default_timezone: str = "Asia/Jakarta"
    session_ttl_hours: int = 168
    dev_login: bool = False

    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_tenant_key: str = ""
    feishu_redirect_uri: str = "http://localhost:8098/api/auth/feishu/callback"
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # 用服务账号走 Vertex AI 时：凭证文件路径由 GOOGLE_APPLICATION_CREDENTIALS 指定，
    # 项目默认取凭证文件里的 project_id
    google_application_credentials: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    anthropic_models: str = "claude-opus-5-5,claude-haiku-5-5"
    openai_models: str = "gpt-5"
    gemini_models: str = "gemini-2.5-pro"
    default_model: str = ""
    embedding_model: str = ""
    # 主动流程（邮件分级、起草、简报）用的模型，provider:model；留空用默认模型
    triage_model: str = ""
    # 轻量模型：读附件、文件后提取要点这类量大但简单的活；留空且配了 Gemini 时用 gemini-3.5-flash-lite，否则用主动流程的模型
    light_model: str = ""
    # worker 并行度：同时跑几个用户的主流程、几个会话的聊天提取（受模型限流和数据库连接数约束）
    worker_concurrency: int = 6
    chat_concurrency: int = 3
    db_pool_size: int = 10
    db_max_overflow: int = 10  # 4 个进程各最多 20 条，合计 80，低于 Postgres 默认的 100

    # Optional observability; no dependency on the monitoring stack for business requests.
    monitoring_enabled: bool = False
    monitoring_port: int = 9101
    prometheus_url: str = "http://prometheus:9090"

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def dev_login_enabled(self) -> bool:
        return self.dev_login and not self.is_production

    @property
    def cookie_secure(self) -> bool:
        return self.frontend_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
