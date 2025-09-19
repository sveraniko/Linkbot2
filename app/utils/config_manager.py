"""Configuration management utility with hot-reload and validation capabilities"""
from __future__ import annotations
import os
import json
import signal
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
import structlog

from app.config import settings, Settings

logger = structlog.get_logger(__name__)


class ConfigurationManager:
    """Advanced configuration management with hot-reload and validation"""
    
    def __init__(self):
        self._reload_callbacks: list = []
        self._watching = False
        
    def add_reload_callback(self, callback) -> None:
        """Add callback to be executed when configuration is reloaded"""
        self._reload_callbacks.append(callback)
        logger.debug("Added configuration reload callback", callback=callback.__name__)
    
    async def reload_configuration(self) -> bool:
        """Reload configuration from environment and execute callbacks"""
        try:
            logger.info("Starting configuration reload")
            
            # Reload settings
            settings.reload_from_env()
            
            # Execute callbacks
            for callback in self._reload_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                    logger.debug("Executed reload callback", callback=callback.__name__)
                except Exception as e:
                    logger.error(
                        "Failed to execute reload callback",
                        callback=callback.__name__,
                        error=str(e)
                    )
            
            logger.info("Configuration reload completed successfully")
            return True
            
        except Exception as e:
            logger.error("Configuration reload failed", error=str(e), error_type=type(e).__name__)
            return False
    
    def validate_configuration(self) -> Dict[str, Any]:
        """Validate current configuration and return validation report"""
        try:
            report = {
                "status": "valid",
                "warnings": [],
                "errors": [],
                "summary": settings.get_configuration_summary()
            }
            
            # Check critical components
            if not settings.telegram.bot_token:
                report["errors"].append("BOT_TOKEN is not configured")
            
            if not settings.database.url:
                report["errors"].append("DATABASE_URL is not configured")
                
            if not settings.minio.is_configured:
                report["warnings"].append("MinIO storage is not configured")
                
            if not settings.llm.is_configured:
                report["warnings"].append("LLM/OpenAI is not configured")
                
            if settings.environment.value == "production":
                if not settings.monitoring.is_sentry_configured:
                    report["warnings"].append("Sentry monitoring not configured for production")
                if settings.monitoring.log_level.value == "DEBUG":
                    report["warnings"].append("DEBUG logging enabled in production")
            
            # Set overall status
            if report["errors"]:
                report["status"] = "invalid"
            elif report["warnings"]:
                report["status"] = "valid_with_warnings"
                
            return report
            
        except Exception as e:
            logger.error("Configuration validation failed", error=str(e))
            return {
                "status": "error",
                "errors": [f"Validation failed: {str(e)}"],
                "warnings": [],
                "summary": {}
            }
    
    def export_configuration_template(self, file_path: Optional[Path] = None) -> str:
        """Export configuration template with all available settings"""
        template = """# Project Memory Bot Configuration Template
# Copy this file to .env and configure the values

# =============================================================================
# MANDATORY SETTINGS - These must be configured for the bot to work
# =============================================================================

# Telegram Bot Token (get from @BotFather)
BOT_TOKEN=your_bot_token_here

# Database connection
DATABASE_URL=postgresql+asyncpg://memuser:secret@db:5432/memdb

# =============================================================================
# OPTIONAL SETTINGS - These have sensible defaults
# =============================================================================

# Application Environment
ENVIRONMENT=development  # development, testing, staging, production

# OpenAI/LLM Configuration
LLM_OPENAI_API_KEY=sk-your_openai_key_here
LLM_DISABLED=false
LLM_MAX_TOKENS_OUT=4000
LLM_TEMPERATURE=0.3
LLM_TIMEOUT=60

# MinIO Object Storage (optional)
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=memory
MINIO_SECURE=false

# Database Pool Settings
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT=30
DATABASE_ECHO=false

# Document Processing
PROCESSING_PROJECT_MAX_CHUNKS=200
PROCESSING_CHUNK_SIZE=1600
PROCESSING_CHUNK_OVERLAP=150

# User Interface
UI_MAX_MESSAGE_LENGTH=4096
UI_MAX_INLINE_BUTTONS=100
UI_DEFAULT_PAGE_SIZE=5

# Security & Retry Logic
SECURITY_MAX_RETRIES=3
SECURITY_RETRY_BASE_DELAY=1.0
SECURITY_RETRY_MAX_DELAY=10.0
SECURITY_CACHE_TTL=3600

# Monitoring & Logging
MONITORING_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
MONITORING_SENTRY_DSN=https://your_sentry_dsn_here
MONITORING_APP_VERSION=1.0.0
MONITORING_ENABLE_METRICS=true
MONITORING_LOG_FORMAT=json  # json, console
"""
        
        if file_path:
            file_path.write_text(template)
            logger.info("Configuration template exported", file_path=str(file_path))
        
        return template
    
    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for configuration reload"""
        def reload_handler(signum, frame):
            logger.info("Received reload signal", signal=signum)
            asyncio.create_task(self.reload_configuration())
        
        # SIGUSR1 for configuration reload (Unix only)
        if hasattr(signal, 'SIGUSR1'):
            signal.signal(signal.SIGUSR1, reload_handler)
            logger.info("Configuration reload signal handler setup (SIGUSR1)")


# Global configuration manager instance
config_manager = ConfigurationManager()


def get_config_value(path: str, default: Any = None) -> Any:
    """Get configuration value by dot-notation path (e.g., 'database.pool_size')"""
    try:
        obj = settings
        for part in path.split('.'):
            obj = getattr(obj, part)
        return obj
    except (AttributeError, KeyError):
        logger.debug("Configuration path not found", path=path, default=default)
        return default


def is_feature_enabled(feature: str) -> bool:
    """Check if a feature is enabled based on configuration"""
    feature_flags = {
        'minio': settings.minio.is_configured,
        'llm': settings.llm.is_configured and not settings.llm.disabled,
        'sentry': settings.monitoring.is_sentry_configured,
        'metrics': settings.monitoring.enable_metrics,
        'sql_echo': settings.database.echo,
    }
    
    return feature_flags.get(feature.lower(), False)


def get_environment_info() -> Dict[str, Any]:
    """Get environment information for debugging"""
    return {
        "environment": settings.environment.value,
        "app_version": settings.monitoring.app_version,
        "python_version": os.sys.version,
        "working_directory": os.getcwd(),
        "env_file_exists": Path(".env").exists(),
        "config_validation": config_manager.validate_configuration()
    }
