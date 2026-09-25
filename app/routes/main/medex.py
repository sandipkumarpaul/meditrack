from flask import request, jsonify
from flask_login import login_required
from app import limiter
from app.services.medex import search_medex, get_medex_details, is_allowed_medex_url
from . import main_bp


# MedEx (Bangladesh) Search API Endpoint
@main_bp.route('/api/medex/search')
@login_required
@limiter.limit("20 per minute")
def medex_search():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'success': True, 'results': []})

    results = search_medex(query)
    return jsonify({
        'success': True,
        'count': len(results),
        'results': results
    })


# MedEx Details & Autofill Fetch Endpoint
@main_bp.route('/api/medex/details', methods=['GET', 'POST'])
@login_required
@limiter.limit("30 per minute")
def medex_details():
    url = request.args.get('url')
    if not url and request.is_json:
        url = (request.get_json() or {}).get('url')
    elif not url and request.form:
        url = request.form.get('url')

    if not url:
        return jsonify({'success': False, 'error': 'Missing MedEx URL'}), 400

    if not is_allowed_medex_url(url):
        return jsonify({'success': False, 'error': 'Only medex.com.bd URLs are supported'}), 400

    details = get_medex_details(url)
    if not details:
        return jsonify({'success': False, 'error': 'Could not fetch details from MedEx'}), 404

    return jsonify({
        'success': True,
        'data': details
    })
