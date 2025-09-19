"""Configuration management system with environment-based validation and hot-reload support"""
from __future__ import annotations
from pydantic_settings import BaseSettings
from pydantic import Field, validator, SecretStr
from typing import Literal, Optional, Union, Dict, Any
import os
from dotenv import load_dotenv
from pathlib import Path
from enum import Enum

# Load environment variables
load_dotenv()

# Try to import structlog, fallback to standard logging if not available
try:
    import structlog
    logger = structlog.get_logger(__name__)
    HAS_STRUCTLOG = True
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    HAS_STRUCTLOG = False

class EnvironmentType(str, Enum):
    """Supported environment types"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"  
    PRODUCTION = "production"

class LogLevel(str, Enum):
    """Supported log levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class DatabaseSettings(BaseSettings):
    """Database-specific configuration"""
    url: str = Field(
        default="postgresql+asyncpg://memuser:secret@db:5432/memdb",
        description="Database connection URL"
    )
    pool_size: int = Field(default=10, ge=1, le=50, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, le=100, description="Max connection overflow")
    pool_timeout: int = Field(default=30, ge=5, le=300, description="Pool timeout in seconds")
    echo: bool = Field(default=False, description="Enable SQL query logging")
    
    @validator('url')
    def validate_database_url(cls, v):
        if not v or not v.startswith(('postgresql://', 'postgresql+asyncpg://')):
            raise ValueError('Database URL must be a valid PostgreSQL connection string')
        return v
    
    class Config:
        env_prefix = "DATABASE_"

class MinIOSettings(BaseSettings):
    """MinIO object storage configuration"""
    endpoint: Optional[str] = Field(default=None, description="MinIO server endpoint")
    access_key: Optional[SecretStr] = Field(default=None, description="MinIO access key")
    secret_key: Optional[SecretStr] = Field(default=None, description="MinIO secret key")
    bucket: str = Field(default="memory", description="Storage bucket name")
    secure: bool = Field(default=False, description="Use HTTPS for MinIO connection")
    
    @validator('endpoint')
    def validate_endpoint(cls, v):
        if v and not v.replace(':', '').replace('-', '').replace('.', '').replace('/', '').isalnum():
            logger.warning("MinIO endpoint format may be invalid", endpoint=v)
        return v
    
    @property
    def is_configured(self) -> bool:
        """Check if MinIO is properly configured"""
        return bool(self.endpoint and self.access_key and self.secret_key)
    
    class Config:
        env_prefix = "MINIO_"

class TelegramSettings(BaseSettings):
    """Telegram Bot configuration"""
    token: Optional[SecretStr] = Field(default=None, description="Telegram bot token")
    webhook_url: Optional[str] = Field(default=None, description="Webhook base URL (without path)")
    webhook_path: str = Field(default="/webhook", description="Webhook path")
    use_webhook: bool = Field(default=False, description="Use webhook instead of polling")
    webhook_secret: Optional[SecretStr] = Field(default=None, description="Webhook secret for verification")
    
    @validator('token')
    def validate_bot_token(cls, v):
        if v:
            token_str = v.get_secret_value() if hasattr(v, 'get_secret_value') else str(v)
            if not token_str or len(token_str.split(':')) != 2:
                raise ValueError('Bot token must be in format "bot_id:bot_secret"')
        return v
    
    @validator('webhook_url')
    def validate_webhook_url(cls, v):
        if v and not v.startswith('https://'):
            logger.warning("Webhook URL should use HTTPS for production", url=v)
        return v
    
    @property
    def is_configured(self) -> bool:
        """Check if Telegram is properly configured"""
        return bool(self.token)
    
    @property
    def webhook_configured(self) -> bool:
        """Check if webhook is properly configured"""
        return bool(self.use_webhook and self.webhook_url)
    
    @property
    def bot_token(self) -> Optional[SecretStr]:
        """Backward compatibility property"""
        return self.token
    
    class Config:
        env_prefix = "BOT_"

class LLMSettings(BaseSettings):
    """LLM and AI configuration"""
    key: Optional[SecretStr] = Field(default=None, description="OpenAI API key")
    disabled: bool = Field(default=False, description="Disable LLM processing")
    max_tokens_out: int = Field(default=4000, ge=100, le=8000, description="Maximum output tokens")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0, description="LLM temperature")
    timeout: int = Field(default=60, ge=10, le=300, description="LLM request timeout in seconds")
    
    @validator('key')
    def validate_openai_key(cls, v):
        if v:
            key_str = v.get_secret_value() if hasattr(v, 'get_secret_value') else str(v)
            if not key_str.startswith('sk-'):
                logger.warning("OpenAI API key format may be invalid")
        return v
    
    @property
    def is_configured(self) -> bool:
        """Check if LLM is properly configured"""
        return bool(self.key and not self.disabled)
    
    @property
    def openai_api_key(self) -> Optional[SecretStr]:
        """Backward compatibility property"""
        return self.key
    
    class Config:
        env_prefix = "OPENAI_API_"

class ProcessingSettings(BaseSettings):
    """Document processing configuration"""
    project_max_chunks: int = Field(default=200, ge=10, le=1000, description="Max chunks per project")
    chunk_size: int = Field(default=1600, ge=500, le=4000, description="Chunk size in characters")
    chunk_overlap: int = Field(default=150, ge=0, le=500, description="Chunk overlap in characters")
    
    @validator('chunk_overlap')
    def validate_chunk_overlap(cls, v, values):
        chunk_size = values.get('chunk_size', 1600)
        if v >= chunk_size:
            raise ValueError('Chunk overlap must be less than chunk size')
        return v
    
    class Config:
        env_prefix = "PROCESSING_"

class UISettings(BaseSettings):
    """User interface configuration"""
    max_message_length: int = Field(default=4096, ge=1000, le=4096, description="Max Telegram message length")
    max_inline_buttons: int = Field(default=100, ge=10, le=100, description="Max inline keyboard buttons")
    default_page_size: int = Field(default=5, ge=1, le=20, description="Default pagination size")
    
    class Config:
        env_prefix = "UI_"

class RedisSettings(BaseSettings):
    """Redis configuration for caching and queues"""
    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis port")
    db: int = Field(default=0, ge=0, le=15, description="Redis database number")
    password: Optional[SecretStr] = Field(default=None, description="Redis password")
    ssl: bool = Field(default=False, description="Use SSL for Redis connection")
    connection_pool_size: int = Field(default=20, ge=1, le=100, description="Redis connection pool size")
    
    @property
    def is_configured(self) -> bool:
        """Check if Redis is properly configured"""
        return bool(self.host and self.port)
    
    class Config:
        env_prefix = "REDIS_"

class FeatureFlags(BaseSettings):
    """Feature flags for safe rollout of optimizations"""
    use_webhook: bool = Field(default=False, description="Enable webhook mode")
    use_cache: bool = Field(default=False, description="Enable Redis caching")
    use_debounce: bool = Field(default=False, description="Enable click debouncing")
    use_connection_pools: bool = Field(default=False, description="Enable HTTP connection pooling")
    use_rate_limiting: bool = Field(default=False, description="Enable rate limiting")
    use_queue: bool = Field(default=False, description="Enable task queuing")
    
    class Config:
        env_prefix = "FEATURE_"

class SecuritySettings(BaseSettings):
    """Security and retry configuration"""
    max_retries: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")
    retry_base_delay: float = Field(default=1.0, ge=0.1, le=5.0, description="Base retry delay in seconds")
    retry_max_delay: float = Field(default=10.0, ge=1.0, le=60.0, description="Max retry delay in seconds")
    cache_ttl: int = Field(default=3600, ge=60, le=86400, description="Cache TTL in seconds")
    
    # Rate limiting settings
    ask_rate_limit: int = Field(default=10, ge=1, le=100, description="Ask requests per minute per user")
    refine_rate_limit: int = Field(default=20, ge=1, le=100, description="Refine requests per minute per user")
    
    # Debounce settings
    debounce_timeout_ms: int = Field(default=500, ge=100, le=2000, description="Debounce timeout in milliseconds")
    
    @validator('retry_max_delay')
    def validate_max_delay(cls, v, values):
        base_delay = values.get('retry_base_delay', 1.0)
        if v <= base_delay:
            raise ValueError('Max delay must be greater than base delay')
        return v
    
    class Config:
        env_prefix = "SECURITY_"

class MonitoringSettings(BaseSettings):
    """Logging and monitoring configuration"""
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Application log level")
    sentry_dsn: Optional[str] = Field(default=None, description="Sentry DSN for error tracking")
    app_version: str = Field(default="1.0.0", description="Application version")
    enable_metrics: bool = Field(default=True, description="Enable metrics collection")
    log_format: Literal["json", "console"] = Field(default="json", description="Log output format")
    
    @validator('sentry_dsn')
    def validate_sentry_dsn(cls, v):
        if v and not v.startswith('https://'):
            logger.warning("Sentry DSN format may be invalid", dsn=v[:20] + "...")
        return v
    
    @property
    def is_sentry_configured(self) -> bool:
        """Check if Sentry is configured"""
        return bool(self.sentry_dsn)
    
    class Config:
        env_prefix = "MONITORING_"

class Settings(BaseSettings):
    """Main application settings with nested configurations"""
    
    # Environment configuration
    environment: EnvironmentType = Field(default=EnvironmentType.DEVELOPMENT, description="Application environment")
    
    # Nested settings
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    minio: MinIOSettings = MinIOSettings()
    telegram: TelegramSettings = TelegramSettings()
    llm: LLMSettings = LLMSettings()
    processing: ProcessingSettings = ProcessingSettings()
    ui: UISettings = UISettings()
    security: SecuritySettings = SecuritySettings()
    monitoring: MonitoringSettings = MonitoringSettings()
    features: FeatureFlags = FeatureFlags()
    
    def __init__(self, **data):
        """Initialize settings with validation"""
        try:
            super().__init__(**data)
            self._validate_configuration()
            logger.info(
                "Configuration loaded successfully",
                environment=self.environment.value,
                database_configured=bool(self.database.url),
                redis_configured=self.redis.is_configured,
                minio_configured=self.minio.is_configured,
                llm_configured=self.llm.is_configured,
                sentry_configured=self.monitoring.is_sentry_configured,
                webhook_configured=self.telegram.webhook_configured
            )
        except Exception as e:
            logger.error(
                "Configuration validation failed",
                error=str(e),
                error_type=type(e).__name__
            )
            raise
    
    def _validate_configuration(self) -> None:
        """Validate critical configuration requirements"""
        errors = []
        
        # Only validate BOT_TOKEN if we're not in testing mode
        if self.environment != EnvironmentType.TESTING and not self.telegram.is_configured:
            logger.warning("BOT_TOKEN is not configured - bot functionality will be limited")
        
        # Database URL validation
        if not self.database.url:
            errors.append("DATABASE_URL is required")
        
        # Environment-specific validations
        if self.environment == EnvironmentType.PRODUCTION:
            if not self.telegram.is_configured:
                errors.append("BOT_TOKEN is required for production environment")
            if not self.monitoring.is_sentry_configured:
                logger.warning("Sentry not configured for production environment")
            if self.monitoring.log_level == LogLevel.DEBUG:
                logger.warning("DEBUG log level not recommended for production")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    def reload_from_env(self) -> None:
        """Reload configuration from environment variables"""
        logger.info("Reloading configuration from environment")
        load_dotenv(override=True)
        
        # Reinitialize nested settings
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.minio = MinIOSettings()
        self.telegram = TelegramSettings()
        self.llm = LLMSettings()
        self.processing = ProcessingSettings()
        self.ui = UISettings()
        self.security = SecuritySettings()
        self.monitoring = MonitoringSettings()
        self.features = FeatureFlags()
        
        self._validate_configuration()
        logger.info("Configuration reloaded successfully")
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get a summary of current configuration (excluding secrets)"""
        return {
            "environment": self.environment.value,
            "app_version": self.monitoring.app_version,
            "database": {
                "pool_size": self.database.pool_size,
                "max_overflow": self.database.max_overflow,
                "pool_timeout": self.database.pool_timeout,
                "echo": self.database.echo
            },
            "minio": {
                "configured": self.minio.is_configured,
                "bucket": self.minio.bucket,
                "secure": self.minio.secure
            },
            "llm": {
                "configured": self.llm.is_configured,
                "disabled": self.llm.disabled,
                "max_tokens_out": self.llm.max_tokens_out,
                "temperature": self.llm.temperature,
                "timeout": self.llm.timeout
            },
            "processing": {
                "project_max_chunks": self.processing.project_max_chunks,
                "chunk_size": self.processing.chunk_size,
                "chunk_overlap": self.processing.chunk_overlap
            },
            "ui": {
                "max_message_length": self.ui.max_message_length,
                "max_inline_buttons": self.ui.max_inline_buttons,
                "default_page_size": self.ui.default_page_size
            },
            "security": {
                "max_retries": self.security.max_retries,
                "retry_base_delay": self.security.retry_base_delay,
                "retry_max_delay": self.security.retry_max_delay,
                "cache_ttl": self.security.cache_ttl
            },
            "monitoring": {
                "log_level": self.monitoring.log_level.value,
                "sentry_configured": self.monitoring.is_sentry_configured,
                "enable_metrics": self.monitoring.enable_metrics,
                "log_format": self.monitoring.log_format
            }
        }
    
    @property
    def DATABASE_URL(self) -> str:
        """Uppercase property for Alembic compatibility"""
        return self.database.url
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment"""
        return self.environment == EnvironmentType.DEVELOPMENT
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.environment == EnvironmentType.PRODUCTION
    
    class Config:
        env_file = ".env"
        extra = "ignore"
        case_sensitive = False


# Create global settings instance
try:
    settings = Settings()
except Exception as e:
    logger.error("Failed to initialize settings", error=str(e))
    # Use minimal fallback configuration
    settings = None
    raise

# Backward compatibility - preserve global constants
LLM_DISABLED = settings.llm.disabled if settings else True
