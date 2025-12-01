import logging
from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import DatabaseManager, RadiusManager, generate_username, generate_password, convert_mbps_to_bits
from config import Config
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'admin@123'

@app.route('/')
def index():
    return redirect(url_for('admin_login'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if Config.ADMIN_CREDENTIALS.get(username) == password:
            session['admin_logged_in'] = True
            session['admin_email'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials!', 'error')

    return render_template('login.html', hide_nav_links=True, show_portal_title=True)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully!', 'error')
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please log in first.', 'warning')
        return redirect(url_for('admin_login'))

    tab = request.args.get('tab', 'SMVRCH')
    search_term = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    admin_email = session.get('admin_email')

    # ---------------- FETCH USERS ---------------- #
    if tab in ['SMVRCH', 'NGO']:
        if search_term:
            all_users = DatabaseManager.search_users(search_term, admin_email, tab)
        else:
            all_users = DatabaseManager.get_users_by_network(admin_email, tab)
            all_users.sort(key=lambda x: x.get('created_at') or datetime.min, reverse=True)

    elif tab == 'GUEST':
        DatabaseManager.sync_user_auth_to_all_users()
        all_users = DatabaseManager.get_guest_users()

        processed_users = []
        user_count = []

        for user in all_users:
           username = user.get('username', '')

           created_at = None
           name_part = username

           if "_" in username:

               try:
                 name_part, date_part = username.rsplit("_", 1)
                 created_at = datetime.strptime(date_part, "%Y%m%d%H%M%S")
               except ValueError:
                 pass

           user['full_name'] = name_part.replace("_", " ")  # format name properly
           user['created_at'] = created_at
           processed_users.append(user)


        processed_users.sort(key=lambda x: x['created_at'] or datetime.min, reverse=True)
        if search_term:
           search_lower = search_term.lower()
           processed_users = [
             u for u in processed_users
             if search_lower in u['full_name'].lower() or search_lower in str(u.get('mobile', '')).lower()
           ]

           all_users = processed_users

        user_count = DatabaseManager.get_users_with_count()

    else:
        all_users = []

    # ---------------- PROCESS ACTIVE / INACTIVE ---------------- #
    for user in all_users:
        expiration = RadiusManager.get_user_expiration(user['username'])

        if isinstance(expiration, str):
            try:
                expiration = datetime.strptime(expiration, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                expiration = None

        user['expiration'] = expiration
        user['is_active'] = expiration and datetime.now() > expiration

    # ---------------- PAGINATION ---------------- #
    items_per_page = 25
    total_users = len(all_users)
    total_pages = (total_users + items_per_page - 1) // items_per_page

    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages

    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    users = all_users[start_idx:end_idx]

    return render_template(
        'dashboard.html',
        users=users,
        search_term=search_term,
        active_tab=tab,
        show_portal_title=False,
        page=page,
        total_pages=total_pages,
        total_users=total_users,
        min=min,
        user_count=user_count,
    )

@app.route('/admin/view_details/<user_id>')
def view_details(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    user = DatabaseManager.get_user_details(user_id)
    if not user:
        flash('User not found!', 'warning')
        return redirect(url_for('admin_dashboard'))

    return render_template('user_details.html', user=user)

# ---------------- REGISTER USER ---------------- #
@app.route('/admin/register', methods=['GET', 'POST'])
def register_user():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        mobile = request.form['mobile']
        network = request.form['network']
        bandwidth_mbps = int(request.form['bandwidth'])
        expiration_hours = float(request.form['expiration_hours'])
        
        start_date = request.form.get('start_date') or None
        end_date = request.form.get('end_datetime') or None
        start_time = request.form.get('start_time') or None
        end_time = request.form.get('end_time') or None

        time_interval = None
        if start_time and end_time:
            time_interval = f"{start_time.replace(':', '.')}-{end_time.replace(':', '.')}"

        username = generate_username(full_name)
        password = generate_password()
        
        password_sent = True

        if start_date and end_date:
            password_sent = False
            password = generate_password()
            logger.info(f"Scheduled user, password will be sent later: {username}")

        elif start_time and end_time:
            time_interval = f"{start_time.replace(':','.')}-{end_time.replace(':','.')}"
            password = generate_password()
            logger.info(f"Time-based user, generated password: {password}")

        else:
            password = generate_password()
            logger.info(f"Generated password for normal user: {password}")

        bandwidth_bits = convert_mbps_to_bits(bandwidth_mbps)

        if DatabaseManager.save_user(full_name, email, mobile, network,
                                     username, password, bandwidth_mbps, expiration_hours,
                                     start_date, end_date, time_interval, password_sent):

            if (RadiusManager.add_user_auth(username, password) and
                RadiusManager.add_user_bandwidth(username, bandwidth_bits) and
                RadiusManager.add_radius_controls(username, expiration_hours, start_time, end_time, end_date) and
                RadiusManager.add_user_network(username, network)):

                if password_sent:
                    session['new_username'] = username
                    session['new_password'] = password
                    flash('User registered successfully!', 'success')
                    return redirect(url_for('register_success'))
                else:
                    session['new_username'] = username
                    session['scheduled_user'] = True
                    session['start_date'] = start_date
                    flash(f'User registered successfully! Password will be sent on {start_date} @ 12AM.', 'info')
                    return redirect(url_for('register_success'))
            else:
                flash('User saved but RADIUS setup failed!', 'warning')
        else:
            flash('Failed to register user!', 'error')

        return redirect(url_for('admin_dashboard'))

    return render_template('register_user.html', show_portal_title=False)

@app.route('/admin/register/success')
def register_success():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    username = session.pop('new_username', None)
    password = session.pop('new_password', None)
    scheduled_user = session.pop('scheduled_user', False)
    start_date = session.pop('start_date', None)

    if not username or (not password and not scheduled_user):
        flash('No registration data found!', 'warning')
        return redirect(url_for('admin_dashboard'))

    return render_template('register_success.html',
                           username=username, password=password,
                           scheduled_user=scheduled_user,
                           start_date=start_date,
                           show_portal_title=False)


# ---------------- DELETE USER ---------------- #
@app.route('/admin/delete/<int:user_id>', methods=["POST"])
def delete_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if DatabaseManager.delete_user(user_id, hard_delete=False):
        flash('User deleted successfully!', 'success')
    else:
        flash('Failed to delete user!', 'error')

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<username>/expiration')
def check_user_expiration(username):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    expiration = RadiusManager.get_user_expiration(username)
    is_expired = RadiusManager.check_user_expired(username)

    return {
        'username': username,
        'expiration': expiration,
        'is_expired': is_expired
    }


# ---------------- SUPERADMIN ---------------- #
@app.route('/superadmin/login', methods=['GET', 'POST'])
def superadmin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username == 'mvgdigital' and password == 'mvg@123':
            session['superadmin_logged_in'] = True
            session['superadmin_username'] = username
            flash('Login successful.', 'success')
            return redirect(url_for('superadmin_dashboard'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('superadmin_login.html')


@app.route('/superadmin/dashboard')
def superadmin_dashboard():
    if not session.get('superadmin_logged_in'):
        return redirect(url_for('superadmin_login'))

    search_term = request.args.get('search', '')

    users = (DatabaseManager.search_users(search_term)
             if search_term else DatabaseManager.get_all_users_all_admins())

    for user in users:
        expiration_str = RadiusManager.get_user_expiration(user['username'])
        if expiration_str:
            try:
                expiration_date = datetime.strptime(expiration_str, "%B %d %Y %H:%M:%S")
                user['is_active'] = datetime.now() > expiration_date
            except Exception:
                user['is_active'] = False
        else:
            user['is_active'] = False

    return render_template('superadmin_dashboard.html', users=users)


@app.route('/superadmin/delete/<int:user_id>', methods=['POST'])
def superadmin_delete_user(user_id, hard_delete=True):
    if not session.get('superadmin_logged_in'):
        return redirect(url_for('superadmin_login'))

    if DatabaseManager.delete_user(user_id, hard_delete=hard_delete):
        flash('User deleted successfully!', 'success')
    else:
        flash('Failed to delete user!', 'error')

    return redirect(url_for('superadmin_dashboard'))


@app.route('/superadmin/logout')
def superadmin_logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('superadmin_login'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)