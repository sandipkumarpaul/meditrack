import json
import logging
import time
from flask import current_app
from app import db
from app.models import User, Profile, Medication, PushSubscription
from app.utils.timeutil import now_local, today_local, utcnow_naive

logger = logging.getLogger(__name__)


def send_web_push(subscription, payload_dict):
    """
    Send an end-to-end encrypted Web Push notification to a browser
    PushSubscription using pywebpush (RFC 8291 / VAPID).
    Automatically prunes expired or unregistered (404/410) subscriptions.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {"success": False, "error": "pywebpush not installed"}

    vapid_private_key = current_app.config.get('VAPID_PRIVATE_KEY')
    vapid_email = current_app.config.get('VAPID_CLAIMS_EMAIL', 'admin@meditrack.local')

    if not vapid_private_key:
        return {"success": False, "error": "VAPID private key is not configured"}

    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth
        }
    }

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload_dict),
            vapid_private_key=vapid_private_key,
            vapid_claims={"sub": f"mailto:{vapid_email}"}
        )
        return {"success": True}
    except WebPushException as ex:
        # If client unregistered or subscription expired, prune from database
        if ex.response and ex.response.status_code in (404, 410):
            logger.info(f"Removing expired push subscription {subscription.id}")
            try:
                db.session.delete(subscription)
                db.session.commit()
            except Exception:
                pass
        return {"success": False, "error": str(ex)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_current_time_slot():
    """Determine default time slot based on the household's local hour."""
    hour = now_local().hour
    if 5 <= hour < 12:
        return "Morning"
    elif 12 <= hour < 17:
        return "Afternoon"
    elif 17 <= hour < 22:
        return "Evening"
    else:
        return "Night"


def check_and_send_reminders(slot='auto', user_id=None, force=False, app_url=None):
    """
    Core engine to evaluate all profiles, check due medications, deduplicate
    alerts, and dispatch end-to-end encrypted Web Push notifications to registered devices.
    """
    if slot == 'auto':
        slot = get_current_time_slot()

    today = today_local()
    results = {
        "timestamp": utcnow_naive().isoformat(),
        "slot_evaluated": slot,
        "web_push_sent": 0,
        "skipped_profiles": 0,
        "details": []
    }

    query = Profile.query
    if user_id:
        query = query.filter_by(user_id=user_id)
    profiles = query.all()

    for profile in profiles:
        user = profile.account_owner

        # Check slot preference for this profile
        slot_enabled = True
        if slot == 'Morning' and not profile.notify_morning:
            slot_enabled = False
        elif slot == 'Afternoon' and not profile.notify_afternoon:
            slot_enabled = False
        elif (slot in ('Evening', 'Night')) and not profile.notify_night:
            slot_enabled = False

        # Gather due medications
        active_meds = profile.active_medications()
        due_meds = []
        low_stock_meds = []

        for med in active_meds:
            med.check_and_reset_daily()

            # Check if scheduled for this slot
            is_slot_match = (
                slot == 'All' or
                slot in med.time_slots_list or
                (slot == 'Night' and 'Bedtime' in med.time_slots_list)
            )

            # Smart skip: only due if pills taken today < daily target
            if is_slot_match and (med.pills_taken_today < med.dosage_target or force):
                due_meds.append(med)

            # Check low stock with once-daily deduplication
            if med.is_low_stock:
                if force or med.last_low_stock_notified_at != today:
                    low_stock_meds.append(med)
                    med.last_low_stock_notified_at = today

        # If nothing is due and no low stock alerts, skip this profile
        if not due_meds and not low_stock_meds:
            results["skipped_profiles"] += 1
            continue

        profile_log = {
            "profile_name": profile.name,
            "due_meds_count": len(due_meds),
            "low_stock_count": len(low_stock_meds),
            "web_push": None
        }

        # Web Push Delivery (to user's subscribed devices with end-to-end encryption)
        if user and user.push_subscriptions and (due_meds or low_stock_meds) and slot_enabled:
            med_names = ", ".join([m.name for m in due_meds]) if due_meds else "Check inventory"
            push_body = f"{profile.name}: Time for {med_names}."
            if low_stock_meds and profile.notify_low_stock:
                push_body += f" ({len(low_stock_meds)} low in stock!)"

            push_payload = {
                "title": f"💊 MediTrack: {slot} Medicine Reminder",
                "body": push_body,
                "url": "/dashboard",
                "tag": f"meditrack-{profile.id}-{slot.lower()}",
                "timestamp": int(time.time() * 1000)
            }

            push_count = 0
            for sub in user.push_subscriptions:
                res = send_web_push(sub, push_payload)
                if res.get("success"):
                    push_count += 1
            
            profile_log["web_push"] = f"Sent to {push_count} device(s)"
            results["web_push_sent"] += push_count

        results["details"].append(profile_log)

    # Commit any low stock date updates
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to commit notification tracking updates: {e}")

    return results
