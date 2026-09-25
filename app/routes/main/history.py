import io
import csv
from datetime import timedelta
from flask import render_template, request, current_app, Response
from flask_login import login_required, current_user
from app.models import Profile, Medication, DoseLog
from app.services.excel_export import generate_dose_history_excel
from app.utils.timeutil import today_local, now_local, local_midnight_utc_naive, utc_to_local
from . import main_bp


def _household_profile_ids():
    profiles = Profile.query.filter_by(user_id=current_user.id).all()
    return profiles, [p.id for p in profiles]


# Adherence and Dose History Log
@main_bp.route('/history')
@login_required
def history():
    profiles, profile_ids = _household_profile_ids()

    selected_profile_id = request.args.get('profile_id', type=int)
    selected_action = request.args.get('action', '').strip()

    # Base query for all logs of current user's household
    base_query = DoseLog.query.join(Medication).filter(
        Medication.profile_id.in_(profile_ids)
    )

    # Statistics (across all family members)
    total_doses_logged = base_query.filter(DoseLog.action == 'increment').count()
    total_reversals = base_query.filter(DoseLog.action == 'decrement').count()
    total_refills = base_query.filter(DoseLog.action == 'refill').count()

    # Doses taken today (local calendar day, not UTC)
    today_start_utc = local_midnight_utc_naive()
    today_doses_count = base_query.filter(
        DoseLog.action == 'increment',
        DoseLog.timestamp >= today_start_utc
    ).count()

    # Apply filters
    filtered_query = base_query
    if selected_profile_id and selected_profile_id in profile_ids:
        filtered_query = filtered_query.filter(Medication.profile_id == selected_profile_id)
    if selected_action in ['increment', 'decrement', 'refill']:
        filtered_query = filtered_query.filter(DoseLog.action == selected_action)

    logs = filtered_query.order_by(DoseLog.timestamp.desc()).limit(200).all()

    # 14-day adherence trend chart (doses taken per local day), respecting the
    # profile filter but not the action filter -- this is about adherence, not audit rows.
    chart_days = 14
    chart_start_date = today_local() - timedelta(days=chart_days - 1)
    chart_query = base_query.filter(
        DoseLog.action == 'increment',
        DoseLog.timestamp >= local_midnight_utc_naive(chart_start_date)
    )
    if selected_profile_id and selected_profile_id in profile_ids:
        chart_query = chart_query.filter(Medication.profile_id == selected_profile_id)

    daily_counts = {}
    for log in chart_query.all():
        local_day = utc_to_local(log.timestamp).date()
        daily_counts[local_day] = daily_counts.get(local_day, 0) + 1

    chart_labels = []
    chart_data = []
    for i in range(chart_days):
        d = chart_start_date + timedelta(days=i)
        chart_labels.append(d.strftime('%b %d'))
        chart_data.append(daily_counts.get(d, 0))

    return render_template(
        'history.html',
        logs=logs,
        profiles=profiles,
        selected_profile_id=selected_profile_id,
        selected_action=selected_action,
        total_doses_logged=total_doses_logged,
        total_reversals=total_reversals,
        total_refills=total_refills,
        today_doses_count=today_doses_count,
        chart_labels=chart_labels,
        chart_data=chart_data
    )


def _filtered_logs_for_export():
    profiles, profile_ids = _household_profile_ids()
    selected_profile_id = request.args.get('profile_id', type=int)
    selected_action = request.args.get('action', '').strip()

    query = DoseLog.query.join(Medication).filter(
        Medication.profile_id.in_(profile_ids)
    )

    if selected_profile_id and selected_profile_id in profile_ids:
        query = query.filter(Medication.profile_id == selected_profile_id)
    if selected_action in ['increment', 'decrement', 'refill']:
        query = query.filter(DoseLog.action == selected_action)

    return query.order_by(DoseLog.timestamp.desc()).all()


# Export Dose History to CSV
@main_bp.route('/history/export.csv')
@login_required
def export_history_csv():
    logs = _filtered_logs_for_export()

    output = io.StringIO()
    writer = csv.writer(output)

    tz_name = current_app.config.get('APP_TIMEZONE', 'Asia/Dhaka')

    # Write CSV Header
    writer.writerow([
        f'Timestamp ({tz_name})',
        'Date',
        'Time',
        'Family Member',
        'Relationship',
        'Medication Name',
        'Category / Genre',
        'Action',
        'Quantity Changed',
        'Log Notes'
    ])

    for log in logs:
        action_label = 'Dose Taken' if log.action == 'increment' else (
            'Dose Undone' if log.action == 'decrement' else 'Inventory Refill'
        )
        sign = '+' if log.action in ['increment', 'refill'] else '-'
        local_ts = utc_to_local(log.timestamp)
        writer.writerow([
            local_ts.strftime('%Y-%m-%d %H:%M:%S'),
            local_ts.strftime('%Y-%m-%d'),
            local_ts.strftime('%I:%M %p'),
            log.medication_ref.person.name,
            log.medication_ref.person.relationship,
            log.medication_ref.name,
            log.medication_ref.genre,
            action_label,
            f"{sign}{log.pills_changed}",
            log.notes or ''
        ])

    csv_data = output.getvalue()
    filename = f"meditrack_dose_history_{today_local().strftime('%Y%m%d')}.csv"

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename={filename}'}
    )


# Export Dose History to Excel (.xlsx)
@main_bp.route('/history/export.xlsx')
@login_required
def export_history_excel():
    logs = _filtered_logs_for_export()

    excel_bytes = generate_dose_history_excel(
        logs=logs,
        username=current_user.username,
        user_email=current_user.email,
        timezone_name=current_app.config.get('APP_TIMEZONE', 'Asia/Dhaka')
    )

    filename = f"meditrack_dose_history_{today_local().strftime('%Y%m%d')}.xlsx"

    return Response(
        excel_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment;filename={filename}'}
    )


# Doctor / Printable Medical Visit Summary
@main_bp.route('/summary')
@login_required
def export_summary():
    profiles, _ = _household_profile_ids()
    return render_template(
        'export_summary.html',
        profiles=profiles,
        generated_date=now_local().strftime('%B %d, %Y - %I:%M %p')
    )
