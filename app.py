from flask import Flask, render_template, request, redirect, session, url_for, jsonify, send_from_directory
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from werkzeug.utils import secure_filename
import os
import time
from elevenlabs import generate, set_api_key
import docx
import PyPDF2
from mutagen.mp3 import MP3  # Para obtener duración de archivos MP3

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

app = Flask(__name__)
app.secret_key = "sinsay_secret_key"
bcrypt = Bcrypt(app)

# Configuración de archivos
UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'audio_files'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'brf'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(AUDIO_FOLDER):
    os.makedirs(AUDIO_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER

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

# ElevenLabs API
set_api_key("fd022cc95a0a8992c0a483aae4e1b62b6312666ea31db3d4afed617f43d8e034")

# Google Cloud API Key (para Text-to-Speech)
os.environ['GOOGLE_API_KEY'] = "AIzaSyBe1bC2-gepvvQdGza9i7O-X6WwEIYNfmo"

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
                    return redirect(url_for('index'))
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
        
        return redirect(url_for('index'))
        
    except Exception as e:
        print(f"❌ ERROR en register: {e}")
        import traceback
        traceback.print_exc()
        return render_template('login.html', error=f"Error al registrar: {str(e)}", instituciones=instituciones)

@app.route('/')
def bienvenida():
    """Página de bienvenida - accesible sin login"""
    return render_template('Bienvenida.html')

@app.route('/index')
def index():
    """Página principal del convertidor TTS - requiere login"""
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

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
        
        libros = list(libros_collection.find({}, {'_id': 0}))
        
        # Agregar ID numérico para cada libro
        for idx, libro in enumerate(libros, start=1):
            libro['id'] = idx
        
        return jsonify({'libros': libros}), 200
    except Exception as e:
        print(f"❌ ERROR al obtener libros: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
        
        # Obtener la voz seleccionada
        voice_id = request.form.get('voice', 'rpqlUOplj0Q0PIilat8h')
        print(f"🎤 Voz seleccionada: {voice_id}")
        
        # Limitar texto si es muy largo
        MAX_CHARS = 5000
        if len(text) > MAX_CHARS:
            print(f"⚠️  Texto muy largo ({len(text)} chars), limitando a {MAX_CHARS}")
            text = text[:MAX_CHARS] + "..."
        
        # Intentar generar audio con ElevenLabs primero
        audio = None
        tts_engine_used = None
        
        print("🎙️  Intentando generar audio con ElevenLabs...")
        try:
            audio = generate(
                text=text,
                voice=voice_id,
                model="eleven_multilingual_v2"
            )
            tts_engine_used = "ElevenLabs"
            print("✅ Audio generado exitosamente con ElevenLabs")
            
        except Exception as eleven_error:
            print(f"⚠️  ElevenLabs falló: {eleven_error}")
            print(f"⚠️  Tipo de error: {type(eleven_error).__name__}")
            print(f"🔍 Verificando disponibilidad de Google TTS: GOOGLE_TTS_AVAILABLE = {GOOGLE_TTS_AVAILABLE}")
            
            # Intentar con Google Cloud TTS como respaldo
            if GOOGLE_TTS_AVAILABLE:
                print("🔄 Cambiando a Google Cloud TTS...")
                try:
                    audio = generate_audio_with_google_tts(text, language_code='es-ES')
                    tts_engine_used = "Google Cloud TTS"
                    print("✅ Audio generado exitosamente con Google Cloud TTS")
                except Exception as google_error:
                    print(f"❌ Google Cloud TTS también falló: {google_error}")
                    import traceback
                    traceback.print_exc()
                    os.remove(filepath)
                    return jsonify({
                        'error': f'Todos los motores TTS fallaron. ElevenLabs: {str(eleven_error)}, Google: {str(google_error)}'
                    }), 500
            else:
                # No hay respaldo disponible
                print("❌ No hay motor TTS de respaldo disponible")
                print("⚠️  Asegúrate de que google-cloud-texttospeech esté instalado")
                os.remove(filepath)
                return jsonify({
                    'error': f'Error al generar audio con ElevenLabs: {str(eleven_error)}. Instala Google Cloud TTS como respaldo: pip install google-cloud-texttospeech'
                }), 500
        
        # Verificar que se generó audio
        if audio is None:
            print("❌ No se pudo generar audio")
            os.remove(filepath)
            return jsonify({'error': 'No se pudo generar audio con ningún motor TTS'}), 500
        
        # Guardar audio
        audio_filename = f"audio_{int(time.time())}.mp3"
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        print(f"💾 Guardando audio en: {audio_path}")
        
        with open(audio_path, 'wb') as f:
            f.write(audio)
        
        file_size = os.path.getsize(audio_path)
        print(f"✅ Audio guardado: {audio_filename} ({file_size} bytes)")
        print(f"🎙️  Motor TTS utilizado: {tts_engine_used}")
        
        # Limpiar archivo subido
        os.remove(filepath)
        print("🗑️  Archivo temporal eliminado")
        
        audio_url = f'/audio_files/{audio_filename}'
        print(f"✅ Conversión completada. URL: {audio_url}")
        
        return jsonify({
            'success': True,
            'audio_url': audio_url,
            'message': f'Conversión exitosa con {tts_engine_used}',
            'tts_engine': tts_engine_used,
            'audio_size': file_size,
            'text_length': len(text)
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

# ...el resto de tu código para la conversión y reproducción de audio...

if __name__ == '__main__':
    app.run(debug=True)
