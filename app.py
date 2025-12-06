import logging,os
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import DatabaseManager, RadiusManager, generate_username, generate_password, convert_mbps_to_bits
from config import Config
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "log")
os.makedirs(LOG_DIR, exist_ok=True)

log_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)

# App log file
app_log_path = os.path.join(LOG_DIR, "app.log")
file_handler = RotatingFileHandler(
    app_log_path, maxBytes=5*1024*1024, backupCount=2
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_formatter)

# Error log file
error_log_path = os.path.join(LOG_DIR, "error.log")
error_handler = RotatingFileHandler(
    error_log_path, maxBytes=5*1024*1024, backupCount=2
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(log_formatter)

# Console logs (optional)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(error_handler)
logger.addHandler(console_handler)

app = Flask(__name__)
app.secret_key = 'admin@123'


@app.route('/')
def index():
    logger.info("Redirect -> Admin Login")
    return redirect(url_for('admin_login'))


# ---------------------- ADMIN LOGIN ---------------------- #
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        logger.info(f"Admin Login Attempt: {username}")
        password = request.form.get('password')

        if Config.ADMIN_CREDENTIALS.get(username) == password:
            session['admin_logged_in'] = True
            session['admin_email'] = username
            logger.info(f"Admin Logged In: {username}")
            flash("Login Successful!", "success")
            return redirect(url_for('admin_dashboard'))

        logger.warning(f"Invalid Login Attempt: {username}")
        flash("Invalid credentials!", "error")

    return render_template('login.html', hide_nav_links=True, show_portal_title=True)


@app.route('/admin/logout')
def admin_logout():
    logger.info(f"Admin logged out: {session.get('admin_email')}")
    session.clear()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('admin_login'))


# ---------------------- ADMIN DASHBOARD ---------------------- #
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        logger.warning("Unauthorized Dashboard Access Attempt")
        flash("Please log in first!", "warning")
        return redirect(url_for('admin_login'))

    tab = request.args.get('tab', 'SMVRCH')
    search_term = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    admin_email = session.get('admin_email')

    logger.info(f"Dashboard -> Admin: {admin_email} | Tab: {tab} | Search: {search_term}")

    try:
        if tab in ['SMVRCH', 'NGO']:
            if search_term:
                all_users = DatabaseManager.search_users(search_term, admin_email, tab)
                logger.info(f"Search Filter Applied | {len(all_users)} users found")
            else:
                all_users = DatabaseManager.get_users_by_network(admin_email, tab)
                logger.info(f"Fetched {len(all_users)} users for network: {tab}")

            all_users.sort(key=lambda x: x.get('created_at') or datetime.min, reverse=True)
            user_count = None

        elif tab == 'GUEST':
            logger.info("Syncing Guest User Table...")
            DatabaseManager.sync_user_auth_to_all_users()

            all_users = DatabaseManager.get_guest_users()
            user_count = DatabaseManager.get_users_with_count()
            user_count_map = {u['user_id']: u['sub_user_count'] for u in user_count}

            processed_users = []
            for user in all_users:
                username = user.get('username', '')
                full_name = username
                created_at = None

                if "_" in username:
                    try:
                        full_name, dt = username.rsplit("_", 1)
                        created_at = datetime.strptime(dt, "%Y%m%d%H%M%S")
                    except ValueError:
                        pass

                user['full_name'] = full_name.replace("_", " ")
                user['created_at'] = created_at
                user['sub_user_count'] = user_count_map.get(user['users_id'], 0)
                uid = user.get('users_id') or user.get('user_id') or user.get('id')
                user['user_id'] = uid
                user['sub_user_count'] = user_count_map.get(uid, 0)

                processed_users.append(user)

            if search_term:
                search_lower = search_term.lower()
                processed_users = [
                    u for u in processed_users
                    if search_lower in u['full_name'].lower()
                       or search_lower in str(u.get('mobile', '')).lower()
                ]
                logger.info(f"Guest search -> {len(processed_users)} user(s) matched")

            processed_users.sort(key=lambda x: x.get('created_at') or datetime.min, reverse=True)
            all_users = processed_users

        else:
            all_users = []
            user_count = None
            logger.info("Unknown tab, returning empty dataset")

        if tab in ['SMVRCH', 'NGO']:
            logger.info("Fetching Expiration Status from Radius...")
            for user in all_users:
                expiration = RadiusManager.get_user_expiration(user['username'])
                try:
                    expiration = datetime.strptime(expiration, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    expiration = None
                user['expiration'] = expiration
                user['is_active'] = expiration and expiration > datetime.now()

        items_per_page = 25
        total_users = len(all_users)
        total_pages = (total_users + items_per_page - 1) // items_per_page

        page = max(1, min(page, total_pages or 1))
        start = (page - 1) * items_per_page
        users = all_users[start:start + items_per_page]

    except Exception as e:
        logger.exception(f"Dashboard Error: {e}")
        flash("Error loading dashboard.", "danger")
        users, total_pages, total_users, user_count = [], 1, 0, None

    return render_template(
        'dashboard.html',
        users=users,
        search_term=search_term,
        active_tab=tab,
        page=page,
        total_pages=total_pages,
        total_users=total_users,
        min=min,
        user_count=user_count,
        show_portal_title=False
    )


# ---------------------- USER DETAILS ---------------------- #
@app.route('/admin/view_details/<user_id>')
def view_details(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    logger.info(f"Fetching Details -> User ID: {user_id}")
    user = DatabaseManager.get_user_details(user_id)

    if not user:
        logger.warning(f"User Not Found -> ID: {user_id}")
        flash("User not found!", "warning")
        return redirect(url_for('admin_dashboard'))

    return render_template('user_details.html', user=user)


# ---------------------- REGISTER USER ---------------------- #
@app.route('/admin/register', methods=['GET', 'POST'])
def register_user():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        try:
            logger.info("Registering New User...")

            full_name = request.form['full_name']
            email = request.form['email']
            mobile = request.form['mobile']
            network = request.form['network']
            bandwidth_mbps = int(request.form['bandwidth'])
            session_timeout = request.form.get('session_timeout') or None

            start_date = request.form.get('start_date') or None
            end_date = request.form.get('end_datetime') or None
            start_time = request.form.get('start_time') or None
            end_time = request.form.get('end_time') or None
            no_of_devices = request.form.get('no_of_devices') or None

            time_interval = f"{start_time.replace(':', '.')}-{end_time.replace(':', '.')}" \
                if start_time and end_time else None

            # Server-side validation: start_date is mandatory if end_date is selected
            if end_date and not start_date:
                flash("Start Date is mandatory when End Date is selected.", "error")
                return redirect(url_for('register_user'))

            if start_date and not end_date:
                flash("End Date is mandatory when Start Date is selected.", "error")
                return redirect(url_for('register_user'))

            username = generate_username(full_name)
            password = generate_password()
            bandwidth_bits = convert_mbps_to_bits(bandwidth_mbps)

            logger.info(f"Generated Credentials -> User: {username}")

            password_sent = start_date is None

            db_status = DatabaseManager.save_user(
                full_name, email, mobile, network, username, password,
                bandwidth_mbps, session_timeout,
                start_date, end_date, time_interval,
                no_of_devices, password_sent
            )

            radius_status = (
                RadiusManager.add_user_auth(username, password) and
                RadiusManager.add_user_bandwidth(username, bandwidth_bits) and
                RadiusManager.add_radius_controls(username, session_timeout, start_time, end_time, end_date) and
                RadiusManager.no_of_devices(username, no_of_devices) and
                RadiusManager.add_user_network(username, network)
            )

            if db_status and radius_status:
                logger.info(f"User Registered Successfully -> {username}")

                if start_date:
                    # Scheduled user: redirect to dashboard
                    flash("User registered successfully!", "success")
                    return redirect(url_for('admin_dashboard'))
                else:
                    # Immediate user (no start_date): redirect to success page with credentials
                    return redirect(url_for('register_success', username=username, password=password, scheduled_user='0'))

            else:
                logger.error(f"Failed to Register User -> {username}")
                flash("Failed to register user!", "error")

        except Exception as e:
            logger.exception(f"Registration Error: {e}")
            flash(f"Error occurred: {e}", "danger")

        return redirect(url_for('admin_dashboard'))

    return render_template('register_user.html')


@app.route('/admin/register_success')
def register_success():
    username = request.args.get('username')
    password = request.args.get('password')
    scheduled_user = request.args.get('scheduled_user')

    return render_template(
        'register_success.html',
        username=username,
        password=password,
        scheduled_user=scheduled_user
    )


# ---------------------- DELETE USER ---------------------- #
@app.route('/admin/delete/<int:user_id>', methods=["POST"])
def delete_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    logger.info(f"Delete Request -> User ID: {user_id}")

    if DatabaseManager.delete_user(user_id):
        logger.info(f"User Deleted -> {user_id}")
        flash("User deleted successfully!", "success")
    else:
        logger.error(f"Delete Failed -> {user_id}")
        flash("Failed to delete user!", "error")

    return redirect(url_for('admin_dashboard'))


# ---------------------- SUPERADMIN LOGOUT ---------------------- #
@app.route('/superadmin/logout')
def superadmin_logout():
    logger.info("Superadmin Logged Out")
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('superadmin_login'))


if __name__ == '__main__':
    logger.info("Server Started -> Port 5001")
    app.run(debug=True, host='0.0.0.0', port=5001)