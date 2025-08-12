from flask import Flask, render_template, request, send_from_directory, jsonify, url_for
import os
from werkzeug.utils import secure_filename
import time # Para nombres de archivo únicos

# Importaciones para extracción de texto
from docx import Document as DocxDocument
import PyPDF2

# Importación para TTS
from gtts import gTTS

# Importación para Braille
import louis

app = Flask(__name__)

# Configuraciones
UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'audio_files'
ALLOWED_EXTENSIONS = {'txt', 'docx', 'pdf', 'brf', 'bra', 'brl'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER

# Crear directorios si no existen
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_braille(filepath):
    """Extrae texto de un archivo Braille (.brf, .bra, .brl)."""
    try:
        with open(filepath, 'rb') as f:
            braille_content = f.read()

        # Traducir de Braille a texto Unicode
        # Se asume una tabla de español, grado 1. Esto podría necesitar ser configurable.
        text = louis.translateString(['es-g1.ctb'], braille_content)
        return text
    except Exception as e:
        print(f"Error extrayendo texto de archivo Braille {filepath}: {e}")
        raise ValueError("No se pudo procesar el archivo Braille.")

def extract_text_from_file(filepath):
    text = ""
    extension = filepath.rsplit('.', 1)[1].lower()
    try:
        if extension in ['brf', 'bra', 'brl']:
            text = extract_text_from_braille(filepath)
        elif extension == 'txt':
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
        elif extension == 'docx':
            doc = DocxDocument(filepath)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif extension == 'pdf':
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                has_text = False
                for page_num in range(len(reader.pages)):
                    page = reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                        has_text = True
                if not has_text and len(reader.pages) > 0:
                    raise ValueError("El archivo PDF no contiene texto extraíble. Puede ser un documento escaneado o basado en imágenes.")
                elif not text and len(reader.pages) == 0:
                    raise ValueError("El archivo PDF está vacío o corrupto.")
    except ValueError: # Re-raise ValueErrors para que sean manejados específicamente
        raise
    except Exception as e:
        print(f"Error extrayendo texto de {filepath}: {e}")
        raise ValueError(f"No se pudo extraer texto del archivo {extension.upper()}. El archivo podría estar corrupto o en un formato inesperado.")
    return text

def text_to_speech_gtts(text, lang='es'):
    if not text.strip():
        raise ValueError("El texto para convertir a audio está vacío.")
    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        # Generar un nombre de archivo único para el audio
        timestamp = str(int(time.time()))
        filename = f"audio_{timestamp}.mp3"
        filepath = os.path.join(app.config['AUDIO_FOLDER'], filename)
        tts.save(filepath)
        return filename
    except Exception as e:
        print(f"Error con gTTS: {e}")
        raise ValueError("Error al generar el audio con gTTS. Verifica tu conexión a internet o el texto proporcionado.")


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file_route():
    if 'file' not in request.files:
        return jsonify({'error': 'No se encontró el archivo en la solicitud.'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo.'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        try:
            file.save(filepath)

            # Extraer texto
            extracted_text = extract_text_from_file(filepath)
            if not extracted_text.strip():
                # Limpiar archivo subido si no se pudo extraer texto útil
                os.remove(filepath)
                return jsonify({'error': 'No se pudo extraer contenido del archivo o está vacío.'}), 400

            # Convertir a audio
            audio_filename = text_to_speech_gtts(extracted_text)

            # Limpiar archivo subido original después de procesarlo
            os.remove(filepath)

            audio_url = url_for('serve_audio', filename=audio_filename, _external=True)
            return jsonify({'audio_url': audio_url, 'message': 'Archivo procesado correctamente.'})

        except ValueError as ve: # Errores de extracción o TTS
            # Si el archivo se guardó y hubo un error después, limpiarlo
            if os.path.exists(filepath):
                os.remove(filepath)
            return jsonify({'error': str(ve)}), 400
        except Exception as e:
            # Si el archivo se guardó y hubo un error después, limpiarlo
            if os.path.exists(filepath):
                os.remove(filepath)
            print(f"Error en /upload: {e}")
            return jsonify({'error': 'Ocurrió un error interno al procesar el archivo.'}), 500
    else:
        return jsonify({'error': 'Tipo de archivo no permitido.'}), 400

@app.route('/audio/<filename>')
def serve_audio(filename):
    return send_from_directory(app.config['AUDIO_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
