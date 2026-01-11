# Filename: services/report_service.py
# Role: Service for generating reports (Weekly HTML, Consolidated AI, etc.) and News

import os
import json
import logging
from datetime import datetime, timedelta
from flask import render_template, current_app
from sqlalchemy import or_

from extensions import db
from models import Task, DailySummary, Person
from config import Config
from services.llm_service import generate_summary_text, generate_consolidated_report_content

logger = logging.getLogger(__name__)

def get_report_data(start_date, end_date):
    """
    Fetches raw data for reporting.
    """
    # 1. Achievements (Closed Tasks)
    # FIX: Task model does not have 'status_updated_at'. Using 'created_at' as proxy for report period.
    # Ideally, we should add 'closed_at' to the model.
    closed_tasks = Task.query.filter(
        or_(Task.status == 'closed', Task.status == 'archived'),
        Task.created_at >= start_date,
        Task.created_at <= end_date
    ).all()
    
    # 2. Planned (In Progress / New)
    planned_tasks = Task.query.filter(
        or_(Task.status == 'new', Task.status == 'in_progress', Task.status == 'paused')
    ).all()
    
    # 3. Stats
    total_received = Task.query.filter(Task.created_at >= start_date, Task.created_at <= end_date).count()
    total_completed = len(closed_tasks)
    
    return {
        "achievements": [t.to_dict() for t in closed_tasks],
        "planned": [t.to_dict() for t in planned_tasks],
        "stats": {
            "received": total_received,
            "completed": total_completed
        }
    }

def generate_weekly_report_logic(start_date, end_date):
    """
    Generates standard HTML Weekly Report using Jinja2 template.
    """
    data = get_report_data(start_date, end_date)
    
    # Calculate Week Number
    week_num = start_date.strftime("%V")
    
    # Enrich data for template
    achievements = data['achievements']
    planned = data['planned']
    
    # Calculate SLA status for template
    sla_limit = getattr(Config, 'SLA_RESPONSE_DAYS', 4)
    for task in achievements:
        task['sla_status'] = 'Unknown' # Default
        
        if task.get('received_at'):
            try:
                # Parse dates
                received = datetime.fromisoformat(task['received_at'].replace('Z', ''))
                
                # FIX: We don't have a reliable 'closed_at' date in the dict. 
                # We will check if 'auto_completed_at' exists (from model update), 
                # otherwise we can't accurately calc SLA for manual closure without that field.
                # Fallback: Compare received_at vs created_at (sync time) as a rough proxy, 
                # or just skip.
                
                # If we assume 'created_at' is close to 'closed_at' for this report context (weak assumption),
                # we can use it. Better to just show 'N/A' if missing.
                closed_at = None
                # Check for auto-complete date if available in dict (requires model to_dict update)
                # Current to_dict doesn't return auto_completed_at standardly unless we added it?
                # The provided models.py snippet shows it IS in to_dict? No, let's check.
                # models.py snippet shows to_dict includes 'action_taken', 'priority'. 
                # It DOES NOT show 'auto_completed_at'.
                
                # So we can't calculate SLA duration. 
                # We can only check if it *was* overdue at time of creation/sync?
                # Let's just set it to 'N/A' to prevent error.
                pass 
                
            except Exception as e:
                logger.warning(f"SLA Calc Error: {e}")

    html_content = render_template(
        'weekly_report.html',
        achievements=achievements,
        planned=planned,
        generated_date=datetime.now().strftime("%Y-%m-%d"),
        week_number=week_num,
        date_range_last_week=f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}",
        date_range_next_week="Next 7 Days"
    )
    
    # Save to file
    filename = f"weekly_report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.html"
    filepath = os.path.join(Config.REPORTS_PATH, filename)
    
    with open(filepath, "w", encoding='utf-8') as f:
        f.write(html_content)
        
    return filepath

def process_daily_summary(summary: DailySummary):
    """
    Generates text summary using LLM and audio using gTTS.
    """
    # 1. Check for Snippets
    if not summary.raw_snippets or summary.raw_snippets == "[]":
        summary.content = "No significant updates found for this day."
        summary.status = 'generated'
        db.session.commit()
        return summary
    
    try:
        snippets = json.loads(summary.raw_snippets)
    except:
        snippets = []

    if not snippets:
        summary.content = "No significant updates found for this day."
        summary.status = 'generated'
        db.session.commit()
        return summary
        
    # 2. Prepare Prompt Text for LLM
    # Format: "From: <name>, Subject: <subj>, Snippet: <text>"
    text_corpus = ""
    for s in snippets:
        if isinstance(s, dict):
            text_corpus += f"- From: {s.get('from', 'Unknown') or s.get('sender', 'Unknown')} | Subject: {s.get('subject', 'No Subject')} | Body: {s.get('snippet', '')}\n"
        else:
            text_corpus += f"- {str(s)}\n"
    
    # 3. Call LLM
    model_name = getattr(Config, 'OLLAMA_MODEL')
    summary_text = generate_summary_text(text_corpus, model_name)
    
    if not summary_text:
        # Fallback if LLM fails
        summary_text = "Could not generate AI summary. Raw updates:\n" + text_corpus[:500] + "..."
        
    # 4. Save Text Content
    summary.content = summary_text
    summary.status = 'generated'
    
    # 5. Generate Audio (gTTS)
    try:
        from gtts import gTTS
        # Clean markdown for speech
        clean_text = summary_text.replace('*', '').replace('#', '').replace('-', '')
        
        # Ensure directory exists
        os.makedirs(Config.BRIEFING_AUDIO_PATH, exist_ok=True)
        
        tts = gTTS(text=clean_text, lang='en', slow=False)
        filename = f"briefing_{summary.id}.mp3"
        filepath = os.path.join(Config.BRIEFING_AUDIO_PATH, filename)
        tts.save(filepath)
        
        summary.audio_file_path = filename
    except Exception as e:
        logger.error(f"Audio Generation Failed: {e}")
        # We don't fail the whole process if audio fails, just log it
        summary.audio_file_path = None
        
    db.session.commit()
    return summary

def generate_consolidated_report_logic(start_date, end_date):
    """
    Generates an AI-Consolidated HTML Report.
    """
    data = get_report_data(start_date, end_date)
    
    # Prepare data for LLM
    data_str = json.dumps(data, indent=2)
    model_name = getattr(Config, 'OLLAMA_MODEL')
    
    # Call LLM
    llm_html_content = generate_consolidated_report_content(data_str, model_name)
    
    if not llm_html_content:
        llm_html_content = "<p>Error: AI could not generate the report.</p>"
        
    # Wrap in basic HTML structure
    start_dt = start_date if isinstance(start_date, datetime) else datetime.now()
    end_dt = end_date if isinstance(end_date, datetime) else datetime.now()
    
    # Restored Enhanced Template
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Consolidated Report</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{ padding: 40px; font-family: ui-sans-serif, system-ui; max-width: 1000px; margin: 0 auto; color: #1e293b; }}
            h1 {{ font-size: 2.25rem; font-weight: 800; margin-bottom: 1.5rem; color: #1e1b4b; }}
            h2 {{ font-size: 1.5rem; font-weight: 700; margin-top: 2rem; margin-bottom: 1rem; color: #312e81; border-bottom: 2px solid #e0e7ff; padding-bottom: 0.5rem; }}
            h3 {{ font-size: 1.25rem; font-weight: 600; margin-top: 1.5rem; color: #4338ca; }}
            /* Styles for the LLM generated tables */
            table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; margin-bottom: 2rem; }}
            th, td {{ border: 1px solid #e2e8f0; padding: 0.75rem; text-align: left; vertical-align: top; }}
            th {{ background-color: #f8fafc; font-weight: 600; color: #475569; }}
            tr:nth-child(even) {{ background-color: #fcfcfc; }}
            ul {{ margin: 0; padding-left: 1.2rem; }}
            li {{ margin-bottom: 0.25rem; }}
        </style>
    </head>
    <body>
        <h1>Consolidated Weekly Report</h1>
        <p class="text-sm text-slate-500 mb-8">Period: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}</p>
        
        {llm_html_content}
        
        <div class="mt-8 pt-4 border-t border-slate-200 text-xs text-slate-400 text-center">
            Generated by HappyTwo AI • {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </body>
    </html>
    """
    
    # Save to file
    if isinstance(start_date, str):
        s_str = start_date.replace('-', '')
        e_str = end_date.replace('-', '')
    else:
        s_str = start_dt.strftime('%Y%m%d')
        e_str = end_dt.strftime('%Y%m%d')
        
    filename = f"consolidated_report_{s_str}_{e_str}.html"
    path = os.path.join(Config.REPORTS_PATH, filename)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(full_html)
        
    return path