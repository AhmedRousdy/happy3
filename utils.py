import re
import json
import logging
from typing import Optional, Dict, Any, List
from config import Config
from models import AppSettings
from extensions import db

logger = logging.getLogger(__name__)

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Fetches a single setting from the AppSettings table."""
    try:
        setting = db.session.get(AppSettings, key)
        return setting.value if setting else default
    except Exception as e:
        logger.warning(f"Error fetching setting '{key}', using default. Error: {e}")
        return default

def get_json_setting(key: str, default_list: List[str]) -> List[str]:
    """Fetches a JSON list setting, returning default_list if empty/invalid."""
    val = get_setting(key)
    if not val:
        return default_list
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return parsed
        return default_list
    except:
        return default_list

def save_setting(key: str, value: str) -> bool:
    """Saves or updates a setting in the AppSettings table."""
    try:
        setting = db.session.get(AppSettings, key)
        if setting:
            setting.value = value
        else:
            setting = AppSettings(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving setting '{key}': {e}")
        db.session.rollback()
        return False

def clean_email_body(body_text: str) -> str:
    """
    Removes clutter from email bodies for better LLM processing.
    """
    if not body_text: return ""
    
    lines = body_text.split('\n')
    cleaned = []
    
    # Common signature/reply delimiters
    markers = [
        "-----Original Message-----",
        "From:",
        "Sent:",
        "To:",
        "Subject:",
        "________________________________",
        "Disclaimer:",
        "This message is intended"
    ]
    
    for line in lines:
        line_str = line.strip()
        if any(m in line_str for m in markers):
            # Stop processing if we hit a reply chain or signature block
            break
        if line_str:
            cleaned.append(line_str)
            
    return "\n".join(cleaned[:100])  # Return first ~100 lines max to save context

def extract_json_from_text(text_to_parse: str) -> Optional[Dict[str, Any]]:
    """
    Legacy extraction logic. Kept for backward compatibility.
    """
    try:
        if not text_to_parse: return None
        start = text_to_parse.find('{')
        end = text_to_parse.rfind('}') + 1
        
        if start == -1 or end == 0:
            return None
            
        json_str = text_to_parse[start:end]
        json_str = json_str.replace('\n', ' ')
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"JSON Parse Error: {e}")
        return None

def extract_snippet(cleaned_body: str, min_len: int = 30, max_chars: int = 250) -> str:
    """Extracts the first meaningful line of an email for a snippet."""
    if not cleaned_body: return "No content"
    lines = [ln.strip() for ln in cleaned_body.splitlines() if ln.strip()]
    for line in lines:
        l = line.lower()
        if (
            len(line) >= min_len and 
            not l.startswith(("hi ", "dear ", "hello", "good morning", "good afternoon")) and
            not l.startswith(">")
        ):
            return line[:max_chars]
    return " ".join(lines[:3])[:max_chars]

def get_priority_from_text(email_content: str) -> str:
    for regex in Config.COMPILED_HIGH_PRIORITY_REGEX:
        if regex.search(email_content):
            return "high"
    return "medium"

def is_email_junk_by_regex(sender: str, subject: str = "", body: str = "") -> bool:
    """
    Checks if email is junk. 
    Supports legacy call (1 arg: content) and new call (3 args: sender, subject, body).
    """
    if subject == "" and body == "":
        # Legacy call where 'sender' argument actually contains the full content string
        content = sender.lower()
    else:
        # New call style
        content = (sender + " " + subject + " " + body).lower()
        
    for regex in Config.COMPILED_JUNK_REGEX:
        if regex.search(content):
            return True
    return False

def extract_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extracts JSON from an LLM response, handling Markdown blocks.
    New helper added for LLM service compatibility.
    """
    try:
        if not response_text: return None
        
        # 1. Try finding a markdown block
        json_match = re.search(r'```json\s*({.*?})\s*```', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
            
        # 2. Try finding just the first { and last }
        start = response_text.find('{')
        end = response_text.rfind('}') + 1
        
        if start != -1 and end != 0:
            json_str = response_text[start:end]
            return json.loads(json_str)
            
        # 3. Last ditch: try loading the whole string
        return json.loads(response_text)
        
    except json.JSONDecodeError as e:
        logger.warning(f"JSON decode failed for LLM response: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing JSON: {e}")
        return None