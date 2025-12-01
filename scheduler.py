import mysql.connector
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime
from config import Config
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Email Credentials
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "ramesramesh0724@gmail.com"
SENDER_PASSWORD = "mlcd zcrf lzrs nuwf"

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB
        )
        return connection
    except mysql.connector.Error as err:
        logger.error(f"Database connection error: {err}")
        return None

def send_email(to_email, username, password, start_date):
    subject = "Your WiFi Access Credentials"
    body = f"""
    Hello,

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
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

def process_scheduled_users():
    conn = get_db_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor(dictionary=True)
        today = datetime.now().date()
        
        # Find users whose start_date has arrived (or passed) and password hasn't been sent
        query = """
        SELECT id, full_name, email, username, password, start_date 
        FROM users 
        WHERE start_date IS NOT NULL 
        AND start_date <= %s 
        AND password_sent = FALSE
        AND is_deleted = FALSE
        """
        cursor.execute(query, (today,))
        users = cursor.fetchall()

        logger.info(f"Found {len(users)} users to process.")

        for user in users:
            logger.info(f"Processing user: {user['username']}")
            if send_email(user['email'], user['username'], user['password'], user['start_date']):
                # Update password_sent status
                update_query = "UPDATE users SET password_sent = TRUE WHERE id = %s"
                cursor.execute(update_query, (user['id'],))
                conn.commit()
                logger.info(f"Updated password_sent status for {user['username']}")
            else:
                logger.warning(f"Skipping status update for {user['username']} due to email failure.")

    except Exception as e:
        logger.error(f"Error processing users: {e}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    logger.info("Starting scheduler...")
    process_scheduled_users()
    logger.info("Scheduler finished.")
