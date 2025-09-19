"""LLM service for handling model calls with proper configuration and error handling."""
import os
import logging
import asyncio
import time
from typing import Tuple, List, Dict, Any, Optional
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.config import settings

logger = logging.getLogger(__name__)

# LLM configuration from environment variables
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_TOKENS_OUT = int(os.getenv("LLM_MAX_TOKENS_OUT", "2048"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_DISABLED = os.getenv("LLM_DISABLED", "0") == "1"

# Initialize OpenAI client
client = AsyncOpenAI(api_key=settings.llm.openai_api_key.get_secret_value() if settings.llm.openai_api_key else None) if settings.llm.openai_api_key else None

# HOTFIX: put near your OpenAI call builder
TEMPERATURE_SUPPORTED = (
    # классические чаты поддерживают кастомную температуру
    "gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "gpt-4o"
)

REASONING_FAMILY = ("o1", "o3", "o4", "o5", "gpt-5", "gpt-5-thinking")

def _model_caps(model: str) -> dict:
    m = model.lower()
    caps = {"use_temperature": False, "tokens_param": "max_tokens"}
    if any(m.startswith(x) for x in TEMPERATURE_SUPPORTED):
        caps["use_temperature"] = True
        caps["tokens_param"] = "max_tokens"
    if any(m.startswith(x) for x in REASONING_FAMILY):
        # reasoning-модели требуют max_completion_tokens и часто игнорируют temperature
        caps["use_temperature"] = False
        caps["tokens_param"] = "max_completion_tokens"
    return caps

def build_openai_payload(model: str, messages: list, *, temperature: float|None, max_tokens: int|None):
    caps = _model_caps(model)
    payload = {"model": model, "messages": messages}

    # лимит токенов: правильное имя параметра
    if max_tokens:
        payload[caps["tokens_param"]] = max_tokens

    # температура — только для семейства, где это поддерживается
    if caps["use_temperature"] and temperature is not None and temperature != 1:
        payload["temperature"] = float(temperature)
    # иначе — вообще не добавляем ключ 'temperature'

    return payload

async def call_llm(
    system_prompt: str,
    context_prompt: str,
    user_prompt: str,
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int = LLM_MAX_TOKENS_OUT,
    timeout: int = LLM_TIMEOUT
) -> Tuple[str, Dict[str, Any]]:
    """
    Call the LLM with the provided prompts.
    
    Returns:
        Tuple of (response_text, metadata)
    """
    if LLM_DISABLED:
        return "LLM functionality is currently disabled.", {}
    
    if not client:
        raise ValueError("OpenAI API key not configured")
    
    # Combine prompts
    messages: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": context_prompt + "\n\n" + user_prompt}
    ]
    
    start_time = time.time()
    
    try:
        # HOTFIX: replace manual dict with helper
        payload = build_openai_payload(
            model=model,
            messages=messages,
            temperature=temperature,     # можно оставить 0.7 — хелпер сам отбросит
            max_tokens=max_tokens or LLM_MAX_TOKENS_OUT
        )
        payload["timeout"] = timeout
        response = await client.chat.completions.create(**payload)
        
        duration = time.time() - start_time
        response_text = response.choices[0].message.content or ""
        
        # Ensure we have a valid response text
        if not response_text.strip():
            response_text = "Извините, я не смог сформулировать ответ на ваш вопрос. Попробуйте переформулировать его или выбрать другие источники."
        
        # Ensure minimum length to avoid Telegram issues
        if len(response_text.strip()) < 1:
            response_text = "Извините, я не смог сформулировать ответ на ваш вопрос. Попробуйте переформулировать его или выбрать другие источники."
        
        metadata = {
            "model": model,
            "tokens_in": response.usage.prompt_tokens if response.usage else 0,
            "tokens_out": response.usage.completion_tokens if response.usage else 0,
            "duration_ms": int(duration * 1000)
        }
        
        logger.info(f"LLM call completed: {metadata}")
        return response_text, metadata
        
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"LLM call failed after {duration:.2f}s: {e}")
        raise

async def call_llm_with_retry(
    system_prompt: str,
    context_prompt: str,
    user_prompt: str,
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int = LLM_MAX_TOKENS_OUT,
    timeout: int = LLM_TIMEOUT,
    max_retries: int = 2
) -> Tuple[str, Dict[str, Any]]:
    """
    Call the LLM with retry logic for handling rate limits and temporary errors.
    """
    last_exception: Optional[Exception] = None
    
    for attempt in range(max_retries + 1):
        try:
            return await call_llm(
                system_prompt, context_prompt, user_prompt,
                model, temperature, max_tokens, timeout
            )
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                # Check if it's a retryable error (rate limit, server error)
                error_str = str(e).lower()
                if "rate limit" in error_str or "429" in error_str or "500" in error_str:
                    # Exponential backoff
                    wait_time = (2 ** attempt) + (attempt * 0.1)
                    logger.warning(f"LLM call failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Non-retryable error
                    break
            else:
                # Max retries exceeded
                break
    
    # If we get here, all retries failed
    if last_exception is not None:
        raise last_exception
    else:
        raise Exception("LLM call failed")
