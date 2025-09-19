"""Configuration management handlers for Telegram bot"""
from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import structlog

from app.config import settings
from app.utils.config_manager import config_manager, get_environment_info, is_feature_enabled
from app.services.memory import _ensure_user_state
from app.db import session_scope

logger = structlog.get_logger(__name__)
router = Router(name="config")


@router.message(F.text == "/config")
async def config_status(message: Message):
    """Show current configuration status"""
    if not message.from_user:
        logger.warning("Config command without user", action="config_status")
        return
        
    logger.info(
        "Config status requested",
        action="config_status",
        user_id=message.from_user.id
    )
    
    try:
        # Get configuration validation report
        validation = config_manager.validate_configuration()
        env_info = get_environment_info()
        
        # Build status message
        status_emoji = {
            "valid": "✅",
            "valid_with_warnings": "⚠️", 
            "invalid": "❌",
            "error": "💥"
        }.get(validation["status"], "❓")
        
        config_text = f"🔧 **Configuration Status** {status_emoji}\n\n"
        config_text += f"**Environment:** {settings.environment.value}\n"
        config_text += f"**Version:** {settings.monitoring.app_version}\n"
        config_text += f"**Status:** {validation['status'].upper()}\n\n"
        
        # Component status
        config_text += "**Components:**\n"
        config_text += f"🤖 Telegram: {'✅' if settings.telegram.is_configured else '❌'}\n"
        config_text += f"🗄️ Database: {'✅' if settings.database.url else '❌'}\n"
        config_text += f"🤖 LLM/AI: {'✅' if settings.llm.is_configured else '❌'}\n"
        config_text += f"💾 MinIO: {'✅' if settings.minio.is_configured else '❌'}\n"
        config_text += f"📊 Sentry: {'✅' if settings.monitoring.is_sentry_configured else '❌'}\n\n"
        
        # Show warnings if any
        if validation.get("warnings"):
            config_text += "**Warnings:**\n"
            for warning in validation["warnings"]:
                config_text += f"⚠️ {warning}\n"
            config_text += "\n"
        
        # Show errors if any
        if validation.get("errors"):
            config_text += "**Errors:**\n"
            for error in validation["errors"]:
                config_text += f"❌ {error}\n"
        
        # Create inline keyboard for config actions
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Reload Config", callback_data="config:reload")
        kb.button(text="📋 Full Details", callback_data="config:details")
        kb.button(text="📝 Export Template", callback_data="config:template")
        kb.adjust(2, 1)
        
        await message.answer(config_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
        
    except Exception as e:
        logger.error(
            "Failed to show config status",
            action="config_status",
            user_id=message.from_user.id,
            error=str(e)
        )
        await message.answer("❌ Failed to load configuration status")


@router.callback_query(F.data == "config:reload")
async def config_reload(callback: CallbackQuery):
    """Reload configuration from environment"""
    if not callback.from_user:
        return await callback.answer("Invalid user")
        
    logger.info(
        "Configuration reload requested",
        action="config_reload", 
        user_id=callback.from_user.id
    )
    
    try:
        # Attempt to reload configuration
        success = await config_manager.reload_configuration()
        
        if success:
            await callback.answer("✅ Configuration reloaded successfully!")
            
            # Update the message with new status
            validation = config_manager.validate_configuration()
            status_emoji = {
                "valid": "✅",
                "valid_with_warnings": "⚠️",
                "invalid": "❌", 
                "error": "💥"
            }.get(validation["status"], "❓")
            
            new_text = f"🔧 **Configuration Status** {status_emoji}\n\n"
            new_text += f"**Environment:** {settings.environment.value}\n"
            new_text += f"**Version:** {settings.monitoring.app_version}\n" 
            new_text += f"**Status:** {validation['status'].upper()}\n"
            new_text += f"**Last Reload:** Just now ✨\n\n"
            
            # Component status
            new_text += "**Components:**\n"
            new_text += f"🤖 Telegram: {'✅' if settings.telegram.is_configured else '❌'}\n"
            new_text += f"🗄️ Database: {'✅' if settings.database.url else '❌'}\n"
            new_text += f"🤖 LLM/AI: {'✅' if settings.llm.is_configured else '❌'}\n"
            new_text += f"💾 MinIO: {'✅' if settings.minio.is_configured else '❌'}\n"
            new_text += f"📊 Sentry: {'✅' if settings.monitoring.is_sentry_configured else '❌'}\n"
            
            # Rebuild keyboard
            kb = InlineKeyboardBuilder()
            kb.button(text="🔄 Reload Config", callback_data="config:reload")
            kb.button(text="📋 Full Details", callback_data="config:details")
            kb.button(text="📝 Export Template", callback_data="config:template")
            kb.adjust(2, 1)
            
            if callback.message:
                try:
                    await callback.message.edit_text(
                        new_text, 
                        reply_markup=kb.as_markup(),
                        parse_mode="Markdown"
                    )
                except Exception:
                    # If editing fails, send new message
                    await callback.message.answer(new_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
        else:
            await callback.answer("❌ Configuration reload failed!", show_alert=True)
            
    except Exception as e:
        logger.error(
            "Configuration reload failed",
            action="config_reload",
            user_id=callback.from_user.id,
            error=str(e)
        )
        await callback.answer("❌ Configuration reload failed!", show_alert=True)


@router.callback_query(F.data == "config:details")
async def config_details(callback: CallbackQuery):
    """Show detailed configuration information"""
    if not callback.from_user:
        return await callback.answer("Invalid user")
        
    logger.info(
        "Configuration details requested", 
        action="config_details",
        user_id=callback.from_user.id
    )
    
    try:
        env_info = get_environment_info()
        summary = settings.get_configuration_summary()
        
        details_text = f"🔧 **Detailed Configuration**\n\n"
        details_text += f"**Environment Info:**\n"
        details_text += f"Environment: `{env_info['environment']}`\n"
        details_text += f"App Version: `{env_info['app_version']}`\n"
        details_text += f"Python Version: `{env_info['python_version'][:20]}...`\n"
        details_text += f"Working Dir: `{env_info['working_directory']}`\n\n"
        
        details_text += f"**Database:**\n"
        details_text += f"Pool Size: `{summary['database']['pool_size']}`\n"
        details_text += f"Max Overflow: `{summary['database']['max_overflow']}`\n"
        details_text += f"Pool Timeout: `{summary['database']['pool_timeout']}s`\n\n"
        
        details_text += f"**LLM Settings:**\n"
        details_text += f"Configured: `{summary['llm']['configured']}`\n"
        details_text += f"Max Tokens: `{summary['llm']['max_tokens_out']}`\n"
        details_text += f"Temperature: `{summary['llm']['temperature']}`\n"
        details_text += f"Timeout: `{summary['llm']['timeout']}s`\n\n"
        
        details_text += f"**Processing:**\n"
        details_text += f"Max Chunks: `{summary['processing']['project_max_chunks']}`\n"
        details_text += f"Chunk Size: `{summary['processing']['chunk_size']}`\n"
        details_text += f"Chunk Overlap: `{summary['processing']['chunk_overlap']}`\n\n"
        
        details_text += f"**Security:**\n"
        details_text += f"Max Retries: `{summary['security']['max_retries']}`\n"
        details_text += f"Base Delay: `{summary['security']['retry_base_delay']}s`\n"
        details_text += f"Max Delay: `{summary['security']['retry_max_delay']}s`\n"
        
        # Back button
        kb = InlineKeyboardBuilder()
        kb.button(text="↩️ Back", callback_data="config:back")
        
        if callback.message:
            try:
                await callback.message.edit_text(
                    details_text,
                    reply_markup=kb.as_markup(),
                    parse_mode="Markdown"
                )
                await callback.answer()
            except Exception as e:
                await callback.answer("❌ Failed to show details", show_alert=True)
                
    except Exception as e:
        logger.error(
            "Failed to show config details",
            action="config_details", 
            user_id=callback.from_user.id,
            error=str(e)
        )
        await callback.answer("❌ Failed to load configuration details", show_alert=True)


@router.callback_query(F.data == "config:template")
async def config_template(callback: CallbackQuery):
    """Export configuration template"""
    if not callback.from_user:
        return await callback.answer("Invalid user")
        
    logger.info(
        "Configuration template requested",
        action="config_template",
        user_id=callback.from_user.id
    )
    
    try:
        # Generate template
        template = config_manager.export_configuration_template()
        
        # Send as file
        from aiogram.types import BufferedInputFile
        file = BufferedInputFile(template.encode('utf-8'), filename=".env.template")
        
        if callback.message:
            await callback.message.answer_document(
                document=file,
                caption="🔧 **Configuration Template**\n\nCopy this template to `.env` and configure your values."
            )
            await callback.answer("✅ Template exported!")
            
    except Exception as e:
        logger.error(
            "Failed to export config template",
            action="config_template",
            user_id=callback.from_user.id, 
            error=str(e)
        )
        await callback.answer("❌ Failed to export template", show_alert=True)


@router.callback_query(F.data == "config:back")
async def config_back(callback: CallbackQuery):
    """Go back to main config status"""
    if not callback.from_user:
        return await callback.answer("Invalid user")
    
    # Redirect to main config status
    await config_reload(callback)
