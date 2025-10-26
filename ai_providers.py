import os
import importlib
from typing import Optional, List, Dict, Tuple
import io
import random
from PIL import Image, ImageDraw, ImageFont

# Lightweight, optional AI provider helpers.
# - Gemini (google-genai): set GOOGLE_API_KEY or GEMINI_API_KEY
# - OpenAI (openai): set OPENAI_API_KEY
# If the library or key is missing, functions return None gracefully.


def _get_gemini_client():
    """Return a google-genai client if available and keyed, else None."""
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        genai = importlib.import_module("google.genai")
        client = genai.Client(api_key=api_key)
        return client
    except Exception:
        return None


def _get_openai_client():
    """Return an OpenAI client if available and keyed, else None."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        openai = importlib.import_module("openai")
        return openai
    except Exception:
        return None


def summarize_text(text: str, max_tokens: int = 120) -> Optional[str]:
    """Attempt to summarize text using Gemini first, then OpenAI. Returns None if unavailable."""
    if not text or not isinstance(text, str):
        return None

    # 1) Try Gemini
    client = _get_gemini_client()
    if client is not None:
        try:
            # Keep the prompt short; models handle long input, but we may truncate.
            prompt = (
                "Resume en 3-4 líneas, claro y conciso, en español, destacando ideas clave y tono accesible.\n\n"
            )
            # You can also use a structured config if needed; the simple call works for text-only.
            resp = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt + text[:6000]  # safety limit
            )
            # Extract text safely
            summary = None
            try:
                summary = resp.candidates[0].content.parts[0].text
            except Exception:
                summary = getattr(resp, "text", None)
            if summary:
                return summary.strip()
        except Exception:
            pass

    # 2) Try OpenAI as fallback
    openai = _get_openai_client()
    if openai is not None:
        try:
            # Use Responses API if available, else chat.completions as fallback
            # Prefer a small fast model name; user can configure via env later if desired
            if hasattr(openai, "chat"):
                r = openai.chat.completions.create(
                    model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                    messages=[
                        {
                            "role": "system",
                            "content": "Eres un asistente que resume textos en español de forma breve (3-4 líneas) y clara."
                        },
                        {"role": "user", "content": text[:6000]},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.4,
                )
                return (r.choices[0].message.content or "").strip()
        except Exception:
            pass

    return None


def analyze_content(text: str) -> Optional[dict]:
    """
    Analiza contenido y devuelve un dict con campos:
    - summary (string)
    - topics (list[str])
    - tone (string)
    - complexity (string)
    - warnings (list[str])
    - faqs (list[str])
    Usa Gemini u OpenAI si hay claves; si no, heurística básica.
    """
    if not text or not isinstance(text, str):
        return None

    # Intentar con Gemini
    client = _get_gemini_client()
    if client is not None:
        try:
            prompt = (
                "Eres un analista. Devuelve JSON con: summary (3-4 líneas), topics (5 palabras clave), "
                "tone (amigable/neutral/técnico/literario), complexity (baja/media/alta), warnings (si hay temas sensibles), "
                "faqs (3-5 preguntas frecuentes). Responde SOLO JSON válido.\n\nTexto:\n"
            )
            resp = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt + text[:8000]
            )
            # Intentar parsear JSON desde el texto de salida
            parsed = None
            try:
                raw = resp.candidates[0].content.parts[0].text
            except Exception:
                raw = getattr(resp, "text", "")
            import json
            parsed = json.loads(raw)
            return parsed
        except Exception:
            pass

    # Intentar con OpenAI
    openai = _get_openai_client()
    if openai is not None:
        try:
            import json as _json
            sysmsg = (
                "Devuelve SOLO JSON con: summary, topics (array), tone, complexity, warnings (array), faqs (array)."
            )
            r = openai.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": sysmsg},
                    {"role": "user", "content": text[:8000]},
                ],
                temperature=0.3,
            )
            content = r.choices[0].message.content or "{}"
            return _json.loads(content)
        except Exception:
            pass

    # Heurística básica si no hay IA
    lowered = text.lower()
    keywords = []
    for kw in ["historia", "ciencia", "tecnología", "arte", "biología", "novela", "cuento", "noticia", "aprendizaje"]:
        if kw in lowered:
            keywords.append(kw)
    tone = "técnico" if any(k in lowered for k in ["investigación", "método", "datos", "teoría"]) else "neutral"
    complexity = "alta" if len(text) > 12000 else ("media" if len(text) > 4000 else "baja")
    warnings = []
    for w in ["violencia", "sexo", "terror", "muerte", "discriminación"]:
        if w in lowered:
            warnings.append(w)
    summary = (text[:400] + "...") if len(text) > 450 else text
    faqs = [
        "¿Cuál es la idea principal del contenido?",
        "¿Qué conceptos clave se presentan?",
        "¿Para quién está dirigido este contenido?",
    ]
    return {
        "summary": summary,
        "topics": keywords[:5],
        "tone": tone,
        "complexity": complexity,
        "warnings": warnings,
        "faqs": faqs,
    }


def expand_query(query: str) -> List[str]:
    """Expand a user query into related keywords using Gemini/OpenAI if available; else tokenized words."""
    if not query:
        return []
    # Try Gemini
    client = _get_gemini_client()
    if client is not None:
        try:
            prompt = (
                "Devuelve una lista separada por comas de 8-12 palabras/phrases relacionadas semánticamente con: "
                f"'{query}'. SOLO la lista, sin explicaciones."
            )
            resp = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            txt = None
            try:
                txt = resp.candidates[0].content.parts[0].text
            except Exception:
                txt = getattr(resp, "text", "")
            if txt:
                items = [w.strip() for w in txt.split(',') if w.strip()]
                base = [t.strip() for t in query.lower().split() if t.strip()]
                return list(dict.fromkeys(base + items))
        except Exception:
            pass
    # Try OpenAI
    openai = _get_openai_client()
    if openai is not None:
        try:
            r = openai.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role":"system","content":"Devuelve solo una lista separada por comas de keywords relacionadas."},
                         {"role":"user","content":query}],
                temperature=0.3,
            )
            txt = r.choices[0].message.content or ''
            items = [w.strip() for w in txt.split(',') if w.strip()]
            base = [t.strip() for t in query.lower().split() if t.strip()]
            return list(dict.fromkeys(base + items))
        except Exception:
            pass
    # Fallback: tokens del query
    return [t.strip() for t in query.lower().split() if t.strip()]


def translate_text(text: str, target_lang: str = 'en') -> Optional[str]:
    """Translate text via Gemini/OpenAI; returns None if unavailable."""
    if not text:
        return None
    client = _get_gemini_client()
    if client is not None:
        try:
            prompt = f"Traduce al {target_lang} conservando el sentido y tono:\n\n{text[:8000]}"
            resp = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            try:
                out = resp.candidates[0].content.parts[0].text
            except Exception:
                out = getattr(resp, "text", None)
            return out.strip() if out else None
        except Exception:
            pass
    openai = _get_openai_client()
    if openai is not None:
        try:
            r = openai.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role":"system","content":f"Traduce al {target_lang}."},
                         {"role":"user","content":text[:8000]}],
                temperature=0.3,
            )
            return (r.choices[0].message.content or '').strip()
        except Exception:
            pass
    return None


def detect_language(text: str) -> str:
    """Very naive language detection; prefer AI if available."""
    if not text:
        return 'und'
    client = _get_gemini_client()
    if client is not None:
        try:
            resp = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=f"Detecta el idioma (código ISO como es,en,pt,fr,de) y responde SOLO el código:\n\n{text[:2000]}"
            )
            code = None
            try:
                code = resp.candidates[0].content.parts[0].text
            except Exception:
                code = getattr(resp, "text", "und")
            return code.strip().lower()[:5]
        except Exception:
            pass
    # naive
    s = text.lower()
    if any(w in s for w in [' el ', ' la ', ' de ', ' que ']):
        return 'es'
    if any(w in s for w in [' the ', ' of ', ' and ']):
        return 'en'
    return 'und'


def generate_quiz(text: str, n: int = 5) -> Optional[List[Dict[str, str]]]:
    """Generate simple Q&A pairs from text via Gemini/OpenAI; returns list of {q,a}."""
    if not text:
        return None
    client = _get_gemini_client()
    if client is not None:
        try:
            prompt = (
                f"Genera {n} preguntas y respuestas cortas en español sobre el texto. Formato JSON array de objetos con 'q' y 'a'.\n\n{text[:8000]}"
            )
            resp = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            raw = None
            try:
                raw = resp.candidates[0].content.parts[0].text
            except Exception:
                raw = getattr(resp, "text", "[]")
            import json
            return json.loads(raw)
        except Exception:
            pass
    openai = _get_openai_client()
    if openai is not None:
        try:
            import json as _json
            r = openai.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role":"system","content":"Devuelve SOLO JSON array con objetos {q,a}."},
                         {"role":"user","content":text[:8000]}],
                temperature=0.4,
            )
            return _json.loads(r.choices[0].message.content or '[]')
        except Exception:
            pass
    # Fallback heurístico: preguntas genéricas
    return [{"q":"¿Cuál es la idea principal?","a":"Trata sobre los conceptos clave presentados en el texto."}]


def generate_notes(text: str) -> Optional[List[str]]:
    """Generate bullet notes from text; fallback to simple split."""
    if not text:
        return None
    client = _get_gemini_client()
    if client is not None:
        try:
            prompt = "Extrae 5-7 puntos clave en viñetas, en español, concisos y claros:\n\n" + text[:8000]
            resp = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            out = None
            try:
                out = resp.candidates[0].content.parts[0].text
            except Exception:
                out = getattr(resp, "text", None)
            if out:
                bullets = [l.strip('-• ').strip() for l in out.split('\n') if l.strip()]
                return bullets[:7]
        except Exception:
            pass
    openai = _get_openai_client()
    if openai is not None:
        try:
            r = openai.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role":"system","content":"Devuelve 5-7 viñetas concisas en español."},
                         {"role":"user","content":text[:8000]}],
                temperature=0.4,
            )
            txt = r.choices[0].message.content or ''
            return [l.strip('-• ').strip() for l in txt.split('\n') if l.strip()][:7]
        except Exception:
            pass
    # Fallback
    return [text[:120] + ('...' if len(text)>120 else '')]


def _heuristic_complexity_metrics(text: str) -> Tuple[float, float]:
    """Return (avg_sentence_len, unique_ratio) as quick proxies for complexity."""
    import re
    sents = re.split(r'[.!?]\s+', text.strip())
    sents = [s for s in sents if s]
    if not sents:
        return 0.0, 0.0
    words = [w for w in re.findall(r"\b\w+\b", text.lower())]
    avg_len = sum(len(re.findall(r"\b\w+\b", s)) for s in sents) / max(1, len(sents))
    unique_ratio = len(set(words)) / max(1, len(words))
    return avg_len, unique_ratio


def analyze_accessibility(text: str) -> Optional[Dict]:
    """Analyze text for accessibility: complexity level, recommended speed, pause points, chapter summaries."""
    if not text:
        return None
    # Try AI first for rich output
    client = _get_gemini_client()
    if client is not None:
        try:
            prompt = (
                "Analiza el texto para accesibilidad. Devuelve JSON con: "
                "complexity_level (baja|media|alta), recommended_speed (0.8-1.3), "
                "pauses (array de frases o indicaciones breves), chapters (array de objetos {title, summary}). "
                "Sé conciso, útil y claro. Texto:\n\n" + text[:8000]
            )
            resp = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            raw = None
            try:
                raw = resp.candidates[0].content.parts[0].text
            except Exception:
                raw = getattr(resp, "text", "{}")
            import json
            data = json.loads(raw)
            # basic guards
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    openai = _get_openai_client()
    if openai is not None:
        try:
            import json as _json
            r = openai.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role":"system","content":"Devuelve SOLO JSON con keys: complexity_level, recommended_speed, pauses, chapters[{title,summary}]"},
                         {"role":"user","content":text[:8000]}],
                temperature=0.2,
            )
            return _json.loads(r.choices[0].message.content or '{}')
        except Exception:
            pass
    # Heuristic fallback
    avg_len, uniq = _heuristic_complexity_metrics(text)
    if avg_len >= 25 or uniq >= 0.55: level = 'alta'
    elif avg_len >= 15 or uniq >= 0.45: level = 'media'
    else: level = 'baja'
    speed = 0.9 if level=='alta' else (1.0 if level=='media' else 1.15)
    # pauses: after long sentences or double newlines
    import re
    raw_sents = re.split(r'([.!?])', text)
    pauses = []
    # recombine sentence with punctuation tokens
    cur = ''
    for part in raw_sents:
        cur += part
        if part in '.!?':
            if len(cur.split()) >= 18:
                pauses.append(cur.strip())
            cur = ''
    # chapters: naive split by headings
    chapters = []
    lines = text.splitlines()
    buffer = []
    current_title = None
    def flush():
        nonlocal buffer, current_title, chapters
        if buffer:
            bl = ' '.join(buffer).strip()
            if bl:
                summ = summarize_text(bl) or bl.split('.')[0][:220]
                chapters.append({'title': current_title or 'Sección', 'summary': summ})
            buffer = []
    for ln in lines:
        if re.match(r'^(cap[ií]tulo|secci[oó]n|\d+\.|#)', ln.strip(), re.IGNORECASE):
            flush()
            current_title = ln.strip()
        else:
            buffer.append(ln)
    flush()
    return {
        'complexity_level': level,
        'recommended_speed': round(speed, 2),
        'pauses': pauses[:12],
        'chapters': chapters[:10],
    }


def support_answer(message: str, context: Optional[str] = None) -> str:
    """Answer support questions about using the app. AI if available; fallback FAQ-like text."""
    if not message:
        return "¿En qué puedo ayudarte? Puedes preguntar por conversión a audio, biblioteca, reproductor o recomendaciones."
    client = _get_gemini_client()
    if client is not None:
        try:
            sys = "Eres el asistente de soporte de SinSay. Sé claro, breve y práctico."
            prompt = (context or sys) + "\n\nUsuario: " + message
            resp = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            try:
                return resp.candidates[0].content.parts[0].text.strip()
            except Exception:
                return (getattr(resp, 'text', None) or '').strip()
        except Exception:
            pass
    openai = _get_openai_client()
    if openai is not None:
        try:
            r = openai.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role":"system","content":"Eres el soporte de SinSay. Sé claro y breve."},
                         {"role":"user","content":message}],
                temperature=0.2,
            )
            return (r.choices[0].message.content or '').strip()
        except Exception:
            pass
    # fallback
    m = message.lower()
    if 'convert' in m or 'audio' in m:
        return "Para convertir un archivo a audio, ve a Reproductor > Generar audio, selecciona el archivo y elige una voz."
    if 'biblioteca' in m or 'library' in m:
        return "En Biblioteca puedes filtrar por categoría, nivel y buscar por título. Haz click en una tarjeta para abrirla."
    if 'reproductor' in m or 'play' in m:
        return "En el Reproductor puedes pausar, adelantar 15s, ajustar volumen y ver texto sincronizado si está disponible."
    return "Puedo ayudarte con: convertir a audio, navegar la biblioteca, reproducir contenidos y recomendaciones personalizadas."


def moderate_text(text: str) -> Dict:
    """Moderate content: flags for inappropriate/sensitive/spam/quality issues; AI-backed with heuristic fallback."""
    flags = { 'inappropriate': False, 'sensitive_content': False, 'spam': False, 'quality_issues': [] }
    if not text:
        return flags
    client = _get_gemini_client()
    if client is not None:
        try:
            prompt = (
                "Analiza el texto y devuelve JSON con flags: inappropriate(bool), sensitive_content(bool), spam(bool), "
                "quality_issues(array de strings breves). Sé estricto con lenguaje explícito/violencia extrema y datos personales. Texto:\n\n" + text[:8000]
            )
            resp = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
            raw = None
            try:
                raw = resp.candidates[0].content.parts[0].text
            except Exception:
                raw = getattr(resp, 'text', '{}')
            import json
            data = json.loads(raw)
            if isinstance(data, dict):
                return {**flags, **data}
        except Exception:
            pass
    # heuristic fallback
    low = text.lower()
    bad_terms = ['odio', 'matar', 'violación', 'sexo explícito']
    if any(t in low for t in bad_terms): flags['inappropriate'] = True
    if any(w in low for w in ['suicidio','autolesión','terrorismo','droga']): flags['sensitive_content'] = True
    if len(low) > 2000 and low.count('http') > 10: flags['spam'] = True
    # quality
    import re
    if not re.search(r'[\.\!\?]', text): flags['quality_issues'].append('Falta puntuación en el texto')
    avg_len, _ = _heuristic_complexity_metrics(text)
    if avg_len > 40: flags['quality_issues'].append('Oraciones excesivamente largas')
    return flags


# --- Simple AI-ish cover generator (local, no external calls) ---
_CATEGORY_STYLES = {
    'novela': {'bg': (37, 99, 235), 'fg': (255,255,255), 'emoji': '📖'},
    'cuento': {'bg': (16, 185, 129), 'fg': (0,0,0), 'emoji': '✨'},
    'ciencia': {'bg': (99, 102, 241), 'fg': (255,255,255), 'emoji': '🔬'},
    'tecnologia': {'bg': (55, 65, 81), 'fg': (255,255,255), 'emoji': '🧠'},
    'tecnología': {'bg': (55, 65, 81), 'fg': (255,255,255), 'emoji': '🧠'},
    'historia': {'bg': (180, 83, 9), 'fg': (255,255,255), 'emoji': '🏺'},
    'arte': {'bg': (236, 72, 153), 'fg': (255,255,255), 'emoji': '🎨'},
    'biologia': {'bg': (34, 197, 94), 'fg': (0,0,0), 'emoji': '🧬'},
    'biología': {'bg': (34, 197, 94), 'fg': (0,0,0), 'emoji': '🧬'},
    'educacion': {'bg': (2, 132, 199), 'fg': (255,255,255), 'emoji': '🎓'},
    'educación': {'bg': (2, 132, 199), 'fg': (255,255,255), 'emoji': '🎓'},
    'poesia': {'bg': (168, 85, 247), 'fg': (255,255,255), 'emoji': '🕊️'},
    'poesía': {'bg': (168, 85, 247), 'fg': (255,255,255), 'emoji': '🕊️'},
}


def _pick_style(category: Optional[str]) -> Dict[str, object]:
    if not category:
        return {'bg': (31, 41, 55), 'fg': (255,255,255), 'emoji': '📚'}
    key = category.strip().lower()
    for k, v in _CATEGORY_STYLES.items():
        if k in key:
            return v
    # fallback random pleasant color
    palettes = [
        (59, 130, 246), (99, 102, 241), (236, 72, 153), (34, 197, 94), (234, 179, 8), (2, 132, 199)
    ]
    return {'bg': random.choice(palettes), 'fg': (255,255,255), 'emoji': '📘'}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    # Try common fonts; fallback to default bitmap font
    for name in [
        "arial.ttf", "Segoe UI.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf",
    ]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def generate_cover_image_bytes(category: Optional[str], title: Optional[str], subtitle: Optional[str] = None,
                               size: Tuple[int, int] = (768, 1024)) -> Optional[bytes]:
    """Generate a simple cover as JPEG bytes based on category and title.
    No external AI calls; safe offline fallback.
    """
    try:
        w, h = size
        style = _pick_style(category)
        img = Image.new('RGB', (w, h), color=style['bg'])
        draw = ImageDraw.Draw(img)

        # Top emoji/icon
        emoji = style.get('emoji', '📚')
        emoji_font = _load_font(int(h * 0.18))
        ef_w, ef_h = draw.textsize(emoji, font=emoji_font)
        draw.text(((w - ef_w) / 2, int(h * 0.08)), emoji, font=emoji_font, fill=style['fg'])

        # Title (wrapped)
        title_text = (title or 'Sin título').strip()
        max_title_width = int(w * 0.80)
        # progressively reduce font size to fit lines
        tsize = int(h * 0.065)
        while tsize >= 26:
            font = _load_font(tsize)
            # naive wrap by measuring words
            words = title_text.split()
            lines = []
            cur = ''
            for wd in words:
                test = (cur + ' ' + wd).strip()
                tw, th = draw.textsize(test, font=font)
                if tw <= max_title_width:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = wd
            if cur:
                lines.append(cur)
            if len(lines) <= 3:
                break
            tsize -= 4
        # Center title block around 45% height
        total_h = sum(draw.textsize(l, font=font)[1] for l in lines) + (len(lines)-1)*8
        y = int(h * 0.40 - total_h / 2)
        for l in lines:
            tw, th = draw.textsize(l, font=font)
            draw.text(((w - tw)/2, y), l, font=font, fill=style['fg'])
            y += th + 8

        # Subtitle/category chip at bottom
        chip = (subtitle or category or '').strip()
        if chip:
            chip_font = _load_font(int(h * 0.035))
            pad_x, pad_y = 16, 10
            ctw, cth = draw.textsize(chip, font=chip_font)
            box_w, box_h = ctw + pad_x*2, cth + pad_y*2
            bx, by = int((w - box_w)/2), int(h*0.80)
            # semi-transparent-like effect via darker bg
            bg = tuple(max(0, int(style['bg'][i] * 0.7)) for i in range(3))
            draw.rounded_rectangle([bx, by, bx+box_w, by+box_h], radius=12, fill=bg)
            draw.text((bx+pad_x, by+pad_y), chip, font=chip_font, fill=style['fg'])

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=88)
        return buf.getvalue()
    except Exception:
        return None
