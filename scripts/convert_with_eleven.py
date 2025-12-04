#!/usr/bin/env python3
"""
Script sencillo para convertir texto a MP3 usando la API HTTP de ElevenLabs.
Útil para pruebas locales cuando el servidor no tiene ELEVEN_API_KEY configurada.

Uso:
  python scripts/convert_with_eleven.py --api-key <KEY> --text "Hola mundo" --output audio_files/out.mp3
  python scripts/convert_with_eleven.py --api-key <KEY> --input-file sample.txt --voice rpqlUOplj0Q0PIilat8h

Este script envía la petición HTTP directamente a ElevenLabs y guarda el MP3 resultante.
"""
import argparse
import json
import os
import sys
import requests

DEFAULT_VOICE = 'Rachel'
DEFAULT_MODEL = 'eleven_multilingual_v2'

def eleven_http_tts(api_key: str, voice_id: str, text: str, model: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        'xi-api-key': api_key,
        'Accept': 'audio/mpeg',
        'Content-Type': 'application/json',
    }
    payload = {
        'text': text,
        'model_id': model,
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=120)
    if resp.status_code >= 400:
        raise Exception(f"HTTP {resp.status_code}: {resp.text}")
    if not resp.content:
        raise Exception("Respuesta vacía de ElevenLabs")
    return resp.content


def main():
    p = argparse.ArgumentParser(description="Convertir texto a MP3 usando ElevenLabs HTTP API")
    p.add_argument('--api-key', '-k', required=False, help='ElevenLabs API key. Si no está, se leerá de ELEVEN_API_KEY env var')
    p.add_argument('--voice', '-v', default=os.environ.get('ELEVEN_VOICE_ID') or DEFAULT_VOICE, help='Voice id o nombre (según tu cuenta)')
    p.add_argument('--model', '-m', default=os.environ.get('ELEVEN_MODEL') or DEFAULT_MODEL, help='Model id a usar')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--text', '-t', help='Texto a convertir (entre comillas)')
    group.add_argument('--input-file', '-i', help='Ruta a archivo de texto (.txt) a convertir')
    p.add_argument('--output', '-o', default=None, help='Ruta de salida (por defecto audio_files/audio_<timestamp>.mp3)')

    args = p.parse_args()
    api_key = args.api_key or os.environ.get('ELEVEN_API_KEY')
    if not api_key:
        print('ERROR: debes proveer --api-key o definir ELEVEN_API_KEY en el entorno', file=sys.stderr)
        sys.exit(2)

    voice = args.voice
    model = args.model

    if args.input_file:
        if not os.path.isfile(args.input_file):
            print(f"ERROR: archivo no encontrado: {args.input_file}", file=sys.stderr)
            sys.exit(2)
        with open(args.input_file, 'r', encoding='utf-8') as f:
            text = f.read()
    else:
        text = args.text or ''

    if not text.strip():
        print('ERROR: texto vacío', file=sys.stderr)
        sys.exit(2)

    try:
        print(f"➡️  Solicitud a ElevenLabs con voice={voice}, model={model} (texto {len(text)} chars)")
        audio_bytes = eleven_http_tts(api_key=api_key, voice_id=voice, text=text, model=model)
        # Asegurar carpeta audio_files
        audio_dir = os.path.join(os.getcwd(), 'audio_files')
        if not os.path.exists(audio_dir):
            os.makedirs(audio_dir, exist_ok=True)
        if args.output:
            out_path = args.output
        else:
            out_path = os.path.join(audio_dir, f"audio_{int(__import__('time').time())}.mp3")
        # Si el usuario pasó un nombre simple, colocarlo dentro de audio_files
        if not os.path.isabs(out_path) and not out_path.startswith('audio_files'):
            out_path = os.path.join(audio_dir, out_path)
        with open(out_path, 'wb') as wf:
            wf.write(audio_bytes)
        print(f"✅ Audio guardado en: {out_path} ({len(audio_bytes)} bytes)")
    except Exception as e:
        print(f"❌ Error generando audio: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
