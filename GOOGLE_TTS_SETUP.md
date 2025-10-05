# Configuración de Google Cloud Text-to-Speech (Respaldo TTS)

## ¿Por qué usar Google Cloud TTS?

Google Cloud TTS actúa como **respaldo automático** cuando ElevenLabs:
- 🚫 Alcanza el límite de cuota mensual
- ⚠️ La API key expira o es inválida
- 🔌 El servicio no está disponible
- ❌ Cualquier otro error ocurre

## Instalación Rápida

### 1. Instalar las librerías necesarias

```bash
pip install google-cloud-texttospeech google-api-core google-auth
```

### 2. API Key ya configurada

✅ **La API key ya está configurada en el código:**
- API Key: `AIzaSyBe1bC2-gepvvQdGza9i7O-X6WwEIYNfmo`
- Configurada en: `app.py` línea ~52

**No necesitas hacer nada más**, el sistema funcionará automáticamente.

## Verificar que funciona

1. Instala las librerías (paso 1 arriba)
2. Reinicia la aplicación: `python app.py`
3. Verás este mensaje:
   ```
   ✅ Google Cloud TTS disponible como respaldo
   ```

## Cómo funciona el sistema de fallback

```python
1. 🎯 Intenta con ElevenLabs (motor principal)
   ↓
2. ❌ Si ElevenLabs falla
   ↓
3. 🔄 Cambia automáticamente a Google Cloud TTS
   ↓
4. ✅ Retorna el audio generado con el motor que funcionó
```

## Voces disponibles en Google Cloud TTS

El sistema usa por defecto:
- **Idioma**: Español (España) - `es-ES`
- **Voz**: `es-ES-Neural2-A` (Voz femenina neuronal)
- **Calidad**: Neural (mejor calidad)

Puedes modificar las voces en `app.py` en la función `generate_audio_with_google_tts()`.

### Otras voces disponibles:

**Español (España):**
- `es-ES-Neural2-A` - Mujer
- `es-ES-Neural2-B` - Hombre
- `es-ES-Neural2-C` - Mujer
- `es-ES-Neural2-D` - Mujer
- `es-ES-Neural2-E` - Mujer
- `es-ES-Neural2-F` - Hombre

**Español (Latinoamérica):**
- `es-US-Neural2-A` - Mujer
- `es-US-Neural2-B` - Hombre
- `es-US-Neural2-C` - Hombre

## Verificar instalación

Ejecuta la aplicación y verás uno de estos mensajes:

✅ **Google Cloud TTS disponible:**
```
✅ Google Cloud TTS disponible como respaldo
```

⚠️ **Google Cloud TTS no instalado:**
```
⚠️  Google Cloud TTS no disponible (ejecuta: pip install google-cloud-texttospeech)
```

## Logs de funcionamiento

Cuando uses el sistema de conversión, verás en consola:

### Si ElevenLabs funciona:
```
🎙️  Intentando generar audio con ElevenLabs...
✅ Audio generado exitosamente con ElevenLabs
🎙️  Motor TTS utilizado: ElevenLabs
```

### Si ElevenLabs falla y usa Google:
```
🎙️  Intentando generar audio con ElevenLabs...
⚠️  ElevenLabs falló: [error]
🔄 Cambiando a Google Cloud TTS...
✅ Audio generado exitosamente con Google Cloud TTS
🎙️  Motor TTS utilizado: Google Cloud TTS
```

## Solución de problemas

### Error: "Could not load the default credentials"

**Solución:** Configura la variable de entorno `GOOGLE_APPLICATION_CREDENTIALS` con la ruta a tu archivo JSON de credenciales.

### Error: "API Text-to-Speech is not enabled"

**Solución:** Habilita la API en Google Cloud Console.

### Error: "Quota exceeded"

**Solución:** Has alcanzado el límite mensual gratuito. Espera al siguiente mes o configura facturación en Google Cloud.

## Comparación ElevenLabs vs Google Cloud TTS

| Característica | ElevenLabs | Google Cloud TTS |
|----------------|------------|------------------|
| Calidad de voz | ⭐⭐⭐⭐⭐ Excelente | ⭐⭐⭐⭐ Muy buena |
| Naturalidad | ⭐⭐⭐⭐⭐ Muy natural | ⭐⭐⭐⭐ Natural |
| Idiomas | 29+ idiomas | 40+ idiomas |
| Cuota gratis/mes | 10,000 caracteres | 1-4 millones de caracteres |
| Velocidad | Rápido | Muy rápido |
| Costo post-cuota | Variable | $4-16/millón chars |

## Recomendaciones

1. ✅ **Usa ElevenLabs como motor principal** (mejor calidad)
2. ✅ **Configura Google Cloud TTS como respaldo** (mayor disponibilidad)
3. ✅ **Monitorea los logs** para ver qué motor se está usando
4. ✅ **Configura alertas** si Google TTS se usa frecuentemente (indica problemas con ElevenLabs)

---

**¿Necesitas ayuda?** Revisa los logs de la aplicación para diagnosticar problemas.
