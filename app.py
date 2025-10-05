from flask import Flask, render_template, request, redirect, session, url_for, jsonify, send_from_directory
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from werkzeug.utils import secure_filename
import os
import time
from elevenlabs import generate, set_api_key
import docx
import PyPDF2

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
    print(f"📊 Base de datos: {db.name}")
    print(f"📁 Colección: usuarios_collection")
except Exception as e:
    print(f"❌ ERROR: No se pudo conectar a MongoDB: {e}")
    print("⚠️  Asegúrate de que MongoDB esté corriendo en localhost:27017")
    client = None
    db = None
    usuarios_collection = None

# ElevenLabs API
set_api_key("fd022cc95a0a8992c0a483aae4e1b62b6312666ea31db3d4afed617f43d8e034")

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
def index():
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
    session.clear()
    return redirect(url_for('login'))

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
        
        # Limitar texto si es muy largo (ElevenLabs tiene límites)
        MAX_CHARS = 5000
        if len(text) > MAX_CHARS:
            print(f"⚠️  Texto muy largo ({len(text)} chars), limitando a {MAX_CHARS}")
            text = text[:MAX_CHARS] + "..."
        
        # Generar audio con ElevenLabs
        print("🎙️  Generando audio con ElevenLabs...")
        print(f"🔑 API Key configurada: {'Sí' if 'ELEVEN_API_KEY' in os.environ or True else 'No'}")
        
        try:
            audio = generate(
                text=text,
                voice=voice_id,
                model="eleven_multilingual_v2"
            )
            print("✅ Audio generado exitosamente")
        except Exception as eleven_error:
            print(f"❌ Error de ElevenLabs: {eleven_error}")
            os.remove(filepath)
            return jsonify({'error': f'Error al generar audio: {str(eleven_error)}'}), 500
        
        # Guardar audio
        audio_filename = f"audio_{int(time.time())}.mp3"
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        print(f"💾 Guardando audio en: {audio_path}")
        
        with open(audio_path, 'wb') as f:
            f.write(audio)
        
        file_size = os.path.getsize(audio_path)
        print(f"✅ Audio guardado: {audio_filename} ({file_size} bytes)")
        
        # Limpiar archivo subido
        os.remove(filepath)
        print("🗑️  Archivo temporal eliminado")
        
        audio_url = f'/audio_files/{audio_filename}'
        print(f"✅ Conversión completada. URL: {audio_url}")
        
        return jsonify({
            'success': True,
            'audio_url': audio_url,
            'message': 'Conversión exitosa',
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
