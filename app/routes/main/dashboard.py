from flask import render_template, request, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import Profile
from app.utils.timeutil import today_local
from . import main_bp


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    profiles = Profile.query.filter_by(user_id=current_user.id).order_by(Profile.created_at.asc()).all()

    # Check and perform automated daily resets if the local date changed
    db_changed = False
    low_stock_meds = []
    total_meds_count = 0

    for profile in profiles:
        for med in profile.medications:
            total_meds_count += 1
            if med.check_and_reset_daily():
                db_changed = True
            if med.is_active and med.is_low_stock:
                low_stock_meds.append({
                    'med': med,
                    'profile': profile
                })

    if db_changed:
        db.session.commit()

    # Common genres for filter/tagging
    common_genres = [
        'Antibiotic', 'Pain Relief', 'Cardiovascular',
        'Supplement & Vitamin', 'Allergy', 'Digestive',
        'Diabetes', 'Mental Health', 'General'
    ]

    selected_profile_id = request.args.get('profile_id', type=int)

    return render_template(
        'dashboard.html',
        profiles=profiles,
        low_stock_meds=low_stock_meds,
        total_meds_count=total_meds_count,
        common_genres=common_genres,
        selected_profile_id=selected_profile_id,
        today_date=today_local().strftime('%A, %B %d, %Y')
    )
