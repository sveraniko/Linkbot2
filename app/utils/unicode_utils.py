"""Unicode utilities for NFC normalization and text processing."""
import unicodedata
import logging
from typing import Optional, Union, List
import os

logger = logging.getLogger(__name__)

def normalize_nfc(text: Optional[str]) -> str:
    """
    Normalize text to NFC (Canonical Decomposition, followed by Canonical Composition).
    
    This ensures consistent Unicode representation, especially important for Cyrillic text.
    
    Args:
        text: Text to normalize
        
    Returns:
        NFC-normalized text
    """
    if not text:
        return ""
    
    try:
        return unicodedata.normalize('NFC', text)
    except Exception as e:
        logger.warning(f"Failed to normalize text to NFC: {e}")
        return text

def normalize_filename(filename: Optional[str]) -> str:
    """
    Normalize filename to NFC and ensure it's safe for filesystem.
    
    Args:
        filename: Original filename
        
    Returns:
        Normalized and safe filename
    """
    if not filename:
        return ""
    
    # First normalize to NFC
    normalized = normalize_nfc(filename)
    
    # Remove or replace problematic characters for cross-platform compatibility
    # Keep most Unicode characters but replace filesystem-unsafe ones
    unsafe_chars = '<>:"|?*'
    for char in unsafe_chars:
        normalized = normalized.replace(char, '_')
    
    # Remove leading/trailing whitespace and dots
    normalized = normalized.strip(' .')
    
    # Ensure it's not empty after cleaning
    if not normalized:
        normalized = "unnamed_file"
    
    return normalized

def normalize_search_term(term: Optional[str]) -> str:
    """
    Normalize search term for consistent searching.
    
    Args:
        term: Search term
        
    Returns:
        Normalized search term
    """
    if not term:
        return ""
    
    # NFC normalization
    normalized = normalize_nfc(term)
    
    # Additional search-specific normalization
    # Convert to lowercase for case-insensitive search
    normalized = normalized.lower()
    
    # Strip whitespace
    normalized = normalized.strip()
    
    return normalized

def normalize_user_input(text: Optional[str]) -> str:
    """
    Normalize user input text (messages, tags, titles, etc.).
    
    Args:
        text: User input text
        
    Returns:
        Normalized text
    """
    if not text:
        return ""
    
    # NFC normalization
    normalized = normalize_nfc(text)
    
    # Strip leading/trailing whitespace but preserve internal whitespace
    normalized = normalized.strip()
    
    return normalized

def normalize_tag(tag: Optional[str]) -> str:
    """
    Normalize tag text with additional tag-specific rules.
    
    Args:
        tag: Tag text
        
    Returns:
        Normalized tag
    """
    if not tag:
        return ""
    
    # NFC normalization
    normalized = normalize_nfc(tag)
    
    # Tags are typically lowercase and trimmed
    normalized = normalized.lower().strip()
    
    # Remove multiple spaces
    normalized = ' '.join(normalized.split())
    
    return normalized

def safe_decode_filename(filename_bytes: bytes, fallback_encoding: str = 'cp1251') -> str:
    """
    Safely decode filename bytes with fallback encoding.
    
    Args:
        filename_bytes: Raw filename bytes
        fallback_encoding: Fallback encoding if UTF-8 fails
        
    Returns:
        Decoded and normalized filename
    """
    if not filename_bytes:
        return ""
    
    # Try UTF-8 first
    try:
        decoded = filename_bytes.decode('utf-8')
        return normalize_filename(decoded)
    except UnicodeDecodeError:
        pass
    
    # Try UTF-8 with BOM
    try:
        decoded = filename_bytes.decode('utf-8-sig')
        return normalize_filename(decoded)
    except UnicodeDecodeError:
        pass
    
    # Try fallback encoding (common for Cyrillic)
    try:
        decoded = filename_bytes.decode(fallback_encoding)
        logger.info(f"Used fallback encoding {fallback_encoding} for filename")
        return normalize_filename(decoded)
    except UnicodeDecodeError:
        pass
    
    # Last resort: decode with errors='replace'
    try:
        decoded = filename_bytes.decode('utf-8', errors='replace')
        logger.warning(f"Used UTF-8 with error replacement for filename")
        return normalize_filename(decoded)
    except Exception as e:
        logger.error(f"Failed to decode filename: {e}")
        return "unknown_filename"

def detect_and_normalize_text(text_bytes: bytes) -> str:
    """
    Detect encoding and normalize text content.
    
    Args:
        text_bytes: Raw text bytes
        
    Returns:
        Decoded and NFC-normalized text
    """
    if not text_bytes:
        return ""
    
    # Common encodings to try
    encodings = ['utf-8', 'utf-8-sig', 'cp1251', 'cp866', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            decoded = text_bytes.decode(encoding)
            normalized = normalize_nfc(decoded)
            
            # Log if we used a fallback encoding
            if encoding != 'utf-8':
                logger.info(f"Used encoding {encoding} for text content")
            
            return normalized
        except UnicodeDecodeError:
            continue
    
    # Last resort
    try:
        decoded = text_bytes.decode('utf-8', errors='replace')
        logger.warning("Used UTF-8 with error replacement for text content")
        return normalize_nfc(decoded)
    except Exception as e:
        logger.error(f"Failed to decode text content: {e}")
        return ""

def normalize_batch(texts: List[str]) -> List[str]:
    """
    Normalize a batch of texts efficiently.
    
    Args:
        texts: List of texts to normalize
        
    Returns:
        List of normalized texts
    """
    return [normalize_nfc(text) for text in texts if text]

# Convenience functions for common use cases
def normalize_title(title: Optional[str]) -> str:
    """Normalize document/artifact title."""
    return normalize_user_input(title)

def normalize_content(content: Optional[str]) -> str:
    """Normalize document/artifact content."""
    return normalize_nfc(content) if content else ""

def normalize_project_name(name: Optional[str]) -> str:
    """Normalize project name."""
    return normalize_user_input(name)
