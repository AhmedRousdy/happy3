import os
import logging
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from datetime import datetime, timedelta

from config import Config
from extensions import db, migrate, login_manager
from routes.views import view_bp
from routes.api import api_bp
from routes.approvals import approval_bp
from routes.auth import auth_bp  # NEW: Authentication blueprint

from services.llm_service import check_and_pull_model
from fix_db import upgrade_database
from services.pipeline_service import scan_network_period 

# Ensure dirs
os.makedirs(Config.BRIEFING_AUDIO_PATH, exist_ok=True)
os.makedirs(Config.REPORTS_PATH, exist_ok=True)

app = Flask(__name__)
app.config.from_object(Config)

# CRITICAL: Set secret key for session encryption
if not app.config.get('SECRET_KEY'):
    # In production, this MUST be set in environment variables
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    if app.config['SECRET_KEY'] == 'dev-secret-key-change-in-production':
        logging.warning("Using default SECRET_KEY. Set SECRET_KEY environment variable in production!")

# Init Extensions
db.init_app(app)
migrate.init_app(app, db)
login_manager.init_app(app)  # NEW: Initialize Flask-Login

# Register Blueprints
app.register_blueprint(auth_bp)  # NEW: Must be registered FIRST (for login redirect)
app.register_blueprint(view_bp)
app.register_blueprint(api_bp)
app.register_blueprint(approval_bp)

# User Loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    from models import User
    return db.session.get(User, int(user_id))

# Scheduler
def start_scheduler():
    scheduler = BackgroundScheduler(timezone=Config.TIMEZONE)
    from services.report_service import generate_weekly_report_logic
    
    def scheduled_network_scan():
        with app.app_context():
            end_date = datetime.now(pytz.timezone(Config.TIMEZONE))
            start_date = end_date - timedelta(days=7)
            scan_network_period(start_date, end_date) 
            
    # Uncomment to enable weekly scan
    # scheduler.add_job(scheduled_network_scan, 'cron', day_of_week='fri', hour=22)
    scheduler.start()

if __name__ == '__main__':
    with app.app_context():
        # 1. Run DB Upgrade
        upgrade_database()
        
        # 2. Create tables
        db.create_all()
        
        # 3. Init Services
        check_and_pull_model(Config.OLLAMA_MODEL)
        # NOTE: EWS init is now user-specific, handled in ews_service.py
        
    # Start Scheduler
    start_scheduler()
    
    # Run
    print(f"--- AI Task Manager (Multi-User Edition) Running on http://localhost:5001 ---")
    print(f"--- Default Login: Use your Exchange credentials ---")
    app.run(debug=True, port=5001)