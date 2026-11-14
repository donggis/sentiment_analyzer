"""
Email utility module for sending emails including password reset emails.
"""
from flask import render_template, current_app
from flask_mail import Mail, Message
from threading import Thread
import logging

class DisabledMail(Mail):
    """Private deployments never send legacy application email."""
    def send(self, message):
        raise RuntimeError('Outbound email is disabled for private deployment')

mail = DisabledMail()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_async_email(app, msg):
    """Send email asynchronously in a background thread."""
    try:
        with app.app_context():
            mail.send(msg)
            logger.info(f'Email sent successfully to {msg.recipients}')
    except Exception as e:
        # Log the error with more details
        logger.error(f'Failed to send email to {msg.recipients}: {str(e)}', exc_info=True)
        app.logger.error(f'Failed to send email to {msg.recipients}: {str(e)}')
        # Re-raise in development for debugging
        if app.config.get('DEBUG', False):
            raise


def send_email_sync(subject, sender, recipients, text_body, html_body):
    """
    Send an email synchronously (blocking). Use this for critical emails.
    
    Args:
        subject: Email subject
        sender: Sender email address
        recipients: List of recipient email addresses
        text_body: Plain text version of the email
        html_body: HTML version of the email
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        msg = Message(subject, sender=sender, recipients=recipients)
        msg.body = text_body
        msg.html = html_body
        
        mail.send(msg)
        logger.info(f'Email sent successfully to {recipients}')
        return True
        
    except Exception as e:
        logger.error(f'Failed to send email to {recipients}: {str(e)}', exc_info=True)
        current_app.logger.error(f'Failed to send email to {recipients}: {str(e)}')
        return False


def send_email(subject, sender, recipients, text_body, html_body, async_send=True):
    """
    Send an email with the given subject and body to the specified recipients.
    
    Args:
        subject: Email subject
        sender: Sender email address
        recipients: List of recipient email addresses
        text_body: Plain text version of the email
        html_body: HTML version of the email
        async_send: Whether to send asynchronously (default: True)
    
    Returns:
        bool: True if email was sent (or queued for async), False if sync send failed
    """
    if not async_send:
        return send_email_sync(subject, sender, recipients, text_body, html_body)
    
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    
    try:
        # Send email asynchronously to avoid blocking the request
        Thread(
            target=send_async_email,
            args=(current_app._get_current_object(), msg),
            daemon=True  # Daemon thread so it doesn't prevent shutdown
        ).start()
        logger.info(f'Email queued for sending to {recipients}')
        return True
    except Exception as e:
        logger.error(f'Failed to queue email to {recipients}: {str(e)}', exc_info=True)
        current_app.logger.error(f'Failed to queue email to {recipients}: {str(e)}')
        return False


def send_password_reset_email(user, use_sync=False):
    """
    Send a password reset email to the user.
    
    Args:
        user: User model instance
        use_sync: If True, send email synchronously (blocking)
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        token = user.get_reset_password_token()
        
        # Check if email configuration is available
        if not current_app.config.get('MAIL_DEFAULT_SENDER'):
            logger.error('MAIL_DEFAULT_SENDER not configured')
            return False
        
        success = send_email(
            subject='[Sentiment Analyzer] Reset Your Password',
            sender=current_app.config['MAIL_DEFAULT_SENDER'],
            recipients=[user.email],
            text_body=render_template('email/reset_password.txt',
                                       user=user, token=token),
            html_body=render_template('email/reset_password.html',
                                       user=user, token=token),
            async_send=not use_sync
        )
        
        if success:
            logger.info(f'Password reset email sent to {user.email}')
        else:
            logger.error(f'Failed to send password reset email to {user.email}')
            
        return success
        
    except Exception as e:
        logger.error(f'Error preparing password reset email for {user.email}: {str(e)}', exc_info=True)
        current_app.logger.error(f'Error preparing password reset email for {user.email}: {str(e)}')
        return False
