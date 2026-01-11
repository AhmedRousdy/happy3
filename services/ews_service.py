# Filename: services/ews_service.py
# Role: Exchange Web Services integration (Multi-User Edition)

from exchangelib import Credentials, Account, Configuration, DELEGATE, Mailbox, FileAttachment, Body, HTMLBody
from exchangelib.items import Message, Contact
from exchangelib.protocol import BaseProtocol
from exchangelib.ewsdatetime import EWSTimeZone
from exchangelib.properties import ItemId
from exchangelib.errors import UnauthorizedError, ErrorAccessDenied, TransportError
import pytz
import logging
import html
from flask_login import current_user
from flask import has_request_context
from config import Config

logger = logging.getLogger(__name__)

# Cache for user accounts (thread-safe in production, use Redis/Memcached)
_user_accounts = {}

def verify_exchange_credentials(auth_username, mailbox_email, password, server):
    """
    Verify Exchange credentials by attempting to connect.
    
    Args:
        auth_username: Username for authentication (e.g., 'okool_arfelous@rta.ae')
        mailbox_email: Email address of the mailbox (e.g., 'okool_ahmed.felous@rta.ae')
        password: Exchange password
        server: EWS server URL
    
    Returns: (is_valid: bool, error_message: str)
    """
    try:
        BaseProtocol.TIMEOUT = 30  # Shorter timeout for verification
        
        # CRITICAL: Use auth_username for Credentials, mailbox_email for Account
        creds = Credentials(username=auth_username, password=password)
        config = Configuration(server=server, credentials=creds)
        
        tz = pytz.timezone(getattr(Config, "TIMEZONE", "Asia/Dubai"))
        ews_tz = EWSTimeZone.from_pytz(tz)
        
        # Attempt to create account using mailbox email
        account = Account(
            primary_smtp_address=mailbox_email,  # Use mailbox email for mailbox access
            config=config,
            autodiscover=False,
            access_type=DELEGATE
        )
        account.default_timezone = ews_tz
        
        # Test access by fetching a single item (validates credentials and mailbox access)
        try:
            list(account.inbox.all()[:1])
        except Exception as test_error:
            logger.error(f"Inbox access test failed: {test_error}")
            return False, "Cannot access mailbox. Check permissions."
        
        logger.info(f"Successfully verified credentials for {mailbox_email} (auth: {auth_username})")
        return True, "Success"
        
    except UnauthorizedError as e:
        return False, "Invalid username or password"
    except ErrorAccessDenied as e:
        return False, "Access denied. Check mailbox permissions."
    except TransportError as e:
        return False, f"Connection error: {str(e)}"
    except Exception as e:
        logger.error(f"Credential verification failed: {e}", exc_info=True)
        return False, f"Verification failed: {str(e)}"


def get_user_account():
    """
    Get or create Exchange account for current logged-in user.
    Uses credentials from session (via auth routes).
    Handles separate authentication username and mailbox email.
    """
    if not has_request_context() or not current_user.is_authenticated:
        logger.error("No authenticated user in context")
        return None
    
    user_id = current_user.id
    
    # Check cache first
    if user_id in _user_accounts:
        return _user_accounts[user_id]
    
    # Import here to avoid circular dependency
    from routes.auth import get_current_user_credentials
    
    auth_username, mailbox_email, password, server = get_current_user_credentials()
    
    if not auth_username or not mailbox_email or not password or not server:
        logger.error(f"Missing credentials for user {current_user.email}")
        return None
    
    try:
        BaseProtocol.TIMEOUT = getattr(Config, 'CONNECTION_TIMEOUT', 300)
        
        # CRITICAL: Use auth_username for authentication, mailbox_email for mailbox
        creds = Credentials(username=auth_username, password=password)
        config = Configuration(server=server, credentials=creds)
        
        tz = pytz.timezone(getattr(Config, "TIMEZONE", "Asia/Dubai"))
        ews_tz = EWSTimeZone.from_pytz(tz)
        
        account = Account(
            primary_smtp_address=mailbox_email,  # Use mailbox email
            config=config,
            autodiscover=False,
            access_type=DELEGATE
        )
        account.default_timezone = ews_tz
        
        # Cache the account
        _user_accounts[user_id] = account
        
        logger.info(f"EWS Connected for user: {mailbox_email} (auth: {auth_username})")
        return account
        
    except Exception as e:
        logger.error(f"EWS Connection Failed for {mailbox_email}: {e}")
        return None


def clear_user_account_cache(user_id=None):
    """
    Clear cached account for a specific user or all users.
    Call this on logout or credential update.
    """
    global _user_accounts
    if user_id:
        _user_accounts.pop(user_id, None)
        logger.info(f"Cleared account cache for user {user_id}")
    else:
        _user_accounts.clear()
        logger.info("Cleared all account caches")


# Legacy compatibility: get_account() now uses current user
def get_account():
    """
    Get current user's Exchange account.
    Replaces old static account logic.
    """
    return get_user_account()


# Keep init_ews for backward compatibility, but deprecate it
def init_ews():
    """
    DEPRECATED: Use get_user_account() instead.
    This function is kept for backward compatibility but returns current user's account.
    """
    logger.warning("init_ews() is deprecated. Use get_user_account() instead.")
    return get_user_account()


# ===== ALL OTHER FUNCTIONS REMAIN THE SAME =====
# Just replace _account with get_account() calls

def fetch_emails(start_time, end_time):
    account = get_account()
    if not account: 
        raise Exception("EWS not connected - user not authenticated")
    
    # [Rest of original function unchanged...]
    try:
        ews_utc = EWSTimeZone.from_pytz(pytz.utc)

        def to_ews_datetime(dt):
            if not dt: return None
            if dt.tzinfo is None:
                return ews_utc.localize(dt)
            return dt.astimezone(ews_utc)

        start_time = to_ews_datetime(start_time)
        end_time = to_ews_datetime(end_time)
        
    except Exception as e:
        logger.warning(f"Timezone conversion warning: {e}")
    
    my_email = current_user.email.lower() if current_user.is_authenticated else ""
    max_emails = getattr(Config, 'MAX_EMAILS_PER_SYNC', 50)
    
    try:
        recent_items = account.inbox.filter(
            item_class='IPM.Note',
            datetime_received__range=(start_time, end_time)
        ).order_by('-datetime_received')[:max_emails]
        
        final_list = []
        for item in recent_items:
            if not isinstance(item, Message): continue
            is_for_me = False
            if item.to_recipients:
                for r in item.to_recipients:
                    if r.email_address and r.email_address.lower() == my_email:
                        is_for_me = True
                        break
            if is_for_me: final_list.append(item)
            
        return final_list
    except Exception as e:
        logger.error(f"Error filtering inbox: {e}")
        return []


def fetch_sent_emails(start_time, end_time):
    account = get_account()
    if not account: return []
    
    try:
        ews_utc = EWSTimeZone.from_pytz(pytz.utc)

        def to_ews_datetime(dt):
            if not dt: return None
            if dt.tzinfo is None:
                return ews_utc.localize(dt)
            return dt.astimezone(ews_utc)

        start_time = to_ews_datetime(start_time)
        end_time = to_ews_datetime(end_time)
    except Exception as e:
         pass 
    
    try:
        sent_items = account.sent.filter(
            item_class='IPM.Note',
            datetime_sent__range=(start_time, end_time)
        ).only(
            'message_id', 
            'in_reply_to', 
            'subject', 
            'body', 
            'text_body', 
            'datetime_sent',
            'to_recipients',
            'cc_recipients',
            'sender'
        ).order_by('-datetime_sent')[:50]
        
        return list(sent_items)
    except Exception as e:
        logger.error(f"Error fetching sent items: {e}")
        return []


def get_gal_details(email_address):
    account = get_account()
    if not account or not email_address: return None
    try:
        matches = account.protocol.resolve_names([email_address], return_full_contact_data=True)
        if not matches: return None
        
        candidate = matches[0]
        contact = None
        
        if isinstance(candidate, tuple):
             for item in candidate:
                 if isinstance(item, Contact):
                     contact = item
                     break
        elif isinstance(candidate, Contact):
            contact = candidate
        elif hasattr(candidate, 'email_address'): 
             pass

        if contact:
             return {
                'name': contact.display_name or contact.name,
                'job_title': getattr(contact, 'job_title', None),
                'department': getattr(contact, 'department', None),
                'office': getattr(contact, 'office_location', None),
                'manager': getattr(contact, 'manager', None) 
            }
            
        if hasattr(candidate, 'email_address') and candidate.email_address.lower() == email_address.lower():
             return {
                 'name': candidate.name,
                 'job_title': None, 'department': None, 'office': None, 'manager': None
             }

    except Exception as e:
        logger.warning(f"GAL Lookup failed for {email_address}: {e}")
    return None


def fetch_email_content(item_id, change_key=None):
    account = get_account()
    if not account: raise Exception("EWS not connected")
    
    item = None
    
    try:
        ck = change_key if change_key else ''
        items = list(account.fetch(ids=[(item_id, ck)]))
        if items and not isinstance(items[0], Exception):
            item = items[0]
    except Exception as e:
        pass

    if not item:
        try:
            inbox_matches = list(account.inbox.filter(message_id=item_id)[:1])
            if inbox_matches:
                found_item = inbox_matches[0]
                items = list(account.fetch(ids=[(found_item.id, found_item.changekey)]))
                if items and not isinstance(items[0], Exception):
                    item = items[0]
            else:
                sent_matches = list(account.sent.filter(message_id=item_id)[:1])
                if sent_matches:
                    found_item = sent_matches[0]
                    items = list(account.fetch(ids=[(found_item.id, found_item.changekey)]))
                    if items and not isinstance(items[0], Exception):
                        item = items[0]
        except Exception as e:
            logger.error(f"Search by Message-ID failed: {e}")

    if not item: 
        return None

    try:
        def format_recipients(recipients):
            if not recipients: return []
            return [{"name": r.name, "email": r.email_address} for r in recipients if r]

        attachments = []
        if item.attachments:
            for att in item.attachments:
                if isinstance(att, FileAttachment):
                    attachments.append({
                        "name": att.name,
                        "content_type": att.content_type,
                        "size": att.size,
                        "id": att.attachment_id.id 
                    })

        raw_body = item.body
        
        if isinstance(raw_body, bytes):
            try:
                raw_body = raw_body.decode('utf-8')
            except:
                raw_body = str(raw_body)
        elif isinstance(raw_body, Body) or isinstance(raw_body, HTMLBody):
             raw_body = str(raw_body)
             
        body_content = raw_body

        if not body_content:
             text_content = item.text_body or getattr(item, 'unique_body', '') or ""
             if text_content:
                 escaped_text = html.escape(text_content)
                 body_content = f"<html><body style='font-family: sans-serif;'><pre style='white-space: pre-wrap; word-wrap: break-word; font-family: inherit;'>{escaped_text}</pre></body></html>"
             else:
                 body_content = ""
        
        if not body_content and item.mime_content:
             try:
                 body_content = item.mime_content.decode('utf-8', errors='ignore')
             except:
                 pass

        return {
            "subject": item.subject,
            "sender": {"name": item.sender.name, "email": item.sender.email_address} if item.sender else {"name": "Unknown", "email": ""},
            "to": format_recipients(item.to_recipients),
            "cc": format_recipients(item.cc_recipients),
            "sent_at": item.datetime_sent.isoformat() if item.datetime_sent else None,
            "received_at": item.datetime_received.isoformat() if item.datetime_received else None,
            "body": str(body_content),
            "attachments": attachments
        }
    except Exception as e:
        logger.error(f"Error processing email content: {e}")
        raise e


def send_reply_email(item_id, body):
    account = get_account()
    if not account: raise Exception("EWS not connected")
    
    item = None
    
    try:
        items = list(account.fetch(ids=[(item_id, '')]))
        if items and not isinstance(items[0], Exception):
            item = items[0]
    except:
        pass
        
    if not item:
        try:
             inbox_matches = list(account.inbox.filter(message_id=item_id)[:1])
             if inbox_matches:
                 item = inbox_matches[0]
             else:
                 sent_matches = list(account.sent.filter(message_id=item_id)[:1])
                 if sent_matches:
                     item = sent_matches[0]
        except Exception as e:
            logger.error(f"Failed to find item for reply: {e}")
            
    if not item:
        raise Exception("Original email not found. Cannot send reply.")

    try:
        if not body: body = " "
        
        if "<" not in body:
            html_body = f"<html><body>{body.replace(chr(10), '<br>')}</body></html>"
        else:
            html_body = body
            
        reply_subject = item.subject
        if not reply_subject.lower().startswith('re:'):
            reply_subject = f"Re: {reply_subject}"

        reply_item = item.reply_all(
            subject=reply_subject,
            body=HTMLBody(html_body)
        )
        
        if hasattr(reply_item, 'send'):
            reply_item.send(save_copy=True)
        
        try:
            if not item.is_read:
                item.is_read = True
                item.save(update_fields=['is_read'])
        except Exception as read_err:
            logger.warning(f"Failed to mark email as read: {read_err}")
        
        return True
    except Exception as e:
        logger.error(f"EWS Reply Failed: {e}")
        raise e