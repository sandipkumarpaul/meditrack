import re
import time
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

ALLOWED_MEDEX_HOST = "medex.com.bd"
_CACHE_TTL_SECONDS = 600  # 10 minutes -- avoids re-scraping MedEx on every keystroke/re-click

_search_cache = {}
_details_cache = {}


def _cache_get(cache, key):
    entry = cache.get(key)
    if not entry:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache, key, value):
    cache[key] = (value, time.time() + _CACHE_TTL_SECONDS)


def is_allowed_medex_url(url):
    """
    Only ever fetch URLs on medex.com.bd. Without this check, get_medex_details()
    would perform a server-side HTTP request to any URL a logged-in user supplies
    (SSRF) -- it's called with a client-provided `url` query param.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host == ALLOWED_MEDEX_HOST or host.endswith("." + ALLOWED_MEDEX_HOST)

GENRE_MAPPING = [
    (r'analgesic|antipyretic|nsaid|pain|opioid|salicylate|acetaminophen|paracetamol', 'Pain Relief'),
    (r'antibiotic|antibacterial|cephalosporin|macrolide|penicillin|fluoroquinolone|carbapenem|tetracycline|antimicrobial', 'Antibiotic'),
    (r'proton pump|gastric|ulcer|antacid|h2 receptor|anti-emetic|laxative|motility|diarrhoea|digestive|omeprazole|esomeprazole|pantoprazole', 'Digestive'),
    (r'cardiovascular|hypertension|ace inhibitor|beta-blocker|calcium channel|arb|statin|angina|lipid|pressure', 'Cardiovascular'),
    (r'allergy|antihistamine|respiratory|asthma|cough|leukotriene|bronchodilator|cetirizine|fexo|montelukast', 'Allergy'),
    (r'vitamin|mineral|supplement|iron|calcium|zinc|nutritional|folic', 'Supplement & Vitamin'),
    (r'diabetes|insulin|hypoglycemic|glucose|biguanide|metformin', 'Diabetes'),
    (r'sedative|hypnotic|antidepressant|anxiolytic|antipsychotic|neurology|epilepsy|clonazepam', 'Mental Health'),
    (r'dermatolog|topical|antifungal|corticosteroid|skin|cream|ointment', 'Dermatology'),
    (r'ophthalmic|eye|ear|nasal|drop', 'Eye & ENT'),
]

def map_genre(text):
    """Maps medical keywords or drug classes to clean app category labels."""
    if not text:
        return "General"
    lower = text.lower()
    for pattern, genre in GENRE_MAPPING:
        if re.search(pattern, lower):
            return genre
    return text.strip()[:30]

def parse_package_counts(package_texts):
    """
    Parses strip size and total box size from MedEx package text.
    E.g.: '(11 x 12: ৳ 330.00)' -> strip_size: 12, box_size: 132
    E.g.: '(3 x 15: ৳ 315.00)'  -> strip_size: 15, box_size: 45
    """
    strip_size = None
    box_size = None

    for text in package_texts:
        match = re.search(r'\((\d+)\s*[xX*]\s*(\d+)', text)
        if match:
            strips = int(match.group(1))
            per_strip = int(match.group(2))
            strip_size = per_strip
            box_size = strips * per_strip
            break

        match_pcs = re.search(r'(\d+)\s*(?:pcs|tablets?|capsules?|pills?)', text, re.IGNORECASE)
        if match_pcs and not strip_size:
            strip_size = int(match_pcs.group(1))

    return {
        'strip_size': strip_size,
        'box_size': box_size,
        'raw': package_texts
    }

def search_medex(query):
    """
    Searches MedEx Bangladesh directory for a medicine name.
    Returns a list of matching brands with name, dosage form, and URL.
    """
    query = (query or '').strip()
    if len(query) < 2:
        return []

    cache_key = query.lower()
    cached = _cache_get(_search_cache, cache_key)
    if cached is not None:
        return cached

    url = f"https://medex.com.bd/search?search={requests.utils.quote(query)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=7)
        if r.status_code != 200:
            return []
    except Exception as e:
        print(f"MedEx search request failed: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    for a in soup.select("a[href*='/brands/']"):
        href = a.get("href", "")
        # Filter out links to non-detail pages
        if not re.search(r'/brands/\d+/', href):
            continue

        full_text = a.get_text(" ", strip=True)
        dosage_form = ""
        form_match = re.search(r'\(([^)]+)\)$', full_text)
        name = full_text
        if form_match:
            dosage_form = form_match.group(1).strip()
            name = full_text[:form_match.start()].strip()

        id_match = re.search(r'/brands/(\d+)/', href)
        brand_id = id_match.group(1) if id_match else None

        # Avoid duplicate results
        if any(r['id'] == brand_id for r in results):
            continue

        full_url = href if href.startswith("http") else f"https://medex.com.bd{href}"

        results.append({
            'id': brand_id,
            'name': name,
            'full_title': full_text,
            'dosage_form': dosage_form,
            'url': full_url
        })

        if len(results) >= 12:
            break

    _cache_set(_search_cache, cache_key, results)
    return results

def get_medex_details(brand_url):
    """
    Fetches full clinical & packaging details for a specific medicine from MedEx.
    Extracts brand title, generic, manufacturer, drug class, strip/box pill counts,
    dosage instructions, food conditions, and daily schedule suggestions.
    """
    if not is_allowed_medex_url(brand_url):
        return None

    cached = _cache_get(_details_cache, brand_url)
    if cached is not None:
        return cached

    try:
        r = requests.get(brand_url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return None
    except Exception as e:
        print(f"MedEx detail fetch failed: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Extract Title and Strength
    title_text = soup.title.string.strip() if soup.title else ""
    title_parts = [p.strip() for p in title_text.split('|') if p.strip()]
    
    # Fallback to h1 if title split fails
    h1 = soup.select_one("h1.page-heading-1-l")
    brand_name = ""
    if len(title_parts) >= 3:
        brand_name = f"{title_parts[0]} {title_parts[1]} ({title_parts[2]})"
    elif h1:
        brand_name = h1.get_text(" ", strip=True)
    else:
        brand_name = title_text[:50]

    # Clean redundant whitespace
    brand_name = re.sub(r'\s+', ' ', brand_name).strip()

    # Generic Name
    gen_el = soup.select_one("a[href*='/generics/']")
    generic_name = gen_el.get_text(strip=True) if gen_el else ""

    # Manufacturer / Pharmaceutical Company
    comp_el = soup.select_one("a[href*='/companies/']")
    company_name = comp_el.get_text(strip=True) if comp_el else ""

    # Packaging & Pill Counts
    package_elements = soup.select(".package-container, [class*='package']")
    package_texts = [p.get_text(" | ", strip=True) for p in package_elements]
    package_texts = list(dict.fromkeys(package_texts)) # unique
    package_info = parse_package_counts(package_texts)

    # Therapeutic Class / Category
    drug_class = ""
    drug_class_div = soup.find("div", id="drug_classes")
    if drug_class_div:
        body = drug_class_div.find_next_sibling("div", class_="ac-body")
        if body:
            drug_class = body.get_text(" ", strip=True)

    # Indications
    indications = ""
    ind_div = soup.find("div", id="indications")
    if ind_div:
        body = ind_div.find_next_sibling("div", class_="ac-body")
        if body:
            indications = body.get_text(" ", strip=True)

    # Dosage & Administration instructions
    dosage_text = ""
    dosage_div = soup.find("div", id="dosage")
    if dosage_div:
        body = dosage_div.find_next_sibling("div", class_="ac-body")
        if body:
            dosage_text = body.get_text(" ", strip=True)

    # Administration details (e.g. food requirements)
    admin_text = ""
    admin_div = soup.find("div", id="administration")
    if admin_div:
        body = admin_div.find_next_sibling("div", class_="ac-body")
        if body:
            admin_text = body.get_text(" ", strip=True)

    # Genre mapping
    mapped_genre = map_genre(f"{drug_class} {generic_name} {indications}")

    # Estimate default daily dosage target and time slots
    suggested_dosage_target = 1
    suggested_time_slots = ["Morning"]
    combined_instructions = f"{dosage_text} {admin_text}".lower()
    if "twice daily" in combined_instructions or "2 times" in combined_instructions or "every 12 hours" in combined_instructions or "twice a day" in combined_instructions:
        suggested_dosage_target = 2
        suggested_time_slots = ["Morning", "Night"]
    elif "3 times" in combined_instructions or "every 8 hours" in combined_instructions or "thrice daily" in combined_instructions or "3 times a day" in combined_instructions:
        suggested_dosage_target = 3
        suggested_time_slots = ["Morning", "Afternoon", "Night"]
    elif "4 times" in combined_instructions or "every 4-6 hours" in combined_instructions or "every 6 hours" in combined_instructions:
        suggested_dosage_target = 4
        suggested_time_slots = ["Morning", "Afternoon", "Evening", "Night"]
    elif "bedtime" in combined_instructions or "at night" in combined_instructions or "evening" in combined_instructions or "before sleep" in combined_instructions:
        suggested_time_slots = ["Night"]
        suggested_dosage_target = 1
    elif "as needed" in combined_instructions or "prn" in combined_instructions:
        suggested_time_slots = ["As Needed"]

    # Compile instructions
    instruction_notes = []
    if admin_text:
        instruction_notes.append(admin_text[:90])
    elif "after meal" in combined_instructions or "after food" in combined_instructions:
        instruction_notes.append("Take after meals with water")
    elif "before meal" in combined_instructions or "empty stomach" in combined_instructions:
        instruction_notes.append("Take 30-60 min before meals")

    if generic_name:
        instruction_notes.append(f"Generic: {generic_name}")
    if company_name:
        instruction_notes.append(f"{company_name}")

    suggested_instructions = " • ".join(instruction_notes)

    # Suggested stock: prioritize strip size (e.g. 10 or 12 or 15 or 5)
    default_stock = package_info['strip_size'] or package_info['box_size'] or 30

    details = {
        'brand_name': brand_name,
        'generic_name': generic_name,
        'company': company_name,
        'drug_class': drug_class,
        'mapped_genre': mapped_genre,
        'strip_size': package_info['strip_size'],
        'box_size': package_info['box_size'],
        'package_descriptions': package_texts,
        'default_stock': default_stock,
        'dosage_text': dosage_text[:200],
        'suggested_dosage_target': suggested_dosage_target,
        'suggested_time_slots': suggested_time_slots,
        'suggested_time_slot': ", ".join(suggested_time_slots),
        'suggested_instructions': suggested_instructions
    }
    _cache_set(_details_cache, brand_url, details)
    return details
