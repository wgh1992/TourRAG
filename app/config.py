"""
Application configuration using Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/tourrag_db"
    
    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4o-mini"  # Use gpt-4o-mini for cost efficiency (supports vision)
    
    # MCP
    MCP_SERVER_URL: str = "http://localhost:8001"
    
    # Google Maps API (for satellite image fallback)
    GOOGLE_MAPS_API_KEY: Optional[str] = None
    
    # Application
    APP_NAME: str = "TourRAG"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Tag Schema
    TAG_SCHEMA_VERSION: str = "v1.0.0"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()

