"""
Populates the database with a demo household so the app can be explored
without typing in data by hand.

    python scripts/seed_demo.py            # create the demo account
    python scripts/seed_demo.py --reset    # delete and recreate it

Log in afterwards with  username: demo  /  password: demo1234
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db  # noqa: E402
from app.models import User, Profile, Medication, DoseLog  # noqa: E402
from app.utils.timeutil import get_app_timezone, today_local, now_local  # noqa: E402

DEMO_USERNAME = 'demo'
DEMO_EMAIL = 'demo@meditrack.local'
DEMO_PASSWORD = 'demo1234'
HISTORY_DAYS = 14

# Local hour at which each slot's dose is typically logged.
SLOT_HOURS = {'Morning': 8, 'Afternoon': 14, 'Evening': 19, 'Night': 22, 'Bedtime': 22}

HOUSEHOLD = [
    {
        'profile': {'relationship': 'Self', 'notes': None},
        'meds': [
            dict(name='Omeprazole 20mg', genre='Digestive', dosage_target=1, total_stock=24,
                 time_slot='Morning', instructions='30 min before breakfast',
                 prescribing_doctor='Dr. Rahman / Square Hospital'),
            dict(name='Cetirizine 10mg', genre='Allergy', dosage_target=1, total_stock=4,
                 time_slot='Night', instructions='May cause drowsiness'),
        ],
    },
    {
        'profile': {'name': 'Ayesha (Mom)', 'relationship': 'Mom',
                    'notes': 'Type 2 diabetes, allergic to sulfa drugs'},
        'meds': [
            dict(name='Metformin 500mg', genre='Diabetes', dosage_target=2, total_stock=48,
                 time_slot='Morning, Night', instructions='Take with meals',
                 prescribing_doctor='Dr. Karim / Labaid'),
            dict(name='Amlodipine 5mg', genre='Cardiovascular', dosage_target=1, total_stock=3,
                 time_slot='Morning', instructions='Same time every day',
                 prescribing_doctor='Dr. Karim / Labaid'),
            dict(name='Vitamin D3 1000 IU', genre='Supplement & Vitamin', dosage_target=1,
                 total_stock=55, time_slot='Afternoon', instructions='After lunch'),
        ],
    },
    {
        'profile': {'name': 'Rafiq (Grandpa)', 'relationship': 'Grandparent',
                    'notes': 'Mild hypertension'},
        'meds': [
            dict(name='Atorvastatin 10mg', genre='Cardiovascular', dosage_target=1, total_stock=26,
                 time_slot='Bedtime', instructions='At bedtime'),
            dict(name='Amoxicillin 500mg', genre='Antibiotic', dosage_target=3, total_stock=0,
                 time_slot='Morning, Afternoon, Night', instructions='7-day course, completed',
                 is_active=False),
        ],
    },
]


def _local_to_utc_naive(local_date, hour, minute):
    tz = get_app_timezone()
    local_dt = datetime(local_date.year, local_date.month, local_date.day, hour, minute, tzinfo=tz)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def seed(reset=False):
    existing = User.query.filter_by(username=DEMO_USERNAME).first()
    if existing:
        if not reset:
            print(f'Demo account "{DEMO_USERNAME}" already exists. Use --reset to recreate it.')
            return
        db.session.delete(existing)
        db.session.commit()

    rng = random.Random(42)
    today = today_local()
    current_hour = now_local().hour

    user = User(username=DEMO_USERNAME, email=DEMO_EMAIL)
    user.set_password(DEMO_PASSWORD)
    db.session.add(user)
    db.session.flush()

    for member in HOUSEHOLD:
        profile_fields = dict(member['profile'])
        profile_fields.setdefault('name', DEMO_USERNAME)
        profile = Profile(user_id=user.id, **profile_fields)
        db.session.add(profile)
        db.session.flush()

        meds = []
        for med_fields in member['meds']:
            med = Medication(profile_id=profile.id, last_reset_date=today, **med_fields)
            db.session.add(med)
            db.session.flush()
            meds.append(med)

            # Past days: most scheduled doses taken, a few missed.
            for days_ago in range(HISTORY_DAYS - 1, 0, -1):
                day = today - timedelta(days=days_ago)
                if not med.is_active and days_ago < 5:
                    continue  # the antibiotic course ended a few days ago
                for slot in med.time_slots_list:
                    if rng.random() < 0.88:
                        db.session.add(DoseLog(
                            medication_id=med.id, action='increment', pills_changed=1,
                            timestamp=_local_to_utc_naive(day, SLOT_HOURS.get(slot, 9), rng.randint(0, 50)),
                            notes='Logged dose',
                        ))

            # Today: doses for slots that have already passed.
            if med.is_active:
                for slot in med.time_slots_list:
                    slot_hour = SLOT_HOURS.get(slot, 9)
                    if slot_hour <= current_hour and med.pills_taken_today < med.dosage_target:
                        med.pills_taken_today += 1
                        db.session.add(DoseLog(
                            medication_id=med.id, action='increment', pills_changed=1,
                            timestamp=_local_to_utc_naive(today, slot_hour, rng.randint(0, 50)),
                            notes=f'Logged dose ({med.pills_taken_today}/{med.dosage_target})',
                        ))

        if profile.relationship == 'Mom':
            metformin = next(m for m in meds if m.name.startswith('Metformin'))
            db.session.add(DoseLog(
                medication_id=metformin.id, action='refill', pills_changed=30,
                timestamp=_local_to_utc_naive(today - timedelta(days=6), 18, 30),
                notes='Added 30 pills',
            ))

    db.session.commit()
    print(f'Demo household created. Log in with  {DEMO_USERNAME} / {DEMO_PASSWORD}')


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        seed(reset='--reset' in sys.argv)
