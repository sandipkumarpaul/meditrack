from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager
from app.utils.timeutil import today_local, now_local, utcnow_naive

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # A user can manage multiple family profiles (Self, Mom, Dad, Child, etc.)
    profiles = db.relationship('Profile', backref='account_owner', cascade='all, delete-orphan', lazy=True)
    push_subscriptions = db.relationship('PushSubscription', backref='subscriber', cascade='all, delete-orphan', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Profile(db.Model):
    __tablename__ = 'profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    relationship = db.Column(db.String(40), default='Self')
    date_of_birth = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Notification Preference Toggles
    notify_morning = db.Column(db.Boolean, default=True, nullable=False)
    notify_afternoon = db.Column(db.Boolean, default=True, nullable=False)
    notify_night = db.Column(db.Boolean, default=True, nullable=False)
    notify_low_stock = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # One profile has many medications
    medications = db.relationship(
        'Medication',
        backref='person',
        cascade='all, delete-orphan',
        lazy=True,
        order_by='Medication.created_at.desc()'
    )

    def active_medications(self):
        return [m for m in self.medications if m.is_active]

    def __repr__(self):
        return f'<Profile {self.name} ({self.relationship})>'


class Medication(db.Model):
    __tablename__ = 'medications'

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    genre = db.Column(db.String(50), nullable=False, default='General') # e.g. Antibiotic, Pain Relief, Cardiovascular
    dosage_target = db.Column(db.Integer, nullable=False, default=1)   # Pills to take per day
    pills_taken_today = db.Column(db.Integer, nullable=False, default=0) # Stepper tracks this
    total_stock = db.Column(db.Integer, nullable=False, default=30)      # Total pill inventory remaining
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=5) # Alert trigger threshold
    time_slot = db.Column(db.String(120), default='Morning')            # e.g., 'Morning, Night'
    instructions = db.Column(db.String(200), nullable=True)             # e.g., "Take 1 pill after lunch"
    prescribing_doctor = db.Column(db.String(100), nullable=True)       # e.g., "Dr. Smith"
    rx_number = db.Column(db.String(50), nullable=True)                 # Prescription #
    is_active = db.Column(db.Boolean, default=True, nullable=False)     # True for ongoing; False for archived course
    last_reset_date = db.Column(db.Date, default=date.today, nullable=False) # Automated daily reset tracking
    last_low_stock_notified_at = db.Column(db.Date, nullable=True)           # Tracks once-daily low stock alert
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    @property
    def time_slots_list(self):
        """Returns list of selected time slots."""
        if not self.time_slot:
            return []
        return [s.strip() for s in self.time_slot.split(',') if s.strip()]

    # Relationship to DoseLog
    dose_logs = db.relationship(
        'DoseLog',
        backref='medication_ref',
        cascade='all, delete-orphan',
        lazy=True,
        order_by='DoseLog.timestamp.desc()'
    )

    def check_and_reset_daily(self):
        """Automatically resets daily dose counter if the local calendar day changed."""
        today = today_local()
        if self.last_reset_date < today:
            self.pills_taken_today = 0
            self.last_reset_date = today
            return True
        return False

    @property
    def is_low_stock(self):
        return self.total_stock <= self.low_stock_threshold

    @property
    def adherence_percentage(self):
        if self.dosage_target <= 0:
            return 0
        return min(100, round((self.pills_taken_today / self.dosage_target) * 100))

    # Approximate hour (local time, 24h) by which each time-of-day slot's
    # dose is expected to have been taken. Used only for the "behind
    # schedule" hint -- the schema tracks a total daily count, not which
    # specific slot each dose belongs to, so this is a best-effort signal.
    _SLOT_EXPECTED_BY_HOUR = {
        'Morning': 12,
        'Afternoon': 17,
        'Evening': 20,
        'Night': 24,
        'Bedtime': 24,
    }

    def expected_doses_by_now(self):
        """How many of this medication's scheduled slots have already
        passed today, based on the current local hour."""
        hour = now_local().hour
        return sum(
            1 for slot in self.time_slots_list
            if hour >= self._SLOT_EXPECTED_BY_HOUR.get(slot, 25)
        )

    @property
    def is_behind_schedule(self):
        """True if fewer doses were logged today than the slots already
        passed would suggest -- a heuristic 'you might have missed a dose'
        flag, not a precise per-slot tracker."""
        if not self.is_active:
            return False
        expected = min(self.expected_doses_by_now(), self.dosage_target)
        return expected > 0 and self.pills_taken_today < expected

    def __repr__(self):
        return f'<Medication {self.name} - {self.genre}>'


class DoseLog(db.Model):
    __tablename__ = 'dose_logs'

    id = db.Column(db.Integer, primary_key=True)
    medication_id = db.Column(db.Integer, db.ForeignKey('medications.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False) # 'increment', 'decrement', 'refill'
    pills_changed = db.Column(db.Integer, nullable=False, default=1)
    timestamp = db.Column(db.DateTime, default=utcnow_naive, nullable=False)
    notes = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f'<DoseLog med_id={self.medication_id} action={self.action} at={self.timestamp}>'


class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    def __repr__(self):
        return f'<PushSubscription id={self.id} user_id={self.user_id}>'
