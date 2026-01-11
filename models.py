# Filename: models.py
# Role: Database models for AI Task Manager (Multi-User Edition)

from datetime import datetime, date
import json
from flask_login import UserMixin
from extensions import db


# =====================================================
# USER MODEL (NEW - Multi-User Authentication)
# =====================================================

class User(UserMixin, db.Model):
    """
    User model for multi-user authentication.
    Does NOT store Exchange passwords - those are kept in encrypted session only.
    """
    __tablename__ = "user"
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=True)
    
    # Account settings
    ews_server = db.Column(db.String(200), nullable=True)  # Allow user-specific server override
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<User {self.email}>'
    
    def get_id(self):
        """Required by Flask-Login"""
        return str(self.id)
    
    @property
    def is_authenticated(self):
        """Required by Flask-Login"""
        return True
    
    @property
    def is_anonymous(self):
        """Required by Flask-Login"""
        return False
    
    def get_id(self):
        """Required by Flask-Login"""
        return str(self.id)
    
    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "ews_server": self.ews_server,
            "is_admin": self.is_admin,
            "is_active": self.is_active,
            "last_login": self.last_login.isoformat() + "Z" if self.last_login else None,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None
        }


# =====================================================
# TASK MODEL (Enhanced with User Support)
# =====================================================

class Task(db.Model):
    """
    Core task model representing actionable items from emails.
    Each task belongs to a user (multi-tenant support).
    """
    __tablename__ = "task"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # NEW: User relationship for multi-tenant support
    # Add this when you want to isolate tasks per user
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    # user = db.relationship('User', backref='tasks')
    
    email_message_id = db.Column(db.String(300), unique=True, nullable=False, index=True)
    subject = db.Column(db.String(500))
    sender = db.Column(db.String(200))
    task_summary = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), nullable=False, default="new", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # SLA Fields
    received_at = db.Column(db.DateTime, nullable=True)
    status_updated_at = db.Column(db.DateTime, nullable=True)  # Track when status changed

    task_detail = db.Column(db.Text)
    required_action = db.Column(db.Text)
    suggested_reply = db.Column(db.Text)
    
    # Reply Variants
    reply_acknowledge = db.Column(db.Text, nullable=True)
    reply_done = db.Column(db.Text, nullable=True)
    reply_delegate = db.Column(db.Text, nullable=True)

    # Action Taken
    action_taken = db.Column(db.String(50), nullable=True)

    # Auto-Completion Evidence
    auto_completed_at = db.Column(db.DateTime, nullable=True)
    completion_evidence = db.Column(db.Text, nullable=True)
    
    # Executive Triage
    triage_category = db.Column(db.String(50), default="deep_work")  # quick_action, deep_work, waiting_for
    delegated_to = db.Column(db.String(200), nullable=True)
    delegated_at = db.Column(db.DateTime, nullable=True)

    # Classification
    project = db.Column(db.String(100), default="Unknown")
    tags_json = db.Column(db.Text, default="[]")
    
    # Smart Classification
    domain_hint = db.Column(db.String(100), default="Unknown")
    effort_estimate_hours = db.Column(db.Float, nullable=True)
    business_impact = db.Column(db.Text, nullable=True)
    
    # EWS Specifics for Reply
    ews_item_id = db.Column(db.String(500), nullable=True)
    ews_change_key = db.Column(db.String(500), nullable=True)
    priority = db.Column(db.String(20), default="medium")
    
    # Recipients (for reference)
    to_recipients_json = db.Column(db.Text, default="[]")
    cc_recipients_json = db.Column(db.Text, default="[]")

    @property
    def tags(self):
        try:
            return json.loads(self.tags_json)
        except:
            return []

    @tags.setter
    def tags(self, value):
        self.tags_json = json.dumps(value)
    
    @property
    def to_recipients(self):
        try:
            return json.loads(self.to_recipients_json)
        except:
            return []
    
    @to_recipients.setter
    def to_recipients(self, value):
        self.to_recipients_json = json.dumps(value)
    
    @property
    def cc_recipients(self):
        try:
            return json.loads(self.cc_recipients_json)
        except:
            return []
    
    @cc_recipients.setter
    def cc_recipients(self, value):
        self.cc_recipients_json = json.dumps(value)

    def to_dict(self):
        return {
            "id": self.id,
            "subject": self.subject,
            "sender": self.sender,
            "task_summary": self.task_summary,
            "status": self.status,
            "received_at": self.received_at.isoformat() + "Z" if self.received_at else None,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "status_updated_at": self.status_updated_at.isoformat() + "Z" if self.status_updated_at else None,
            "task_detail": self.task_detail,
            "required_action": self.required_action,
            "project": self.project,
            "tags": self.tags,
            "domain_hint": self.domain_hint,
            "effort_estimate_hours": self.effort_estimate_hours,
            "business_impact": self.business_impact,
            "action_taken": self.action_taken,
            "priority": self.priority,
            # Reply drafts
            "reply_acknowledge": self.reply_acknowledge,
            "reply_done": self.reply_done,
            "reply_delegate": self.reply_delegate,
            "suggested_reply": self.suggested_reply,
            # Triage
            "triage_category": self.triage_category,
            "delegated_to": self.delegated_to,
            "delegated_at": self.delegated_at.isoformat() + "Z" if self.delegated_at else None,
            # Auto-completion
            "auto_completed_at": self.auto_completed_at.isoformat() + "Z" if self.auto_completed_at else None,
            "completion_evidence": self.completion_evidence
        }


# =====================================================
# PERSON MODEL (Professional Circle / CRM)
# =====================================================

class Person(db.Model):
    """
    Professional circle model for tracking contacts and relationships.
    Shared across users (global contact database) or can be made user-specific.
    """
    __tablename__ = "person"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # NEW: Optional user relationship for user-specific contacts
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    # user = db.relationship('User', backref='contacts')
    
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=True)
    job_title = db.Column(db.String(200), nullable=True)
    department = db.Column(db.String(200), nullable=True)
    office_location = db.Column(db.String(200), nullable=True)
    manager_name = db.Column(db.String(200), nullable=True)
    
    # Stats
    interaction_count = db.Column(db.Integer, default=0)
    last_interaction_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Manual Override
    manual_role = db.Column(db.String(100), nullable=True)
    is_hidden = db.Column(db.Boolean, default=False)
    
    # Projects association (JSON list of objects)
    projects_json = db.Column(db.Text, default="[]")
    
    # Notes
    notes = db.Column(db.Text, nullable=True)

    @property
    def projects(self):
        try:
            return json.loads(self.projects_json)
        except:
            return []
    
    @projects.setter
    def projects(self, value):
        self.projects_json = json.dumps(value)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "job_title": self.job_title,
            "department": self.department,
            "office_location": self.office_location,
            "manager_name": self.manager_name,
            "interaction_count": self.interaction_count,
            "last_interaction_at": self.last_interaction_at.isoformat() + "Z" if self.last_interaction_at else None,
            "manual_role": self.manual_role,
            "is_hidden": self.is_hidden,
            "projects": self.projects,
            "notes": self.notes
        }


# =====================================================
# APP SETTINGS MODEL
# =====================================================

class AppSettings(db.Model):
    """
    Key-value store for application settings.
    Can be made user-specific by adding user_id foreign key.
    """
    __tablename__ = "app_settings"
    
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    
    # NEW: Optional user-specific settings
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    # user = db.relationship('User', backref='settings')
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None
        }


# =====================================================
# DAILY SUMMARY MODEL (News/Briefings)
# =====================================================

class DailySummary(db.Model):
    """
    Daily news summaries generated from INFO emails.
    Can be made user-specific for personalized briefings.
    """
    __tablename__ = "daily_summary"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # NEW: Optional user relationship for personalized summaries
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    # user = db.relationship('User', backref='summaries')
    
    summary_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    raw_snippets = db.Column(db.Text)  # JSON array of email snippets
    content = db.Column(db.Text)  # Generated summary text
    status = db.Column(db.String(50), nullable=False, default="pending")  # pending, generating, generated, failed
    audio_file_path = db.Column(db.String(500), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    generated_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('summary_date', name='uniq_summary_date'),
        # If making user-specific:
        # db.UniqueConstraint('summary_date', 'user_id', name='uniq_user_summary_date'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "summary_date": self.summary_date.isoformat(),
            "content": self.content,
            "status": self.status,
            "audio_file_path": self.audio_file_path,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "generated_at": self.generated_at.isoformat() + "Z" if self.generated_at else None
        }


# =====================================================
# APPROVAL REQUEST MODEL
# =====================================================

class ApprovalRequest(db.Model):
    """
    Approval requests extracted from emails.
    Tracks approval workflows and decisions.
    """
    __tablename__ = "approval_request"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # NEW: Optional user relationship (approver)
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    # user = db.relationship('User', backref='approval_requests')
    
    source_email_id = db.Column(db.String(300), unique=True, nullable=False, index=True)
    
    # Classification
    request_type = db.Column(db.String(100), nullable=False)  # Budget, Leave, Document, Access, IT Change
    summary = db.Column(db.Text, nullable=False)
    
    # Detailed Analysis (5W1H) stored as JSON
    details_5w1h_json = db.Column(db.Text, default="{}")
    
    # Risk & AI Logic
    risk_level = db.Column(db.String(20), default="Medium", index=True)  # Low, Medium, High
    ai_recommendation = db.Column(db.String(20))  # Approve, Reject, Review
    confidence_score = db.Column(db.Float, default=0.0)
    
    # Impact & Conflict
    impact_analysis = db.Column(db.Text, nullable=True)
    conflict_flag = db.Column(db.Text, nullable=True)
    
    # State
    status = db.Column(db.String(50), default="Pending", index=True)  # Pending, Approved, Rejected, Escalated
    human_action_at = db.Column(db.DateTime, nullable=True)
    human_notes = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # EWS Link for Actions
    ews_item_id = db.Column(db.String(500), nullable=True)

    @property
    def details(self):
        try:
            return json.loads(self.details_5w1h_json)
        except:
            return {}
    
    @details.setter
    def details(self, value):
        self.details_5w1h_json = json.dumps(value)

    def to_dict(self):
        return {
            "id": self.id,
            "request_type": self.request_type,
            "summary": self.summary,
            "details": self.details,
            "risk_level": self.risk_level,
            "ai_recommendation": self.ai_recommendation,
            "confidence_score": self.confidence_score,
            "impact_analysis": self.impact_analysis,
            "conflict_flag": self.conflict_flag,
            "status": self.status,
            "human_action_at": self.human_action_at.isoformat() + "Z" if self.human_action_at else None,
            "human_notes": self.human_notes,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None
        }


# =====================================================
# APPROVAL AUDIT LOG MODEL
# =====================================================

class ApprovalAuditLog(db.Model):
    """
    Audit trail for all approval actions for compliance.
    Tracks who did what and when.
    """
    __tablename__ = "approval_audit_log"
    
    id = db.Column(db.Integer, primary_key=True)
    approval_id = db.Column(db.Integer, db.ForeignKey('approval_request.id'), nullable=False, index=True)
    
    # Action tracking
    action = db.Column(db.String(50), nullable=False)  # AI_Classified, User_Viewed, User_Approved, User_Rejected
    metadata_json = db.Column(db.Text, default="{}")  # IP, Device, Notes, etc.
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # NEW: Track which user performed the action
    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    # user = db.relationship('User', backref='approval_actions')
    
    # Relationship to approval request
    approval = db.relationship('ApprovalRequest', backref='audit_logs')

    @property
    def action_metadata(self):
        """Get metadata as dict (renamed to avoid SQLAlchemy conflict)"""
        try:
            return json.loads(self.metadata_json)
        except:
            return {}
    
    @action_metadata.setter
    def action_metadata(self, value):
        """Set metadata from dict"""
        self.metadata_json = json.dumps(value)

    def to_dict(self):
        return {
            "id": self.id,
            "approval_id": self.approval_id,
            "action": self.action,
            "metadata": self.action_metadata,  # Use the property accessor
            "timestamp": self.timestamp.isoformat() + "Z" if self.timestamp else None
        }


# =====================================================
# OPTIONAL: USER PREFERENCES MODEL
# =====================================================

class UserPreference(db.Model):
    """
    Optional: User-specific preferences and settings.
    Useful for UI customization, notification settings, etc.
    """
    __tablename__ = "user_preference"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Preferences (stored as JSON for flexibility)
    preferences_json = db.Column(db.Text, default="{}")
    
    # Quick access fields
    theme = db.Column(db.String(20), default="light")  # light, dark, auto
    language = db.Column(db.String(10), default="en")  # en, ar
    timezone = db.Column(db.String(50), default="Asia/Dubai")
    
    # Notification settings
    email_notifications = db.Column(db.Boolean, default=True)
    daily_summary_time = db.Column(db.String(5), default="08:00")  # HH:MM format
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='preferences')

    @property
    def preferences(self):
        try:
            return json.loads(self.preferences_json)
        except:
            return {}
    
    @preferences.setter
    def preferences(self, value):
        self.preferences_json = json.dumps(value)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "theme": self.theme,
            "language": self.language,
            "timezone": self.timezone,
            "email_notifications": self.email_notifications,
            "daily_summary_time": self.daily_summary_time,
            "preferences": self.preferences,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None
        }


# =====================================================
# DATABASE HELPER FUNCTIONS
# =====================================================

def init_default_data():
    """
    Initialize default data for new installations.
    Called during first-time setup.
    """
    # Add default settings if they don't exist
    default_settings = {
        'ollama_model': 'deepseek-v3.1:671b-cloud',
        'classification_projects': json.dumps([
            "CTS", "CRM", "ERP", "Mobile App", "HR Portal", 
            "DubaiNow", "GIS", "Procurement", "Finance", 
            "Internal", "Personal", "Unknown"
        ]),
        'classification_tags': json.dumps([
            "Bug", "Feature Request", "Information Request", 
            "Service Request", "Approval", "Access Request", 
            "Meeting", "Report", "Complaint", "Security", 
            "Onboarding", "Budget", "Legal", "Vendor-Related", 
            "Training", "Update", "Other"
        ]),
        'classification_domains': json.dumps([
            "IT Support", "Finance", "Procurement", "Legal", 
            "HR", "Facilities", "Security", "Vendor", "Unknown"
        ])
    }
    
    for key, value in default_settings.items():
        if not AppSettings.query.filter_by(key=key).first():
            setting = AppSettings(key=key, value=value)
            db.session.add(setting)
    
    db.session.commit()


# =====================================================
# MIGRATION NOTES
# =====================================================
"""
MULTI-USER MIGRATION NOTES:

To fully enable multi-user isolation, uncomment the user_id foreign keys in:
- Task model (to isolate tasks per user)
- Person model (to isolate contacts per user)
- AppSettings model (for user-specific settings)
- DailySummary model (for personalized briefings)
- ApprovalRequest model (to track which user received the approval)
- ApprovalAuditLog model (to track which user took action)

Then run database migration:
1. flask db migrate -m "Add user relationships"
2. flask db upgrade

Or update fix_db.py to add the foreign key columns.

IMPORTANT: After adding user_id relationships, update all queries to filter by current_user:
Example:
    tasks = Task.query.filter_by(user_id=current_user.id).all()

This ensures complete data isolation between users.
"""