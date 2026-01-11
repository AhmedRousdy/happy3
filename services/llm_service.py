# Filename: services/llm_service.py
# Role: Service for interacting with local LLM (Ollama)

import logging
import requests
import json
from config import Config

# --- FIX: Import the extraction utility ---
from utils import extract_json_from_response, get_json_setting

logger = logging.getLogger(__name__)

def check_and_pull_model(model_name):
    """
    Checks if model exists locally.
    """
    pass

def call_ollama(model, prompt, system=None, json_format=False):
    """Generic wrapper for Ollama API."""
    try:
        url = f"{Config.OLLAMA_HOST}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": 4096,
                "temperature": 0.2
            }
        }
        
        if system:
            payload["system"] = system
            
        if json_format:
            payload["format"] = "json"
            
        logger.info(f"Calling Ollama: {model}")
        response = requests.post(url, json=payload, timeout=getattr(Config, 'OLLAMA_TIMEOUT', 600))
        response.raise_for_status()
        
        result = response.json()
        return result.get('response', '').strip()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama Connection Error: {e}")
        return None
    except Exception as e:
        logger.error(f"Ollama Error: {e}")
        return None

def run_triage_model(email_content, model_name):
    """
    Phase 1: Lightweight Triage (ACTION / INFO / SPAM).
    """
    system = Config.SYSTEM_PROMPT_TRIAGE
    user_prompt = f"Classify this email:\n{email_content[:2000]}"
    
    response = call_ollama(model_name, user_prompt, system=system)
    
    if not response:
        return "INFO" # Default safe fallback
        
    cleaned = response.strip().upper().replace('*', '').replace('.', '')
    
    if "ACTION" in cleaned: return "ACTION"
    if "SPAM" in cleaned: return "SPAM"
    return "INFO"

def extract_task_json(content, model_name):
    """
    Phase 2: Deep Analysis to extract JSON.
    """
    # Fetch dynamic settings
    projects = get_json_setting('classification_projects', Config.DEFAULT_PROJECTS)
    tags = get_json_setting('classification_tags', Config.DEFAULT_TAGS)
    domains = get_json_setting('classification_domains', Config.DEFAULT_DOMAINS)
    
    # Inject into prompt
    system = Config.SYSTEM_PROMPT_TEMPLATE.replace('{{PROJECTS}}', str(projects))\
                                          .replace('{{TAGS}}', str(tags))\
                                          .replace('{{DOMAINS}}', str(domains))
                                          
    user_prompt = f"Extract task details from:\n{content}"
    
    response = call_ollama(model_name, user_prompt, system=system, json_format=True)
    if not response: return None
    
    # --- FIX: Use robust extraction instead of raw json.loads ---
    try:
        return extract_json_from_response(response)
    except Exception as e:
        logger.error(f"Failed to decode JSON from LLM: {e}")
        return None

def generate_summary_text(snippets_text, model_name):
    system = Config.SYSTEM_PROMPT_SUMMARIZER
    return call_ollama(model_name, snippets_text, system=system)

def generate_consolidated_report_content(data_text, model_name):
    """
    Sends structured task data (text) to LLM to consolidate and summarize.
    """
    system = Config.SYSTEM_PROMPT_CONSOLIDATED_REPORT
    user_prompt = f"Generate a consolidated report from this data:\n{data_text}"
    
    # Not forcing JSON here as we want HTML
    return call_ollama(model_name, user_prompt, system=system)