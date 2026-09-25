import hmac
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db, csrf, limiter
from app.models import Profile, PushSubscription
from app.services.notifications import check_and_send_reminders, send_web_push
from . import main_bp


@main_bp.route('/notifications')
@login_required
def notifications_settings():
    profiles = Profile.query.filter_by(user_id=current_user.id).order_by(Profile.created_at.asc()).all()
    push_count = PushSubscription.query.filter_by(user_id=current_user.id).count()
    cron_token = current_app.config.get('CRON_SECRET_TOKEN')
    cron_webhook_url = url_for('main.cron_check_reminders', token=cron_token, _external=True)
    vapid_public_key = current_app.config.get('VAPID_PUBLIC_KEY', '')

    return render_template(
        'notifications_settings.html',
        profiles=profiles,
        push_subscriptions_count=push_count,
        cron_webhook_url=cron_webhook_url,
        vapid_public_key=vapid_public_key
    )


@main_bp.route('/notifications/profile/<int:profile_id>', methods=['POST'])
@login_required
def save_profile_notification(profile_id):
    profile = Profile.query.filter_by(id=profile_id, user_id=current_user.id).first_or_404()

    profile.notify_morning = bool(request.form.get('notify_morning'))
    profile.notify_afternoon = bool(request.form.get('notify_afternoon'))
    profile.notify_night = bool(request.form.get('notify_night'))
    profile.notify_low_stock = bool(request.form.get('notify_low_stock'))

    db.session.commit()
    flash(f'Notification preferences saved for {profile.name}.', 'success')
    return redirect(url_for('main.notifications_settings'))


@main_bp.route('/api/notifications/subscribe', methods=['POST'])
@login_required
def subscribe_push():
    data = request.get_json() or {}
    endpoint = data.get('endpoint')
    keys = data.get('keys', {})
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')

    if not endpoint or not p256dh or not auth:
        return jsonify({'success': False, 'error': 'Invalid subscription payload'}), 400

    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if not sub:
        sub = PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=request.headers.get('User-Agent', '')[:255]
        )
        db.session.add(sub)
    else:
        sub.user_id = current_user.id
        sub.p256dh = p256dh
        sub.auth = auth

    db.session.commit()
    return jsonify({'success': True, 'subscription_id': sub.id})


@main_bp.route('/api/notifications/test-push', methods=['POST'])
@login_required
def test_push():
    subs = PushSubscription.query.filter_by(user_id=current_user.id).all()
    if not subs:
        return jsonify({'success': False, 'error': 'No active browser push subscriptions found'}), 400

    payload = {
        "title": "💊 MediTrack Test Notification",
        "body": "Web browser push notifications are working smoothly!",
        "url": "/dashboard",
        "tag": "meditrack-test"
    }

    success_count = 0
    errors = []
    for sub in subs:
        res = send_web_push(sub, payload)
        if res.get('success'):
            success_count += 1
        else:
            errors.append(res.get('error'))

    return jsonify({
        'success': success_count > 0,
        'devices_notified': success_count,
        'errors': errors
    })


# Called by an external cron pinger (e.g. cron-job.org), not a logged-in
# browser session -- authenticated by the shared secret token instead of a
# CSRF token/session cookie, so it must be exempt from CSRF checks.
@main_bp.route('/api/cron/check-reminders', methods=['GET', 'POST'])
@csrf.exempt
@limiter.limit("20 per minute")
def cron_check_reminders():
    token = request.args.get('token') or request.headers.get('X-Cron-Secret')
    expected_token = current_app.config.get('CRON_SECRET_TOKEN')

    if not token or not expected_token or not hmac.compare_digest(token.encode(), expected_token.encode()):
        return jsonify({'success': False, 'error': 'Unauthorized: invalid or missing cron token'}), 401

    slot = request.args.get('slot', 'auto')
    force = request.args.get('force', '').lower() in ('true', '1')
    app_url = url_for('main.dashboard', _external=True)

    results = check_and_send_reminders(slot=slot, force=force, app_url=app_url)
    return jsonify(results)
