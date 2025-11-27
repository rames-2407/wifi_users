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
        print(f"Database connection error: {err}")
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
        print(f"RADIUS database connection error: {err}")

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
    def save_user(full_name, email, mobile, mac_address, network, username, password, bandwidth, expiration_hours):
        """Save user to database"""
        connection = get_db_connection()
        if not connection:
            return False
        
        try:
            cursor = connection.cursor()
            query = """
            INSERT INTO users (full_name, email, mobile, mac_address,network, username, password, bandwidth_mbps, expiration_hours,is_active,created_by)
            VALUES (%s, %s, %s, %s, %s,%s, %s, %s, %s,%s,%s)
            """
            cursor.execute(query, (full_name, email, mobile, mac_address,network, username, password, bandwidth, expiration_hours,True,session.get('admin_email')))
            connection.commit()
            print(f"User {username} saved successfully to wifi_portal")
            return True
        except Exception as e:
            print(f"Error saving user: {e}")
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
            print(f"Error: {e}")
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
            print(f"Error fetching users: {e}")
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    
    @staticmethod
    def search_users(search_term):
        connection = get_db_connection()
        if not connection:
            return []
        
        try:
            cursor = connection.cursor(dictionary=True)
            query = """
            SELECT * FROM users 
            WHERE username LIKE %s OR email LIKE %s OR mac_address LIKE %s
            ORDER BY created_at DESC
            """
            pattern = f"%{search_term}%"
            cursor.execute(query, (pattern, pattern, pattern))
            return cursor.fetchall()
        except Exception as e:
            print(f"Error searching users: {e}")
            return []
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    
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
                print(f"deleting user {username} from wifi_portal")
                connection.commit()

                print(f"Deleted user {username} from wifi_portal")
                success = RadiusManager.delete_user_from_radius(username)
                if not success:
                    print(f"Failed to delete user {username} from RADIUS DB")

            else:
                cursor.execute("UPDATE users SET is_deleted = TRUE WHERE id = %s", (user_id,))
                print(f"Soft-deleted user {username} (hidden from Admin dashboard)")
                connection.commit()

            return True
        except Exception as e:
            print(f"Error deleting user from wifi_portal: {e}")
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

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
                print(f"Successfully connected to RADIUS database")
                return connection
            else:
                print("Failed to connect to RADIUS database")
                return None
        except Error as e:
            print(f"Database connection error: {e}")
            return None
        except Exception as e:
            print(f"Unexpected connection error: {e}")
            print(f"Full traceback: {traceback.format_exc()}")
            return None
    
    @staticmethod
    def add_user_auth(username, password):
        """Add user to radcheck table with detailed logging"""
        print(f"Adding user auth for: {username}")
        connection = RadiusManager.get_connection()
        if not connection:
            print("Failed to get database connection for add_user_auth")
            return False
        
        try:
            cursor = connection.cursor()
            
            # Check if user already exists
            cursor.execute("SELECT COUNT(*) FROM radcheck WHERE username = %s", (username,))
            exists = cursor.fetchone()[0]
            if exists > 0:
                print(f"User {username} already exists in radcheck")
                return False
            
            query = """
            INSERT INTO radcheck (username, attribute, op, value) 
            VALUES (%s, 'Cleartext-Password', ':=', %s)
            """
            print(f"Executing query: {query} with values: ({username}, {password})")
            cursor.execute(query, (username, password))
            connection.commit()
            print(f"Successfully added user {username} to radcheck")
            return True
            
        except Error as e:
            print(f"MySQL Error adding to radcheck: {e}")
            connection.rollback()
            return False
        except Exception as e:
            print(f"Unexpected error adding to radcheck: {e}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
                print("Database connection closed for add_user_auth")

    @staticmethod
    def add_user_expiration(username, expiration_hours):
        """Add user expiration timeout to radcheck table"""
        print(f"Adding user expiration for: {username}")
        print(f"Expiration hours: {expiration_hours}")
        
        connection = RadiusManager.get_connection()
        if not connection:
            print("Failed to get database connection for add_user_expiration")
            return False
        
        try:
            cursor = connection.cursor()

            expiration_date = datetime.now() + timedelta(hours=expiration_hours)
            expiration_string = expiration_date.strftime("%B %d %Y %H:%M:%S")

            query = """
            INSERT INTO radcheck (username, attribute, op, value) 
            VALUES (%s, 'Expiration', ':=', %s)
            """
            print(f"Executing expiration query: {query}")
            print(f"Expiration string: {expiration_string}")
            cursor.execute(query, (username, expiration_string))
            
            connection.commit()
            print(f"Successfully added expiration for user {username}: {expiration_string}")
            return True
            
        except Error as e:
            print(f"MySQL Error adding expiration: {e}")
            connection.rollback()
            return False
        except Exception as e:
            print(f"Unexpected error adding expiration: {e}")
            print(f"Full traceback: {traceback.format_exc()}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
                print("Database connection closed for add_user_expiration")

    @staticmethod
    def add_user_bandwidth(username, bandwidth_bits):
        """Add only bandwidth limit to radreply table"""
        print(f"Adding bandwidth limit for: {username}")
        print(f"Bandwidth: {bandwidth_bits} bits")
        
        connection = RadiusManager.get_connection()
        if not connection:
            print("Failed to get database connection for add_user_bandwidth")
            return False
        
        try:
            cursor = connection.cursor()
            
            # Add bandwidth limit (download) to radreply
            query = """
            INSERT INTO radreply (username, attribute, op, value) 
            VALUES (%s, 'WISPr-Bandwidth-Max-Down', ':=', %s)
            """
            print(f"Executing bandwidth query: {query}")
            cursor.execute(query, (username, str(bandwidth_bits)))
            
            connection.commit()
            print(f"Successfully added bandwidth limit for user {username}")
            return True
            
        except Error as e:
            print(f"MySQL Error adding bandwidth: {e}")
            connection.rollback()
            return False
        except Exception as e:
            print(f"Unexpected error adding bandwidth: {e}")
            print(f"Full traceback: {traceback.format_exc()}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
                print("Database connection closed for add_user_bandwidth")

    @staticmethod
    def add_user_network(username, network):
        """Add User to the radusergroup table"""
        print(f"Adding network for: {username}")
        print(f"Assigned Network: {network}")

        connection = RadiusManager.get_connection()
        if not connection:
            print("Failed to get database connection for add_user_bandwidth")
            return False
        
        try:
            cursor = connection.cursor()
            
            query = """
            INSERT INTO radusergroup (username, groupname, priority) 
            VALUES (%s,%s,'0')
            """
            print(f"Executing bandwidth query: {query}")
            cursor.execute(query, (username, network))
            
            connection.commit()
            print(f"Successfully added network for user {username}")
            return True
            
        except Error as e:
            print(f"MySQL Error adding bandwidth: {e}")
            connection.rollback()
            return False
        except Exception as e:
            print(f"Unexpected error adding bandwidth: {e}")
            print(f"Full traceback: {traceback.format_exc()}")
            connection.rollback()
            return False
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
                print("Database connection closed for add_user_bandwidth")


    @staticmethod
    def create_user_complete(username, password, bandwidth_mbps, expiration_hours):
        """Create a complete user with auth, expiration, and bandwidth"""
        print(f"Creating complete user: {username}")
        
        # Add authentication
        if not RadiusManager.add_user_auth(username, password):
            print(f"Failed to add authentication for {username}")
            return False
        
        # Add expiration timeout
        if not RadiusManager.add_user_expiration(username, expiration_hours):
            print(f"Failed to add expiration for {username}")
            # Cleanup: remove auth entry
            RadiusManager.delete_user_from_radius(username)
            return False
        
        # Add bandwidth limit
        bandwidth_bits = bandwidth_mbps * 1024 * 1024  # Convert Mbps to bits
        if not RadiusManager.add_user_bandwidth(username, bandwidth_bits):
            print(f"Failed to add bandwidth for {username}")
            # Cleanup: remove auth and expiration entries
            RadiusManager.delete_user_from_radius(username)
            return False
        
        print(f"Successfully created complete user: {username}")
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
            print(f"Deleted {username} from radcheck")

            # Delete from radreply
            cursor.execute("DELETE FROM radreply WHERE username = %s", (username,))
            print(f"Deleted {username} from radreply")

            # Delete from radusergroup
            cursor.execute("DELETE FROM radusergroup WHERE username = %s", (username,))
            print(f"Deleted {username} from radusergroup")

            connection.commit()
            return True
        
        except Exception as e:
            print(f"Error deleting user {username} from RADIUS DB: {e}")
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
            print(f"Error getting expiration: {e}")
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
            
            print(f"Updated expiration for {username} to: {expiration_string}")
            return True
        except Exception as e:
            print(f"Error updating expiration: {e}")
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
            print(f"Error authenticating: {e}")
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
            print(f"Error checking expiration: {e}")
            return False

