"""
Pytest suite for MediTrack. Run with: pytest
Covers auth, profiles, medications, the AJAX stepper, daily reset, exports,
the reminder engine, MedEx parsing, and security behaviour (login open-redirect
guard, cron token check, MedEx SSRF guard, type-to-confirm deletes).
"""
import io
from datetime import date, timedelta

import pytest
from app.models import User, Profile, Medication, DoseLog, PushSubscription


@pytest.fixture()
def signed_up(client, db):
    """Signs up a user (creating their default 'Self' profile) and returns it, logged in."""
    client.post('/signup', data={
        'username': 'alice',
        'email': 'alice@example.com',
        'password': 'password123'
    }, follow_redirects=True)
    return User.query.filter_by(username='alice').first()


@pytest.fixture()
def dad_profile(client, db, signed_up):
    client.post('/profile/add', data={
        'name': 'Robert (Dad)',
        'relationship': 'Dad',
        'date_of_birth': '1960-05-14',
        'notes': 'Mild hypertension, allergic to Penicillin'
    }, follow_redirects=True)
    return Profile.query.filter_by(name='Robert (Dad)').first()


class TestAuth:
    def test_signup_creates_user_and_default_profile(self, client, db):
        res = client.post('/signup', data={
            'username': 'alice',
            'email': 'alice@example.com',
            'password': 'password123'
        }, follow_redirects=True)
        assert res.status_code == 200

        user = User.query.filter_by(username='alice').first()
        assert user is not None
        assert user.check_password('password123')
        assert len(user.profiles) == 1
        assert user.profiles[0].relationship == 'Self'

    def test_login_rejects_wrong_password(self, client, signed_up):
        client.get('/logout')  # the signup fixture leaves the session logged in
        res = client.post('/login', data={
            'identifier': 'alice',
            'password': 'wrong-password'
        }, follow_redirects=True)
        assert b'Invalid username/email or password' in res.data

    @pytest.mark.parametrize('next_url', [
        'https://evil.example/phish',
        '//evil.example/phish',
        '/\\evil.example/phish',
    ])
    def test_login_ignores_external_next_redirect(self, client, signed_up, next_url):
        client.get('/logout')
        res = client.post(f'/login?next={next_url}', data={
            'identifier': 'alice',
            'password': 'password123'
        })
        assert res.status_code == 302
        assert res.headers['Location'].endswith('/dashboard')

    def test_login_follows_internal_next_redirect(self, client, signed_up):
        client.get('/logout')
        res = client.post('/login?next=/history', data={
            'identifier': 'alice',
            'password': 'password123'
        })
        assert res.status_code == 302
        assert res.headers['Location'].endswith('/history')

    def test_settings_username_change_syncs_self_profile(self, client, db, signed_up):
        client.post('/settings', data={
            'action': 'update_username',
            'username': 'alice_medic'
        }, follow_redirects=True)

        db.session.refresh(signed_up)
        self_profile = Profile.query.filter_by(user_id=signed_up.id, relationship='Self').first()
        assert signed_up.username == 'alice_medic'
        assert self_profile.name == 'alice_medic'

    def test_delete_account_requires_correct_password_and_confirm_text(self, client, db, signed_up):
        # Wrong confirm text -> account survives
        client.post('/settings/delete-account', data={
            'password': 'password123',
            'confirm_text': 'not delete'
        }, follow_redirects=True)
        assert User.query.filter_by(username='alice').first() is not None

        # Wrong password -> account survives
        client.post('/settings/delete-account', data={
            'password': 'wrong-password',
            'confirm_text': 'DELETE'
        }, follow_redirects=True)
        assert User.query.filter_by(username='alice').first() is not None

        # Correct password + exact confirm text -> account and its data are gone
        user_id = signed_up.id
        client.post('/settings/delete-account', data={
            'password': 'password123',
            'confirm_text': 'DELETE'
        }, follow_redirects=True)
        assert db.session.get(User, user_id) is None

    def test_export_data_returns_json_backup(self, client, db, dad_profile):
        client.post('/medication/add', data={
            'profile_id': dad_profile.id,
            'name': 'Lisinopril',
            'genre': 'Cardiovascular',
            'dosage_target': 1,
            'total_stock': 10,
            'low_stock_threshold': 5,
            'time_slot': 'Morning',
        }, follow_redirects=True)

        res = client.get('/settings/export-data')
        assert res.status_code == 200
        assert res.mimetype == 'application/json'
        import json
        payload = json.loads(res.data)
        assert payload['account']['username'] == 'alice'
        profile_names = [p['name'] for p in payload['profiles']]
        assert 'Robert (Dad)' in profile_names


class TestProfilesAndMedications:
    def test_add_family_profile(self, client, db, dad_profile):
        assert dad_profile is not None
        assert dad_profile.relationship == 'Dad'

    def test_delete_profile_requires_exact_name_match(self, client, db, dad_profile):
        # Wrong confirmation text -> profile survives
        res = client.post(f'/profile/{dad_profile.id}/delete', data={
            'confirm_text': 'wrong name'
        }, follow_redirects=True)
        assert res.status_code == 200
        assert db.session.get(Profile, dad_profile.id) is not None

        # Exact name -> profile (and cascade) is deleted
        client.post(f'/profile/{dad_profile.id}/delete', data={
            'confirm_text': dad_profile.name
        }, follow_redirects=True)
        assert db.session.get(Profile, dad_profile.id) is None

    def test_add_medication_with_multiple_time_slots(self, client, db, dad_profile):
        client.post('/medication/add', data={
            'profile_id': dad_profile.id,
            'name': 'Metformin',
            'genre': 'Diabetes',
            'dosage_target': 2,
            'total_stock': 30,
            'low_stock_threshold': 5,
            'time_slots': ['Morning', 'Night'],
            'instructions': 'Take with meals'
        }, follow_redirects=True)

        med = Medication.query.filter_by(name='Metformin').first()
        assert med is not None
        assert set(med.time_slots_list) == {'Morning', 'Night'}

    def test_delete_medication_requires_exact_name_match(self, client, db, dad_profile):
        client.post('/medication/add', data={
            'profile_id': dad_profile.id,
            'name': 'Lisinopril',
            'genre': 'Cardiovascular',
            'dosage_target': 1,
            'total_stock': 10,
            'low_stock_threshold': 5,
            'time_slot': 'Morning',
        }, follow_redirects=True)
        med = Medication.query.filter_by(name='Lisinopril').first()

        client.post(f'/medication/{med.id}/delete', data={'confirm_text': 'nope'}, follow_redirects=True)
        assert db.session.get(Medication, med.id) is not None

        client.post(f'/medication/{med.id}/delete', data={'confirm_text': 'Lisinopril'}, follow_redirects=True)
        assert db.session.get(Medication, med.id) is None


class TestDoseStepperAndInventory:
    @pytest.fixture()
    def med(self, client, db, dad_profile):
        client.post('/medication/add', data={
            'profile_id': dad_profile.id,
            'name': 'Lisinopril',
            'genre': 'Cardiovascular',
            'dosage_target': 2,
            'total_stock': 10,
            'low_stock_threshold': 5,
            'time_slot': 'Morning',
        }, follow_redirects=True)
        return Medication.query.filter_by(name='Lisinopril').first()

    def test_increment_logs_dose_and_decrements_stock(self, client, db, med):
        res = client.post(f'/api/medication/{med.id}/step', json={'action': 'increment'})
        data = res.get_json()
        assert data['success'] is True
        assert data['pills_taken_today'] == 1
        assert data['total_stock'] == 9
        assert data['adherence_percentage'] == 50
        assert DoseLog.query.filter_by(medication_id=med.id, action='increment').count() == 1

    def test_decrement_restores_stock(self, client, db, med):
        client.post(f'/api/medication/{med.id}/step', json={'action': 'increment'})
        res = client.post(f'/api/medication/{med.id}/step', json={'action': 'decrement'})
        data = res.get_json()
        assert data['pills_taken_today'] == 0
        assert data['total_stock'] == 10

    def test_decrement_at_zero_is_a_noop(self, client, db, med):
        res = client.post(f'/api/medication/{med.id}/step', json={'action': 'decrement'})
        data = res.get_json()
        assert data['success'] is True
        assert data['pills_taken_today'] == 0
        assert med.total_stock == 10  # unchanged

    def test_low_stock_flag(self, db, med):
        med.total_stock = 4
        db.session.commit()
        assert med.is_low_stock is True

    def test_quick_refill_adds_stock_and_logs(self, client, db, med):
        res = client.post(f'/medication/{med.id}/refill', data={'refill_amount': 30}, follow_redirects=True)
        assert res.status_code == 200
        db.session.refresh(med)
        assert med.total_stock == 40
        refill_log = DoseLog.query.filter_by(medication_id=med.id, action='refill').first()
        assert refill_log.pills_changed == 30

    def test_daily_reset_zeroes_pills_taken(self, db, med):
        med.last_reset_date = date.today() - timedelta(days=1)
        med.pills_taken_today = 2
        db.session.commit()

        assert med.check_and_reset_daily() is True
        assert med.pills_taken_today == 0


class TestHistoryAndExports:
    @pytest.fixture()
    def logged_med(self, client, db, dad_profile):
        client.post('/medication/add', data={
            'profile_id': dad_profile.id,
            'name': 'Lisinopril',
            'genre': 'Cardiovascular',
            'dosage_target': 1,
            'total_stock': 10,
            'low_stock_threshold': 5,
            'time_slot': 'Morning',
        }, follow_redirects=True)
        med = Medication.query.filter_by(name='Lisinopril').first()
        client.post(f'/api/medication/{med.id}/step', json={'action': 'increment'})
        return med

    def test_history_page_renders(self, client, logged_med):
        res = client.get('/history')
        assert res.status_code == 200
        assert b'Audit Trail' in res.data

    def test_csv_export_contains_logged_dose(self, client, logged_med):
        res = client.get('/history/export.csv')
        assert res.status_code == 200
        assert res.mimetype == 'text/csv'
        assert b'Lisinopril' in res.data
        assert b'Dose Taken' in res.data

    def test_excel_export_is_a_valid_workbook(self, client, logged_med):
        import openpyxl
        res = client.get('/history/export.xlsx')
        assert res.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb['Dose History']
        assert ws.cell(row=4, column=1).value == "Date"

    def test_doctor_summary_lists_active_medications(self, client, dad_profile, logged_med):
        res = client.get('/summary')
        assert res.status_code == 200
        assert b'Lisinopril' in res.data
        assert b'Robert (Dad)' in res.data


class TestNotificationsAndCron:
    def test_cron_webhook_rejects_missing_or_wrong_token(self, client):
        assert client.get('/api/cron/check-reminders').status_code == 401
        assert client.get('/api/cron/check-reminders?token=wrong').status_code == 401

    def test_cron_webhook_accepts_valid_token(self, client, app):
        token = app.config['CRON_SECRET_TOKEN']
        res = client.get(f'/api/cron/check-reminders?token={token}&slot=Morning')
        assert res.status_code == 200
        assert res.get_json()['slot_evaluated'] == 'Morning'

    def test_push_subscription_is_saved_for_current_user(self, client, db, signed_up):
        res = client.post('/api/notifications/subscribe', json={
            'endpoint': 'https://fcm.googleapis.com/fcm/send/test-endpoint',
            'keys': {'p256dh': 'sample-p256dh', 'auth': 'sample-auth'}
        })
        assert res.status_code == 200
        sub = PushSubscription.query.filter_by(endpoint='https://fcm.googleapis.com/fcm/send/test-endpoint').first()
        assert sub is not None
        assert sub.user_id == signed_up.id


    def test_profile_notification_preferences_are_saved(self, client, db, dad_profile):
        res = client.post(f'/notifications/profile/{dad_profile.id}', data={
            'notify_morning': 'on',
            'notify_afternoon': 'on',
            'notify_low_stock': 'on'
            # notify_night omitted -> unchecked checkbox
        }, follow_redirects=True)
        assert res.status_code == 200
        db.session.refresh(dad_profile)
        assert dad_profile.notify_morning is True
        assert dad_profile.notify_night is False
        assert dad_profile.notify_low_stock is True

    def test_reminder_engine_skips_taken_doses_and_dedupes_low_stock(self, db, signed_up, dad_profile):
        from app.services.notifications import check_and_send_reminders
        from app.utils.timeutil import today_local

        med = Medication(
            profile_id=dad_profile.id, name='Amlodipine', genre='Cardiovascular',
            dosage_target=1, total_stock=3, low_stock_threshold=5,
            time_slot='Morning', is_active=True, last_reset_date=today_local()
        )
        db.session.add(med)
        db.session.commit()

        # First run: the Morning dose is due and stock is low -> Dad is flagged
        first = check_and_send_reminders(slot='Morning', user_id=signed_up.id)
        dad_entry = next(d for d in first['details'] if d['profile_name'] == dad_profile.name)
        assert dad_entry['due_meds_count'] == 1
        assert dad_entry['low_stock_count'] == 1
        db.session.refresh(med)
        assert med.last_low_stock_notified_at == today_local()

        # Dose taken + low-stock alert already sent today -> nothing left to remind about
        med.pills_taken_today = 1
        db.session.commit()
        second = check_and_send_reminders(slot='Morning', user_id=signed_up.id)
        assert all(d['profile_name'] != dad_profile.name for d in second['details'])

    def test_service_worker_is_served_from_root(self, client):
        res = client.get('/sw.js')
        assert res.status_code == 200
        assert b'notificationclick' in res.data


class TestMedexParsing:
    """Offline checks for the MedEx scraper's parsing helpers (no network)."""

    def test_package_counts_from_strip_notation(self):
        from app.services.medex import parse_package_counts
        info = parse_package_counts(['(11 x 12: ৳ 330.00)'])
        assert info['strip_size'] == 12
        assert info['box_size'] == 132

    def test_genre_mapping(self):
        from app.services.medex import map_genre
        assert map_genre('Non-steroidal Anti-inflammatory Drugs (NSAID)') == 'Pain Relief'
        assert map_genre('Proton Pump Inhibitor') == 'Digestive'
        assert map_genre('') == 'General'


class TestMedexSsrfGuard:
    """
    get_medex_details() is called with a client-supplied URL. Before the fix
    it would perform a server-side request to ANY url the caller provided.
    """

    def test_rejects_non_medex_domain(self, client, signed_up):
        res = client.get('/api/medex/details?url=http://169.254.169.254/latest/meta-data/')
        assert res.status_code == 400
        assert res.get_json()['success'] is False

    def test_rejects_lookalike_domain(self, client, signed_up):
        res = client.get('/api/medex/details?url=https://medex.com.bd.evil.com/brands/1/x')
        assert res.status_code == 400

    def test_service_layer_guard_directly(self):
        from app.services.medex import is_allowed_medex_url
        assert is_allowed_medex_url('https://medex.com.bd/brands/123/napa') is True
        assert is_allowed_medex_url('https://sub.medex.com.bd/brands/123/napa') is True
        assert is_allowed_medex_url('https://medex.com.bd.evil.com/x') is False
        assert is_allowed_medex_url('http://127.0.0.1/') is False
        assert is_allowed_medex_url('file:///etc/passwd') is False
        assert is_allowed_medex_url('') is False
