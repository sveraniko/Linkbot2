import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import MenuButtonCommands, BotCommand
from aiogram.exceptions import TelegramUnauthorizedError, TelegramAPIError
from app.config import settings
from app.utils.config_manager import config_manager, get_environment_info
from app.handlers import router as root_router
from app.storage import ensure_bucket
from app.utils.logging_setup import setup_structured_logging, setup_sentry, logger, metrics

# Initialize structured logging and monitoring
setup_structured_logging()
setup_sentry()

async def main():
    logger.info("Starting Telegram bot", component="main", action="startup")
    
    await ensure_bucket()
    logger.info("MinIO bucket ensured", component="storage", action="bucket_check")
    
    # Create bot instance
    # Handle bot token properly with fallback
    if settings.telegram.is_configured:
        bot = Bot(token=settings.telegram.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode='HTML'))
    else:
        logger.error("Bot token not configured", component="main", action="startup")
        raise ValueError("BOT_TOKEN must be configured to run the bot")
    
    # Set bot commands (handle errors gracefully)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Start the bot"),
            BotCommand(command="project", description="Select/create project"),
            BotCommand(command="memory", description="Manage memory entries"),
            BotCommand(command="import", description="Import files"),
            BotCommand(command="ask", description="Ask questions with context"),
            BotCommand(command="ctx", description="Set context filters"),
            BotCommand(command="model", description="Select AI model"),
            BotCommand(command="menu", description="Open quick actions menu"),
            BotCommand(command="actions", description="Open advanced actions panel"),
            BotCommand(command="status", description="Show current status"),
            BotCommand(command="kb_on", description="Enable keyboard"),
        ])
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Bot commands set successfully", component="telegram", action="set_commands")
    except TelegramUnauthorizedError:
        logger.warning("Invalid bot token. Skipping command setup", 
                      component="telegram", action="set_commands", 
                      error="unauthorized", development_mode=True)
    except TelegramAPIError as e:
        logger.warning("Telegram API error when setting commands", 
                      component="telegram", action="set_commands",
                      error_type="TelegramAPIError", error=str(e))
    except Exception as e:
        logger.error("Unexpected error when setting bot commands",
                    component="telegram", action="set_commands", 
                    error=str(e))
    
    # Create dispatcher and start polling
    try:
        dp = Dispatcher()
        dp.include_router(root_router)
        logger.info("Routers registered, starting polling", 
                   component="dispatcher", action="start_polling")
        
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error("Invalid bot token",
                    component="dispatcher", action="start_polling",
                    error_type="TelegramUnauthorizedError",
                    suggestion="Check BOT_TOKEN in .env file")
        logger.info("Bot shutting down due to invalid token",
                   component="main", action="shutdown", reason="invalid_token")
    except Exception as e:
        logger.error("Error starting bot",
                    component="dispatcher", action="start_polling", error=str(e))
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user", component="main", action="shutdown", reason="keyboard_interrupt")
    except Exception as e:
        logger.error("Bot crashed", component="main", action="crash", error=str(e))
