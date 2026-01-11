# Filename: routes/auth.py
# Role: Authentication routes for multi-user login system

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, current_user
from datetime import datetime
from cryptography.fernet import Fernet

from extensions import db, login_manager
from models import User
from services.ews_service import verify_exchange_credentials
from config import Config

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Encryption key for session credentials (generate once, store in config)
def get_or_create_encryption_key():
    """Get or create an encryption key for credential storage"""
    key = getattr(Config, 'CREDENTIAL_ENCRYPTION_KEY', None)
    if not key:
        # In production, this should be stored securely (env var or secrets manager)
        key = Fernet.generate_key()
        logger.warning("Generated new encryption key. Set CREDENTIAL_ENCRYPTION_KEY in config for production!")
    return key

CIPHER_SUITE = Fernet(get_or_create_encryption_key())

def encrypt_password(password):
    """Encrypt password for session storage"""
    return CIPHER_SUITE.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password):
    """Decrypt password from session storage"""
    return CIPHER_SUITE.decrypt(encrypted_password.encode()).decode()


@login_manager.user_loader
def load_user(user_id):
    """Required by Flask-Login to reload user from session"""
    return db.session.get(User, int(user_id))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page and handler"""
    if current_user.is_authenticated:
        return redirect(url_for('views.index'))
    
    if request.method == 'POST':
        login_username = request.form.get('login_username', '').strip()
        mailbox_email = request.form.get('mailbox_email', '').strip()
        password = request.form.get('password', '')
        ews_server = request.form.get('ews_server', '').strip()
        remember = request.form.get('remember', False)
        
        # If mailbox_email is empty, assume it's the same as login_username
        if not mailbox_email:
            mailbox_email = login_username
        
        if not login_username or not password:
            flash('Username and password are required.', 'error')
            return render_template('login.html')
        
        # Use default server from config if not provided
        if not ews_server:
            ews_server = Config.EWS_SERVER
        
        # Verify Exchange credentials (use login_username for auth, mailbox_email for mailbox)
        is_valid, error_msg = verify_exchange_credentials(
            auth_username=login_username,
            mailbox_email=mailbox_email,
            password=password,
            server=ews_server
        )
        
        if not is_valid:
            flash(f'Login failed: {error_msg}', 'error')
            logger.warning(f"Failed login attempt for {login_username}")
            return render_template('login.html')
        
        # Find or create user (indexed by mailbox email)
        user = User.query.filter_by(email=mailbox_email).first()
        if not user:
            user = User(
                email=mailbox_email,
                login_username=login_username,
                ews_server=ews_server,
                is_active=True
            )
            db.session.add(user)
            logger.info(f"Created new user account for {mailbox_email} (login: {login_username})")
        else:
            # Update login_username if it changed
            if user.login_username != login_username:
                user.login_username = login_username
        
        # Update last login
        user.last_login = datetime.utcnow()
        if ews_server and not user.ews_server:
            user.ews_server = ews_server
        
        db.session.commit()
        
        # Store encrypted credentials in session
        session['ews_login_username'] = login_username  # NEW: Store auth username separately
        session['ews_email'] = mailbox_email  # Store mailbox email
        session['ews_password'] = encrypt_password(password)
        session['ews_server'] = ews_server
        
        # Log in user
        login_user(user, remember=remember)
        
        logger.info(f"Successful login for {mailbox_email} (auth: {login_username})")
        flash('Login successful!', 'success')
        
        # Redirect to next page or home
        next_page = request.args.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)
        return redirect(url_for('views.index'))
    
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    """Logout and clear session"""
    if current_user.is_authenticated:
        logger.info(f"User {current_user.email} logged out")
    
    # Clear encrypted credentials from session
    session.pop('ews_login_username', None)  # NEW: Clear auth username
    session.pop('ews_email', None)
    session.pop('ews_password', None)
    session.pop('ews_server', None)
    
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


def get_current_user_credentials():
    """
    Retrieve current user's Exchange credentials from session.
    Returns: (auth_username, mailbox_email, password, server) or (None, None, None, None)
    
    auth_username: Used for authentication with Exchange
    mailbox_email: Used for accessing the mailbox
    """
    if not current_user.is_authenticated:
        return None, None, None, None
    
    login_username = session.get('ews_login_username')
    email = session.get('ews_email')
    encrypted_password = session.get('ews_password')
    server = session.get('ews_server')
    
    # Fallback: If login_username not in session (old sessions), use email
    if not login_username:
        login_username = email
    
    if not email or not encrypted_password or not server:
        logger.error(f"Missing credentials in session for user {current_user.email}")
        return None, None, None, None
    
    try:
        password = decrypt_password(encrypted_password)
        return login_username, email, password, server
    except Exception as e:
        logger.error(f"Failed to decrypt credentials: {e}")
        return None, None, None, None