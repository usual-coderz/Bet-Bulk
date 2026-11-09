from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # core
    bot_token: str
    admin_ids: str = ""
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "betbot"
    fernet_key: str
    captcha_key: str = ""
    log_level: str = "INFO"

    # queue / batching
    job_workers: int = 1
    batch: int = 4
    per_site: int = 2
    max_accounts_per_job: int = 25

    # proxy
    proxy_mode: str = "auto"          # auto | off
    max_validate: int = 200
    validate_concurrency: int = 40
    proxy_refresh_sec: int = 1200

    # browser timeouts
    goto_ms: int = 30000
    goto_ms_proxy: int = 15000
    form_ms: int = 20000
    redirect_ms: int = 45000
    headless: bool = True

    # debug
    debug_dump: bool = True

    @property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip()}


settings = Settings()