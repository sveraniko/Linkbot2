"""Callback data utilities for size optimization and encoding."""
import base64
import json
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Telegram callback_data limit is 64 bytes
CALLBACK_DATA_LIMIT = 64

def encode_callback_data(data: str) -> str:
    """
    Encode callback data with size checking and base64url if needed.
    
    Args:
        data: Callback data string
        
    Returns:
        Encoded callback data (base64url if too long, original if fits)
    """
    if not data:
        return ""
    
    # Check if data fits in limit
    data_bytes = data.encode('utf-8')
    if len(data_bytes) <= CALLBACK_DATA_LIMIT:
        return data
    
    # Use base64url encoding for long data
    encoded = base64.urlsafe_b64encode(data_bytes).decode('ascii').rstrip('=')
    
    # Add prefix to indicate encoding
    result = f"b64:{encoded}"
    
    # Check if encoded version still fits
    if len(result.encode('utf-8')) > CALLBACK_DATA_LIMIT:
        logger.warning(f"Callback data too long even after encoding: {len(result)} bytes")
        # Truncate if still too long
        max_encoded_len = CALLBACK_DATA_LIMIT - 4  # Reserve 4 bytes for "b64:"
        truncated = encoded[:max_encoded_len]
        result = f"b64:{truncated}"
    
    return result

def decode_callback_data(data: str) -> str:
    """
    Decode callback data if it was base64url encoded.
    
    Args:
        data: Potentially encoded callback data
        
    Returns:
        Decoded callback data
    """
    if not data:
        return ""
    
    if not data.startswith("b64:"):
        return data
    
    try:
        encoded = data[4:]  # Remove "b64:" prefix
        # Add padding if needed
        padding = 4 - (len(encoded) % 4)
        if padding != 4:
            encoded += '=' * padding
        
        decoded_bytes = base64.urlsafe_b64decode(encoded)
        return decoded_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to decode callback data: {e}")
        return data

def safe_callback_data(prefix: str, *args: Any) -> str:
    """
    Create safe callback data with automatic encoding if needed.
    
    Args:
        prefix: Callback prefix (e.g., "ask", "mem")
        *args: Additional arguments to join
        
    Returns:
        Safe callback data string
    """
    parts = [prefix] + [str(arg) for arg in args if arg is not None]
    data = ":".join(parts)
    return encode_callback_data(data)

def check_callback_size(data: str) -> Dict[str, Any]:
    """
    Check callback data size and provide statistics.
    
    Args:
        data: Callback data string
        
    Returns:
        Dictionary with size info and recommendations
    """
    if not data:
        return {"size": 0, "fits": True, "needs_encoding": False}
    
    size = len(data.encode('utf-8'))
    fits = size <= CALLBACK_DATA_LIMIT
    needs_encoding = not fits
    
    return {
        "size": size,
        "limit": CALLBACK_DATA_LIMIT,
        "fits": fits,
        "needs_encoding": needs_encoding,
        "utilization": round((size / CALLBACK_DATA_LIMIT) * 100, 1)
    }

def optimize_callback_data(data: str) -> str:
    """
    Optimize callback data by shortening common patterns.
    
    Args:
        data: Original callback data
        
    Returns:
        Optimized callback data
    """
    if not data:
        return ""
    
    # Common optimizations
    optimizations = {
        "answer": "ans",
        "sources": "src", 
        "confirm": "cf",
        "cancel": "cx",
        "delete": "del",
        "toggle": "tg",
        "page": "p",
        "back": "bk"
    }
    
    result = data
    for long_form, short_form in optimizations.items():
        result = result.replace(f":{long_form}:", f":{short_form}:")
        result = result.replace(f"{long_form}:", f"{short_form}:")
    
    return result
