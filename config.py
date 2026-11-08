from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    admin_ids: str = ""
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "betbot"
    fernet_key: str
    captcha_key: str = ""
    max_accounts_per_job: int = 25
    job_workers: int = 2
    proxy_refresh_sec: int = 1200

    @property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip()}


settings = Settings()