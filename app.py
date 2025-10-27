from flask import Flask, render_template, request, redirect, session, url_for, jsonify, send_from_directory, send_file
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    # Fallback no-op if python-dotenv is not installed, so the app still starts
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from werkzeug.utils import secure_filename
import os
import time
import re
import io
import unicodedata
import math
from datetime import datetime, timedelta
ELEVEN_AVAILABLE = False
ELEVEN_USE_LEGACY = False
try:
    # Prefer legacy simple API if present
    from elevenlabs import generate as el_generate, set_api_key as el_set_api_key  # type: ignore
    ELEVEN_AVAILABLE = True
    ELEVEN_USE_LEGACY = True
    print("✅ ElevenLabs (legacy API) disponible")
except Exception:
    try:
        # Newer client API
        from elevenlabs.client import ElevenLabs  # type: ignore
        ELEVEN_AVAILABLE = True
        ELEVEN_USE_LEGACY = False
        print("✅ ElevenLabs (client API) disponible")
    except Exception as e:
        print(f"⚠️  ElevenLabs no disponible: {e}")
import docx
import PyPDF2
from mutagen.mp3 import MP3  # Para obtener duración de archivos MP3
from bson import ObjectId
from ai_providers import (
    summarize_text,
    analyze_content,
    expand_query,
    translate_text,
    detect_language,
    generate_quiz,
    generate_notes,
    analyze_accessibility,
    support_answer,
    moderate_text,
    generate_cover_image_bytes,
)

# Google Cloud TTS como fallback
try:
    from google.cloud import texttospeech
    GOOGLE_TTS_AVAILABLE = True
    print("✅ Google Cloud TTS disponible como respaldo")
    print(f"📦 Versión de google-cloud-texttospeech importada correctamente")
except ImportError as e:
    GOOGLE_TTS_AVAILABLE = False
    print(f"⚠️  Google Cloud TTS no disponible: {e}")
    print("⚠️  Ejecuta: pip install google-cloud-texttospeech")

load_dotenv()  # Lee variables desde .env si existe
app = Flask(__name__)
app.secret_key = "sinsay_secret_key"
bcrypt = Bcrypt(app)

# Estado simple para diagnóstico de TTS
LAST_TTS_STATUS = {
    'engine': None,            # 'ElevenLabs' | 'Google Cloud TTS' | None
    'fallback_reason': None,   # str | None
    'timestamp': None          # int epoch | None
}

# Configuración de archivos
UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'audio_files'
COVERS_FOLDER = os.path.join('static', 'covers')
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'brf'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(AUDIO_FOLDER):
    os.makedirs(AUDIO_FOLDER)
if not os.path.exists(COVERS_FOLDER):
    os.makedirs(COVERS_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER
app.config['COVERS_FOLDER'] = COVERS_FOLDER

# MongoDB
try:
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    # Verificar conexión
    client.admin.command('ping')
    print("✅ Conexión exitosa a MongoDB")
    db = client["sinsay"]
    usuarios_collection = db["usuarios"]
    libros_collection = db["libros"]
    print(f"📊 Base de datos: {db.name}")
    print(f"📁 Colección: usuarios_collection")
    print(f"📚 Colección: libros_collection")
except Exception as e:
    print(f"❌ ERROR: No se pudo conectar a MongoDB: {e}")
    print("⚠️  Asegúrate de que MongoDB esté corriendo en localhost:27017")
    client = None
    db = None
    usuarios_collection = None
    libros_collection = None

# ElevenLabs API (principal TTS)
ELEVEN_API_KEY = os.environ.get("ELEVEN_API_KEY")
if ELEVEN_AVAILABLE and ELEVEN_API_KEY:
    try:
        if ELEVEN_USE_LEGACY:
            el_set_api_key(ELEVEN_API_KEY)
        else:
            # instantiate client lazily in generator function
            pass
        print("🔑 Clave ElevenLabs configurada (*** oculto)")
    except Exception as e:
        print(f"⚠️  No se pudo configurar ElevenLabs: {e}")
else:
    if ELEVEN_AVAILABLE:
        print("⚠️  ELEVEN_API_KEY no configurada; ElevenLabs no se usará")

# Google Cloud API Key (para Text-to-Speech)
os.environ['GOOGLE_API_KEY'] = "AIzaSyBe1bC2-gepvvQdGza9i7O-X6WwEIYNfmo"


def _to_roman(num: int) -> str:
    """Convierte enteros 1..3999 a números romanos (para capítulos)."""
    if num <= 0:
        return str(num)
    vals = [
        (1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
        (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
        (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')
    ]
    res = []
    n = num
    for v, s in vals:
        while n >= v:
            res.append(s)
            n -= v
    return ''.join(res)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_file(filepath):
    """Extrae texto de archivos PDF, DOCX o TXT"""
    ext = filepath.rsplit('.', 1)[1].lower()
    
    if ext == 'txt' or ext == 'brf':
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    
    elif ext == 'docx':
        doc = docx.Document(filepath)
        return '\n'.join([paragraph.text for paragraph in doc.paragraphs])
    
    elif ext == 'pdf':
        text = ""
        with open(filepath, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            for page in pdf_reader.pages:
                text += page.extract_text()
        return text
    
    return ""

def generate_audio_with_google_tts(text, language_code='es-ES', output_file=None):
    """
    Genera audio usando Google Cloud Text-to-Speech como respaldo
    Usa API Key directamente sin necesidad de service account
    """
    if not GOOGLE_TTS_AVAILABLE:
        raise Exception("Google Cloud TTS no está disponible - librería no instalada")
    
    print("🔄 Usando Google Cloud TTS como respaldo...")
    
    try:
        # Inicializar cliente con API key desde variable de entorno
        api_key = os.environ.get('GOOGLE_API_KEY')
        if not api_key:
            raise Exception("GOOGLE_API_KEY no está configurada en las variables de entorno")
        
        print(f"🔑 Usando API Key de Google Cloud (primeros 10 caracteres): {api_key[:10]}...")
        
        # Crear cliente con API key
        from google.api_core import client_options as client_options_lib
        client_opts = client_options_lib.ClientOptions(api_key=api_key)
        client = texttospeech.TextToSpeechClient(client_options=client_opts)
        
        print("✅ Cliente de Google Cloud TTS inicializado correctamente")
        
    except Exception as auth_error:
        print(f"⚠️  Error al inicializar cliente Google: {auth_error}")
        print("⚠️  Intentando con configuración por defecto...")
        try:
            client = texttospeech.TextToSpeechClient()
        except Exception as fallback_error:
            raise Exception(f"No se pudo inicializar Google Cloud TTS: {fallback_error}")
    
    # Configurar la entrada de texto
    synthesis_input = texttospeech.SynthesisInput(text=text)
    
    # Configurar la voz (español con voz neuronal)
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name="es-ES-Neural2-A",  # Voz femenina neuronal española
        ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
    )
    
    # Configurar el audio de salida
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
        pitch=0.0
    )
    
    # Generar el audio
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    
    print("✅ Audio generado con Google Cloud TTS")
    return response.audio_content


def generate_audio_with_elevenlabs(text: str, voice_id: str = None, model: str = None) -> bytes:
    """Genera audio con ElevenLabs y devuelve bytes MP3.
    Usa API legacy si está disponible, si no usa el client API.
    """
    if not ELEVEN_AVAILABLE:
        raise Exception("ElevenLabs no está disponible (módulo no importado)")
    if not ELEVEN_API_KEY:
        raise Exception("ELEVEN_API_KEY no configurada")
    voice = voice_id or os.environ.get('ELEVEN_VOICE_ID') or 'Rachel'
    mdl = model or os.environ.get('ELEVEN_MODEL', 'eleven_multilingual_v2')
    print(f"🎙️  Usando ElevenLabs: voice={voice}, model={mdl}")
    if ELEVEN_USE_LEGACY:
        # Legacy simple API
        try:
            audio_bytes = el_generate(text=text, voice=voice, model=mdl)
            return audio_bytes
        except Exception as e:
            raise Exception(f"ElevenLabs (legacy) falló: {e}")
    else:
        # Client API
        try:
            client = ElevenLabs(api_key=ELEVEN_API_KEY)
            # text_to_speech.convert returns a stream; assemble bytes
            # API signature may vary by version; handle expected params
            response = client.text_to_speech.convert(
                voice_id=voice,
                optimize_streaming_latency=0,
                output_format="mp3_44100_128",
                model_id=mdl,
                text=text,
            )
            # response is a generator of chunks
            chunks = []
            for chunk in response:
                # each chunk is bytes
                chunks.append(chunk)
            return b''.join(chunks)
        except Exception as e:
            raise Exception(f"ElevenLabs (client) falló: {e}")

@app.route('/login', methods=['GET', 'POST'])
def login():
    print("\n🔐 LOGIN - Solicitud recibida")
    instituciones = ["Universidad Andrés Bello"]
    
    if request.method == 'POST':
        print("📥 Método POST detectado")
        correo = request.form.get('correo')
        password = request.form.get('password')
        print(f"📧 Correo recibido: {correo}")
        print(f"🔑 Password recibida: {'*' * len(password) if password else 'None'}")
        
        if usuarios_collection is None:
            print("❌ ERROR: No hay conexión a MongoDB")
            return render_template('login.html', error="Error de conexión a la base de datos", instituciones=instituciones)
        
        try:
            print(f"🔍 Buscando usuario con correo: {correo}")
            usuario = usuarios_collection.find_one({'correo': correo})
            print(f"👤 Usuario encontrado: {usuario is not None}")
            
            if usuario:
                print(f"✅ Usuario existe en BD: {usuario.get('nombre')}")
                # Verificar si la contraseña está hasheada (bcrypt) o en texto plano
                contraseña_guardada = usuario.get('contraseña', '')
                print(f"🔐 Longitud de contraseña guardada: {len(contraseña_guardada)}")
                print(f"🔐 Primeros caracteres: {contraseña_guardada[:10] if len(contraseña_guardada) >= 10 else contraseña_guardada}")
                
                password_valida = False
                
                # Detectar si es un hash de bcrypt (comienza con $2b$ o $2a$ o $2y$)
                if contraseña_guardada.startswith('$2b$') or contraseña_guardada.startswith('$2a$') or contraseña_guardada.startswith('$2y$'):
                    print("🔐 Detectado hash bcrypt, verificando...")
                    try:
                        password_valida = bcrypt.check_password_hash(contraseña_guardada, password)
                        if password_valida:
                            print("✅ Contraseña verificada con bcrypt")
                        else:
                            print("❌ Contraseña incorrecta (bcrypt)")
                    except Exception as e:
                        print(f"⚠️  Error al verificar con bcrypt: {e}")
                        password_valida = False
                else:
                    # Contraseña en texto plano (usuarios antiguos)
                    print("🔐 Contraseña en texto plano, comparando directamente...")
                    if contraseña_guardada == password:
                        print("✅ Contraseña verificada con texto plano")
                        password_valida = True
                        # Actualizar la contraseña a formato hash
                        try:
                            hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
                            usuarios_collection.update_one(
                                {'_id': usuario['_id']},
                                {'$set': {'contraseña': hashed_pw}}
                            )
                            print("🔄 Contraseña actualizada a formato hash")
                        except Exception as e:
                            print(f"⚠️  Error al actualizar contraseña: {e}")
                    else:
                        print("❌ Contraseña incorrecta (texto plano)")
                
                if password_valida:
                    session['usuario_id'] = str(usuario['_id'])
                    print(f"✅ Sesión creada para usuario: {usuario['_id']}")
                    return redirect(url_for('home'))
                else:
                    print("❌ Credenciales incorrectas - contraseña no coincide")
            else:
                print("❌ No se encontró usuario con ese correo")
            
            print("❌ Credenciales incorrectas")
        except Exception as e:
            print(f"❌ ERROR en login: {e}")
            return render_template('login.html', error=f"Error: {str(e)}", instituciones=instituciones)
        
        return render_template('login.html', error="Correo o contraseña incorrectos", instituciones=instituciones)
    
    print("📄 Método GET - Mostrando formulario de login")
    return render_template('login.html', instituciones=instituciones)

@app.route('/register', methods=['POST'])
def register():
    print("\n📝 REGISTER - Solicitud recibida")
    instituciones = ["Universidad Andrés Bello"]
    
    tipo_usuario = request.form.get('tipo_usuario')
    institucion = request.form.get('institucion') if tipo_usuario == 'profesor' else None
    nombre = request.form.get('nombre')
    correo = request.form.get('correo')
    password = request.form.get('password')
    
    print(f"👤 Tipo usuario: {tipo_usuario}")
    print(f"🏢 Institución: {institucion}")
    print(f"📛 Nombre: {nombre}")
    print(f"📧 Correo: {correo}")
    print(f"🔑 Password: {'*' * len(password) if password else 'None'}")
    
    if usuarios_collection is None:
        print("❌ ERROR: No hay conexión a MongoDB")
        return render_template('login.html', error="Error de conexión a la base de datos", instituciones=instituciones)
    
    try:
        print(f"🔍 Verificando si el correo ya existe: {correo}")
        existing_user = usuarios_collection.find_one({'correo': correo})
        
        if existing_user:
            print(f"⚠️  El correo ya está registrado")
            return render_template('login.html', error="El correo ya está registrado", instituciones=instituciones)
        
        print("🔐 Generando hash de contraseña...")
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        print(f"✅ Hash generado (longitud: {len(hashed_pw)})")
        print(f"✅ Hash primeros caracteres: {hashed_pw[:30]}...")
        print(f"✅ Hash empieza con $2b$: {hashed_pw.startswith('$2b$')}")
        
        usuario = {
            'tipo_usuario': tipo_usuario,
            'institucion': institucion if institucion else None,
            'nombre': nombre,
            'correo': correo,
            'contraseña': hashed_pw
        }
        
        print("💾 Insertando usuario en MongoDB...")
        print(f"📄 Documento a insertar: {{'tipo_usuario': '{tipo_usuario}', 'nombre': '{nombre}', 'correo': '{correo}', 'contraseña': '[HASH]'}}")
        result = usuarios_collection.insert_one(usuario)
        print(f"✅ Usuario insertado con ID: {result.inserted_id}")
        
        session['usuario_id'] = str(result.inserted_id)
        print(f"✅ Sesión creada para nuevo usuario")
        
        # Verificar que se guardó correctamente
        verificacion = usuarios_collection.find_one({'_id': result.inserted_id})
        if verificacion:
            print(f"✅ Verificación: Usuario guardado correctamente - {verificacion.get('nombre')}")
            print(f"✅ Contraseña en BD (primeros chars): {verificacion.get('contraseña', '')[:30]}...")
            print(f"✅ Longitud de contraseña en BD: {len(verificacion.get('contraseña', ''))}")
        else:
            print("⚠️  ADVERTENCIA: No se pudo verificar el usuario guardado")
        
        return redirect(url_for('home'))
        
    except Exception as e:
        print(f"❌ ERROR en register: {e}")
        import traceback
        traceback.print_exc()
        return render_template('login.html', error=f"Error al registrar: {str(e)}", instituciones=instituciones)

@app.route('/')
def bienvenida():
    """Página de bienvenida - accesible sin login"""
    if 'usuario_id' in session:
        return redirect(url_for('home'))
    return render_template('Bienvenida.html')

@app.route('/index')
def index():
    """Página principal del convertidor TTS - requiere login"""
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/home')
def home():
    """Página principal de la plataforma tras iniciar sesión (dashboard)"""
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('HomePage.html')

@app.route('/test-db')
def test_db():
    """Endpoint para verificar la conexión a MongoDB"""
    try:
        if client is None:
            return jsonify({'error': 'No hay conexión a MongoDB'}), 500
        
        # Ping a MongoDB
        client.admin.command('ping')
        
        # Contar usuarios
        count = usuarios_collection.count_documents({})
        
        # Obtener todos los usuarios (sin contraseñas)
        usuarios = list(usuarios_collection.find({}, {'contraseña': 0}))
        
        # Convertir ObjectId a string
        for u in usuarios:
            u['_id'] = str(u['_id'])
        
        return jsonify({
            'status': 'Conectado',
            'database': db.name,
            'collection': 'usuarios',
            'total_usuarios': count,
            'usuarios': usuarios
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    """Cerrar sesión y redirigir a página de bienvenida"""
    session.clear()
    return redirect(url_for('bienvenida'))

@app.route('/biblioteca')
def biblioteca():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('biblioteca.html')

@app.route('/descubrir')
def descubrir():
    """Página de descubrimiento y recomendaciones"""
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('Descubrir.html')

# Ruta habilitada: página para subir libros manualmente
@app.route('/subir_libro', methods=['GET', 'POST'])
def subir_libro():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'GET':
        return render_template('subir_libro.html')
    
    # POST - Procesar el formulario
    try:
        print("\n📚 SUBIR LIBRO - Guardando nuevo libro en la biblioteca")
        
        # Verificar que hay un archivo de audio
        if 'audioFile' not in request.files:
            return jsonify({'error': 'No se proporcionó el archivo de audio'}), 400
        
        audio_file = request.files['audioFile']
        if audio_file.filename == '':
            return jsonify({'error': 'No se seleccionó ningún archivo de audio'}), 400
        
        # Validar que sea MP3
        if not audio_file.filename.lower().endswith('.mp3'):
            return jsonify({'error': 'El archivo de audio debe ser formato MP3'}), 400
        
        # Obtener datos del formulario
        title = request.form.get('title', '').strip()
        subtitle = request.form.get('subtitle', '').strip()
        category = request.form.get('category', '').strip()
        level = request.form.get('level', '').strip()
        content_text = request.form.get('contentText', '').strip()
        
        # Validar campos requeridos
        if not all([title, subtitle, category, level]):
            return jsonify({'error': 'Todos los campos son requeridos'}), 400
        
        timestamp = int(time.time())
        
        # Guardar archivo de audio
        audio_filename = secure_filename(audio_file.filename)
        unique_audio_filename = f"{timestamp}_audio_{audio_filename}"
        audio_filepath = os.path.join(app.config['AUDIO_FOLDER'], unique_audio_filename)
        audio_file.save(audio_filepath)
        
        print(f"🎵 Archivo de audio guardado: {unique_audio_filename}")
        
        # Calcular duración del audio
        try:
            audio = MP3(audio_filepath)
            duration_seconds = int(audio.info.length)
            
            # Formatear duración
            if duration_seconds < 60:
                duration = f"{duration_seconds} seg"
            elif duration_seconds < 3600:
                minutes = duration_seconds // 60
                seconds = duration_seconds % 60
                duration = f"{minutes} min {seconds} seg" if seconds > 0 else f"{minutes} min"
            else:
                hours = duration_seconds // 3600
                minutes = (duration_seconds % 3600) // 60
                duration = f"{hours}h {minutes}min" if minutes > 0 else f"{hours}h"
            
            print(f"⏱️  Duración del audio: {duration}")
        except Exception as e:
            print(f"⚠️  No se pudo calcular la duración del audio: {e}")
            duration = "Duración no disponible"
        
        # Mapeo de categorías a etiquetas visuales
        category_labels = {
            'historia': 'Historia',
            'cuentos': 'Cuentos',
            'novelas': 'Novelas',
            'aprendizaje': 'Aprendizaje',
            'biologia': 'Biología',
            'ciencia': 'Ciencia',
            'tecnologia': 'Tecnología',
            'arte': 'Arte',
            'noticias': 'Noticias'
        }
        
        level_labels = {
            'facil': 'Fácil',
            'medio': 'Medio',
            'alta': 'Alta'
        }
        
        # Crear documento para MongoDB
        libro_data = {
            'title': title,
            'subtitle': subtitle,
            'category': category,
            'categoryLabel': category_labels.get(category, category.title()),
            'level': level,
            'levelLabel': level_labels.get(level, level.title()),
            'duration': duration,
            'duration_seconds': duration_seconds,
            'audio_filename': unique_audio_filename,
            'audio_url': f'/audio_files/{unique_audio_filename}',
            'text': content_text if content_text else None,
            'uploaded_by': session['usuario_id'],
            'uploaded_at': timestamp,
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Guardar en MongoDB
        if libros_collection is not None:
            result = libros_collection.insert_one(libro_data)
            print(f"📚 Libro guardado en MongoDB con ID: {result.inserted_id}")
            
            return jsonify({
                'message': f'Libro "{title}" guardado exitosamente en la biblioteca',
                'libro_id': str(result.inserted_id)
            }), 200
        else:
            return jsonify({'error': 'No hay conexión a la base de datos'}), 500
            
    except Exception as e:
        print(f"❌ ERROR al guardar libro: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Error al guardar el libro: {str(e)}'}), 500

@app.route('/api/libros', methods=['GET'])
def obtener_libros():
    """API para obtener todos los libros de la biblioteca"""
    try:
        if libros_collection is None:
            return jsonify({'error': 'No hay conexión a la base de datos'}), 500
        
        # Traer también el _id para poder navegar a un libro específico
        libros = list(libros_collection.find({}))
        
        # Agregar ID numérico para cada libro
        for idx, libro in enumerate(libros, start=1):
            # Conservar un id incremental para la UI
            libro['id'] = idx
            # Exponer el ObjectId como string para navegación directa
            if '_id' in libro:
                libro['_id'] = str(libro['_id'])
            # Normalizar parent_id si existe
            if 'parent_id' in libro and libro['parent_id']:
                try:
                    libro['parent_id'] = str(libro['parent_id'])
                except Exception:
                    pass
        
        return jsonify({'libros': libros}), 200
    except Exception as e:
        print(f"❌ ERROR al obtener libros: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/autocomplete', methods=['GET'])
def api_autocomplete():
    """Devuelve sugerencias rápidas para el buscador (títulos y categorías)."""
    try:
        if libros_collection is None:
            return jsonify({'suggestions': []})
        q = (request.args.get('q') or '').strip()
        if not q:
            return jsonify({'suggestions': []})
        # Traer un subconjunto razonable (hasta 200) para sugerencias
        docs = list(libros_collection.find({}, {'title': 1, 'subtitle': 1, 'category': 1, 'categoryLabel': 1}).sort('uploaded_at', -1).limit(200))
        ql = q.lower()
        # Preferimos los que empiezan con el query, luego los que contienen
        titles = []
        for d in docs:
            t = str(d.get('title') or '')
            if t:
                titles.append(t)
        # Únicos, preservando orden
        seen = set()
        titles_unique = []
        for t in titles:
            if t not in seen:
                seen.add(t)
                titles_unique.append(t)
        starts = [t for t in titles_unique if t.lower().startswith(ql)]
        contains = [t for t in titles_unique if ql in t.lower() and t not in starts]
        # Añadir categorías relacionadas
        cats = list({(d.get('categoryLabel') or d.get('category') or '') for d in docs})
        cat_contains = [c for c in cats if ql and ql in str(c).lower()]
        # Limitar
        suggestions = (starts + contains + cat_contains)[:10]
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        print(f"❌ ERROR autocomplete: {e}")
        return jsonify({'suggestions': []})


@app.route('/api/search', methods=['GET'])
def api_search():
    """Búsqueda semántica ligera por título, subtítulo, categoría, topics (si existen)."""
    try:
        if libros_collection is None:
            return jsonify({'libros': []})
        q = (request.args.get('q') or '').strip()
        if not q:
            # sin query: devolver recientes
            docs = list(libros_collection.find({}).sort('uploaded_at', -1).limit(50))
            for d in docs:
                d['_id'] = str(d['_id'])
            return jsonify({'libros': docs})
        # expandir query con IA si está disponible
        keywords = expand_query(q)
        kws = [k.lower() for k in keywords]
        # traer un conjunto de documentos y rankear en Python
        docs = list(libros_collection.find({}).limit(500))
        def score(doc):
            s = 0
            t = str(doc.get('title') or '').lower()
            sub = str(doc.get('subtitle') or '').lower()
            cat = str(doc.get('category') or '').lower() + ' ' + str(doc.get('categoryLabel') or '').lower()
            topics = ' '.join((doc.get('analysis', {}) or {}).get('topics', [])).lower()
            # pesos simples
            for k in kws:
                if k in t: s += 3
                if k in sub: s += 2
                if k in cat: s += 2
                if k and k in topics: s += 2
            return s
        ranked = sorted(docs, key=score, reverse=True)
        top = [
            {**d, '_id': str(d.get('_id'))}
            for d in ranked[:30]
            if score(d) > 0
        ]
        return jsonify({'libros': top})
    except Exception as e:
        print(f"❌ ERROR search: {e}")
        return jsonify({'libros': []})

@app.route('/reproductor/<book_id>')
def reproductor(book_id):
    """Página de reproducción de un libro específico por su ObjectId"""
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    if libros_collection is None:
        return redirect(url_for('biblioteca'))

    try:
        libro = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not libro:
            return redirect(url_for('biblioteca'))

        # Registrar última reproducción para "Recientes"
        try:
            now = datetime.utcnow()
            libros_collection.update_one({'_id': ObjectId(book_id)}, {
                '$set': {
                    'last_played_at': now,
                    'last_played_by': str(session.get('usuario_id', ''))
                },
                '$inc': { 'play_count': 1 }
            })
        except Exception as _e:
            print(f"⚠️  No se pudo registrar last_played_at: {_e}")

        # Convertir _id para evitar problemas en la plantilla y asegurar campos esperados
        libro['_id'] = str(libro['_id'])
        return render_template('reproductor.html', libro=libro)
    except Exception as e:
        print(f"❌ ERROR en reproductor({book_id}): {e}")
        return redirect(url_for('biblioteca'))

@app.route('/reproductor', endpoint='reproductor_root')
def reproductor_root():
    """Página de reproductor sin selección: muestra lista rápida en sidebar"""
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    # Renderiza la misma plantilla sin 'libro' para que muestre un estado vacío y la lista de libros en el sidebar
    return render_template('reproductor.html', libro=None)

@app.route('/api/playback/event', methods=['POST'])
def api_playback_event():
    """Registra eventos de reproducción para calcular progreso y finalización.
    Body JSON: { book_id, event: 'start'|'progress'|'ended', position?: sec, duration?: sec }
    """
    try:
        if libros_collection is None:
            return jsonify({'ok': False, 'error': 'DB unavailable'}), 503
        data = request.get_json(force=True, silent=True) or {}
        book_id = (data.get('book_id') or '').strip()
        event = (data.get('event') or '').strip().lower()
        if not book_id or event not in ('start','progress','ended'):
            return jsonify({'ok': False, 'error': 'invalid-payload'}), 400
        position = float(data.get('position') or 0)
        duration = float(data.get('duration') or 0)
        now = datetime.utcnow()
        updates = {
            '$set': {
                'last_played_at': now,
                'last_played_by': str(session.get('usuario_id', '')),
            },
            '$inc': { 'play_count': 1 } if event == 'start' else {}
        }
        # calcular progreso si hay duración > 0
        prog = None
        if duration and duration > 0:
            p = int(max(0, min(100, round((position / duration) * 100))))
            prog = p
            updates['$set']['progress'] = p
            updates['$set']['last_position_sec'] = int(max(0, round(position)))
            updates['$set']['duration_seconds'] = int(max(0, round(duration)))
        if event == 'ended':
            updates['$set']['progress'] = 100
            updates['$set']['completed_at'] = now
        # limpiar inc vacío
        if not updates['$inc']:
            updates.pop('$inc', None)
        libros_collection.update_one({'_id': ObjectId(book_id)}, updates)
        return jsonify({'ok': True, 'progress': prog if prog is not None else None})
    except Exception as e:
        print(f"❌ ERROR playback/event: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/recientes')
def recientes():
    """Lista de libros reproducidos en las últimas 24 horas."""
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    try:
        if libros_collection is None:
            return render_template('recientes.html', recientes=[], total=0, completed=0, in_progress=0, today_count=0)
        now = datetime.utcnow()
        from_dt = now - timedelta(hours=24)
        cursor = libros_collection.find({ 'last_played_at': { '$gte': from_dt } }).sort('last_played_at', -1)
        recientes = []
        for d in cursor:
            d['_id'] = str(d.get('_id'))
            # Normalizar campos usados en la UI
            d['title'] = d.get('title') or 'Sin título'
            d['subtitle'] = d.get('subtitle') or ''
            d['categoryLabel'] = d.get('categoryLabel') or d.get('category') or ''
            d['cover_image_url'] = d.get('cover_image_url') or ''
            d['duration'] = d.get('duration') or ''
            d['progress'] = d.get('progress') or 0
            d['last_played_at'] = d.get('last_played_at')
            d['completed_at'] = d.get('completed_at')
            recientes.append(d)
        # Métricas: total, completados, en progreso, hoy
        today_date = now.date()
        total = len(recientes)
        # Completados: terminados en las últimas 24h (completed_at dentro de la ventana)
        completed = 0
        in_progress = 0
        today_count = 0
        for d in recientes:
            prog = int(d.get('progress') or 0)
            c_at = d.get('completed_at')
            # completados en 24h
            if c_at and c_at >= from_dt:
                completed += 1
                # hoy = completados cuya fecha es hoy
                try:
                    if c_at.date() == today_date:
                        today_count += 1
                except Exception:
                    pass
            else:
                # en progreso en la ventana si no están completos
                if 0 < prog < 100:
                    in_progress += 1
        return render_template('recientes.html', recientes=recientes, total=total, completed=completed, in_progress=in_progress, today_count=today_count)
    except Exception as e:
        print(f"❌ ERROR en /recientes: {e}")
        return render_template('recientes.html', recientes=[], total=0, completed=0, in_progress=0, today_count=0)

@app.route('/upload', methods=['POST'])
def upload():
    print("\n🎵 UPLOAD - Solicitud de conversión de texto a audio")
    try:
        print("📁 Verificando archivo...")
        if 'file' not in request.files:
            print("❌ No se encontró ningún archivo en la solicitud")
            return jsonify({'error': 'No se encontró ningún archivo'}), 400
        
        file = request.files['file']
        print(f"📄 Archivo recibido: {file.filename}")
        
        if file.filename == '':
            print("❌ El nombre del archivo está vacío")
            return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
        
        if not allowed_file(file.filename):
            print(f"❌ Tipo de archivo no permitido: {file.filename}")
            return jsonify({'error': 'Tipo de archivo no permitido. Usa: .txt, .pdf, .docx, .brf'}), 400
        
        # Guardar archivo
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        print(f"💾 Guardando archivo en: {filepath}")
        file.save(filepath)
        print("✅ Archivo guardado")
        
    # Extraer texto
        print("📖 Extrayendo texto del archivo...")
        text = extract_text_from_file(filepath)
        print(f"✅ Texto extraído: {len(text)} caracteres")
        print(f"📝 Primeros 100 caracteres: {text[:100]}...")
        
        if not text or len(text.strip()) == 0:
            print("❌ No se pudo extraer texto del archivo")
            os.remove(filepath)
            return jsonify({'error': 'No se pudo extraer texto del archivo o está vacío'}), 400
        
        # Enriquecimiento IA: resumen (opcional)
        ai_summary = None
        try:
            ai_summary = summarize_text(text)
            if ai_summary:
                print(f"🧠 Resumen IA generado ({len(ai_summary)} chars)")
        except Exception as se:
            print(f"⚠️  No se pudo generar resumen IA: {se}")

        # Obtener la voz seleccionada
        voice_id = request.form.get('voice', 'rpqlUOplj0Q0PIilat8h')
        print(f"🎤 Voz seleccionada: {voice_id}")
        
        # Limitar texto si es muy largo
        MAX_CHARS = 5000
        if len(text) > MAX_CHARS:
            print(f"⚠️  Texto muy largo ({len(text)} chars), limitando a {MAX_CHARS}")
            text = text[:MAX_CHARS] + "..."
        
        # TTS: ElevenLabs como principal, Google como respaldo
        audio = None
        tts_engine_used = None
        primary = (os.environ.get('TTS_PRIMARY') or 'elevenlabs').lower()
        engines = []
        if primary == 'elevenlabs':
            engines = ['elevenlabs', 'google']
        elif primary == 'google':
            engines = ['google', 'elevenlabs']
        else:
            engines = ['elevenlabs', 'google']

        last_err = None
        for eng in engines:
            if eng == 'elevenlabs':
                if ELEVEN_AVAILABLE and ELEVEN_API_KEY:
                    try:
                        audio = generate_audio_with_elevenlabs(text, voice_id=voice_id)
                        tts_engine_used = 'ElevenLabs'
                        print("✅ Audio generado con ElevenLabs")
                        break
                    except Exception as e:
                        print(f"⚠️  ElevenLabs falló: {e}")
                        last_err = e
                else:
                    print("ℹ️  ElevenLabs no disponible o sin API KEY; saltando…")
            elif eng == 'google':
                if GOOGLE_TTS_AVAILABLE:
                    try:
                        audio = generate_audio_with_google_tts(text, language_code='es-ES')
                        tts_engine_used = 'Google Cloud TTS'
                        print("✅ Audio generado con Google Cloud TTS")
                        break
                    except Exception as e:
                        print(f"⚠️  Google TTS falló: {e}")
                        last_err = e
                else:
                    print("ℹ️  Google TTS no disponible; saltando…")

        if audio is None:
            os.remove(filepath)
            return jsonify({'error': f'No se pudo generar audio (último error: {last_err})'}), 500
        
        # Guardar audio
        audio_filename = f"audio_{int(time.time())}.mp3"
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        print(f"💾 Guardando audio en: {audio_path}")
        
        with open(audio_path, 'wb') as f:
            f.write(audio)
        
        file_size = os.path.getsize(audio_path)
        print(f"✅ Audio guardado: {audio_filename} ({file_size} bytes)")
        print(f"🎙️  Motor TTS utilizado: {tts_engine_used}")

        # Calcular duración del audio generado (siempre) para sincronización
        try:
            audio_mp3 = MP3(audio_path)
            duration_seconds = int(audio_mp3.info.length)
            print(f"⏱️  Duración del audio generado: {duration_seconds}s")
        except Exception as e:
            print(f"⚠️  No se pudo calcular la duración del audio generado: {e}")
            duration_seconds = 0
        
        # Limpiar archivo subido
        os.remove(filepath)
        print("🗑️  Archivo temporal eliminado")
        
        audio_url = f'/audio_files/{audio_filename}'
        print(f"✅ Conversión completada. URL: {audio_url}")
        # Actualizar diagnóstico
        try:
            LAST_TTS_STATUS['engine'] = tts_engine_used
            # Normalizar comparación de motor primario vs usado
            primary_norm = engines[0]
            used_norm = 'elevenlabs' if tts_engine_used == 'ElevenLabs' else ('google' if tts_engine_used == 'Google Cloud TTS' else None)
            LAST_TTS_STATUS['fallback_reason'] = None if (used_norm == primary_norm) else (str(last_err) if last_err else 'fallback')
            LAST_TTS_STATUS['timestamp'] = int(time.time())
        except Exception:
            pass
        
        # ¿Guardar automáticamente en biblioteca?
        save_to_library = request.form.get('saveToLibrary') in ['true', 'True', '1', 'on', 'yes']
        saved_doc_id = None
        if save_to_library:
            print("📚 Opción 'Guardar en Biblioteca' activada")
            title = request.form.get('title', '').strip()
            subtitle = request.form.get('subtitle', '').strip()
            category = request.form.get('category', '').strip()
            level = request.form.get('level', '').strip()
            save_as_chapter = request.form.get('saveAsChapter') in ['true','True','1','on','yes']
            parent_book_id = (request.form.get('parentBookId') or '').strip()
            chapter_title = (request.form.get('chapterTitle') or '').strip()

            # Validación mínima cuando se desea guardar
            if not save_as_chapter:
                if not all([title, subtitle, category, level]):
                    print("❌ Datos incompletos para guardar en biblioteca")
                    return jsonify({'error': 'Faltan campos para guardar en biblioteca (título, descripción, categoría, nivel).', 'audio_url': audio_url}), 400
            else:
                # Guardar como capítulo de libro existente
                if not parent_book_id:
                    return jsonify({'error': 'Debes seleccionar el libro al que pertenece el capítulo.', 'audio_url': audio_url}), 400
                parent_doc = None
                try:
                    parent_doc = libros_collection.find_one({'_id': ObjectId(parent_book_id)}) if libros_collection is not None else None
                except Exception:
                    parent_doc = None
                if not parent_doc:
                    return jsonify({'error': 'Libro padre no encontrado.', 'audio_url': audio_url}), 404
                # Heredar categoría/nivel si no se proporcionan
                if not category:
                    category = parent_doc.get('category', '')
                if not level:
                    level = parent_doc.get('level', '')
                # Título por defecto si no viene
                if not title:
                    # Construir: "<Título padre> — Capítulo <ROMAN>" (+ opcional subtítulo con chapter_title)
                    # Número se calculará más abajo, placeholder temporal
                    title = parent_doc.get('title', 'Libro')

            # Formatear duración reutilizando duration_seconds ya calculado
            if duration_seconds > 0:
                if duration_seconds < 60:
                    duration = f"{duration_seconds} seg"
                elif duration_seconds < 3600:
                    minutes = duration_seconds // 60
                    seconds = duration_seconds % 60
                    duration = f"{minutes} min {seconds} seg" if seconds > 0 else f"{minutes} min"
                else:
                    hours = duration_seconds // 3600
                    minutes = (duration_seconds % 3600) // 60
                    duration = f"{hours}h {minutes}min" if minutes > 0 else f"{hours}h"
            else:
                duration = "Duración no disponible"

            # Etiquetas
            category_labels = {
                'historia': 'Historia', 'cuentos': 'Cuentos', 'novelas': 'Novelas', 'aprendizaje': 'Aprendizaje',
                'biologia': 'Biología', 'ciencia': 'Ciencia', 'tecnologia': 'Tecnología', 'arte': 'Arte', 'noticias': 'Noticias'
            }
            level_labels = { 'facil': 'Fácil', 'medio': 'Medio', 'alta': 'Alta' }

            # Documento
            libro_data = {
                'title': title,
                'subtitle': subtitle,
                'category': category,
                'categoryLabel': category_labels.get(category, category.title()) if isinstance(category, str) else str(category),
                'level': level,
                'levelLabel': level_labels.get(level, level.title()) if isinstance(level, str) else str(level),
                'duration': duration,
                'duration_seconds': duration_seconds,
                'audio_filename': audio_filename,
                'audio_url': audio_url,
                # Guardar el texto que realmente se usó para el TTS (posiblemente truncado)
                'text': text,
                'summary': ai_summary,
                'uploaded_by': session.get('usuario_id'),
                'uploaded_at': int(time.time()),
                'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }

            # Portada: si es libro raíz, generar una portada local; si es capítulo, heredar del padre
            try:
                cover_url = None
                if save_as_chapter:
                    if parent_doc:
                        cover_url = parent_doc.get('cover_image_url')
                else:
                    # Generar portada simple basada en categoría/título
                    cov_bytes = generate_cover_image_bytes(
                        category=libro_data.get('categoryLabel') or libro_data.get('category'),
                        title=libro_data.get('title'),
                        subtitle=libro_data.get('subtitle') or libro_data.get('summary')
                    )
                    if cov_bytes:
                        cname = f"cover_{int(time.time())}.jpg"
                        cpath = os.path.join(app.config['COVERS_FOLDER'], cname)
                        with open(cpath, 'wb') as cf:
                            cf.write(cov_bytes)
                        cover_url = f"/static/covers/{cname}"
                if cover_url:
                    libro_data['cover_image_url'] = cover_url
            except Exception as ce:
                print(f"⚠️  No se pudo generar/asignar portada: {ce}")

            # Si es capítulo, calcular numeración y completar campos
            if save_as_chapter:
                try:
                    existing = 0
                    if libros_collection is not None:
                        or_conds = []
                        try:
                            or_conds.append({'parent_id': ObjectId(parent_book_id)})
                        except Exception:
                            pass
                        or_conds.append({'parent_id': parent_book_id})
                        existing = libros_collection.count_documents({'$or': or_conds})
                    chap_num = int(existing) + 1
                except Exception:
                    chap_num = 1
                chap_roman = _to_roman(chap_num)
                # Ajustar título si es placeholder
                if parent_doc and (title == parent_doc.get('title') or not title):
                    base = parent_doc.get('title', 'Libro')
                    if chapter_title:
                        libro_data['title'] = f"{base} — Capítulo {chap_roman}: {chapter_title}"
                    else:
                        libro_data['title'] = f"{base} — Capítulo {chap_roman}"
                libro_data.update({
                    'is_chapter': True,
                    'parent_id': ObjectId(parent_book_id),
                    'chapter_number': chap_num,
                    'chapter_roman': chap_roman,
                    'chapter_title': chapter_title or None,
                })

            if libros_collection is not None:
                try:
                    result = libros_collection.insert_one(libro_data)
                    saved_doc_id = str(result.inserted_id)
                    print(f"✅ Libro guardado automáticamente en biblioteca con ID: {saved_doc_id}")
                except Exception as e:
                    print(f"❌ Error al guardar automáticamente en biblioteca: {e}")
            else:
                print("❌ No hay conexión a la base de datos para guardar el libro")

        return jsonify({
            'success': True,
            'audio_url': audio_url,
            'message': f'Conversión exitosa con {tts_engine_used}',
            'tts_engine': tts_engine_used,
            'audio_size': file_size,
            'text_length': len(text),
            # Devolver el texto utilizado para permitir sincronización en el reproductor sin necesidad de guardar
            'text': text,
            'summary': ai_summary,
            'duration_seconds': duration_seconds,
            'saved_to_library': bool(saved_doc_id),
            'libro_id': saved_doc_id
        })
    
    except Exception as e:
        print(f"❌ ERROR en upload: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Error al procesar el archivo: {str(e)}'}), 500

@app.route('/audio_files/<filename>')
def serve_audio(filename):
    """Sirve archivos de audio generados"""
    print(f"🎵 Sirviendo archivo de audio: {filename}")
    try:
        return send_from_directory(app.config['AUDIO_FOLDER'], filename)
    except Exception as e:
        print(f"❌ Error al servir audio: {e}")
        return jsonify({'error': 'Archivo no encontrado'}), 404


@app.route('/api/audio', methods=['DELETE'])
def api_delete_audio_file():
    """Elimina un archivo de audio suelto por nombre de archivo o URL.
    Acepta query params: filename=audio_*.mp3 o audio_url=/audio_files/audio_*.mp3
    """
    try:
        # Obtener filename directo o desde la URL
        filename = (request.args.get('filename') or '').strip()
        audio_url = (request.args.get('audio_url') or '').strip()
        if not filename and audio_url:
            # Extraer basename de /audio_files/<name>
            try:
                from urllib.parse import urlparse
                path = urlparse(audio_url).path or ''
                if '/audio_files/' in path:
                    filename = path.split('/audio_files/')[-1]
                else:
                    # si mandaron solo el path completo en relativo
                    if path:
                        filename = path.split('/')[-1]
            except Exception:
                filename = ''
        # Sanitizar
        filename = os.path.basename(filename)
        if not filename:
            return jsonify({'error': 'Parámetro filename o audio_url requerido'}), 400

        # Construir ruta absoluta dentro de la carpeta de audios
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], filename)
        # Verificar que realmente apunta a la carpeta de audios
        safe_root = os.path.abspath(app.config['AUDIO_FOLDER'])
        safe_path = os.path.abspath(audio_path)
        if not safe_path.startswith(safe_root + os.sep) and safe_path != safe_root:
            return jsonify({'error': 'Ruta inválida'}), 400

        if not os.path.isfile(audio_path):
            return jsonify({'error': 'Archivo no encontrado'}), 404

        os.remove(audio_path)
        return jsonify({'success': True, 'deleted': filename})
    except Exception as e:
        print(f"❌ ERROR al eliminar audio suelto: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/libros/<book_id>/chapters', methods=['GET'])
def api_get_chapters(book_id):
    """Devuelve la lista de capítulos para un libro padre, ordenados por chapter_number."""
    try:
        if libros_collection is None:
            return jsonify({'error': 'No hay conexión a la base de datos'}), 500
        # Soportar parent_id como ObjectId o string
        conds = [{ 'parent_id': book_id }]
        try:
            conds.append({ 'parent_id': ObjectId(book_id) })
        except Exception:
            pass
        # Incluir variaciones antiguas: is_chapter como string 'True' o 1
        q = {
            '$and': [
                { '$or': conds },
                { '$or': [ { 'is_chapter': True }, { 'is_chapter': 'True' }, { 'is_chapter': 1 } ] }
            ]
        }
        chapters = list(libros_collection.find(q).sort('chapter_number', 1))
        for ch in chapters:
            ch['_id'] = str(ch['_id'])
            if 'parent_id' in ch and ch['parent_id']:
                try:
                    ch['parent_id'] = str(ch['parent_id'])
                except Exception:
                    pass
        return jsonify({ 'chapters': chapters })
    except Exception as e:
        print(f"❌ ERROR al obtener capítulos: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/libros/<book_id>/reparent', methods=['POST'])
def api_reparent_book(book_id):
    """Convierte un libro existente en capítulo de un libro padre y lo numera al final.
    Body: parentBookId (requerido), keepTitle (opcional: 'true'/'false'), chapterTitle (opcional)
    """
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        payload = request.get_json(silent=True) or request.form or {}
        parent_id_in = (payload.get('parentBookId') or '').strip()
        keep_title = str(payload.get('keepTitle')).lower() in ['true', '1', 'yes', 'on']
        chap_title = (payload.get('chapterTitle') or '').strip()
        if not parent_id_in:
            return jsonify({'error': 'parentBookId es requerido'}), 400

        # Resolver child por ObjectId o string
        oid_child = None
        try:
            oid_child = ObjectId(book_id)
        except Exception:
            oid_child = None
        q_child = {'$or': []}
        if oid_child is not None:
            q_child['$or'].append({'_id': oid_child})
        q_child['$or'].append({'_id': book_id})
        child = libros_collection.find_one(q_child)
        if not child:
            return jsonify({'error': 'Libro a convertir no encontrado'}), 404

        # Resolver parent
        oid_parent = None
        try:
            oid_parent = ObjectId(parent_id_in)
        except Exception:
            oid_parent = None
        q_parent = {'$or': []}
        if oid_parent is not None:
            q_parent['$or'].append({'_id': oid_parent})
        q_parent['$or'].append({'_id': parent_id_in})
        parent = libros_collection.find_one(q_parent)
        if not parent:
            return jsonify({'error': 'Libro padre no encontrado'}), 404

        # Contar capítulos existentes del padre (ambos tipos de parent_id)
        child_or = []
        if oid_parent is not None:
            child_or.append({'parent_id': oid_parent})
        child_or.append({'parent_id': parent_id_in})
        existing = libros_collection.count_documents({'$or': child_or})
        chap_num = int(existing) + 1
        chap_roman = _to_roman(chap_num)

        # Preparar actualización
        update = {
            'is_chapter': True,
            'parent_id': oid_parent if oid_parent is not None else parent_id_in,
            'chapter_number': chap_num,
            'chapter_roman': chap_roman,
        }
        # Chapter title: si viene explícito, usarlo; si no, derivar del título actual
        if chap_title:
            update['chapter_title'] = chap_title
        else:
            # Intentar derivar: si el título ya contiene "Capítulo", no forzar
            cur_title = (child.get('title') or '').strip()
            update['chapter_title'] = None if ('capítulo' in cur_title.lower()) else cur_title

        # Heredar categoría/nivel si faltan
        if not child.get('category'):
            update['category'] = parent.get('category')
            update['categoryLabel'] = parent.get('categoryLabel')
        if not child.get('level'):
            update['level'] = parent.get('level')
            update['levelLabel'] = parent.get('levelLabel')
        # Heredar portada si falta
        if not child.get('cover_image_url') and parent.get('cover_image_url'):
            update['cover_image_url'] = parent.get('cover_image_url')

        # Título compuesto (salvo que se pida conservar)
        if not keep_title:
            base = parent.get('title', 'Libro')
            if update.get('chapter_title'):
                update['title'] = f"{base} — Capítulo {chap_roman}: {update['chapter_title']}"
            else:
                update['title'] = f"{base} — Capítulo {chap_roman}"

        libros_collection.update_one({'_id': child['_id']}, {'$set': update})
        child = libros_collection.find_one({'_id': child['_id']})
        # Normalizar salida
        child['_id'] = str(child['_id'])
        if 'parent_id' in child and child['parent_id']:
            try: child['parent_id'] = str(child['parent_id'])
            except Exception: pass
        return jsonify({'success': True, 'chapter': child})
    except Exception as e:
        print(f"❌ ERROR reparent: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/orphan-audios', methods=['GET'])
def api_list_orphan_audios():
    """Lista archivos .mp3 en la carpeta de audios que no están referenciados en la colección de libros."""
    try:
        # Listar archivos en disco
        all_files = []
        try:
            for name in os.listdir(app.config['AUDIO_FOLDER']):
                if name.lower().endswith('.mp3'):
                    all_files.append(name)
        except FileNotFoundError:
            all_files = []

        if libros_collection is None:
            # Sin DB: consideramos todos como huérfanos
            return jsonify({'orphans': all_files})

        # Recolectar nombres en DB
        referenced = set()
        try:
            for d in libros_collection.find({}, {'audio_filename': 1}).limit(100000):
                fn = d.get('audio_filename')
                if fn:
                    referenced.add(str(fn))
        except Exception as e:
            print(f"⚠️  Error al consultar DB para huérfanos: {e}")

        orphans = [f for f in all_files if f not in referenced]
        return jsonify({'orphans': orphans})
    except Exception as e:
        print(f"❌ ERROR al listar audios huérfanos: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/backfill-covers', methods=['POST'])
def api_backfill_covers():
    """Genera portadas para libros sin cover_image_url.
    - Para libros raíz: genera imagen local basada en categoría/título.
    - Para capítulos: hereda la portada del padre; si el padre no tiene, la genera.
    Devuelve conteos de generados e heredados.
    """
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        created = 0
        inherited = 0
        # Traer candidatos sin portada
        candidates = list(libros_collection.find({
            '$or': [
                { 'cover_image_url': { '$exists': False } },
                { 'cover_image_url': None },
                { 'cover_image_url': '' }
            ]
        }).limit(5000))
        for d in candidates:
            try:
                is_ch = bool(d.get('is_chapter'))
                if is_ch:
                    # heredar del padre
                    pid = d.get('parent_id')
                    parent = None
                    if pid is not None:
                        # soportar ObjectId/string
                        q = {'$or': []}
                        try:
                            q['$or'].append({'_id': ObjectId(str(pid))})
                        except Exception:
                            pass
                        q['$or'].append({'_id': str(pid)})
                        parent = libros_collection.find_one(q)
                    if parent:
                        p_cover = parent.get('cover_image_url')
                        if not p_cover:
                            # generar para el padre primero
                            cat = parent.get('categoryLabel') or parent.get('category')
                            cov = generate_cover_image_bytes(cat, parent.get('title'), parent.get('subtitle') or parent.get('summary'))
                            if cov:
                                cname = f"cover_{str(parent.get('_id'))}_{int(time.time())}.jpg"
                                cpath = os.path.join(app.config['COVERS_FOLDER'], cname)
                                with open(cpath, 'wb') as cf: cf.write(cov)
                                p_cover = f"/static/covers/{cname}"
                                libros_collection.update_one({'_id': parent['_id']}, {'$set': {'cover_image_url': p_cover}})
                                created += 1
                        if p_cover:
                            libros_collection.update_one({'_id': d['_id']}, {'$set': {'cover_image_url': p_cover}})
                            inherited += 1
                    continue
                # libro raíz: generar
                cat = d.get('categoryLabel') or d.get('category')
                cov = generate_cover_image_bytes(cat, d.get('title'), d.get('subtitle') or d.get('summary'))
                if cov:
                    cname = f"cover_{str(d.get('_id'))}_{int(time.time())}.jpg"
                    cpath = os.path.join(app.config['COVERS_FOLDER'], cname)
                    with open(cpath, 'wb') as cf: cf.write(cov)
                    cover_url = f"/static/covers/{cname}"
                    libros_collection.update_one({'_id': d['_id']}, {'$set': {'cover_image_url': cover_url}})
                    created += 1
            except Exception as _e:
                print(f"⚠️  Backfill cover error para {d.get('_id')}: {_e}")
                continue
        return jsonify({'success': True, 'created': created, 'inherited': inherited})
    except Exception as e:
        print(f"❌ ERROR backfill covers: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/orphan-audios/<path:filename>', methods=['DELETE'])
def api_delete_orphan_audio(filename):
    """Elimina un archivo huérfano por nombre (sin consultar DB en cascada)."""
    try:
        safe_name = os.path.basename(filename)
        if not safe_name:
            return jsonify({'error': 'Nombre de archivo inválido'}), 400
        path = os.path.join(app.config['AUDIO_FOLDER'], safe_name)
        if not os.path.isfile(path):
            return jsonify({'error': 'Archivo no encontrado'}), 404
        os.remove(path)
        return jsonify({'success': True, 'deleted': safe_name})
    except Exception as e:
        print(f"❌ ERROR al eliminar huérfano {filename}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/tts-status')
def api_tts_status():
    """Devuelve el estado del motor TTS para diagnóstico rápido."""
    try:
        status = {
            'eleven_available': bool(ELEVEN_AVAILABLE),
            'eleven_api_key_present': bool(ELEVEN_API_KEY),
            'eleven_api_mode': ('legacy' if ELEVEN_USE_LEGACY else ('client' if ELEVEN_AVAILABLE else None)),
            'google_available': bool(GOOGLE_TTS_AVAILABLE),
            'tts_primary': (os.environ.get('TTS_PRIMARY') or 'elevenlabs').lower(),
            'last': LAST_TTS_STATUS,
        }
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/orphan-audios/<path:filename>/save', methods=['POST'])
def api_save_orphan_audio(filename):
    """Guarda un archivo de audio huérfano como libro mínimo en la DB.
    Acepta campos opcionales: title, subtitle, category, level.
    """
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        safe_name = os.path.basename(filename)
        if not safe_name:
            return jsonify({'error': 'Nombre de archivo inválido'}), 400
        path = os.path.join(app.config['AUDIO_FOLDER'], safe_name)
        if not os.path.isfile(path):
            return jsonify({'error': 'Archivo no encontrado'}), 404

        # Datos recibidos
        title = (request.form.get('title') or request.json.get('title') if request.is_json else request.form.get('title') or '').strip()
        subtitle = (request.form.get('subtitle') or (request.json.get('subtitle') if request.is_json else '')).strip() if (request.form.get('subtitle') or (request.is_json and request.json.get('subtitle'))) else ''
        category = (request.form.get('category') or (request.json.get('category') if request.is_json else '')).strip() if (request.form.get('category') or (request.is_json and request.json.get('category'))) else ''
        level = (request.form.get('level') or (request.json.get('level') if request.is_json else '')).strip() if (request.form.get('level') or (request.is_json and request.json.get('level'))) else ''

        # Defaults si faltan
        if not title:
            base = os.path.splitext(safe_name)[0]
            title = f"Audio importado — {base}"
        if not category:
            category = 'otros'
        if not level:
            level = 'medio'

        # Etiquetas
        category_labels = {
            'historia': 'Historia', 'cuentos': 'Cuentos', 'novelas': 'Novelas', 'aprendizaje': 'Aprendizaje',
            'biologia': 'Biología', 'ciencia': 'Ciencia', 'tecnologia': 'Tecnología', 'arte': 'Arte', 'noticias': 'Noticias',
            'otros': 'Otros'
        }
        level_labels = { 'facil': 'Fácil', 'medio': 'Medio', 'alta': 'Alta' }

        # Duración
        try:
            audio_mp3 = MP3(path)
            duration_seconds = int(audio_mp3.info.length)
        except Exception:
            duration_seconds = 0
        if duration_seconds > 0:
            if duration_seconds < 60:
                duration = f"{duration_seconds} seg"
            elif duration_seconds < 3600:
                minutes = duration_seconds // 60
                seconds = duration_seconds % 60
                duration = f"{minutes} min {seconds} seg" if seconds > 0 else f"{minutes} min"
            else:
                hours = duration_seconds // 3600
                minutes = (duration_seconds % 3600) // 60
                duration = f"{hours}h {minutes}min" if minutes > 0 else f"{hours}h"
        else:
            duration = "Duración no disponible"

        audio_url = f"/audio_files/{safe_name}"
        libro_data = {
            'title': title,
            'subtitle': subtitle,
            'category': category,
            'categoryLabel': category_labels.get(category, category.title() if isinstance(category, str) else str(category)),
            'level': level,
            'levelLabel': level_labels.get(level, level.title() if isinstance(level, str) else str(level)),
            'duration': duration,
            'duration_seconds': duration_seconds,
            'audio_filename': safe_name,
            'audio_url': audio_url,
            'text': '',
            'summary': None,
            'uploaded_by': session.get('usuario_id'),
            'uploaded_at': int(time.time()),
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        # Generar portada también para importación de huérfanos
        try:
            cov_bytes = generate_cover_image_bytes(
                category=libro_data.get('categoryLabel') or libro_data.get('category'),
                title=libro_data.get('title'),
                subtitle=libro_data.get('subtitle')
            )
            if cov_bytes:
                cname = f"cover_{int(time.time())}.jpg"
                cpath = os.path.join(app.config['COVERS_FOLDER'], cname)
                with open(cpath, 'wb') as cf:
                    cf.write(cov_bytes)
                libro_data['cover_image_url'] = f"/static/covers/{cname}"
        except Exception as _ce:
            print(f"⚠️  No se pudo generar portada para huérfano: {_ce}")

        result = libros_collection.insert_one(libro_data)
        return jsonify({'success': True, 'libro_id': str(result.inserted_id), 'audio_url': audio_url})
    except Exception as e:
        print(f"❌ ERROR al guardar huérfano {filename}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/summarize/<book_id>', methods=['POST'])
def api_summarize(book_id):
    """Genera y guarda un resumen IA para un libro existente (si tiene texto)."""
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = doc.get('text') or ''
        if not text.strip():
            return jsonify({'error': 'Este libro no tiene texto almacenado para resumir'}), 400
        summary = summarize_text(text)
        if not summary:
            return jsonify({'error': 'No se pudo generar resumen (falta clave o proveedor no disponible)'}), 500
        libros_collection.update_one({'_id': ObjectId(book_id)}, {'$set': {'summary': summary}})
        return jsonify({'success': True, 'summary': summary})
    except Exception as e:
        print(f"❌ ERROR resumen IA: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/libros/<book_id>', methods=['DELETE'])
def api_delete_book(book_id):
    """Elimina un libro por ID. Si es libro raíz, elimina también capítulos dependientes.
    Borra los archivos de audio asociados cuando existan.
    """
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        # Resolver documento por ObjectId o por _id string (soporta datos antiguos)
        oid = None
        try:
            oid = ObjectId(book_id)
        except Exception:
            oid = None
        query_main = {'$or': []}
        if oid is not None:
            query_main['$or'].append({'_id': oid})
        query_main['$or'].append({'_id': book_id})

        print(f"🗑️  DELETE solicitado para ID: {book_id}")
        doc = libros_collection.find_one(query_main)
        if not doc:
            # Fallback: escanear un subconjunto y comparar str(_id)
            try:
                cursor = libros_collection.find({}, {'_id': 1}).sort('uploaded_at', -1).limit(2000)
                for d in cursor:
                    try:
                        if str(d.get('_id')) == book_id:
                            doc = libros_collection.find_one({'_id': d.get('_id')})
                            break
                    except Exception:
                        continue
            except Exception as scan_err:
                print(f"⚠️  Error en fallback de escaneo: {scan_err}")
        if not doc:
            print("❌ Libro no encontrado para eliminar")
            return jsonify({'error': 'Libro no encontrado'}), 404

        deleted = 0
        audio_deleted = 0

        # Helper para borrar audio si existe
        def _delete_audio_file(audio_filename):
            nonlocal audio_deleted
            try:
                if audio_filename:
                    path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
                    if os.path.isfile(path):
                        os.remove(path)
                        audio_deleted += 1
            except Exception as _e:
                print(f"⚠️  No se pudo borrar audio {audio_filename}: {_e}")

        # Si es libro raíz, borrar capítulos primero (cascada)
        if not doc.get('is_chapter'):
            try:
                # Buscar hijos por parent_id como ObjectId o string
                child_or = []
                if oid is not None:
                    child_or.append({'parent_id': oid})
                child_or.append({'parent_id': book_id})
                children = list(libros_collection.find({'$or': child_or}))
                for ch in children:
                    _delete_audio_file(ch.get('audio_filename'))
                    libros_collection.delete_one({'_id': ch['_id']})
                    deleted += 1
            except Exception as ce:
                print(f"⚠️  Error al borrar capítulos en cascada: {ce}")

        # Borrar el documento principal
        _delete_audio_file(doc.get('audio_filename'))
        # Borrar principal por su _id exacto
        libros_collection.delete_one({'_id': doc['_id']})
        deleted += 1

        return jsonify({'success': True, 'deleted_docs': deleted, 'deleted_audio_files': audio_deleted})
    except Exception as e:
        print(f"❌ ERROR al eliminar libro: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze/<book_id>', methods=['POST'])
def api_analyze(book_id):
    """Analiza y guarda metadatos IA (topics, tone, complexity, warnings, faqs)."""
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = doc.get('text') or ''
        if not text.strip():
            return jsonify({'error': 'Este libro no tiene texto almacenado para analizar'}), 400
        analysis = analyze_content(text)
        if not analysis:
            return jsonify({'error': 'No se pudo analizar contenido (falta clave o proveedor no disponible)'}), 500
        libros_collection.update_one({'_id': ObjectId(book_id)}, {'$set': {'analysis': analysis}})
        return jsonify({'success': True, 'analysis': analysis})
    except Exception as e:
        print(f"❌ ERROR análisis IA: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/subtitles/<book_id>')
def api_subtitles(book_id):
    """Genera WebVTT básico a partir del texto del libro; opcional traducción con ?lang=xx o lang=auto."""
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        target = (request.args.get('lang') or 'auto').lower()
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Este libro no tiene texto almacenado para generar subtítulos'}), 400
        # detectar idioma si auto
        content = text
        if target and target != 'auto':
            src = detect_language(text) or 'und'
            if src != target:
                tr = translate_text(text, target)
                if tr:
                    content = tr
        # construir VTT
        import re
        words = content.replace('\n', ' ').split()
        wps = 2.5  # palabras por segundo aproximado
        # segmentar en bloques de ~12 palabras (≈ 4-5s)
        segments = []
        step = 12
        for i in range(0, len(words), step):
            seg_words = words[i:i+step]
            if not seg_words: break
            segments.append(' '.join(seg_words))
        def fmt_time(ms):
            h = ms//3600000; ms%=3600000
            m = ms//60000; ms%=60000
            s = ms//1000; cs = ms%1000
            return f"{h:02d}:{m:02d}:{s:02d}.{cs:03d}"
        cur_ms = 0
        vtt_lines = ["WEBVTT", ""]
        for idx, seg in enumerate(segments, start=1):
            dur_sec = max(2.0, min(7.0, len(seg.split())/wps))
            start = fmt_time(int(cur_ms))
            end = fmt_time(int(cur_ms + dur_sec*1000))
            vtt_lines.append(str(idx))
            vtt_lines.append(f"{start} --> {end}")
            vtt_lines.append(seg)
            vtt_lines.append("")
            cur_ms += int(dur_sec*1000)
        vtt_text = "\n".join(vtt_lines)
        from flask import Response
        return Response(vtt_text, mimetype='text/vtt')
    except Exception as e:
        print(f"❌ ERROR subtitles: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/quiz/<book_id>')
def api_quiz(book_id):
    """Genera preguntas/respuestas cortas sobre el libro."""
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Este libro no tiene texto almacenado para generar preguntas'}), 400
        quiz = generate_quiz(text, n=5) or []
        return jsonify({'quiz': quiz})
    except Exception as e:
        print(f"❌ ERROR quiz: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/notes/<book_id>')
def api_notes(book_id):
    """Genera notas/resumen en viñetas sobre el libro."""
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Este libro no tiene texto almacenado para generar notas'}), 400
        notes = generate_notes(text) or []
        return jsonify({'notes': notes})
    except Exception as e:
        print(f"❌ ERROR notes: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/accessibility/<book_id>')
def api_accessibility(book_id):
    """Analiza accesibilidad: complejidad, velocidad recomendada, pausas y resúmenes por secciones."""
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Este libro no tiene texto almacenado para analizar'}), 400
        acc = analyze_accessibility(text)
        if acc:
            libros_collection.update_one({'_id': ObjectId(book_id)}, {'$set': {'accessibility': acc}})
        return jsonify({'accessibility': acc or {}})
    except Exception as e:
        print(f"❌ ERROR accessibility: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/moderate/<book_id>')
def api_moderate(book_id):
    """Modera el texto del libro y guarda flags."""
    if libros_collection is None:
        return jsonify({'error': 'No hay conexión a la base de datos'}), 500
    try:
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        flags = moderate_text(text or '')
        libros_collection.update_one({'_id': ObjectId(book_id)}, {'$set': {'moderation': flags}})
        return jsonify({'moderation': flags})
    except Exception as e:
        print(f"❌ ERROR moderation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/playlists/smart')
def api_playlists_smart():
    """Crea una mezcla inteligente por mood. moods: relax, energy, focus, news, mix."""
    try:
        if libros_collection is None:
            return jsonify({'libros': []})
        mood = (request.args.get('mood') or 'mix').lower()
        size = int(request.args.get('size') or 10)
        all_docs = list(libros_collection.find({}).sort('uploaded_at', -1).limit(500))
        def pick(cats):
            return [d for d in all_docs if (d.get('category') or '').lower() in cats]
        if mood == 'relax': sel = pick(['novelas','cuentos','arte'])
        elif mood == 'energy': sel = pick(['tecnologia','ciencia','aprendizaje'])
        elif mood == 'focus': sel = pick(['ciencia','aprendizaje'])
        elif mood == 'news': sel = pick(['noticias']) or all_docs
        else:
            # mix: balance entre categorías más frecuentes
            from collections import Counter
            cnt = Counter((d.get('category') or '').lower() for d in all_docs)
            top = [k for k,_ in cnt.most_common(3)]
            sel = [d for d in all_docs if (d.get('category') or '').lower() in top]
        # asegurar variedad
        import random
        random.shuffle(sel)
        out = []
        seen = set()
        for d in sel:
            oid = str(d.get('_id'))
            if oid in seen: continue
            seen.add(oid)
            d['_id'] = oid
            out.append(d)
            if len(out) >= size: break
        return jsonify({'libros': out})
    except Exception as e:
        print(f"❌ ERROR playlists smart: {e}")
        return jsonify({'libros': []})


@app.route('/api/support', methods=['POST'])
def api_support():
    """Chat de soporte simple. Body JSON: { message: str }"""
    try:
        data = request.get_json(silent=True) or {}
        msg = (data.get('message') or '').strip()
        resp = support_answer(msg)
        return jsonify({'reply': resp or ''})
    except Exception as e:
        print(f"❌ ERROR support: {e}")
        return jsonify({'reply': 'Estoy teniendo problemas para responder ahora. Intenta de nuevo.'}), 200

@app.route('/api/assistant/chat', methods=['POST'])
def api_assistant_chat():
    """Asistente de voz/chat: interpreta comandos para reproducir por título o categoría.
    Body JSON: { message: str }
    Respuesta: { action: 'navigate'|'not_found'|'help'|'error', url?: str, speech?: str, error?: str }
    """
    try:
        if libros_collection is None:
            return jsonify({'action': 'error', 'error': 'DB no disponible'}), 503
        payload = request.get_json(silent=True) or {}
        msg = str(payload.get('message') or '').strip()
        if not msg:
            return jsonify({'action': 'error', 'error': 'Mensaje vacío'}), 400

        t = msg.lower()
        print(f"🗣️ assistant/chat msg='{msg}'")

        def root_filter():
            return {
                '$or': [
                    { 'is_chapter': { '$in': [False, 0, None, 'false', '0'] } },
                    { 'parent_id': { '$exists': False } },
                    { 'parent_id': '' }
                ]
            }

        def pick_known_category(text_lower: str):
            """Devuelve la mejor categoría conocida encontrada en el texto (singular/plural), o None."""
            try:
                recent = list(libros_collection.find({}, {'category': 1, 'categoryLabel': 1}).sort('uploaded_at', -1).limit(200))
                known = { (d.get('categoryLabel') or d.get('category') or '').strip().lower() for d in recent }
            except Exception:
                known = set()
            # generar variantes singular/plural simples
            variants = set()
            for k in known:
                if not k: continue
                variants.add(k)
                if k.endswith('s') and len(k) > 4:
                    variants.add(k[:-1])
                else:
                    variants.add(k + 's')
            # buscar por palabra completa
            best = None
            for c in sorted(variants, key=lambda s: -len(s)):
                if not c: continue
                if re.search(rf"\b{re.escape(c)}\b", text_lower):
                    best = c
                    break
            return best

        # 0) Genéricos: "reproduce un audio" | "reproduce un libro"
        if re.search(r"\breproduce(n|r)?\b.*\b(audio|libro|cap[íi]tulo)s?\b", t):
            # Tomar el más reciente libro raíz (no capítulo)
            doc = libros_collection.find_one(root_filter(), sort=[('uploaded_at', -1)])
            if not doc:
                # fallback: cualquiera con audio_url
                doc = libros_collection.find_one({ 'audio_url': { '$exists': True } }, sort=[('uploaded_at', -1)])
            if doc:
                url = f"/reproductor/{str(doc.get('_id'))}?autoplay=1"
                speech = f"Reproduciendo {doc.get('title') or 'el contenido'}."
                print(f"➡️ navigate to root recent id={doc.get('_id')} title={doc.get('title')}")
                return jsonify({'action': 'navigate', 'url': url, 'speech': speech})

        # 1) Categoría explícita ("categoría X" / "de la categoría X")
        cat = None
        mcat = re.search(r'categor[íi]a\s+(?:de\s+)?["“]?([^"”]+)["”]?', t)
        if mcat:
            cat = (mcat.group(1) or '').strip()
        else:
            # patrón "libro de X" o "audio de X"
            mde = re.search(r'(?:libro|audio)s?\s+de\s+([\wáéíóúñ]+)', t)
            if mde:
                cat = (mde.group(1) or '').strip()
            if not cat:
                # fallback: detectar categoría conocida en el texto (singular/plural)
                cat = pick_known_category(t)

        if cat:
            q_exact = {
                **root_filter(),
                '$or': [
                    { 'category': { '$regex': f'^{re.escape(cat)}$', '$options': 'i' } },
                    { 'categoryLabel': { '$regex': f'^{re.escape(cat)}$', '$options': 'i' } },
                ]
            }
            doc = libros_collection.find_one(q_exact, sort=[('uploaded_at', -1)])
            if not doc:
                q_partial = {
                    **root_filter(),
                    '$or': [
                        { 'category': { '$regex': cat, '$options': 'i' } },
                        { 'categoryLabel': { '$regex': cat, '$options': 'i' } },
                    ]
                }
                doc = libros_collection.find_one(q_partial, sort=[('uploaded_at', -1)])
            if doc:
                url = f"/reproductor/{str(doc.get('_id'))}?autoplay=1"
                speech = f"Reproduciendo {doc.get('title') or 'el libro'} de la categoría {doc.get('categoryLabel') or doc.get('category') or cat}."
                print(f"➡️ navigate by category '{cat}' id={doc.get('_id')} title={doc.get('title')}")
                return jsonify({'action': 'navigate', 'url': url, 'speech': speech})
            return jsonify({'action': 'not_found', 'speech': f"No encontré contenido en la categoría {cat}."}), 404

        # 2) Título entre comillas
        title = None
        mtitle = re.search(r'["“]([^"”]+)["”]', msg)
        if mtitle:
            title = (mtitle.group(1) or '').strip()
        else:
            # 3) Título después de un verbo: reproduce/pon/play/lee/escuchar/quiero escuchar
            mverb = re.search(r'(reproduce|pon|play|escuchar|quiero\s+escuchar|lee|leer)\s+(.+)', t)
            if mverb:
                title = (mverb.group(2) or '').strip()

        if title:
            q_exact = {
                '$or': [
                    { 'title': { '$regex': f'^{re.escape(title)}$', '$options': 'i' } },
                    { 'subtitle': { '$regex': f'^{re.escape(title)}$', '$options': 'i' } },
                ]
            }
            doc = libros_collection.find_one(q_exact, sort=[('uploaded_at', -1)])
            if not doc:
                q_partial = {
                    '$or': [
                        { 'title': { '$regex': title, '$options': 'i' } },
                        { 'subtitle': { '$regex': title, '$options': 'i' } },
                    ]
                }
                doc = libros_collection.find_one(q_partial, sort=[('uploaded_at', -1)])
            if doc:
                url = f"/reproductor/{str(doc.get('_id'))}?autoplay=1"
                speech = f"Reproduciendo {doc.get('title') or 'el contenido'}."
                print(f"➡️ navigate by title '{title}' id={doc.get('_id')} title={doc.get('title')}")
                return jsonify({'action': 'navigate', 'url': url, 'speech': speech})
            return jsonify({'action': 'not_found', 'speech': f"No encontré ‘{title}’ en tu biblioteca."}), 404

        # 4) Último intento: tratar todo el mensaje como categoría
        q_any = {
            '$or': [
                { 'category': { '$regex': t, '$options': 'i' } },
                { 'categoryLabel': { '$regex': t, '$options': 'i' } },
            ]
        }
        doc = libros_collection.find_one(q_any, sort=[('uploaded_at', -1)])
        if doc:
            url = f"/reproductor/{str(doc.get('_id'))}?autoplay=1"
            speech = f"Reproduciendo {doc.get('title') or 'el libro'} de {doc.get('categoryLabel') or doc.get('category')}."
            print(f"➡️ navigate by fallback-any id={doc.get('_id')} title={doc.get('title')}")
            return jsonify({'action': 'navigate', 'url': url, 'speech': speech})

        return jsonify({'action': 'help', 'speech': 'Puedo reproducir libros por título o por categoría. Por ejemplo: “reproduce "El Principito"” o “reproduce categoría ciencia”.'})
    except Exception as e:
        print(f"❌ ERROR assistant/chat: {e}")
        return jsonify({'action': 'error', 'error': 'Error interno'}), 500

# =====================
#  Accesibilidad: Braille (PDF)
# =====================

def _strip_accents(s: str) -> str:
    try:
        nfkd = unicodedata.normalize('NFD', s)
        return ''.join(c for c in nfkd if not unicodedata.combining(c))
    except Exception:
        return s

def _b_bits(*dots: int) -> int:
    v = 0
    for d in dots:
        if 1 <= d <= 8:
            v |= (1 << (d - 1))
    return v

_BRAILLE_ALPHA = {
    'a': _b_bits(1),
    'b': _b_bits(1,2),
    'c': _b_bits(1,4),
    'd': _b_bits(1,4,5),
    'e': _b_bits(1,5),
    'f': _b_bits(1,2,4),
    'g': _b_bits(1,2,4,5),
    'h': _b_bits(1,2,5),
    'i': _b_bits(2,4),
    'j': _b_bits(2,4,5),
    'k': _b_bits(1,3),
    'l': _b_bits(1,2,3),
    'm': _b_bits(1,3,4),
    'n': _b_bits(1,3,4,5),
    'o': _b_bits(1,3,5),
    'p': _b_bits(1,2,3,4),
    'q': _b_bits(1,2,3,4,5),
    'r': _b_bits(1,2,3,5),
    's': _b_bits(2,3,4),
    't': _b_bits(2,3,4,5),
    'u': _b_bits(1,3,6),
    'v': _b_bits(1,2,3,6),
    'w': _b_bits(2,4,5,6),
    'x': _b_bits(1,3,4,6),
    'y': _b_bits(1,3,4,5,6),
    'z': _b_bits(1,3,5,6),
}

_BRAILLE_PUNCT = {
    ',': _b_bits(2),
    ';': _b_bits(2,3),
    ':': _b_bits(2,5),
    '.': _b_bits(2,5,6),
    '!': _b_bits(2,3,5),
    '?': _b_bits(2,6),
    '-': _b_bits(3,6),
    '(': _b_bits(1,2,6),
    ')': _b_bits(3,4,5),
    '"': _b_bits(2,3,6),
    '\'': _b_bits(3),
}

_BRAILLE_NUMBER_SIGN = _b_bits(3,4,5,6)

def _char_to_braille_bits(ch: str, in_number: bool):
    """Convierte un char a uno o varios celdas en bits Braille (6 puntos).
    Retorna (lista_bits, nuevo_estado_in_number).
    - Dígitos: añade prefijo signo de número si no estamos ya en modo número.
    - Letras: mapeo básico a-z (sin contracciones). Ignora mayúsculas y acentos (se eliminan).
    - Puntuación y espacio: mapeo simple.
    """
    if ch.isdigit():
        num_map = {
            '1': _BRAILLE_ALPHA['a'], '2': _BRAILLE_ALPHA['b'], '3': _BRAILLE_ALPHA['c'], '4': _BRAILLE_ALPHA['d'], '5': _BRAILLE_ALPHA['e'],
            '6': _BRAILLE_ALPHA['f'], '7': _BRAILLE_ALPHA['g'], '8': _BRAILLE_ALPHA['h'], '9': _BRAILLE_ALPHA['i'], '0': _BRAILLE_ALPHA['j'],
        }
        bits = []
        if not in_number:
            bits.append(_BRAILLE_NUMBER_SIGN)
            in_number = True
        bits.append(num_map[ch])
        return bits, in_number
    else:
        if ch.isspace():
            return [0], False
        base = _strip_accents(ch.lower())
        if base and base[0] in _BRAILLE_ALPHA:
            return [_BRAILLE_ALPHA[base[0]]], False
        if ch in _BRAILLE_PUNCT:
            return [_BRAILLE_PUNCT[ch]], False
        return [0], False


def _generate_braille_pdf_response(text: str, title: str):
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    pw, ph = A4
    margin = 18 * mm
    dot_r = 0.7 * mm
    dot_dx = 2.5 * mm
    dot_dy = 2.5 * mm
    cell_w = 6.0 * mm
    cell_h = 10.0 * mm
    col_gap = 1.5 * mm
    row_gap = 2.0 * mm
    usable_w = pw - 2*margin
    usable_h = ph - 2*margin
    cols = max(1, int(usable_w // (cell_w + col_gap)))
    rows = max(1, int(usable_h // (cell_h + row_gap)))
    def draw_cell(col_idx: int, row_idx: int, bits: int):
        x0 = margin + col_idx * (cell_w + col_gap)
        y_top = ph - margin - row_idx * (cell_h + row_gap)
        positions = [ (0, 0), (0, -dot_dy), (0, -2*dot_dy), (dot_dx, 0), (dot_dx, -dot_dy), (dot_dx, -2*dot_dy) ]
        for i in range(6):
            if bits & (1 << i):
                dx, dy = positions[i]
                cx = x0 + dx + dot_r + 1.0
                cy = y_top + dy - dot_r - 1.0
                c.circle(cx, cy, dot_r, stroke=0, fill=1)
    try:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, ph - margin + 8, f"Braille: {title[:80]}")
    except Exception:
        pass
    col = 0
    row = 0
    in_number = False
    for ch in text:
        if ch == '\n':
            col = 0
            row += 1
            in_number = False
            if row >= rows:
                c.showPage()
                row = 0
            continue
        bits_list, in_number = _char_to_braille_bits(ch, in_number)
        for bits in bits_list:
            if col >= cols:
                col = 0
                row += 1
                in_number = False
            if row >= rows:
                c.showPage()
                row = 0
            draw_cell(col, row, bits)
            col += 1
    c.showPage()
    c.save()
    buf.seek(0)
    safe_name = re.sub(r"[^\w\- ]+", "", title).strip() or "contenido"
    filename = f"braille_{safe_name}.pdf"
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)

@app.route('/api/braille/pdf', methods=['POST'])
def api_braille_pdf():
    try:
        data = request.get_json(silent=True) or {}
        text = (data.get('text') or '').strip()
        title = (data.get('title') or 'contenido').strip()
        if not text:
            return jsonify({'error': 'Texto vacío'}), 400
        return _generate_braille_pdf_response(text, title)
    except Exception as e:
        print(f"❌ ERROR braille/pdf: {e}")
        return jsonify({'error': 'No se pudo generar el PDF Braille'}), 500

@app.route('/api/braille/pdf/book/<book_id>')
def api_braille_pdf_book(book_id):
    try:
        if libros_collection is None:
            return jsonify({'error': 'No hay conexión a la base de datos'}), 500
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Este libro no tiene texto almacenado'}), 400
        title = (doc.get('title') or 'contenido').strip()
        return _generate_braille_pdf_response(text, title)
    except Exception as e:
        print(f"❌ ERROR braille/pdf/book: {e}")
        return jsonify({'error': 'No se pudo generar el PDF Braille del libro'}), 500

# =====================
# Braille: BRF (ASCII 7-bit, 40x25)
# =====================

def _to_brf_ascii(text: str, cols: int = 40, lines_per_page: int = 25) -> str:
    """Convierte texto plano a un BRF ASCII 7-bit simple (grado 1 aproximado):
    - Letras: se emiten en minúsculas (a..z)
    - Números: prefijo '#' y mapeo 1..0 -> a..j, se mantiene modo número hasta separador
    - Espacio y saltos: se preservan
    - Puntuación ASCII básica: se deja pasar (.,;:!?-()"')
    - Ajuste de línea a 'cols' y salto de página cada 'lines_per_page' líneas con form feed (\f)
    Nota: Indicador de mayúsculas no incluido por defecto (se normaliza a minúsculas) para máxima compatibilidad.
    """
    digit_map = {'1':'a','2':'b','3':'c','4':'d','5':'e','6':'f','7':'g','8':'h','9':'i','0':'j'}
    allowed_punct = set(list(".,;:!?-()\"'"))
    out_lines = []
    cur_line = []
    col = 0
    line_count = 0
    in_number = False

    def emit_char(ch: str):
        nonlocal col, line_count, cur_line, out_lines
        cur_line.append(ch)
        col += 1
        if col >= cols:
            out_lines.append(''.join(cur_line))
            cur_line = []
            col = 0
            line_count += 1
            if line_count >= lines_per_page:
                out_lines.append('\f')
                line_count = 0

    for ch in text:
        if ch == '\n':
            out_lines.append(''.join(cur_line))
            cur_line = []
            col = 0
            line_count += 1
            if line_count >= lines_per_page:
                out_lines.append('\f')
                line_count = 0
            in_number = False
            continue
        if ch.isdigit():
            if not in_number:
                emit_char('#')
                in_number = True
            emit_char(digit_map[ch])
            continue
        # separadores salen del modo número
        if ch.isspace():
            emit_char(' ')
            in_number = False
            continue
        base = _strip_accents(ch)
        if base.isalpha():
            # Normalizar a minúscula por compatibilidad
            emit_char(base.lower())
            in_number = False
            continue
        if ch in allowed_punct:
            emit_char(ch)
            in_number = False
            continue
        # default
        emit_char(' ')
        in_number = False

    # flush última línea
    if cur_line:
        out_lines.append(''.join(cur_line))

    return '\n'.join(out_lines)

@app.route('/api/braille/brf', methods=['POST'])
def api_braille_brf():
    try:
        data = request.get_json(silent=True) or {}
        text = (data.get('text') or '').strip()
        title = (data.get('title') or 'contenido').strip()
        if not text:
            return jsonify({'error': 'Texto vacío'}), 400
        brf_text = _to_brf_ascii(text, cols=40, lines_per_page=25)
        buf = io.BytesIO(brf_text.encode('ascii', errors='ignore'))
        safe_name = re.sub(r"[^\w\- ]+", "", title).strip() or "contenido"
        filename = f"braille_{safe_name}.brf"
        return send_file(buf, mimetype='text/plain; charset=us-ascii', as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"❌ ERROR braille/brf: {e}")
        return jsonify({'error': 'No se pudo generar el BRF'}), 500

@app.route('/api/braille/brf/book/<book_id>')
def api_braille_brf_book(book_id):
    try:
        if libros_collection is None:
            return jsonify({'error': 'No hay conexión a la base de datos'}), 500
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Este libro no tiene texto almacenado'}), 400
        title = (doc.get('title') or 'contenido').strip()
        brf_text = _to_brf_ascii(text, cols=40, lines_per_page=25)
        buf = io.BytesIO(brf_text.encode('ascii', errors='ignore'))
        safe_name = re.sub(r"[^\w\- ]+", "", title).strip() or "contenido"
        filename = f"braille_{safe_name}.brf"
        return send_file(buf, mimetype='text/plain; charset=us-ascii', as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"❌ ERROR braille/brf/book: {e}")
        return jsonify({'error': 'No se pudo generar el BRF del libro'}), 500

# =====================
# Braille: STL (3D)
# =====================

def _generate_stl_for_text(text: str, max_cells: int = 1200) -> str:
    cell_w = 6.0; cell_h = 10.0; gap_x = 1.5; gap_y = 2.0
    dot_w = 1.8; dot_d = 1.8; dot_h = 1.5; base_h = 1.0
    margin_x = 5.0; margin_y = 5.0
    dot_dx = 2.5; dot_dy = 2.5
    positions = [(0.0,0.0),(0.0,-dot_dy),(0.0,-2*dot_dy),(dot_dx,0.0),(dot_dx,-dot_dy),(dot_dx,-2*dot_dy)]
    max_cols = 24
    col = 0; row = 0; used_cols = 0; used_rows = 1
    cells = []
    in_number = False; count_cells = 0
    for ch in text:
        if count_cells >= max_cells: break
        if ch == '\n':
            col = 0; row += 1; used_rows = max(used_rows, row+1); in_number = False; continue
        bits_list, in_number = _char_to_braille_bits(ch, in_number)
        for bits in bits_list:
            if count_cells >= max_cells: break
            if col >= max_cols:
                col = 0; row += 1; used_rows = max(used_rows, row+1); in_number = False
            cells.append((col,row,bits))
            used_cols = max(used_cols, col+1)
            col += 1; count_cells += 1
    panel_w = margin_x*2 + used_cols*(cell_w+gap_x) - (gap_x if used_cols>0 else 0)
    panel_h = margin_y*2 + used_rows*(cell_h+gap_y) - (gap_y if used_rows>0 else 0)
    facets = []
    def add_tri(n,v1,v2,v3): facets.append((n,v1,v2,v3))
    def add_box(x,y,z,w,d,h):
        x2=x+w; y2=y+d; z2=z+h
        add_tri((0,0,1),(x,y,z2),(x2,y,z2),(x2,y2,z2)); add_tri((0,0,1),(x,y,z2),(x2,y2,z2),(x,y2,z2))
        add_tri((0,0,-1),(x,y2,z),(x2,y2,z),(x2,y,z)); add_tri((0,0,-1),(x,y2,z),(x2,y,z),(x,y,z))
        add_tri((0,1,0),(x,y2,z),(x2,y2,z),(x2,y2,z2)); add_tri((0,1,0),(x,y2,z),(x2,y2,z2),(x,y2,z2))
        add_tri((0,-1,0),(x,y,z2),(x2,y,z2),(x2,y,z)); add_tri((0,-1,0),(x,y,z2),(x2,y,z),(x,y,z))
        add_tri((1,0,0),(x2,y,z),(x2,y2,z),(x2,y2,z2)); add_tri((1,0,0),(x2,y,z),(x2,y2,z2),(x2,y,z2))
        add_tri((-1,0,0),(x,y2,z2),(x,y2,z),(x,y,z)); add_tri((-1,0,0),(x,y2,z2),(x,y,z),(x,y,z2))
    add_box(0.0,0.0,0.0,panel_w,panel_h,base_h)
    for (c,r,bits) in cells:
        x0 = margin_x + c*(cell_w+gap_x)
        y_top = panel_h - margin_y - r*(cell_h+gap_y)
        for i in range(6):
            if bits & (1<<i):
                dx,dy = positions[i]
                cx = x0 + dx
                cy = y_top + dy - dot_d
                add_box(cx,cy,base_h,dot_w,dot_d,dot_h)
    lines=["solid braille"]
    for n,v1,v2,v3 in facets:
        lines.append(f"  facet normal {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v1[0]:.6f} {v1[1]:.6f} {v1[2]:.6f}")
        lines.append(f"      vertex {v2[0]:.6f} {v2[1]:.6f} {v2[2]:.6f}")
        lines.append(f"      vertex {v3[0]:.6f} {v3[1]:.6f} {v3[2]:.6f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid braille")
    return "\n".join(lines)

@app.route('/api/braille/stl', methods=['POST'])
def api_braille_stl():
    try:
        data = request.get_json(silent=True) or {}
        text = (data.get('text') or '').strip()
        title = (data.get('title') or 'contenido').strip()
        if not text:
            return jsonify({'error': 'Texto vacío'}), 400
        stl = _generate_stl_for_text(text)
        buf = io.BytesIO(stl.encode('utf-8'))
        safe_name = re.sub(r"[^\w\- ]+", "", title).strip() or "contenido"
        filename = f"braille_{safe_name}.stl"
        return send_file(buf, mimetype='model/stl', as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"❌ ERROR braille/stl: {e}")
        return jsonify({'error': 'No se pudo generar el STL'}), 500

@app.route('/api/braille/stl/book/<book_id>')
def api_braille_stl_book(book_id):
    try:
        if libros_collection is None:
            return jsonify({'error': 'No hay conexión a la base de datos'}), 500
        doc = libros_collection.find_one({'_id': ObjectId(book_id)})
        if not doc:
            return jsonify({'error': 'Libro no encontrado'}), 404
        text = (doc.get('text') or '').strip()
        if not text:
            return jsonify({'error': 'Este libro no tiene texto almacenado'}), 400
        title = (doc.get('title') or 'contenido').strip()
        stl = _generate_stl_for_text(text)
        buf = io.BytesIO(stl.encode('utf-8'))
        safe_name = re.sub(r"[^\w\- ]+", "", title).strip() or "contenido"
        filename = f"braille_{safe_name}.stl"
        return send_file(buf, mimetype='model/stl', as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"❌ ERROR braille/stl/book: {e}")
        return jsonify({'error': 'No se pudo generar el STL del libro'}), 500

if __name__ == '__main__':
    # En Windows puede aparecer OSError 10038 con el recargador automático del servidor de desarrollo.
    # Desactivamos el reloader para evitar el reinicio con "* Restarting with stat" que provoca el error.
    app.run(debug=True, use_reloader=False)
