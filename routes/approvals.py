from flask import Blueprint, jsonify, request
from services.approval_service import ApprovalService
from models import ApprovalRequest, ApprovalAuditLog
from extensions import db
import logging

logger = logging.getLogger(__name__)
approval_bp = Blueprint('approvals', __name__, url_prefix='/api/approvals')

@approval_bp.route('/count', methods=['GET'])
def get_pending_count():
    try:
        count = ApprovalRequest.query.filter_by(status='Pending').count()
        return jsonify({"count": count})
    except Exception as e:
        logger.error(f"Count Fetch Error: {e}")
        return jsonify({"count": 0}), 200

@approval_bp.route('/feed', methods=['GET'])
def get_approval_feed():
    try:
        requests = ApprovalRequest.query.filter_by(status='Pending')\
            .order_by(ApprovalRequest.risk_level.desc(), ApprovalRequest.created_at.desc())\
            .all()
        return jsonify([r.to_dict() for r in requests])
    except Exception as e:
        logger.error(f"Feed Fetch Error: {e}")
        return jsonify({"error": str(e)}), 500

@approval_bp.route('/<int:id>/action', methods=['POST'])
def take_action(id):
    data = request.json
    action = data.get('action')
    notes = data.get('notes')
    
    if action not in ['Approved', 'Rejected']:
        return jsonify({"error": "Invalid action"}), 400
        
    success, message = ApprovalService.execute_action(id, action, notes)
    
    if success:
        return jsonify({"message": message})
    else:
        return jsonify({"error": message}), 500

@approval_bp.route('/history', methods=['GET'])
def get_history():
    try:
        limit = request.args.get('limit', 50)
        requests = ApprovalRequest.query.filter(ApprovalRequest.status != 'Pending')\
            .order_by(ApprovalRequest.human_action_at.desc())\
            .limit(limit)\
            .all()
        return jsonify([r.to_dict() for r in requests])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@approval_bp.route('/<int:id>/audit', methods=['GET'])
def get_audit_log(id):
    logs = ApprovalAuditLog.query.filter_by(approval_id=id).order_by(ApprovalAuditLog.timestamp.asc()).all()
    return jsonify([l.to_dict() for l in logs])

# --- DELETE ENDPOINT ---
@approval_bp.route('/<int:id>', methods=['DELETE'])
def delete_approval(id):
    """
    Deletes an approval request and its audit logs.
    """
    try:
        req = db.session.get(ApprovalRequest, id)
        if not req:
            return jsonify({"error": "Request not found"}), 404
        
        # Delete associated audit logs first
        ApprovalAuditLog.query.filter_by(approval_id=id).delete()
        
        db.session.delete(req)
        db.session.commit()
        return jsonify({"message": "Deleted successfully"})
    except Exception as e:
        logger.error(f"Delete Error: {e}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500