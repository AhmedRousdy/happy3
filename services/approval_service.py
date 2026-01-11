import json
import logging
import re
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import ApprovalRequest, ApprovalAuditLog
from config import Config
from services.llm_service import call_ollama
# We will need EWS service to send reply emails upon approval/rejection
from services.ews_service import send_reply_email
from utils import extract_json_from_response  # --- FIX: Import robust JSON extractor ---

logger = logging.getLogger(__name__)

class ApprovalService:
    """
    Core logic for the Approval Assistant System.
    Handles analysis, risk scoring, and execution of approval workflows.
    """

    @staticmethod
    def is_potential_approval(subject, body):
        """
        Heuristic check to see if an email looks like an approval request.
        Used by the pipeline router to catch items the LLM might miss or to speed up triage.
        """
        subject = subject.lower() if subject else ""
        body = body.lower() if body else ""
        
        # 1. Strong Keywords in Subject
        strong_triggers = [
            "approval", "approve", "permission", "authorization", "sign-off", 
            "review request", "request for approval", "please approve", "action required"
        ]
        if any(w in subject for w in strong_triggers):
            return True

        # 2. Leave/Time Off Specific Patterns (Subject or Start of Body)
        leave_triggers = ["annual leave", "vacation", "time off", "sick leave", "wfh request"]
        if any(w in subject for w in leave_triggers):
            return True

        # 3. Body context (Start of email)
        # Expanded to catch variations like "Kindly provide your approval"
        body_start = body[:1500] # Expanded search window to 1500 chars
        phrase_triggers = [
            "kindly for your approval", 
            "kindly provide your approval",
            "provide your approval",
            "please sign off", 
            "requires your approval", 
            "waiting for your approval",
            "for your review and approval",
            "approve this",
            "sign off on",
            "availability confirmation",
            "confirmation on the below"
        ]
        if any(phrase in body_start for phrase in phrase_triggers):
            return True
            
        # 4. IT / Change Management Patterns (NEW)
        # Catches CRs, Deployments, and Downtime requests
        it_triggers = ["cr number", "change request", "crq", "downtime required", "production deployment", "cts activity"]
        if any(w in body_start for w in it_triggers):
            # If it's an IT request, it's almost certainly an approval if it mentions 'approval' or 'confirm' anywhere
            if "approval" in body_start or "approve" in body_start or "confirm" in body_start:
                return True

        return False

    @staticmethod
    def ingest_request(email_item):
        """
        Entry point for the pipeline. Converts an email into an ApprovalRequest.
        """
        try:
            # 1. Deduplication check
            exists = ApprovalRequest.query.filter_by(source_email_id=email_item.message_id).first()
            if exists:
                logger.info(f"Approval request already exists for email {email_item.message_id}")
                return exists

            # 2. Analyze Content (5W1H & Risk)
            # Use fallback if analysis fails so we don't lose the approval
            analysis = ApprovalService._analyze_email_content(email_item.subject, email_item.body or email_item.text_body or "")
            
            if not analysis:
                logger.warning("LLM Analysis failed. Using fallback default values.")
                analysis = {
                    'request_type': 'General',
                    'summary': email_item.subject,
                    '5w1h': {'details': 'Automatic analysis failed. Review email manually.'},
                    'risk_level': 'Medium',
                    'recommendation': 'Review',
                    'confidence_score': 0.0,
                    'who': email_item.sender.name if email_item.sender else "Unknown"
                }

            # Ensure 5W1H has the requester name if missing
            details = analysis.get('5w1h', {})
            if 'who' not in details or not details['who']:
                 details['who'] = email_item.sender.name if email_item.sender else "Unknown"

            # 3. Create Record
            req = ApprovalRequest(
                source_email_id=email_item.message_id,
                request_type=analysis.get('request_type', 'General'),
                summary=analysis.get('summary', email_item.subject),
                details_5w1h_json=json.dumps(details),
                risk_level=analysis.get('risk_level', 'Medium'),
                ai_recommendation=analysis.get('recommendation', 'Review'),
                confidence_score=analysis.get('confidence_score', 0.0),
                impact_analysis=analysis.get('impact_analysis'),
                conflict_flag=analysis.get('conflict_flag'),
                ews_item_id=email_item.id if hasattr(email_item, 'id') else None, # Store EWS ID for actions
                status='Pending'
            )
            
            db.session.add(req)
            db.session.commit()
            
            # 4. Audit Log
            ApprovalService._log_audit(req.id, 'AI_Classified', {'score': req.confidence_score})
            
            return req

        except Exception as e:
            logger.error(f"Error ingesting approval request: {e}", exc_info=True)
            db.session.rollback()
            return None

    @staticmethod
    def _analyze_email_content(subject, body):
        """
        Uses LLM to extract structured approval data.
        """
        prompt = f"""
        Analyze this approval request email. Extract the 5W1H details.
        
        EMAIL SUBJECT: {subject}
        EMAIL BODY: {body[:3000]}
        
        Return JSON ONLY. No markdown. No intro.
        {{
            "request_type": "Budget" | "Leave" | "Document" | "Access" | "General" | "IT Change",
            "summary": "1-sentence summary",
            "5w1h": {{
                "who": "Name/Role of requester",
                "what": "What is requested?",
                "where": "Location/Context",
                "when": "Date/Deadline (e.g. 2nd Jan 2026)",
                "why": "Justification",
                "how": "Cost/Method"
            }},
            "risk_level": "Low" | "Medium" | "High",
            "recommendation": "Approve" | "Reject" | "Review",
            "confidence_score": 0.9,
            "impact_analysis": "Consequences if approved",
            "conflict_flag": "Any policy conflicts?"
        }}
        """
        
        try:
            # Force JSON format option if supported by model/wrapper
            response = call_ollama(Config.OLLAMA_MODEL, prompt, json_format=True)
            if not response: return None
            
            # --- FIX: Use robust extractor instead of raw json.loads ---
            return extract_json_from_response(response)
            
        except Exception as e:
            logger.error(f"Failed to parse Approval LLM JSON: {e}")
            return None

    @staticmethod
    def execute_action(request_id, action, user_notes=None):
        """
        Executes a human decision (Approve/Reject).
        """
        req = db.session.get(ApprovalRequest, request_id)
        if not req: return False, "Request not found"
        
        try:
            req.status = action # Approved / Rejected
            req.human_action_at = datetime.utcnow()
            
            # 1. Send Reply Email
            # We use source_email_id (Internet Message ID) because EWS Item IDs can change/expire.
            # The ews_service.send_reply_email function handles lookup by Message-ID robustly.
            if req.source_email_id:
                reply_body = f"Your request has been {action.lower()}."
                if user_notes:
                    reply_body += f"\n\nNote: {user_notes}"
                
                # Use existing EWS service to send
                send_reply_email(req.source_email_id, reply_body)
            
            # 2. Audit Log
            ApprovalService._log_audit(req.id, f'User_{action}', {'notes': user_notes})
            
            db.session.commit()
            return True, f"Request {action} successfully."
            
        except Exception as e:
            logger.error(f"Error executing approval action: {e}")
            return False, str(e)

    @staticmethod
    def _log_audit(req_id, action, metadata=None):
        try:
            log = ApprovalAuditLog(
                approval_id=req_id,
                action=action,
                metadata_json=json.dumps(metadata or {})
            )
            db.session.add(log)
            # Commit handled by caller usually, but safe to add to session
        except Exception as e:
            logger.error(f"Audit log failed: {e}")