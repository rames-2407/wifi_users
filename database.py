import mysql.connector
from mysql.connector import Error
import uuid
from flask import session
import string
import secrets
from datetime import datetime, timedelta
from config import Config
import traceback
import logging
import os

# ---------------------- LOGGING SETUP ---------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "log")
os.makedirs(LOG_DIR, exist_ok=True)

log_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

db_log_path = os.path.join(LOG_DIR, "db.log")
db_error_log_path = os.path.join(LOG_DIR, "db_error.log")

db_file_handler = logging.FileHandler(db_log_path)
db_file_handler.setFormatter(log_formatter)
db_file_handler.setLevel(logging.INFO)

db_error_handler = logging.FileHandler(db_error_log_path)
db_error_handler.setFormatter(log_formatter)
db_error_handler.setLevel(logging.ERROR)

logger = logging.getLogger("DatabaseManager")
logger.setLevel(logging.DEBUG)
logger.addHandler(db_file_handler)
logger.addHandler(db_error_handler)
# ----------------------------------------------------------- #


def get_db_connection():
    """Get MySQL database connection"""
    try:
        connection = mysql.connector.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DB
        )
        if connection.is_connected():
            logger.debug("Connected to MySQL Portal DB")
        return connection
    except Error as err:
        logger.error(f"Portal DB connection error: {err}")
        return None


def radius_db_connection():
    """Connection for RADIUS DB if needed"""
    try:
        connection = mysql.connector.connect(
            host=Config.RADIUS_DB_HOST,
            user=Config.RADIUS_DB_USER,
            password=Config.RADIUS_DB_PASSWORD,
            database=Config.RADIUS_DB_NAME
        )
        logger.debug("Connected to RADIUS DB (legacy method)")
        return connection
    except Error as err:
        logger.error(f"Legacy Radius DB connection error: {err}")
        return None


def generate_username(full_name):
    parts = full_name.lower().strip().split()
    first = parts[0][:6] if parts else 'user'
    last_initial = parts[1][0] if len(parts) > 1 else ''
    timestamp = datetime.now().strftime('%H%M%S')[1:]
    random_part = str(uuid.uuid4().int)[:2]
    username = f"{first}{last_initial}{timestamp}{random_part}"
    logger.info(f"Generated username: {username}")
    return username


def generate_password(length=10):
    alphabet = string.ascii_letters + string.digits
    pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
    logger.debug("Generated password")
    return pwd


def convert_mbps_to_bits(mbps):
    return mbps * 1000000


def convert_hours_to_seconds(hours):
    return int(hours * 3600)


class DatabaseManager:

    @staticmethod
    def save_user(full_name, email, mobile, network, username, password,
                  bandwidth, expiration_hours, start_date=None, end_date=None,
                  time_interval=None, no_of_devices=None, password_sent=None):

        logger.info(f"Saving user into Portal DB: {username}")
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            query = """
                INSERT INTO users (
                    full_name, email, mobile, network,
                    username, password, bandwidth_mbps, expiration_hours,
                    is_active, created_by, start_date, end_date,
                    time_interval, no_of_devices, password_sent
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(query, (
                full_name, email, mobile, network,
                username, password, bandwidth, expiration_hours,
                True, session.get('admin_email'),
                start_date, end_date, time_interval, no_of_devices, password_sent
            ))

            connection.commit()
            logger.info(f"User saved successfully: {username}")
            return True

        except Exception as e:
            logger.error(f"Error saving user {username}: {e}")
            logger.debug(traceback.format_exc())
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def get_all_users_all_admins():
        logger.debug("Fetching all users regardless of admin")
        connection = get_db_connection()
        if not connection:
            return []

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
            users = cursor.fetchall()
            logger.info(f"Fetched {len(users)} users")
            return users

        except Exception as e:
            logger.error(f"Error fetching users: {e}")
            return []

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def get_all_users(admin_email):
        logger.debug(f"Fetching users created by admin: {admin_email}")
        connection = get_db_connection()
        if not connection:
            return []

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE created_by = %s AND is_deleted=FALSE", (admin_email,))
            users = cursor.fetchall()
            logger.info(f"Admin {admin_email} -> fetched {len(users)} user(s)")
            return users

        except Exception as e:
            logger.error(f"Error fetching admin users: {e}")
            return []

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def get_users_by_network(admin_email, network):
        logger.debug(f"Fetching users | admin={admin_email} | network={network}")
        connection = get_db_connection()
        if not connection:
            return []

        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM users
                WHERE created_by=%s AND network=%s AND is_deleted=FALSE
                ORDER BY created_at DESC
            """, (admin_email, network))
            users = cursor.fetchall()
            logger.info(f"Users fetched from network {network}: {len(users)}")
            return users

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def search_users(search, admin_email, network):
        logger.info(f"User search -> '{search}' | Network={network}")
        connection = get_db_connection()
        if not connection:
            return []

        try:
            patt = f"%{search}%"
            cursor = connection.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM users
                WHERE created_by = %s AND network = %s AND
                (username LIKE %s OR email LIKE %s)
                ORDER BY created_at DESC
            """, (admin_email, network, patt, patt))
            res = cursor.fetchall()
            logger.info(f"Search result count: {len(res)}")
            return res

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def delete_user(user_id, hard_delete=False):
        """Soft delete or full removal with RADIUS"""
        logger.info(f"Delete request -> ID={user_id}, hard={hard_delete}")
        connection = get_db_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            result = cursor.fetchone()

            if not result:
                logger.warning("User not found during delete")
                return False

            username = result[0]
            logger.info(f"Deleting user: {username}")

            if hard_delete:
                cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
                connection.commit()
                logger.warning(f"Hard deleted Portal User: {username}")
            else:
                cursor.execute("UPDATE users SET is_deleted=TRUE WHERE id=%s", (user_id,))
                connection.commit()
                logger.info(f"Soft deleted user (hidden): {username}")

            return True

        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def get_guest_users():
        logger.debug("Fetching GUEST portal users")
        conn = mysql.connector.connect(**Config.EXTERNAL_DB_CONFIG)
        cursor = conn.cursor(buffered = True,dictionary=True)

        cursor.execute("SELECT id AS users_id, email, mobile, username FROM user_auth")
        data = cursor.fetchall()

        cursor.close()
        conn.close()
        logger.info(f"GUEST users count: {len(data)}")
        return data

    @staticmethod
    def get_user_details(user_id):
        logger.info(f"Fetching USER details: {user_id}")
        conn = None
        cursor = None

        try:
            conn = mysql.connector.connect(**Config.EXTERNAL_DB_CONFIG)
            cursor = conn.cursor(buffered=True,dictionary=True)

            cursor.execute("""
                SELECT
                    ua.id,
                    COALESCE(au.name, ua.username) AS full_name,
                    ua.username,
                    ua.email,
                    ua.mobile,
                    ua.created_at
                FROM user_auth ua
                LEFT JOIN all_users au ON ua.id = au.users_id
                WHERE ua.id = %s OR ua.username = %s
            """, (user_id, user_id))

            primary = cursor.fetchone()
            if not primary:
                logger.warning(f"No user found: {user_id}")
                return None

            cursor.execute("""
                SELECT name, email, mobile, created_at
                FROM all_users
                WHERE users_id = %s ORDER BY created_at DESC
            """, (primary['id'],))

            subs = cursor.fetchall() or []
            logger.info(f"Found {len(subs)} sub-users for {primary['username']}")

            return {
                "primary_user": primary,
                "sub_users": subs,
                "total_count": len(subs)
            }

        except Exception as e:
            logger.error(f"Error fetching user details: {e}")
            logger.debug(traceback.format_exc())
            return None

        finally:
            try:
                if cursor:
                    cursor.close()
            except:
                pass
            try:
                if conn and conn.is_connected():
                    conn.close()
            except:
                pass

    @staticmethod
    def get_users_with_count():
        logger.debug("Counting guest sub-users")
        conn = mysql.connector.connect(**Config.EXTERNAL_DB_CONFIG)
        cursor = conn.cursor(dictionary=True,buffered=True)

        query = """
            SELECT ua.username, ua.email, ua.mobile, ua.id AS user_id,
                   COUNT(au.id) AS sub_user_count
            FROM user_auth ua
            LEFT JOIN all_users au ON ua.id = au.users_id
            GROUP BY ua.id
        """

        try:
            cursor.execute(query)
            rows = cursor.fetchall()
            logger.info(f"Counted {len(rows)} user(s) with sub-user count")
            return rows

        except Exception as e:
            logger.error(f"Count query failed: {e}")
            return []

        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def sync_user_auth_to_all_users():
        logger.info("Syncing guest users to all_users table")
        try:
            conn = mysql.connector.connect(**Config.EXTERNAL_DB_CONFIG)
            cursor = conn.cursor(buffered=True,dictionary=True)

            cursor.execute("SELECT id, username, created_at FROM user_auth")
            auth_users = cursor.fetchall()

            cursor.execute("SELECT users_id FROM all_users")
            existing = {u['users_id'] for u in cursor.fetchall()}

            to_insert = []
            for u in auth_users:
                if u['id'] not in existing:
                    created = u['created_at'] or datetime.now()
                    to_insert.append((u['id'], u['username'], created))

            if to_insert:
                cursor.executemany("""
                    INSERT INTO all_users (users_id, name, created_at)
                    VALUES (%s, %s, %s)
                """, to_insert)
                conn.commit()

                logger.info(f"Inserted {len(to_insert)} missing guest users")

            else:
                logger.info("No missing records to sync")

        except Exception as e:
            logger.error(f"Failed sync: {e}")
            logger.debug(traceback.format_exc())

        finally:
            try:
                cursor.close()
                conn.close()
            except:
                pass


# ---------------------- RADIUS MANAGER ---------------------- #
class RadiusManager:

    @staticmethod
    def get_connection():
        try:
            conn = mysql.connector.connect(
                host="192.168.9.239",
                user="radius",
                password="Str0ngR@diusPass",
                database="radius",
                port=3306,
                connection_timeout=10
            )
            logger.debug("Connected to RADIUS database")
            return conn

        except Exception as e:
            logger.error(f"Radius DB connection error: {e}")
            logger.debug(traceback.format_exc())
            return None

    @staticmethod
    def add_user_auth(username, password):
        logger.info(f"RADIUS -> Add auth for: {username}")
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()

            cursor.execute("SELECT COUNT(*) FROM radcheck WHERE username=%s", (username,))
            if cursor.fetchone()[0] > 0:
                logger.warning(f"RADIUS auth exists: {username}")
                return False

            cursor.execute("""
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, 'Cleartext-Password', ':=', %s)
            """, (username, password))

            connection.commit()
            logger.info(f"Auth added -> {username}")
            return True

        except Exception as e:
            logger.error(f"Error adding RADIUS auth: {e}")
            connection.rollback()
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def add_radius_controls(username, expiration_hours=None, start_time=None, end_time=None, end_datetime=None):
        logger.info(f"RADIUS -> Add controls: {username}")
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()

            if expiration_hours:
                seconds = int(float(expiration_hours)) * 3600
                cursor.execute("""
                    INSERT INTO radreply (username, attribute, op, value)
                    VALUES (%s, 'Session-Timeout', ':=', %s)
                """, (username, seconds))

            if end_datetime:
                dt = datetime.strptime(end_datetime, "%Y-%m-%dT%H:%M")
                expiry_dt = dt.strftime("%d %b %Y %H:%M")
                cursor.execute("""
                    INSERT INTO radreply (username, attribute, op, value)
                    VALUES (%s, 'Expiration', ':=', %s)
                """, (username, expiry_dt))

            lt_value = f"Al{start_time.replace(':','')}-{end_time.replace(':','')}" if start_time and end_time else "Al0000-2400"

            cursor.execute("""
                INSERT INTO radreply (username, attribute, op, value)
                VALUES (%s, 'Login-Time', ':=', %s)
            """, (username, lt_value))

            connection.commit()
            logger.info(f"Controls added -> {username}")
            return True

        except Exception as e:
            logger.error(f"Control error: {e}")
            connection.rollback()
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def add_user_bandwidth(username, bandwidth_bits):
        logger.info(f"Add bandwidth -> {bandwidth_bits} bits | User={username}")
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            cursor.execute("""
                INSERT INTO radreply (username, attribute, op, value)
                VALUES (%s, 'WISPr-Bandwidth-Max-Down', ':=', %s)
            """, (username, str(bandwidth_bits)))

            cursor.execute("""
                INSERT INTO radreply (username, attribute, op, value)
                VALUES (%s, 'WISPr-Bandwidth-Max-Up', ':=', %s)
            """, (username, str(bandwidth_bits)))

            connection.commit()
            return True

        except Exception as e:
            logger.error(f"Bandwidth add failed: {e}")
            connection.rollback()
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def no_of_devices(username, no_of_devices):
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()

            query = """
                INSERT INTO radcheck (username, attribute, op, value)
                VALUES (%s, 'Simultaneous-Use', ':=', %s)
                ON DUPLICATE KEY UPDATE value = VALUES(value)
            """

            cursor.execute(query, (username, str(no_of_devices)))
            connection.commit()
            return True

        except Exception as e:
            logger.error(f"no_of_devices add failed: {e}")
            connection.rollback()
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def add_user_network(username, network):
        logger.info(f"Add network group -> {username} => {network}")
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            cursor.execute("""
                INSERT INTO radusergroup (username, groupname, priority)
                VALUES (%s,%s,'0')
            """, (username, network))

            connection.commit()
            return True

        except Exception as e:
            logger.error(f"Network add failed: {e}")
            connection.rollback()
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def delete_user_from_radius(username):
        logger.warning(f"RADIUS -> Delete user: {username}")
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM radcheck WHERE username=%s", (username,))
            cursor.execute("DELETE FROM radreply WHERE username=%s", (username,))
            cursor.execute("DELETE FROM radusergroup WHERE username=%s", (username,))
            connection.commit()
            return True

        except Exception as e:
            logger.error(f"Delete failed: {e}")
            connection.rollback()
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def get_user_expiration(username):
        logger.debug(f"Fetching expiration -> {username}")
        connection = RadiusManager.get_connection()
        if not connection:
            return None

        try:
            cursor = connection.cursor()
            cursor.execute("""
                SELECT value FROM radcheck WHERE username=%s AND attribute='Expiration'
            """, (username,))
            result = cursor.fetchone()
            return result[0] if result else None

        except Exception as e:
            logger.error(f"Expiration fetch failed: {e}")
            return None

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def authenticate_user(username, password):
        logger.debug(f"Auth check -> {username}")
        connection = RadiusManager.get_connection()
        if not connection:
            return False

        try:
            cursor = connection.cursor()
            cursor.execute("""
                SELECT value FROM radcheck WHERE username=%s AND attribute='Cleartext-Password'
            """, (username,))
            result = cursor.fetchone()
            return result and result[0] == password

        except Exception as e:
            logger.error(f"Auth error: {e}")
            return False

        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def check_user_expired(username):
        exp = RadiusManager.get_user_expiration(username)
        if not exp:
            return False

        try:
            exp_dt = datetime.strptime(exp, "%d %b %Y %H:%M")
            expired = datetime.now() > exp_dt
            logger.info(f"Expire check -> User={username}, Expired={expired}")
            return expired

        except Exception as e:
            logger.error(f"Expiration check error: {e}")
            return False