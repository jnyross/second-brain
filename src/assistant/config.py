from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_bot_token: str = ""
    notion_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    anthropic_api_key: str = ""

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
    google_maps_api_key: str = ""

    # WhatsApp Business Cloud API settings
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""

    user_timezone: str = "UTC"
    user_home_address: str = ""
    user_telegram_chat_id: str = ""

    # Sentry error tracking
    sentry_dsn: str = ""
    sentry_environment: str = "production"

    # UptimeRobot heartbeat monitoring
    uptimerobot_heartbeat_url: str = ""
    uptimerobot_heartbeat_interval: int = 300  # seconds (5 min default)

    confidence_threshold: int = 80
    morning_briefing_hour: int = 7
    log_level: str = "INFO"
    data_dir: str = "~/.second-brain"

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
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_google(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def has_google_maps(self) -> bool:
        return bool(self.google_maps_api_key)

    @property
    def has_whatsapp(self) -> bool:
        return bool(self.whatsapp_phone_number_id and self.whatsapp_access_token)

    @property
    def has_sentry(self) -> bool:
        return bool(self.sentry_dsn)

    @property
    def has_uptimerobot(self) -> bool:
        return bool(self.uptimerobot_heartbeat_url)


settings = Settings()
