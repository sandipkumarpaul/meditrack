// MediTrack Frontend JavaScript Controller

// CSRF token for same-origin AJAX POSTs (Flask-WTF checks this header on unsafe methods)
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}
window.getCsrfToken = getCsrfToken;

// Escapes text before it is interpolated into an HTML string. Medication
// names are user-entered and MedEx results are scraped third-party HTML, so
// neither may be inserted via innerHTML unescaped.
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

document.addEventListener('DOMContentLoaded', () => {

    // Helper: Show floating Bootstrap Toast
    function showToast(message, title = 'MediTrack Notice', type = 'primary') {
        const toastContainer = document.getElementById('toastPlacement');
        if (!toastContainer) return;

        const toastId = 'toast-' + Date.now();
        const iconClass = type === 'danger' ? 'bi-exclamation-triangle-fill text-danger' :
                          type === 'success' ? 'bi-check-circle-fill text-success' :
                          'bi-info-circle-fill text-primary';

        const toastHtml = `
            <div id="${toastId}" class="toast align-items-center shadow-lg border-0 mb-2" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header bg-white">
                    <i class="bi ${iconClass} me-2 fs-6"></i>
                    <strong class="me-auto text-dark">${escapeHtml(title)}</strong>
                    <small class="text-muted">Just now</small>
                    <button type="button" class="btn-close ms-2 mb-1" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
                <div class="toast-body bg-light text-dark py-2">
                    ${message}
                </div>
            </div>
        `;

        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
        const toastEl = document.getElementById(toastId);
        const bsToast = new bootstrap.Toast(toastEl, { delay: 3500 });
        bsToast.show();

        toastEl.addEventListener('hidden.bs.toast', () => {
            toastEl.remove();
        });
    }
    window.showToast = showToast;

    // Handle large touch-friendly + and - dose steppers
    document.querySelectorAll('.btn-stepper').forEach(button => {
        button.addEventListener('click', async function(e) {
            e.preventDefault();
            const medId = this.getAttribute('data-id');
            const action = this.getAttribute('data-action');
            const originalButtonContent = this.innerHTML;

            // Visual active feedback
            this.classList.add('opacity-75');

            try {
                const response = await fetch(`/api/medication/${medId}/step`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify({ action: action })
                });

                if (!response.ok) {
                    throw new Error(`HTTP error ${response.status}`);
                }

                const data = await response.json();

                if (data.success) {
                    // Update pills taken count
                    const takenEl = document.getElementById(`taken-count-${medId}`);
                    if (takenEl) {
                        takenEl.innerText = data.pills_taken_today;
                        if (data.pills_taken_today >= data.dosage_target) {
                            takenEl.classList.add('text-success');
                            takenEl.classList.remove('text-primary');
                        } else {
                            takenEl.classList.add('text-primary');
                            takenEl.classList.remove('text-success');
                        }
                    }

                    // Update adherence progress bar
                    const progressEl = document.getElementById(`progress-bar-${medId}`);
                    if (progressEl) {
                        const pct = Math.min(100, Math.round(data.adherence_percentage));
                        progressEl.style.width = `${pct}%`;
                        progressEl.setAttribute('aria-valuenow', pct);
                        if (pct >= 100) {
                            progressEl.className = 'progress-bar bg-success';
                        } else {
                            progressEl.className = 'progress-bar bg-primary';
                        }
                    }

                    // Update total stock count and low stock badge
                    const stockEl = document.getElementById(`stock-count-${medId}`);
                    if (stockEl) {
                        if (data.is_low_stock) {
                            stockEl.className = 'badge bg-danger text-white shadow-sm';
                            stockEl.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-1"></i>${data.total_stock} pills (Low)`;
                        } else {
                            stockEl.className = 'badge bg-light text-dark border';
                            stockEl.innerHTML = `${data.total_stock} pills`;
                        }
                    }

                    // Update "behind schedule" hint badge
                    const scheduleEl = document.getElementById(`schedule-badge-${medId}`);
                    if (scheduleEl) {
                        scheduleEl.classList.toggle('d-none', !data.is_behind_schedule);
                    }

                    // Dose completion celebration toast
                    if (action === 'increment' && data.pills_taken_today === data.dosage_target) {
                        showToast(`Great job! Daily dosage target reached for <strong>${escapeHtml(data.name)}</strong>.`, 'Target Complete 🎉', 'success');
                    } else if (action === 'increment' && data.is_low_stock) {
                        showToast(`Dose recorded for <strong>${escapeHtml(data.name)}</strong>. Note: Stock is running low (${data.total_stock} pills remaining).`, 'Stock Warning', 'danger');
                    }
                } else {
                    showToast(escapeHtml(data.error || 'Failed to update dose count.'), 'Action Error', 'danger');
                }
            } catch (err) {
                console.error('Stepper network error:', err);
                showToast('Could not reach the server. Please check your connection.', 'Connection Error', 'danger');
            } finally {
                this.classList.remove('opacity-75');
            }
        });
    });

    // Handle Quick Refill buttons via AJAX
    document.querySelectorAll('.btn-quick-refill').forEach(button => {
        button.addEventListener('click', async function(e) {
            e.preventDefault();
            const medId = this.getAttribute('data-id');
            const refillAmount = this.getAttribute('data-amount') || 30;

            const formData = new FormData();
            formData.append('refill_amount', refillAmount);

            try {
                const response = await fetch(`/medication/${medId}/refill`, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: formData
                });

                if (response.ok) {
                    const data = await response.json();
                    if (data.success) {
                        const stockEl = document.getElementById(`stock-count-${medId}`);
                        if (stockEl) {
                            if (data.is_low_stock) {
                                stockEl.className = 'badge bg-danger text-white';
                                stockEl.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-1"></i>${data.total_stock} pills (Low)`;
                            } else {
                                stockEl.className = 'badge bg-light text-dark border';
                                stockEl.innerHTML = `${data.total_stock} pills`;
                            }
                        }
                        showToast(data.message, 'Inventory Refilled', 'success');
                    }
                }
            } catch (err) {
                console.error('Refill error:', err);
                showToast('Failed to refill medication inventory.', 'Refill Failed', 'danger');
            }
        });
    });

    // MedEx (Bangladesh) Search & Autofill Integration
    const medexSearchInput = document.getElementById('medex_search_query');
    const medexSearchBtn = document.getElementById('btn_medex_search');
    const medexSpinner = document.getElementById('medex_spinner');
    const medexSearchIcon = document.getElementById('medex_search_icon');
    const medexResultsBox = document.getElementById('medex_results_box');
    const medexResultsList = document.getElementById('medex_results_list');
    const medexInfoAlert = document.getElementById('medex_info_alert');
    const medexInfoText = document.getElementById('medex_info_text');
    const medexPkgSuggestions = document.getElementById('medex_packaging_suggestions');
    const medexPkgButtons = document.getElementById('medex_packaging_buttons');

    async function performMedexSearch() {
        if (!medexSearchInput) return;
        const query = medexSearchInput.value.trim();
        if (query.length < 2) {
            showToast('Please type at least 2 characters to search MedEx.', 'Search Notice', 'info');
            medexSearchInput.focus();
            return;
        }

        // Show spinner
        if (medexSpinner) medexSpinner.classList.remove('d-none');
        if (medexSearchIcon) medexSearchIcon.classList.add('d-none');
        if (medexSearchBtn) medexSearchBtn.disabled = true;

        if (medexInfoAlert) medexInfoAlert.classList.add('d-none');
        if (medexPkgSuggestions) medexPkgSuggestions.classList.add('d-none');

        try {
            const res = await fetch(`/api/medex/search?q=${encodeURIComponent(query)}`);
            if (!res.ok) throw new Error('Failed to query MedEx');
            const data = await res.json();

            medexResultsList.innerHTML = '';

            if (data.results && data.results.length > 0) {
                data.results.forEach(item => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center py-2 px-3';
                    btn.innerHTML = `
                        <div class="text-start">
                            <span class="fw-bold text-dark">${escapeHtml(item.name)}</span>
                            <span class="text-muted small d-block" style="font-size: 0.75rem;">${escapeHtml(item.full_title)}</span>
                        </div>
                        <span class="badge bg-primary-subtle text-primary rounded-pill border ms-2">${escapeHtml(item.dosage_form || 'Med')}</span>
                    `;

                    btn.addEventListener('click', async () => {
                        // User picked a medicine from MedEx
                        btn.innerHTML = `
                            <div class="d-flex align-items-center py-1">
                                <span class="spinner-border spinner-border-sm text-primary me-2"></span>
                                <span class="small text-primary fw-semibold">Fetching packaging & clinical data...</span>
                            </div>
                        `;
                        btn.disabled = true;

                        try {
                            const detailRes = await fetch(`/api/medex/details?url=${encodeURIComponent(item.url)}`);
                            if (!detailRes.ok) throw new Error('Failed to fetch details');
                            const detailData = await detailRes.json();
                            const med = detailData.data;

                            if (med) {
                                const nameInput = document.getElementById('med_add_name');
                                const genreInput = document.getElementById('med_add_genre');
                                const targetInput = document.getElementById('med_add_dosage_target');
                                const stockInput = document.getElementById('med_add_total_stock');
                                const instructionsInput = document.getElementById('med_add_instructions');

                                if (nameInput) nameInput.value = med.brand_name || item.full_title;
                                if (genreInput) genreInput.value = med.mapped_genre || 'General';
                                if (targetInput) targetInput.value = med.suggested_dosage_target || 1;
                                if (stockInput) stockInput.value = med.default_stock || 30;
                                if (instructionsInput && med.suggested_instructions) instructionsInput.value = med.suggested_instructions;

                                // Sync time slot checkboxes with MedEx suggestion
                                const suggestedSlots = med.suggested_time_slots || ['Morning'];
                                document.querySelectorAll('.add-time-slot-checkbox').forEach(cb => {
                                    cb.checked = suggestedSlots.includes(cb.value);
                                });
                                updateAddSlotsBadge(false);

                                // Show packaging buttons
                                if (medexPkgButtons) {
                                    medexPkgButtons.innerHTML = '';
                                    if (med.strip_size) {
                                        const stripBtn = document.createElement('button');
                                        stripBtn.type = 'button';
                                        stripBtn.className = 'btn btn-outline-primary btn-sm rounded-pill px-2 py-0';
                                        stripBtn.innerHTML = `<i class="bi bi-box me-1"></i>1 Strip (${med.strip_size} pills)`;
                                        stripBtn.onclick = () => { if (stockInput) stockInput.value = med.strip_size; };
                                        medexPkgButtons.appendChild(stripBtn);

                                        const twoStripsBtn = document.createElement('button');
                                        twoStripsBtn.type = 'button';
                                        twoStripsBtn.className = 'btn btn-outline-primary btn-sm rounded-pill px-2 py-0';
                                        twoStripsBtn.innerHTML = `<i class="bi bi-box me-1"></i>2 Strips (${med.strip_size * 2} pills)`;
                                        twoStripsBtn.onclick = () => { if (stockInput) stockInput.value = med.strip_size * 2; };
                                        medexPkgButtons.appendChild(twoStripsBtn);
                                    }

                                    if (med.box_size) {
                                        const boxBtn = document.createElement('button');
                                        boxBtn.type = 'button';
                                        boxBtn.className = 'btn btn-outline-success btn-sm rounded-pill px-2 py-0';
                                        boxBtn.innerHTML = `<i class="bi bi-boxes me-1"></i>Full Box (${med.box_size} pills)`;
                                        boxBtn.onclick = () => { if (stockInput) stockInput.value = med.box_size; };
                                        medexPkgButtons.appendChild(boxBtn);
                                    }

                                    if (medexPkgSuggestions) medexPkgSuggestions.classList.remove('d-none');
                                }

                                // Show success confirmation
                                if (medexInfoAlert && medexInfoText) {
                                    medexInfoText.innerHTML = `Autofilled <strong>${escapeHtml(med.brand_name)}</strong> &bull; Generic: <em>${escapeHtml(med.generic_name)}</em> &bull; Category: <span class="badge bg-success-subtle text-success">${escapeHtml(med.mapped_genre)}</span>`;
                                    medexInfoAlert.classList.remove('d-none');
                                }

                                // Collapse search list to keep UI clean
                                if (medexResultsBox) medexResultsBox.classList.add('d-none');

                                showToast(`Autofilled details from MedEx for ${escapeHtml(med.brand_name)}`, 'MedEx Autofill', 'success');
                            }
                        } catch (err) {
                            console.error('Details error:', err);
                            showToast('Could not load details from MedEx.', 'Fetch Error', 'danger');
                        }
                    });

                    medexResultsList.appendChild(btn);
                });

                if (medexResultsBox) medexResultsBox.classList.remove('d-none');
            } else {
                medexResultsList.innerHTML = `<div class="p-3 text-center text-muted small"><i class="bi bi-search me-1"></i> No matching medicines found on MedEx.</div>`;
                if (medexResultsBox) medexResultsBox.classList.remove('d-none');
            }

        } catch (err) {
            console.error('Search error:', err);
            showToast('Failed to connect to MedEx search.', 'Search Failed', 'danger');
        } finally {
            if (medexSpinner) medexSpinner.classList.add('d-none');
            if (medexSearchIcon) medexSearchIcon.classList.remove('d-none');
            if (medexSearchBtn) medexSearchBtn.disabled = false;
        }
    }

    // Prescribed Dose Times Checklist sync
    function updateAddSlotsBadge(syncDosage = true) {
        const checked = document.querySelectorAll('.add-time-slot-checkbox:checked');
        const badge = document.getElementById('add_selected_slots_badge');
        const targetInput = document.getElementById('med_add_dosage_target');
        if (badge) {
            badge.innerText = `${checked.length} slot(s) selected`;
            if (checked.length === 0) {
                badge.className = 'badge bg-warning-subtle text-danger border';
                badge.innerText = '0 slots (Select at least 1)';
            } else {
                badge.className = 'badge bg-light text-secondary border';
            }
        }
        // Automatically sync daily dosage target with number of selected time slots
        if (syncDosage && targetInput && checked.length > 0) {
            targetInput.value = checked.length;
        }
    }

    document.querySelectorAll('.add-time-slot-checkbox').forEach(cb => {
        cb.addEventListener('change', () => updateAddSlotsBadge(true));
    });

    if (medexSearchBtn) {
        medexSearchBtn.addEventListener('click', performMedexSearch);
    }

    if (medexSearchInput) {
        medexSearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                performMedexSearch();
            }
        });
    }

    // Type-to-confirm safeguard for irreversible deletes (profile / medication).
    // The submit button in each of these modals starts disabled; typing the
    // exact expected phrase (data-expected) into the paired input enables it.
    // The server independently re-checks the same phrase before deleting.
    document.querySelectorAll('.type-to-confirm-input').forEach(input => {
        const modal = input.closest('.modal-content');
        const submitBtn = modal ? modal.querySelector('.type-to-confirm-submit') : null;
        if (!submitBtn) return;

        input.addEventListener('input', () => {
            submitBtn.disabled = input.value.trim() !== input.getAttribute('data-expected');
        });

        const modalEl = input.closest('.modal');
        if (modalEl) {
            modalEl.addEventListener('hidden.bs.modal', () => {
                input.value = '';
                submitBtn.disabled = true;
            });
        }
    });

    // Live client-side filter for medication cards by name / genre / doctor
    const medSearchInput = document.getElementById('medSearchInput');
    if (medSearchInput) {
        medSearchInput.addEventListener('input', () => {
            const term = medSearchInput.value.trim().toLowerCase();
            document.querySelectorAll('.medication-card').forEach(card => {
                const col = card.closest('.col-lg-6') || card.parentElement;
                const haystack = card.innerText.toLowerCase();
                col.classList.toggle('d-none', !(!term || haystack.includes(term)));
            });
        });
    }

});

