from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_bot_token: str = ""
    notion_api_key: str = ""
    openai_api_key: str = ""

    notion_inbox_db_id: str = ""
    notion_tasks_db_id: str = ""
    notion_people_db_id: str = ""
    notion_projects_db_id: str = ""
    notion_places_db_id: str = ""
    notion_preferences_db_id: str = ""
    notion_patterns_db_id: str = ""
    notion_emails_db_id: str = ""
    notion_log_db_id: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""

    user_timezone: str = "UTC"
    user_telegram_chat_id: str = ""

    confidence_threshold: int = 80
    morning_briefing_hour: int = 7
    log_level: str = "INFO"

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def has_notion(self) -> bool:
        return bool(self.notion_api_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_google(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()
