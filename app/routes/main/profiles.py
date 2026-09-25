from datetime import datetime
from flask import request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Profile
from . import main_bp


@main_bp.route('/profile/add', methods=['POST'])
@login_required
def add_profile():
    name = request.form.get('name', '').strip()
    relationship = request.form.get('relationship', 'Family Member').strip()
    notes = request.form.get('notes', '').strip()
    dob_str = request.form.get('date_of_birth', '').strip()

    dob = None
    if dob_str:
        try:
            dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
        except ValueError:
            dob = None

    if name:
        profile = Profile(
            user_id=current_user.id,
            name=name,
            relationship=relationship,
            date_of_birth=dob,
            notes=notes
        )
        db.session.add(profile)
        db.session.commit()
        flash(f'Family member profile "{name}" added successfully!', 'success')
    else:
        flash('Person name cannot be empty.', 'danger')

    return redirect(url_for('main.dashboard'))


@main_bp.route('/profile/<int:profile_id>/delete', methods=['POST'])
@login_required
def delete_profile(profile_id):
    profile = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first_or_404()

    confirm_text = request.form.get('confirm_text', '').strip()
    if confirm_text != profile.name:
        flash('Profile name did not match. Deletion cancelled to protect your data.', 'warning')
        return redirect(url_for('main.dashboard'))

    name = profile.name
    db.session.delete(profile)
    db.session.commit()
    flash(f'Profile "{name}" and all associated medications deleted.', 'info')
    return redirect(url_for('main.dashboard'))
