from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "teams-meeting-assistant"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BASE_URL: str  # Public URL, e.g. https://your-app.azurecontainerapps.io

    # Database
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host:5432/dbname

    # Microsoft Entra ID (Azure AD)
    AZURE_TENANT_ID: str
    AZURE_CLIENT_ID: str
    AZURE_CLIENT_SECRET: str

    # Azure Communication Services
    ACS_CONNECTION_STRING: str
    ACS_ENDPOINT: str  # https://<resource>.communication.azure.com

    # Azure AI Foundry
    AI_FOUNDRY_ENDPOINT: str  # https://<resource>.openai.azure.com/
    AI_FOUNDRY_API_KEY: str
    AI_FOUNDRY_DEPLOYMENT_NAME: str = "gpt-4o-mini"
    AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX: str = "gpt-4o"

    # Meeting Bot Behavior
    BOT_DISPLAY_NAME: str = "Meeting Assistant"
    BOT_JOIN_BEFORE_MINUTES: int = 1
    NUDGE_CHECK_INTERVAL_MINUTES: int = 30
    NUDGE_ESCALATION_THRESHOLD: int = 2
    LONG_MEETING_THRESHOLD_MINUTES: int = 120

    # Media Bot (C# service)
    MEDIA_BOT_BASE_URL: str = "http://media-bot:8080"
    INTER_SERVICE_HMAC_KEY: str = ""

    # Redis (for task queue, optional)
    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
