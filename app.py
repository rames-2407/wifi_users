from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import DatabaseManager, RadiusManager, generate_username, generate_password, convert_mbps_to_bits
from config import Config
from datetime import datetime


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

    search_term = request.args.get('search', '')
    admin_email = session.get('admin_email')
    
    if search_term:
        users = DatabaseManager.search_users(search_term,admin_email)
    else:
        users = DatabaseManager.get_all_users(admin_email)

    for user in users:
        expiration_str = RadiusManager.get_user_expiration(user.username)
        if expiration_str:
            try:
                expiration_date = datetime.strptime(expiration_str, "%B %d %Y %H:%M:%S")
                user.is_active = datetime.now() > expiration_date  
            except Exception as e:
                print(f"[Expiration Parsing Error] {user.username}: {e}")
                user.is_active = False  
        else:
            user.is_active = False

    return render_template('dashboard.html', users=users, search_term=search_term, show_portal_title=False)


# Register User
@app.route('/admin/register', methods=['GET', 'POST'])
def register_user():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        # Get form data
        full_name = request.form['full_name']
        email = request.form['email']
        mobile = request.form['mobile']
        mac_address = request.form['mac_address']
        network = request.form['network']
        bandwidth_mbps = int(request.form['bandwidth'])
        expiration_hours = float(request.form['expiration_hours'])

        # Generate credentials
        username = generate_username(full_name)
        password = generate_password()
        print(f"Username: {username}, Password: {password}")

        # Convert units
        bandwidth_bits = convert_mbps_to_bits(bandwidth_mbps)

        # Save to app database
        if DatabaseManager.save_user(full_name, email, mobile, mac_address,network, username, password, bandwidth_mbps, expiration_hours):
            # Save to FreeRADIUS
            if  RadiusManager.add_user_auth(username, password) and \
                RadiusManager.add_user_bandwidth(username, bandwidth_bits) and \
                RadiusManager.add_user_expiration(username, expiration_hours) and \
                RadiusManager.add_user_network(username, network):

                session['new_username'] = username
                session['new_password'] = password
                flash('User registered successfully!', 'success')
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

    if not username or not password:
        flash('No registration data found!', 'warning')
        return redirect(url_for('admin_dashboard'))

    return render_template('register_success.html', username=username, password=password, show_portal_title=False)

# Delete User
@app.route('/admin/delete/<int:user_id>',methods=["POST"])
def delete_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if DatabaseManager.delete_user(user_id,hard_delete=False):
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
    
    users = DatabaseManager.search_users(search_term) if search_term else DatabaseManager.get_all_users_all_admins()

    for user in users:
        expiration_str = RadiusManager.get_user_expiration(user['is_active'])
        if expiration_str:
            try:
                expiration_date = datetime.strptime(expiration_str, "%B %d %Y %H:%M:%S")
                user['is_active'] = datetime.now() > expiration_date  
            except Exception as e:
                print(f"[Expiration Parsing Error] {user['username']}: {e}")
                user['is_active'] = False  
        else:
            user['is_active'] = False

    return render_template('superadmin_dashboard.html', users=users)

@app.route('/superadmin/delete/<int:user_id>', methods=['POST'])
def superadmin_delete_user(user_id,hard_delete=True):
    if not session.get('superadmin_logged_in'):
        return redirect(url_for('superadmin_login'))
    
    if DatabaseManager.delete_user(user_id,hard_delete=hard_delete):
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
