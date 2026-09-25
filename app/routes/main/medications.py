from flask import request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Profile, Medication, DoseLog
from app.utils.timeutil import today_local, utcnow_naive
from . import main_bp


@main_bp.route('/medication/add', methods=['POST'])
@login_required
def add_medication():
    profile_id = request.form.get('profile_id', type=int)
    name = request.form.get('name', '').strip()
    genre = request.form.get('genre', '').strip() or 'General'
    dosage_target = request.form.get('dosage_target', type=int, default=1)
    total_stock = request.form.get('total_stock', type=int, default=30)
    low_stock_threshold = request.form.get('low_stock_threshold', type=int, default=5)
    time_slots = request.form.getlist('time_slots')
    if not time_slots and request.form.get('time_slot'):
        time_slots = [request.form.get('time_slot').strip()]
    time_slot = ", ".join(time_slots) if time_slots else "Morning"
    instructions = request.form.get('instructions', '').strip()
    prescribing_doctor = request.form.get('prescribing_doctor', '').strip()

    profile = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first()
    if not profile or not name:
        flash('Invalid profile or missing medication name.', 'danger')
        return redirect(url_for('main.dashboard'))

    med = Medication(
        profile_id=profile.id,
        name=name,
        genre=genre,
        dosage_target=max(1, dosage_target),
        total_stock=max(0, total_stock),
        low_stock_threshold=max(1, low_stock_threshold),
        time_slot=time_slot,
        instructions=instructions,
        prescribing_doctor=prescribing_doctor,
        is_active=True,
        last_reset_date=today_local()
    )
    db.session.add(med)
    db.session.commit()
    flash(f'Medication "{name}" ({genre}) added for {profile.name}.', 'success')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/medication/<int:med_id>/edit', methods=['POST'])
@login_required
def edit_medication(med_id):
    med = Medication.query.join(Profile).filter(
        Medication.id == med_id,
        Profile.user_id == current_user.id
    ).first_or_404()

    med.name = request.form.get('name', med.name).strip()
    med.genre = request.form.get('genre', med.genre).strip() or 'General'
    med.dosage_target = max(1, request.form.get('dosage_target', type=int, default=med.dosage_target))
    med.total_stock = max(0, request.form.get('total_stock', type=int, default=med.total_stock))
    med.low_stock_threshold = max(1, request.form.get('low_stock_threshold', type=int, default=med.low_stock_threshold))

    time_slots = request.form.getlist('time_slots')
    if time_slots:
        med.time_slot = ", ".join(time_slots)
    elif request.form.get('time_slot'):
        med.time_slot = request.form.get('time_slot').strip()

    med.instructions = request.form.get('instructions', '').strip()
    med.prescribing_doctor = request.form.get('prescribing_doctor', '').strip()

    db.session.commit()
    flash(f'Updated details for "{med.name}".', 'success')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/medication/<int:med_id>/toggle-archive', methods=['POST'])
@login_required
def toggle_archive_medication(med_id):
    med = Medication.query.join(Profile).filter(
        Medication.id == med_id,
        Profile.user_id == current_user.id
    ).first_or_404()

    med.is_active = not med.is_active
    db.session.commit()
    status_str = "active" if med.is_active else "archived/completed"
    flash(f'Medication "{med.name}" marked as {status_str}.', 'info')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/medication/<int:med_id>/delete', methods=['POST'])
@login_required
def delete_medication(med_id):
    med = Medication.query.join(Profile).filter(
        Medication.id == med_id,
        Profile.user_id == current_user.id
    ).first_or_404()

    confirm_text = request.form.get('confirm_text', '').strip()
    if confirm_text != med.name:
        flash('Medication name did not match. Deletion cancelled to protect your dose history.', 'warning')
        return redirect(url_for('main.dashboard'))

    name = med.name
    db.session.delete(med)
    db.session.commit()
    flash(f'Medication "{name}" deleted.', 'info')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/medication/<int:med_id>/refill', methods=['POST'])
@login_required
def refill_medication(med_id):
    med = Medication.query.join(Profile).filter(
        Medication.id == med_id,
        Profile.user_id == current_user.id
    ).first_or_404()

    pills_to_add = request.form.get('refill_amount', type=int, default=30)
    if pills_to_add <= 0:
        pills_to_add = 30

    med.total_stock += pills_to_add

    # Log the refill event
    log = DoseLog(
        medication_id=med.id,
        action='refill',
        pills_changed=pills_to_add,
        timestamp=utcnow_naive(),
        notes=f"Added {pills_to_add} pills"
    )
    db.session.add(log)
    db.session.commit()

    # If it's an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'total_stock': med.total_stock,
            'is_low_stock': med.is_low_stock,
            'message': f'Refilled +{pills_to_add} pills. Total stock: {med.total_stock}'
        })

    flash(f'Refilled "{med.name}" (+{pills_to_add} pills). Total stock: {med.total_stock}', 'success')
    return redirect(url_for('main.dashboard'))


# AJAX Endpoint for Big + / - Stepper Buttons
@main_bp.route('/api/medication/<int:med_id>/step', methods=['POST'])
@login_required
def step_pill_count(med_id):
    med = Medication.query.join(Profile).filter(
        Medication.id == med_id,
        Profile.user_id == current_user.id
    ).first()

    if not med:
        return jsonify({'success': False, 'error': 'Medication not found'}), 404

    # Automated daily reset check
    med.check_and_reset_daily()

    data = request.get_json() or {}
    action = data.get('action')

    if action == 'increment':
        med.pills_taken_today += 1
        if med.total_stock > 0:
            med.total_stock -= 1

        log = DoseLog(
            medication_id=med.id,
            action='increment',
            pills_changed=1,
            timestamp=utcnow_naive(),
            notes=f"Logged dose ({med.pills_taken_today}/{med.dosage_target})"
        )
        db.session.add(log)

    elif action == 'decrement':
        if med.pills_taken_today > 0:
            med.pills_taken_today -= 1
            med.total_stock += 1

            log = DoseLog(
                medication_id=med.id,
                action='decrement',
                pills_changed=1,
                timestamp=utcnow_naive(),
                notes=f"Undid dose ({med.pills_taken_today}/{med.dosage_target})"
            )
            db.session.add(log)
        else:
            return jsonify({
                'success': True,
                'pills_taken_today': med.pills_taken_today,
                'dosage_target': med.dosage_target,
                'total_stock': med.total_stock,
                'adherence_percentage': med.adherence_percentage,
                'is_low_stock': med.is_low_stock,
                'message': 'Count already at zero'
            })
    else:
        return jsonify({'success': False, 'error': 'Invalid action'}), 400

    db.session.commit()

    return jsonify({
        'success': True,
        'pills_taken_today': med.pills_taken_today,
        'dosage_target': med.dosage_target,
        'total_stock': med.total_stock,
        'adherence_percentage': med.adherence_percentage,
        'is_low_stock': med.is_low_stock,
        'low_stock_threshold': med.low_stock_threshold,
        'is_behind_schedule': med.is_behind_schedule,
        'name': med.name
    })
