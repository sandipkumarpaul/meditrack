import json
from urllib.parse import urlparse
from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_user, logout_user, login_required, current_user
from app import db, limiter
from app.models import User, Profile
from app.utils.timeutil import today_local, utcnow_naive

auth_bp = Blueprint('auth', __name__)


def _is_safe_redirect(target):
    """Only follow ?next= to a relative path on this site. Without this check,
    a crafted login link like /login?next=https://evil.example would send the
    user to an external site right after they authenticate (open redirect)."""
    if not target:
        return False
    target = target.replace('\\', '/')
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and target.startswith('/') and not target.startswith('//')


@auth_bp.route('/signup', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not username or not email or not password:
            flash('Please fill in all required fields.', 'danger')
            return render_template('auth/signup.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'warning')
            return render_template('auth/signup.html')

        existing_user = User.query.filter(
            (User.username.ilike(username)) | (User.email.ilike(email))
        ).first()

        if existing_user:
            flash('Username or Email already exists.', 'warning')
            return render_template('auth/signup.html')

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # assigns user.id without committing, so a failure below leaves no orphaned user

        # Create a default "Self" profile for the user
        default_profile = Profile(user_id=user.id, name=username, relationship='Self')
        db.session.add(default_profile)
        db.session.commit()

        login_user(user)
        flash('Account created successfully! Welcome to MediTrack.', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('auth/signup.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("15 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')

        if not identifier or not password:
            flash('Please provide your username/email and password.', 'warning')
            return render_template('auth/login.html')

        user = User.query.filter(
            (User.username.ilike(identifier)) | (User.email.ilike(identifier.lower()))
        ).first()

        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            if not _is_safe_redirect(next_page):
                next_page = None
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(next_page or url_for('main.dashboard'))
        else:
            flash('Invalid username/email or password.', 'danger')
            return render_template('auth/login.html')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out safely.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action', 'update_username')

        if action == 'update_username':
            new_username = request.form.get('username', '').strip()

            if not new_username:
                flash('Username cannot be empty.', 'danger')
                return redirect(url_for('auth.settings'))

            if len(new_username) < 3:
                flash('Username must be at least 3 characters long.', 'warning')
                return redirect(url_for('auth.settings'))

            if len(new_username) > 50:
                flash('Username cannot exceed 50 characters.', 'warning')
                return redirect(url_for('auth.settings'))

            if new_username.lower() == current_user.username.lower():
                flash('New username is the same as your current username.', 'info')
                return redirect(url_for('auth.settings'))

            # Check for uniqueness
            existing = User.query.filter(
                User.username.ilike(new_username),
                User.id != current_user.id
            ).first()

            if existing:
                flash(f'Username "{new_username}" is already taken. Please pick a different one.', 'warning')
                return redirect(url_for('auth.settings'))

            old_username = current_user.username
            current_user.username = new_username

            # Also update the "Self" profile name if it was named after the old username
            self_profile = Profile.query.filter_by(
                user_id=current_user.id,
                relationship='Self'
            ).first()
            if self_profile and (self_profile.name == old_username or self_profile.name == ''):
                self_profile.name = new_username

            db.session.commit()
            flash(f'Your username has been successfully updated to "{new_username}".', 'success')
            return redirect(url_for('auth.settings'))

        elif action == 'update_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not current_password or not new_password:
                flash('Please provide both current and new passwords.', 'warning')
                return redirect(url_for('auth.settings'))

            if not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('auth.settings'))

            if len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'warning')
                return redirect(url_for('auth.settings'))

            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('auth.settings'))

            current_user.set_password(new_password)
            db.session.commit()
            flash('Your password has been changed successfully.', 'success')
            return redirect(url_for('auth.settings'))

    return render_template('auth/settings.html')


@auth_bp.route('/settings/export-data')
@login_required
def export_data():
    """Full account backup as JSON: profiles, medications, and complete dose history."""
    profiles_data = []
    for p in current_user.profiles:
        meds_data = []
        for m in p.medications:
            meds_data.append({
                'name': m.name,
                'genre': m.genre,
                'dosage_target': m.dosage_target,
                'pills_taken_today': m.pills_taken_today,
                'total_stock': m.total_stock,
                'low_stock_threshold': m.low_stock_threshold,
                'time_slot': m.time_slot,
                'instructions': m.instructions,
                'prescribing_doctor': m.prescribing_doctor,
                'rx_number': m.rx_number,
                'is_active': m.is_active,
                'created_at': m.created_at.isoformat() if m.created_at else None,
                'dose_logs': [
                    {
                        'action': log.action,
                        'pills_changed': log.pills_changed,
                        'timestamp_utc': log.timestamp.isoformat() if log.timestamp else None,
                        'notes': log.notes
                    }
                    for log in m.dose_logs
                ]
            })
        profiles_data.append({
            'name': p.name,
            'relationship': p.relationship,
            'date_of_birth': p.date_of_birth.isoformat() if p.date_of_birth else None,
            'notes': p.notes,
            'medications': meds_data
        })

    payload = {
        'export_generated_at_utc': utcnow_naive().isoformat(),
        'account': {
            'username': current_user.username,
            'email': current_user.email
        },
        'profiles': profiles_data
    }

    filename = f"meditrack_backup_{today_local().strftime('%Y%m%d')}.json"
    return Response(
        json.dumps(payload, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment;filename={filename}'}
    )


@auth_bp.route('/settings/delete-account', methods=['POST'])
@login_required
def delete_account():
    password = request.form.get('password', '')
    confirm_text = request.form.get('confirm_text', '').strip()

    if confirm_text != 'DELETE':
        flash('Please type DELETE exactly to confirm permanent account deletion.', 'warning')
        return redirect(url_for('auth.settings'))

    if not current_user.check_password(password):
        flash('Incorrect password. Your account was not deleted.', 'danger')
        return redirect(url_for('auth.settings'))

    user = db.session.get(User, current_user.id)
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash('Your MediTrack account and all associated data have been permanently deleted.', 'info')
    return redirect(url_for('auth.signup'))

