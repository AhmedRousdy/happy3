import os
import glob
import json
import logging
import csv
import io
from flask import Blueprint, jsonify, request, make_response
import pytz
from datetime import datetime, timedelta
from sqlalchemy import or_
from exchangelib.items import Message

from extensions import db
from models import Task, DailySummary, Person, AppSettings
from utils import get_setting, save_setting, get_json_setting
from config import Config

# Service Imports
from services.pipeline_service import run_sync_pipeline, scan_network_period
from services.report_service import generate_weekly_report_logic, process_daily_summary, generate_consolidated_report_logic
from services.ews_service import get_account, fetch_email_content, send_reply_email

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')
pytz_tz = pytz.timezone(getattr(Config, "TIMEZONE", "Asia/Dubai"))

# --- HELPER: Auto-Archive ---
def _perform_auto_archive():
    """Archives closed tasks older than Config.ARCHIVE_AFTER_DAYS."""
    try:
        days = getattr(Config, 'ARCHIVE_AFTER_DAYS', 3)
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Use created_at or another valid date field if status_updated_at is missing
        to_archive = Task.query.filter(
            Task.status == 'closed',
            Task.created_at < cutoff_date 
        ).all()
        
        if to_archive:
            count = 0
            for t in to_archive:
                t.status = 'archived'
                count += 1
            db.session.commit()
            logger.info(f"Auto-archived {count} tasks.")
    except Exception as e:
        logger.error(f"Auto-archive failed: {e}")

# =====================================================
# 1. TASK ENDPOINTS (Kanban)
# =====================================================

@api_bp.route('/tasks', methods=['GET'])
def get_tasks():
    _perform_auto_archive()
    
    # Fetch all non-archived tasks + recently closed
    tasks = Task.query.filter(Task.status != 'archived').all()
    return jsonify([t.to_dict() for t in tasks])

@api_bp.route('/tasks/archived', methods=['GET'])
def get_archived_tasks():
    search = request.args.get('search', '').lower()
    query = Task.query.filter(Task.status == 'archived')
    
    if search:
        query = query.filter(
            or_(
                Task.task_summary.ilike(f"%{search}%"),
                Task.sender.ilike(f"%{search}%"),
                Task.subject.ilike(f"%{search}%")
            )
        )
    
    # Limit to last 200 to prevent overload
    tasks = query.order_by(Task.created_at.desc()).limit(200).all()
    return jsonify([t.to_dict() for t in tasks])

@api_bp.route('/tasks/<int:id>', methods=['PUT'])
def update_task(id):
    task = db.session.get(Task, id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
        
    data = request.json
    
    if 'status' in data:
        task.status = data['status']
        if data['status'] == 'closed':
            task.action_taken = "Manual Completion"
            
    if 'triage_category' in data:
        task.triage_category = data['triage_category']
        
    if 'delegated_to' in data:
        task.delegated_to = data['delegated_to']
        task.delegated_at = datetime.utcnow()
        
    db.session.commit()
    return jsonify(task.to_dict())

@api_bp.route('/tasks/<int:id>', methods=['DELETE'])
def delete_task(id):
    task = db.session.get(Task, id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    db.session.delete(task)
    db.session.commit()
    return jsonify({"message": "Deleted"})

@api_bp.route('/tasks/<int:id>/email', methods=['GET'])
def get_task_email(id):
    """Fetches the original email content from Exchange"""
    task = db.session.get(Task, id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
        
    if not task.email_message_id:
        return jsonify({"error": "No EWS ID linked to this task"}), 400
        
    try:
        content = fetch_email_content(task.email_message_id)
        if not content:
             return jsonify({"error": "Email not found on server"}), 404
        return jsonify(content)
    except Exception as e:
        logger.error(f"Get Email Error: {e}")
        return jsonify({"error": str(e)}), 500

@api_bp.route('/tasks/<int:id>/reply', methods=['POST'])
def send_reply(id):
    task = db.session.get(Task, id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    if not task.email_message_id:
        return jsonify({"error": "No EWS ID linked to this task"}), 400
        
    data = request.json
    reply_body = data.get('reply_body')
    reply_type = data.get('reply_type', 'reply') 
    
    if not reply_body:
        return jsonify({"error": "Reply body required"}), 400
        
    try:
        # Use email_message_id. Services layer handles fallback if it's an internet ID.
        success = send_reply_email(task.email_message_id, reply_body)
        
        if success:
            task.action_taken = "Replied via App"
            if reply_type == 'done':
                task.status = 'closed'
                task.action_taken = "Completed & Replied"
                
            db.session.commit()
            return jsonify({"message": "Reply sent successfully"})
        else:
            return jsonify({"error": "Failed to send reply"}), 500
            
    except Exception as e:
        logger.error(f"Send Reply API Error: {e}")
        return jsonify({"error": str(e)}), 500

# =====================================================
# 2. SYNC ENDPOINTS
# =====================================================

@api_bp.route('/sync', methods=['POST'])
def sync_now():
    """Triggers the pipeline manually (defaults to last 24 hours)."""
    try:
        # Default sync window: Last 24 hours
        tz = pytz.timezone(getattr(Config, "TIMEZONE", "Asia/Dubai"))
        end_time = datetime.now(tz)
        start_time = end_time - timedelta(days=1)
        
        result = run_sync_pipeline(start_time, end_time)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Sync error: {e}")
        return jsonify({"error": str(e)}), 500

@api_bp.route('/sync/historical', methods=['POST'])
def sync_historical():
    data = request.json
    date_str = data.get('date')
    if not date_str:
        return jsonify({"error": "Date required"}), 400
        
    try:
        # Simple implementation: Scan that specific day
        tz = pytz.timezone(getattr(Config, "TIMEZONE", "Asia/Dubai"))
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        
        # Create localized timezones
        start_naive = target_date.replace(hour=0, minute=0, second=0)
        end_naive = target_date.replace(hour=23, minute=59, second=59)
        
        start = tz.localize(start_naive)
        end = tz.localize(end_naive)
        
        # Use existing scan logic
        scan_network_period(start, end)
        return jsonify({"message": f"Historical scan complete for {date_str}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/status', methods=['GET'])
def get_status():
    last_sync = get_setting('last_sync_time')
    return jsonify({"last_sync_time": last_sync})

# =====================================================
# 3. CIRCLE (CRM) ENDPOINTS
# =====================================================

@api_bp.route('/circle', methods=['GET'])
def get_circle():
    search = request.args.get('search', '').lower()
    role = request.args.get('role', '')
    
    query = Person.query.filter(Person.is_hidden == False)
    
    if search:
        query = query.filter(
            or_(
                Person.name.ilike(f"%{search}%"),
                Person.email.ilike(f"%{search}%"),
                Person.department.ilike(f"%{search}%")
            )
        )
    if role:
        query = query.filter(Person.manual_role == role)
        
    people = query.order_by(Person.interaction_count.desc()).all()
    return jsonify([p.to_dict() for p in people])

@api_bp.route('/circle', methods=['POST'])
def add_contact():
    data = request.json
    if not data.get('email'): return jsonify({"error": "Email required"}), 400
    
    existing = Person.query.filter_by(email=data['email'].lower()).first()
    if existing: return jsonify({"error": "Contact exists"}), 400
    
    p = Person(
        email=data['email'].lower(),
        name=data.get('name'),
        job_title=data.get('job_title'),
        department=data.get('department'),
        manual_role=data.get('manual_role'),
        projects_json=json.dumps(data.get('projects', []))
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(p.to_dict())

@api_bp.route('/circle/<int:id>', methods=['PUT'])
def update_contact(id):
    p = db.session.get(Person, id)
    if not p: return jsonify({"error": "Not found"}), 404
    
    data = request.json
    if 'name' in data: p.name = data['name']
    if 'job_title' in data: p.job_title = data['job_title']
    if 'department' in data: p.department = data['department']
    if 'manual_role' in data: p.manual_role = data['manual_role']
    if 'projects' in data: p.projects_json = json.dumps(data['projects'])
    
    db.session.commit()
    return jsonify(p.to_dict())

@api_bp.route('/circle/<int:id>', methods=['DELETE'])
def hide_contact(id):
    p = db.session.get(Person, id)
    if not p: return jsonify({"error": "Not found"}), 404
    p.is_hidden = True
    db.session.commit()
    return jsonify({"message": "Contact hidden"})

@api_bp.route('/circle/<int:id>/profile', methods=['GET'])
def get_contact_profile(id):
    p = db.session.get(Person, id)
    if not p: return jsonify({"error": "Not found"}), 404
    
    # Get active tasks from this person
    active_tasks = Task.query.filter(
        Task.sender.ilike(f"%{p.name}%"), # Simple matching
        Task.status.in_(['new', 'in_progress'])
    ).limit(5).all()
    
    # Get recent history
    recent_closed = Task.query.filter(
        Task.sender.ilike(f"%{p.name}%"),
        Task.status == 'closed'
    ).order_by(Task.created_at.desc()).limit(5).all()
    
    return jsonify({
        "person": p.to_dict(),
        "active_tasks": [t.to_dict() for t in active_tasks],
        "recent_closed": [t.to_dict() for t in recent_closed]
    })

@api_bp.route('/circle/scan', methods=['POST'])
def scan_network_api():
    data = request.json
    start = datetime.strptime(data['start_date'], '%Y-%m-%d')
    end = datetime.strptime(data['end_date'], '%Y-%m-%d')
    
    # Fix timezone awareness here too if needed, but scan_network_period usually handles fetches.
    # However, to be safe, let's localize if naive.
    tz = pytz.timezone(getattr(Config, "TIMEZONE", "Asia/Dubai"))
    start = tz.localize(start.replace(hour=0, minute=0, second=0))
    end = tz.localize(end.replace(hour=23, minute=59, second=59))
    
    count = scan_network_period(start, end)
    return jsonify({"scanned": count})

# =====================================================
# 4. REPORT ENDPOINTS
# =====================================================

@api_bp.route('/reports/list', methods=['GET'])
def list_reports():
    """Lists generated HTML files in the reports folder."""
    if not os.path.exists(Config.REPORTS_PATH):
        return jsonify([])
        
    files = []
    # Sort by modification time (newest first)
    all_files = sorted(glob.glob(os.path.join(Config.REPORTS_PATH, "*.html")), key=os.path.getmtime, reverse=True)
    
    for f in all_files:
        name = os.path.basename(f)
        created = datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M')
        files.append({"filename": name, "created": created})
        
    return jsonify(files)

@api_bp.route('/reports/custom', methods=['POST'])
def generate_custom_report():
    data = request.json
    start = datetime.strptime(data['start_date'], '%Y-%m-%d')
    end = datetime.strptime(data['end_date'], '%Y-%m-%d')
    
    # Standard HTML Generation
    filepath = generate_weekly_report_logic(start, end)
    filename = os.path.basename(filepath)
    
    return jsonify({"message": "Generated", "filename": filename, "url": f"/reports/{filename}"})

@api_bp.route('/reports/consolidated', methods=['POST'])
def generate_consolidated_report():
    data = request.json
    start = datetime.strptime(data['start_date'], '%Y-%m-%d')
    end = datetime.strptime(data['end_date'], '%Y-%m-%d')
    
    # AI Consolidated Generation
    filepath = generate_consolidated_report_logic(start, end)
    filename = os.path.basename(filepath)
    
    return jsonify({"message": "Generated", "filename": filename, "url": f"/reports/{filename}"})


# =====================================================
# 5. NEWS / SUMMARY ENDPOINTS (FIXED)
# =====================================================

@api_bp.route('/summaries', methods=['GET'])
def get_summaries():
    # Only fetch last 7 days to keep UI clean
    seven_days_ago = datetime.utcnow().date() - timedelta(days=7)
    
    # Ensure a summary exists for today (even if empty)
    today = datetime.utcnow().date()
    today_summary = DailySummary.query.filter_by(summary_date=today).first()
    
    if not today_summary:
        # Create a blank placeholder for today so UI shows "Generate"
        today_summary = DailySummary(summary_date=today, raw_snippets="[]", status="pending")
        db.session.add(today_summary)
        db.session.commit()

    summaries = DailySummary.query.filter(DailySummary.summary_date >= seven_days_ago)\
        .order_by(DailySummary.summary_date.desc()).all()
    
    # --- FIX FOR TTS: Prepend URL prefix ---
    results = []
    url_prefix = getattr(Config, 'BRIEFING_AUDIO_URL_PREFIX', 'briefings')
    
    for s in summaries:
        data = s.to_dict()
        # If audio exists, make it a full URL for the frontend
        if data.get('audio_file_path'):
            data['audio_file_path'] = f"/{url_prefix}/{data['audio_file_path']}"
        results.append(data)
        
    return jsonify(results)

@api_bp.route('/summaries/generate/<int:id>', methods=['POST'])
def generate_summary_api(id):
    summary = db.session.get(DailySummary, id)
    if not summary:
        return jsonify({"error": "Summary not found"}), 404
        
    # Trigger generation logic
    try:
        # Mark as generating
        summary.status = 'generating'
        db.session.commit()
        
        # Process Summary (AI + Audio)
        result_summary = process_daily_summary(summary)
        
        # --- FIX FOR TTS: Prepend URL prefix ---
        data = result_summary.to_dict()
        if data.get('audio_file_path'):
            url_prefix = getattr(Config, 'BRIEFING_AUDIO_URL_PREFIX', 'briefings')
            data['audio_file_path'] = f"/{url_prefix}/{data['audio_file_path']}"
        
        return jsonify(data)
    except Exception as e:
        logger.error(f"Generation Failed: {e}")
        summary.status = 'failed'
        summary.content = str(e)
        db.session.commit()
        return jsonify({"error": str(e)}), 500

@api_bp.route('/summaries/regenerate/<int:id>', methods=['POST'])
def regenerate_summary_api(id):
    summary = db.session.get(DailySummary, id)
    if not summary:
        return jsonify({"error": "Summary not found"}), 404

    try:
        # Reset content and regenerate
        summary.status = 'generating'
        summary.content = None
        summary.audio_file_path = None
        db.session.commit()

        # Process Summary (AI + Audio)
        result_summary = process_daily_summary(summary)
        
        # --- FIX FOR TTS: Prepend URL prefix ---
        data = result_summary.to_dict()
        if data.get('audio_file_path'):
            url_prefix = getattr(Config, 'BRIEFING_AUDIO_URL_PREFIX', 'briefings')
            data['audio_file_path'] = f"/{url_prefix}/{data['audio_file_path']}"
            
        return jsonify(data)
    except Exception as e:
        logger.error(f"Regeneration Failed: {e}")
        summary.status = 'failed'
        summary.content = str(e)
        db.session.commit()
        return jsonify({"error": str(e)}), 500


# =====================================================
# 6. SETTINGS ENDPOINTS
# =====================================================

@api_bp.route('/settings', methods=['GET'])
def get_settings():
    """Returns general settings + classification lists + SLA config."""
    model = get_setting('ollama_model') or Config.OLLAMA_MODEL
    sla_days = getattr(Config, 'SLA_RESPONSE_DAYS', 4) 
    
    projects = get_json_setting('classification_projects', Config.DEFAULT_PROJECTS)
    tags = get_json_setting('classification_tags', Config.DEFAULT_TAGS)
    domains = get_json_setting('classification_domains', Config.DEFAULT_DOMAINS)
    
    return jsonify({
        'ollama_model': model,
        'projects': projects,
        'tags': tags,
        'domains': domains,
        'sla_days': sla_days 
    })

@api_bp.route('/settings', methods=['POST'])
def update_settings():
    """Updates general settings + classification lists."""
    try:
        data = request.json
        if 'ollama_model' in data:
            save_setting('ollama_model', data['ollama_model'])
            
        if 'projects' in data:
            save_setting('classification_projects', json.dumps(data['projects']))
        if 'tags' in data:
            save_setting('classification_tags', json.dumps(data['tags']))
        if 'domains' in data:
            save_setting('classification_domains', json.dumps(data['domains']))
            
        return jsonify({"message": "Saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500