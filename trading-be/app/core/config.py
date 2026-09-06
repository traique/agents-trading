from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import secrets

class Settings(BaseSettings):
    PROJECT_NAME: str = "TradingAgents Backend"
    API_V1_STR: str = "/api/v1"

    # Security - token tự sinh mỗi boot nếu không set env (session cũ vô hiệu
    # sau restart) thay vì khóa ký cố định ai cũng đoán được.
    SECRET_KEY: str = secrets.token_hex(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS - danh sách origin phân tách bởi dấu phẩy
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./trading_agents.db"
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "trading_agents_logs"
    
    # AI / LLM Config
    OPENAI_API_KEY: Optional[str] = None
    LLM_PROVIDER: str = "openai"
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="allow")

settings = Settings()
