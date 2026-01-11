from flask import Blueprint, render_template, send_from_directory
from flask_login import login_required, current_user
from config import Config

view_bp = Blueprint('views', __name__)

@view_bp.route('/')
@login_required
def index():
    return render_template('index.html')

@view_bp.route('/archive')
@login_required
def archive_page():
    return render_template('archive.html')

@view_bp.route('/news')
@login_required
def news_page():
    return render_template('news.html')

@view_bp.route('/reports')
@login_required
def reports_page():
    return render_template('reports.html')

@view_bp.route('/circle')
@login_required
def circle_page():
    return render_template('circle.html')

@view_bp.route('/approvals')
@login_required
def approvals_page():
    return render_template('approvals.html')

@view_bp.route('/favicon.ico')
def favicon():
    return '', 204

@view_bp.route(f'/{Config.BRIEFING_AUDIO_URL_PREFIX}/<filename>')
@login_required
def serve_briefing_audio(filename):
    return send_from_directory(Config.BRIEFING_AUDIO_PATH, filename)

@view_bp.route('/reports/<filename>')
@login_required
def serve_report(filename):
    return send_from_directory(Config.REPORTS_PATH, filename)