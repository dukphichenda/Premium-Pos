import os
import re
import json
import base64
import logging
import requests
from database import query_one, execute

logger = logging.getLogger('inflow.ai_customer_extractor')

def get_configured_gemini_api_key():
    """Retrieve Gemini API key from environment or database settings."""
    env_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if env_key and env_key.strip():
        return env_key.strip()
    
    try:
        inv = query_one("SELECT gemini_api_key FROM invoice_settings WHERE gemini_api_key IS NOT NULL AND gemini_api_key != '' LIMIT 1")
        if inv and inv.get('gemini_api_key'):
            return inv['gemini_api_key'].strip()
        
        comp = query_one("SELECT gemini_api_key FROM companies WHERE gemini_api_key IS NOT NULL AND gemini_api_key != '' LIMIT 1")
        if comp and comp.get('gemini_api_key'):
            return comp['gemini_api_key'].strip()
    except Exception as e:
        logger.warning(f"Error reading gemini_api_key from DB: {e}")
        
    return None

def save_gemini_api_key(api_key):
    """Save Gemini API key to DB and current environment."""
    clean_key = (api_key or '').strip()
    try:
        execute("UPDATE invoice_settings SET gemini_api_key = %s;", (clean_key,))
        execute("UPDATE companies SET gemini_api_key = %s;", (clean_key,))
        if clean_key:
            os.environ['GEMINI_API_KEY'] = clean_key
        elif 'GEMINI_API_KEY' in os.environ:
            del os.environ['GEMINI_API_KEY']
        return True
    except Exception as e:
        logger.error(f"Error saving gemini_api_key: {e}")
        return False

def parse_customer_text(text):
    """
    Intelligent heuristic regex and NLP parser for Cambodian customer contacts and addresses.
    Supports Khmer (ភាសាខ្មែរ) and English formats.
    """
    if not text:
        return {'name': '', 'contact_name': '', 'phone': '', 'address': '', 'pricing_scheme': 'Retail 1'}

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    extracted = {
        'name': '',
        'contact_name': '',
        'phone': '',
        'address': '',
        'pricing_scheme': 'Retail 1'
    }

    # 1. Phone extraction
    # Cambodian phone numbers: 010, 012, 016, 098, 088, +855...
    phone_pattern = re.compile(r'(?:\+?855|0)\s*(?:[1-9][0-9]?)\s*[\s\-\.]?[0-9]{3}\s*[\s\-\.]?[0-9]{3,4}')
    all_phones = phone_pattern.findall(text)
    if all_phones:
        cleaned_phones = []
        for p in all_phones:
            digits = re.sub(r'[^\d+]', '', p)
            if digits.startswith('+855'):
                digits = '0' + digits[4:]
            elif digits.startswith('855'):
                digits = '0' + digits[3:]
            if len(digits) in (9, 10):
                formatted = f"{digits[:3]} {digits[3:6]} {digits[6:]}"
                if formatted not in cleaned_phones:
                    cleaned_phones.append(formatted)
        if cleaned_phones:
            extracted['phone'] = ' / '.join(cleaned_phones[:2])

    # 2. Check line by line for labeled data
    remaining_lines = []
    for line in lines:
        lower = line.lower()

        # Name patterns (e.g. ឈ្មោះ: ..., ហាង: ..., ក្រុមហ៊ុន: ..., Name: ...)
        name_match = re.search(r'^(?:ឈ្មោះ|អតិថិជន|ហាង|ក្រុមហ៊ុន|customer(?:\s*name)?|name|company|client|shop|store)\s*[:=\-–]\s*(.+)$', line, re.I)
        if name_match and not extracted['name']:
            extracted['name'] = name_match.group(1).strip()
            continue

        # Contact person patterns (e.g. អ្នកទំនាក់ទំនង: ..., អ្នកទទួល: ..., Contact: ..., Attn: ...)
        contact_match = re.search(r'^(?:អ្នកទំនាក់ទំនង|អ្នកទទួល|contact(?:\s*person)?|attn|receiver|contact)\s*[:=\-–]\s*(.+)$', line, re.I)
        if contact_match and not extracted['contact_name']:
            extracted['contact_name'] = contact_match.group(1).strip()
            continue

        # Address patterns (e.g. អាសយដ្ឋាន: ..., ទីតាំង: ..., Address: ..., Location: ...)
        addr_match = re.search(r'^(?:អាសយដ្ឋាន|ទីតាំង|address|location|ship\s*to)\s*[:=\-–]\s*(.+)$', line, re.I)
        if addr_match and not extracted['address']:
            extracted['address'] = addr_match.group(1).strip()
            continue

        # If line contains phone label only
        if re.search(r'^(?:លេខទូរស័ព្ទ|ទូរស័ព្ទ|phone|tel|mobile|hp|cell)\s*[:=\-–]', line, re.I):
            continue

        # Check if line looks like address without explicit label
        addr_keywords = ['phnom penh', 'sangkat', 'khan', 'street', 'st.', 'st ', 'borey', 'road', 'blvd',
                         'ភ្នំពេញ', 'សង្កាត់', 'ខណ្ឌ', 'ផ្លូវ', 'ផ្ទះ', 'បុរី', 'ខេត្ត']
        if any(k in lower for k in addr_keywords):
            if not extracted['address']:
                extracted['address'] = line
            else:
                extracted['address'] += ', ' + line
            continue

        remaining_lines.append(line)

    # If name still empty, pick first non-empty suitable remaining line
    if not extracted['name'] and remaining_lines:
        for r_line in list(remaining_lines):
            # Check it's not just a phone number, price, or date
            if not phone_pattern.search(r_line) and len(r_line) > 2 and not any(x in r_line.lower() for x in ['$', '៛', 'usd', 'total', 'invoice']):
                extracted['name'] = r_line
                remaining_lines.remove(r_line)
                break

    # If contact_name is empty but we have another personal name line
    if not extracted['contact_name'] and remaining_lines:
        for r_line in remaining_lines:
            if len(r_line) < 35 and not any(x in r_line.lower() for x in ['$', '៛', 'usd', 'riel', 'total', 'date', 'invoice', 'no.', 'code']):
                extracted['contact_name'] = r_line
                break

    return extracted

def extract_customer_info_via_gemini(image_bytes=None, image_b64=None, mime_type="image/jpeg", api_key=None):
    """Call Google Gemini 2.0 / 1.5 Flash Vision to extract customer details from image."""
    key = api_key or get_configured_gemini_api_key()
    if not key:
        return None, "No Gemini API Key configured."

    if image_bytes and not image_b64:
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

    if not image_b64:
        return None, "No image data provided."

    prompt = (
        "You are an expert AI vision assistant for a Cambodian POS & Wholesale ERP system.\n"
        "Carefully analyze this customer image (which may be a business card, a Telegram/Messenger delivery screenshot, "
        "a receipt, a handwritten delivery paper, or an invoice).\n"
        "Read all visible text in Khmer (ភាសាខ្មែរ) and English.\n"
        "Extract the customer details and return ONLY a valid JSON object with EXACTLY these keys:\n"
        "{\n"
        '  "name": "Customer Name or Company / Shop / Store name in Khmer or English",\n'
        '  "contact_name": "Contact person name or manager name (if available)",\n'
        '  "phone": "Phone number(s), formatted with spaces e.g. 012 345 678. If multiple, separate with /",\n'
        '  "address": "Full delivery or street address (House #, Street, Sangkat, Khan, City/Province)",\n'
        '  "pricing_scheme": "Retail 1"\n'
        "}\n"
        "If a field is not present in the image, return an empty string \"\" for that field.\n"
        "Output ONLY the JSON object without backticks, markdown, or commentary."
    )

    models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-flash-latest']
    last_err = ""

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type or "image/jpeg",
                            "data": image_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                res_json = resp.json()
                candidates = res_json.get('candidates') or []
                if candidates and candidates[0].get('content'):
                    parts = candidates[0]['content'].get('parts') or []
                    if parts and parts[0].get('text'):
                        raw_text = parts[0]['text'].strip()
                        # Clean backticks if any
                        clean_text = re.sub(r'^```json\s*', '', raw_text, flags=re.I)
                        clean_text = re.sub(r'\s*```$', '', clean_text)
                        parsed = json.loads(clean_text)
                        return {
                            'name': (parsed.get('name') or '').strip(),
                            'contact_name': (parsed.get('contact_name') or '').strip(),
                            'phone': (parsed.get('phone') or '').strip(),
                            'address': (parsed.get('address') or '').strip(),
                            'pricing_scheme': (parsed.get('pricing_scheme') or 'Retail 1').strip()
                        }, None
            else:
                last_err = f"API Error ({resp.status_code}): {resp.text[:200]}"
                logger.warning(f"Gemini model {model} failed: {last_err}")
        except Exception as e:
            last_err = str(e)
            logger.warning(f"Error calling {model}: {e}")

    return None, last_err

def extract_customer_info(image_bytes=None, image_b64=None, mime_type="image/jpeg", text_fallback="", api_key=None):
    """
    Unified extraction pipeline:
    1. Tries Gemini AI Vision if API key is available and image provided.
    2. Falls back to Cambodian Heuristic Parser on text_fallback.
    """
    # 1. Try Gemini Vision if image available
    if image_bytes or image_b64:
        gemini_result, gemini_err = extract_customer_info_via_gemini(
            image_bytes=image_bytes,
            image_b64=image_b64,
            mime_type=mime_type,
            api_key=api_key
        )
        if gemini_result and (gemini_result.get('name') or gemini_result.get('phone')):
            return {
                'success': True,
                'extracted': gemini_result,
                'method': 'gemini_vision',
                'ai_powered': True,
                'message': '✨ Customer details extracted using Gemini AI Vision!'
            }

    # 2. Heuristic fallback on text (e.g. from client-side OCR or user paste)
    if text_fallback and text_fallback.strip():
        parsed = parse_customer_text(text_fallback)
        return {
            'success': True,
            'extracted': parsed,
            'method': 'text_ocr_parser',
            'ai_powered': False,
            'message': 'Customer details extracted from text/OCR analysis.'
        }

    return {
        'success': False,
        'extracted': {
            'name': '',
            'contact_name': '',
            'phone': '',
            'address': '',
            'pricing_scheme': 'Retail 1'
        },
        'method': 'none',
        'ai_powered': False,
        'message': 'No text or details could be recognized from the image.'
    }
