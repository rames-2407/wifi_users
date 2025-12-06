#!/usr/bin/env python3
import mysql.connector
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime
from config import Config
import logging
import sys
import os

# Set up logging with file handler
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f'scheduler_{datetime.now().strftime("%Y%m%d")}.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Email Credentials
SMTP_SERVER = Config.SMTP_SERVER
SMTP_PORT = Config.SMTP_PORT
SENDER_EMAIL = Config.SENDER_EMAIL
SENDER_PASSWORD = Config.SENDER_PASSWORD

def get_db_connection():
    """Establish database connection with retry logic"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            connection = mysql.connector.connect(
                host=Config.MYSQL_HOST,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                database=Config.MYSQL_DB,
                connect_timeout=10
            )
            logger.info("Database connection established successfully")
            return connection
        except mysql.connector.Error as err:
            retry_count += 1
            logger.error(f"Database connection error (attempt {retry_count}/{max_retries}): {err}")
            if retry_count >= max_retries:
                return None
    return None

def send_email(to_email, username, password, start_date):
    """Send WiFi credentials via email"""
    subject = "WiFi Access Credentials"
    body = f"""Hello,

Your WiFi access has been scheduled to start from {start_date}.
Here are your login credentials:

Username: {username}
Password: {password}

Please login at the portal to access the internet.

Regards,
The Madras Seva Sadan
"""

    message = MIMEMultipart()
    message["From"] = formataddr(("The Madras Seva Sadan", SENDER_EMAIL))
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, message.as_string())
        server.quit()
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(f"SMTP authentication failed - check credentials")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email to {to_email}: {e}")
        return False

def process_scheduled_users():
    """Main function to process users scheduled for today"""
    conn = get_db_connection()
    if not conn:
        logger.critical("Failed to establish database connection. Exiting.")
        return False

    success = True
    cursor = None
    
    try:
        cursor = conn.cursor(dictionary=True)
        today = datetime.now().date()
        
        logger.info(f"Processing users for date: {today}")
        
        query = """
        SELECT id, full_name, email, username, password, start_date 
        FROM users 
        WHERE start_date IS NOT NULL 
        AND start_date <= %s 
        AND password_sent = FALSE
        """
        cursor.execute(query, (today,))
        users = cursor.fetchall()

        logger.info(f"Found {len(users)} users to process")

        if len(users) == 0:
            logger.info("No users to process today")
            return True

        successful_sends = 0
        failed_sends = 0

        for user in users:
            logger.info(f"Processing user: {user['username']} ({user['email']})")
            
            if send_email(user['email'], user['username'], user['password'], user['start_date']):
                try:
                    update_query = "UPDATE users SET password_sent = TRUE WHERE id = %s"
                    cursor.execute(update_query, (user['id'],))
                    conn.commit()
                    logger.info(f"Updated password_sent status for {user['username']}")
                    successful_sends += 1
                except mysql.connector.Error as e:
                    logger.error(f"Database update failed for {user['username']}: {e}")
                    conn.rollback()
                    failed_sends += 1
            else:
                logger.warning(f"Skipping status update for {user['username']} due to email failure")
                failed_sends += 1

        logger.info(f"Processing complete. Success: {successful_sends}, Failed: {failed_sends}")
        
        if failed_sends > 0:
            success = False

    except mysql.connector.Error as e:
        logger.error(f"Database error while processing users: {e}")
        success = False
    except Exception as e:
        logger.error(f"Unexpected error processing users: {e}")
        success = False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            logger.info("Database connection closed")
    
    return success

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting WiFi credentials scheduler")
    logger.info("=" * 60)
    
    try:
        success = process_scheduled_users()
        
        if success:
            logger.info("Scheduler completed successfully")
            sys.exit(0)
        else:
            logger.error("Scheduler completed with errors")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.warning("Scheduler interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("=" * 60)
        logger.info("Scheduler finished")
        logger.info("=" * 60)