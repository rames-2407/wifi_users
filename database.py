import mysql.connector
from mysql.connector import Error
import uuid
from flask import session
import string
import secrets
from datetime import datetime
from config import Config
import traceback
from datetime import datetime, timedelta
import logging

# Set up logging
logger = logging.getLogger(__name__)

def get_db_connection():
    """Get MySQL database connection"""
    try:
        connection = mysql.connector.connect(
            host= Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database= Config.MYSQL_DB
        )
        return connection
    except mysql.connector.Error as err:
        logger.error(f"Database connection error: {err}")
        return None
    
def radius_db_connection():
    try:
        connection = mysql.connector.connect(
            host= Config.RADIUS_DB_HOST,
            user=Config.RADIUS_DB_USER,
            password=Config.RADIUS_DB_PASSWORD,
            database= Config.RADIUS_DB_NAME
        )
        return connection
    except mysql.connector.Error as err:
        logger.error(f"RADIUS database connection error: {err}")

def generate_username(full_name):

    parts = full_name.lower().strip().split()
    first = parts[0][:6] if parts else 'user'
    last_initial = parts[1][0] if len(parts) > 1 else ''
    timestamp = datetime.now().strftime('%H%M%S')[1:]  
    random_part = str(uuid.uuid4().int)[:2] 
    return f"{first}{last_initial}{timestamp}{random_part}"

def generate_password(length=10):
    """Generate strong password"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def convert_mbps_to_bits(mbps):
    """Convert Mbps to bits per second"""
    return mbps * 1000000

def convert_hours_to_seconds(hours):
    """Convert hours to seconds"""
    return int(hours * 3600)

class DatabaseManager:
    
    @staticmethod
    def save_user(full_name, email, mobile, mac_address, network, username, password,
                bandwidth, expiration_hours, start_date=None, end_date=None,
                time_interval=None, no_of_devices=None, password_sent=None):

        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()

            # If scheduled access, expiration_hours not needed
            if start_date and end_date:
                expiration_hours = None

            query = """
            INSERT INTO users (
                full_name, email, mobile, network,
                username, password, bandwidth_mbps, expiration_hours,
                is_active, created_by, start_date, end_date,
                time_interval, no_of_devices, password_sent
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(query, (
                full_name, email, mobile, network,
                username, password, bandwidth, expiration_hours,
                True, session.get('admin_email'),
                start_date, end_date, time_interval, no_of_devices, password_sent
            ))

            connection.commit()
            logger.info(f"User {username} saved successfully!")
            return True
        except Exception as e:
            logger.error(f"Error saving user: {e}")
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()


    @staticmethod
    def get_all_users_all_admins():
        connection = get_db_connection()
        if not connection:
            return []

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error: {e}")
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
     
    @staticmethod
    def get_all_users(admin_email):
        connection = get_db_connection()
        if not connection:
            return []
        
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE created_by = %s and is_deleted=FALSE",(admin_email,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error fetching users: {e}")
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_users_by_network(admin_email, network):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM users 
            WHERE created_by=%s AND network=%s AND is_deleted=FALSE
            ORDER BY created_at DESC
        """, (admin_email, network))
        data = cursor.fetchall()
        cursor.close()
        conn.close()

        return data

    
    @staticmethod
    def search_users(search, admin_email, network):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        patt = f"%{search}%"
        cursor.execute("""
            SELECT * FROM users 
        WHERE created_by = %s AND network = %s 
        AND (username LIKE %s OR email LIKE %s)
        ORDER BY created_at DESC
    """, (admin_email, network, patt, patt))
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        return data

    
    @staticmethod
    def delete_user(user_id, hard_delete=False):
        """Delete user and RADIUS entries"""
        connection = get_db_connection()
        if not connection:
            return False
        
        try:
            cursor = connection.cursor()
            
            cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            result = cursor.fetchone()
            if not result:
                return False
            
            username = result[0]

            if hard_delete:
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
                logger.info(f"Deleting user {username} from wifi_portal")
                connection.commit()

                logger.info(f"Deleted user {username} from wifi_portal")
                success = RadiusManager.delete_user_from_radius(username)
                if not success:
                    logger.warning(f"Failed to delete user {username} from RADIUS DB")

            else:
                cursor.execute("UPDATE users SET is_deleted = TRUE WHERE id = %s", (user_id,))
                logger.info(f"Soft-deleted user {username} (hidden from Admin dashboard)")
                connection.commit()

            return True
        except Exception as e:
            logger.error(f"Error deleting user from wifi_portal: {e}")
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_guest_users():
        conn = mysql.connector.connect(**Config.EXTERNAL_DB_CONFIG) 
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, email, mobile, username, password FROM user_auth")
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        return users

    @staticmethod
    def get_user_details(user_id):
        connection = get_db_connection()
        if not connection:
            return []
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT name,created_at FROM all_users WHERE users_id=%s",(user_id,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error fetching users: {e}")
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def get_users_with_count():
        """
        Fetches primary user details along with the count of their sub-registrations 
        using a single, efficient SQL query.
        """
        conn = mysql.connector.connect(**Config.EXTERNAL_DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        
        # SQL Query using LEFT JOIN and COUNT()
        query = """
            SELECT 
                ua.name, 
                ua.email, 
                ua.mobile, 
                ua.id AS user_id, 
                COUNT(au.id) AS sub_user_count
            FROM 
                user_auth ua
            LEFT JOIN 
                all_users au ON ua.id = au.users_id
            GROUP BY 
                ua.id, ua.name, ua.email, ua.mobile;
        """
        
        try:
            cursor.execute(query)
            users_with_counts = cursor.fetchall()
            return users_with_counts
        except Exception as e:
            # Handle potential SQL errors
            logger.error(f"Error fetching users with counts: {e}")
            return []
        finally:
            # Ensure connection is closed
            cursor.close()
            conn.close()

    @staticmethod
    def sync_user_auth_to_all_users():
        """
        Synchronizes users from user_auth to all_users.
        If a user exists in user_auth but not in all_users, insert them.
        """
        conn = mysql.connector.connect(**Config.EXTERNAL_DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        
        try:
            # 1. Get all users from user_auth
            cursor.execute("SELECT id, name, created_at FROM user_auth")
            auth_users = cursor.fetchall()
            
            # 2. Get all user IDs from all_users
            cursor.execute("SELECT users_id FROM all_users")
            existing_users = {row['users_id'] for row in cursor.fetchall()}
            
            # 3. Find missing users and insert them
            users_to_insert = []
            for user in auth_users:
                if user['id'] not in existing_users:
                    # Handle created_at being None or string
                    created_at = user['created_at']
                    if not created_at:
                        created_at = datetime.now()
                    
                    users_to_insert.append((
                        user['id'], 
                        user['name'], 
                        created_at
                    ))
            
            if users_to_insert:
                insert_query = """
                    INSERT INTO all_users (users_id, name, created_at)
                    VALUES (%s, %s, %s)
                """
                cursor.executemany(insert_query, users_to_insert)
                conn.commit()
                logger.info(f"Synced {len(users_to_insert)} users from user_auth to all_users")
                
        except Exception as e:
            logger.error(f"Error syncing users: {e}")
            conn.rollback()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()


class RadiusManager:   

    @staticmethod
    def get_connection():
        """Get RADIUS database connection with detailed error handling"""
        try:
            connection = mysql.connector.connect(
                host="192.168.9.239",
                user="radius",
                password="Str0ngR@diusPass",
                database="radius",
                port=3306,
                connection_timeout=10,
                autocommit=False
            )
            if connection.is_connected():
                logger.info(f"Successfully connected to RADIUS database")
                return connection
            else:
                logger.error("Failed to connect to RADIUS database")
                return None
        except Error as e:
            logger.error(f"Database connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected connection error: {e}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return None
    
    @staticmethod
    def add_user_auth(username, password):
        """Add user to radcheck table with detailed logging"""
        logger.info(f"Adding user auth for: {username}")
        connection = RadiusManager.get_connection()
        if not connection:
            logger.error("Failed to get database connection for add_user_auth")
            return False

        try:
            cursor = connection.cursor()

            # Check if user already exists
            cursor.execute("SELECT COUNT(*) FROM radcheck WHERE username = %s", (username,))
            exists = cursor.fetchone()[0]
            if exists > 0:
                logger.warning(f"User {username} already exists in radcheck")
                return False

            query = """
            INSERT INTO radcheck (username, attribute, op, value)
            VALUES (%s, 'Cleartext-Password', ':=', %s)
            """
            logger.debug(f"Executing query: {query} with values: ({username}, {password})")
            cursor.execute(query, (username, password))
            connection.commit()
            logger.info(f"Successfully added user {username} to radcheck")
            return True

        except Error as e:
            logger.error(f"MySQL Error adding to radcheck: {e}")
            connection.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error adding to radcheck: {e}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
                logger.debug("Database connection closed for add_user_auth")

    @staticmethod
    def add_radius_controls(username, expiration_hours=None, start_time=None, end_time=None, end_datetime=None):
        """Manage all RADIUS access rules: Expiration, Session-Timeout, Login-Time"""
        
        logger.info(f"Applying RADIUS rules for {username}")

        connection = RadiusManager.get_connection()
        if not connection:
            logger.error("Failed DB connection")
            return False

        try:
            cursor = connection.cursor()

            # 1️⃣ Session Timeout (Hours → Seconds)
            if expiration_hours:
                session_seconds = int(float(expiration_hours) * 3600)
                cursor.execute("""
                    INSERT INTO radcheck (username, attribute, op, value)
                    VALUES (%s, 'Session-Timeout', ':=', %s)
                """, (username, session_seconds))
                logger.info(f"Session-Timeout: {session_seconds}")

            # 2️⃣ Expiration when date-time provided
            if end_datetime:
                expiry_dt = datetime.strptime(end_datetime, "%Y-%m-%dT%H:%M")
                expiry_formatted = expiry_dt.strftime("%d %b %Y %H:%M")

                cursor.execute("""
                    INSERT INTO radcheck (username, attribute, op, value)
                    VALUES (%s, 'Expiration', ':=', %s)
                """, (username, expiry_formatted))
                logger.info(f"Expiration: {expiry_formatted}")

            # 3️⃣ Login-Time based on interval
            if start_time and end_time:
                lt_value = f"Al{start_time.replace(':','')}-{end_time.replace(':','')}"
            else:
                lt_value = "Al0000-2400"

            cursor.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, 'Login-Time', ':=', %s)
            """, (username, lt_value))
            logger.info(f"Login-Time: {lt_value}")

            connection.commit()
            return True

        except Exception as e:
            logger.error(f"RADIUS Error: {e}")
            connection.rollback()
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def add_user_bandwidth(username, bandwidth_bits):
        """Add only bandwidth limit to radreply table"""
        logger.info(f"Adding bandwidth limit for: {username}")
        logger.debug(f"Bandwidth: {bandwidth_bits} bits")

        connection = RadiusManager.get_connection()
        if not connection:
            logger.error("Failed to get database connection for add_user_bandwidth")
            return False

        try:
            cursor = connection.cursor()

            # Add bandwidth limit (download) to radreply
            query = """
            INSERT INTO radreply (username, attribute, op, value)
            VALUES (%s, 'WISPr-Bandwidth-Max-Down', ':=', %s)
            """
            logger.debug(f"Executing bandwidth query: {query}")
            cursor.execute(query, (username, str(bandwidth_bits)))

            connection.commit()
            logger.info(f"Successfully added bandwidth limit for user {username}")
            return True

        except Error as e:
            logger.error(f"MySQL Error adding bandwidth: {e}")
            connection.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error adding bandwidth: {e}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
                logger.debug("Database connection closed for add_user_bandwidth")

    @staticmethod
    def add_user_network(username, network):
        """Add User to the radusergroup table"""
        logger.info(f"Adding network for: {username}")
        logger.debug(f"Assigned Network: {network}")

        connection = RadiusManager.get_connection()
        if not connection:
            logger.error("Failed to get database connection for add_user_network")
            return False

        try:
            cursor = connection.cursor()

            query = """
            INSERT INTO radusergroup (username, groupname, priority)
            VALUES (%s,%s,'0')
            """
            logger.debug(f"Executing network query: {query}")
            cursor.execute(query, (username, network))

            connection.commit()
            logger.info(f"Successfully added network for user {username}")
            return True

        except Error as e:
            logger.error(f"MySQL Error adding network: {e}")
            connection.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error adding network: {e}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
                logger.debug("Database connection closed for add_user_network")


    @staticmethod
    def create_user_complete(username, password, bandwidth_mbps, expiration_hours):
        """Create a complete user with auth, expiration, and bandwidth"""
        logger.info(f"Creating complete user: {username}")

        # Add authentication
        if not RadiusManager.add_user_auth(username, password):
            logger.error(f"Failed to add authentication for {username}")
            return False

        # Add expiration timeout
        if not RadiusManager.add_user_expiration(username, expiration_hours):
            logger.error(f"Failed to add expiration for {username}")
            # Cleanup: remove auth entry
            RadiusManager.delete_user_from_radius(username)
            return False

        # Add bandwidth limit
        bandwidth_bits = bandwidth_mbps * 1024 * 1024  # Convert Mbps to bits
        if not RadiusManager.add_user_bandwidth(username, bandwidth_bits):
            logger.error(f"Failed to add bandwidth for {username}")
            # Cleanup: remove auth and expiration entries
            RadiusManager.delete_user_from_radius(username)
            return False

        logger.info(f"Successfully created complete user: {username}")
        return True

    @staticmethod
    def delete_user_from_radius(username):
        """Delete user from radcheck,radreply and radusergroup table"""
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()

            # Delete from radcheck
            cursor.execute("DELETE FROM radcheck WHERE username = %s", (username,))
            logger.info(f"Deleted {username} from radcheck")

            # Delete from radreply
            cursor.execute("DELETE FROM radreply WHERE username = %s", (username,))
            logger.info(f"Deleted {username} from radreply")

            # Delete from radusergroup
            cursor.execute("DELETE FROM radusergroup WHERE username = %s", (username,))
            logger.info(f"Deleted {username} from radusergroup")

            connection.commit()
            return True

        except Exception as e:
            logger.error(f"Error deleting user {username} from RADIUS DB: {e}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()


    @staticmethod
    def get_user_expiration(username):
        """Get user expiration date"""
        connection = RadiusManager.get_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor()
            query = """
            SELECT value FROM radcheck
            WHERE username = %s AND attribute = 'Expiration'
            """
            cursor.execute(query, (username,))
            result = cursor.fetchone()

            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting expiration: {e}")
            return None
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def update_user_expiration(username, new_expiration_hours):
        """Update user expiration"""
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()

            # Calculate new expiration date
            new_expiration_date = datetime.now() + timedelta(hours=new_expiration_hours)
            expiration_string = new_expiration_date.strftime("%B %d %Y %H:%M:%S")

            # Update expiration in radcheck
            query = """
            UPDATE radcheck SET value = %s
            WHERE username = %s AND attribute = 'Expiration'
            """
            cursor.execute(query, (expiration_string, username))
            connection.commit()

            logger.info(f"Updated expiration for {username} to: {expiration_string}")
            return True
        except Exception as e:
            logger.error(f"Error updating expiration: {e}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def authenticate_user(username, password):
        """Authenticate user against RADIUS"""
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            query = """
            SELECT value FROM radcheck
            WHERE username = %s AND attribute = 'Cleartext-Password'
            """
            cursor.execute(query, (username,))
            result = cursor.fetchone()

            return result and result[0] == password
        except Exception as e:
            logger.error(f"Error authenticating: {e}")
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

    @staticmethod
    def check_user_expired(username):
        """Check if user account has expired"""
        expiration_str = RadiusManager.get_user_expiration(username)
        if not expiration_str:
            return False

        try:
            expiration_date = datetime.strptime(expiration_str, "%B %d %Y %H:%M:%S")
            current_date = datetime.now()

            return current_date > expiration_date
        except Exception as e:
            logger.error(f"Error checking expiration: {e}")
            return False

