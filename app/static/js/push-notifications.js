// MediTrack Browser Web Push Client Helper

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/\-/g, '+')
        .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

const PushClient = {
    vapidPublicKey: null,

    async init(vapidKey) {
        this.vapidPublicKey = vapidKey;
        this.updateUiState();
    },

    isSupported() {
        return ('serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window);
    },

    getPermissionState() {
        if (!this.isSupported()) return 'unsupported';
        return Notification.permission; // 'default', 'granted', 'denied'
    },

    updateUiState() {
        const badge = document.getElementById('pushStatusBadge');
        const enableBtn = document.getElementById('enablePushBtn');
        const testBtn = document.getElementById('testPushBtn');

        if (!badge) return;

        if (!this.isSupported()) {
            badge.className = 'badge bg-secondary';
            badge.textContent = 'Not Supported on this Browser';
            if (enableBtn) enableBtn.disabled = true;
            if (testBtn) testBtn.disabled = true;
            return;
        }

        const perm = Notification.permission;
        if (perm === 'granted') {
            badge.className = 'badge bg-success';
            badge.textContent = 'Active on this Browser';
            if (enableBtn) {
                enableBtn.textContent = 'Push Notifications Enabled';
                enableBtn.className = 'btn btn-outline-success rounded-pill px-4 fw-semibold';
                enableBtn.disabled = true;
            }
            if (testBtn) testBtn.disabled = false;
        } else if (perm === 'denied') {
            badge.className = 'badge bg-danger';
            badge.textContent = 'Blocked by Browser';
            if (enableBtn) {
                enableBtn.textContent = 'Notifications Blocked';
                enableBtn.disabled = true;
            }
            if (testBtn) testBtn.disabled = true;
        } else {
            badge.className = 'badge bg-warning text-dark';
            badge.textContent = 'Not Enabled Yet';
            if (enableBtn) {
                enableBtn.textContent = 'Enable Browser Notifications';
                enableBtn.disabled = false;
            }
            if (testBtn) testBtn.disabled = true;
        }
    },

    async enablePush() {
        if (!this.isSupported()) {
            alert('Push notifications are not supported on this browser.');
            return false;
        }

        if (!this.vapidPublicKey) {
            alert('VAPID public key is missing on the server.');
            return false;
        }

        try {
            const permission = await Notification.requestPermission();
            this.updateUiState();

            if (permission !== 'granted') {
                alert('Permission was not granted for push notifications.');
                return false;
            }

            // Register service worker
            const registration = await navigator.serviceWorker.register('/sw.js');
            await navigator.serviceWorker.ready;

            // Subscribe to push
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(this.vapidPublicKey)
            });

            // Send subscription to server
            const res = await fetch('/api/notifications/subscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.getCsrfToken ? window.getCsrfToken() : ''
                },
                body: JSON.stringify(subscription)
            });

            const result = await res.json();
            if (result.success) {
                this.updateUiState();
                if (window.showToast) {
                    window.showToast('Browser push notifications enabled successfully!', 'Push Notifications', 'success');
                } else {
                    alert('Browser push notifications enabled successfully!');
                }
                return true;
            } else {
                alert('Failed to register subscription: ' + (result.error || 'Unknown error'));
                return false;
            }
        } catch (err) {
            console.error('Error enabling push:', err);
            alert('Could not enable push notifications: ' + err.message);
            return false;
        }
    },

    async sendTestPush() {
        const testBtn = document.getElementById('testPushBtn');
        if (testBtn) testBtn.disabled = true;

        try {
            const res = await fetch('/api/notifications/test-push', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.getCsrfToken ? window.getCsrfToken() : ''
                }
            });
            const data = await res.json();
            if (data.success) {
                if (window.showToast) {
                    window.showToast('Test notification sent! Check your system notification area.', 'Push Notifications', 'success');
                } else {
                    alert('Test notification sent!');
                }
            } else {
                alert('Test push failed: ' + (data.error || 'Unknown error'));
            }
        } catch (err) {
            alert('Error sending test push: ' + err.message);
        } finally {
            if (testBtn) testBtn.disabled = false;
        }
    }
};

window.PushClient = PushClient;
