# Configuración del Grupo para Subida Automática

## Configuración de ID para Subida Automática
- **ID Configurado**: `-1002688892136`
- **Tipo**: Canal/Grupo para contenido multimedia automático
- **Función**: El bot procesará automáticamente el contenido multimedia enviado a este chat

⚠️ **IMPORTANTE**: Si este ID corresponde a un canal en lugar de un grupo, el bot funcionará igual. La automatización funciona tanto en grupos como en canales.

## Cómo Funciona la Subida Automática

### 1. Configuración Inicial
El bot está configurado para procesar automáticamente contenido multimedia (películas y series) cuando:
- El contenido se envía al chat con ID `-1002688892136`
- La automatización IA está activada
- El bot tiene permisos de administrador en el chat

### 2. Activar la Automatización
Para que el bot procese automáticamente el contenido, un administrador debe activar la automatización IA:

```
/ai_auto on
```

Para verificar el estado:
```
/ai_status
```

### 3. Configurar el Auto Uploader
El sistema de subida automática también debe estar activado:

```
/ai_uploader on
```

Para ver la configuración actual:
```
/ai_uploader
```

### 4. Proceso Automático
Cuando se envía contenido multimedia al chat configurado:

1. **Detección**: El bot detecta automáticamente si el archivo es una película o serie
2. **Análisis**: Utiliza IA para analizar el contenido y extraer información
3. **Búsqueda**: Busca automáticamente información en IMDb si está habilitado
4. **Generación**: Crea una descripción automática con la información encontrada
5. **Subida**: Sube el contenido a los canales correspondientes:
   - Canal principal (`CHANNEL_ID`): Para la portada y descripción
   - Canal de búsqueda (`SEARCH_CHANNEL_ID`): Para el archivo multimedia

### 5. Comandos de Administración

#### Automatización IA
- `/ai_auto on/off` - Activar/desactivar automatización IA
- `/ai_status` - Ver estado de la automatización
- `/ai_config` - Configurar parámetros de IA

#### Auto Uploader
- `/ai_uploader on/off` - Activar/desactivar auto uploader
- `/ai_uploader confidence 0.8` - Establecer confianza mínima (0.1-1.0)
- `/ai_uploader imdb on/off` - Activar/desactivar búsqueda automática IMDb
- `/ai_uploader poster on/off` - Activar/desactivar descarga automática de posters

#### Comando Manual /load
Los administradores también pueden usar el comando `/load` para subida manual:
1. Enviar `/load` para iniciar el proceso
2. Enviar el nombre del contenido
3. Enviar los archivos multimedia
4. Enviar `/load` nuevamente para finalizar

#### Comando /group_load (NUEVO)
**Comando especial para activar procesamiento automático en grupo:**
- `/group_load` - Activar/desactivar modo de procesamiento automático en grupo
- **Función**: Permite que los administradores señalen cuando van a enviar contenido al grupo para procesamiento automático
- **Ventajas**:
  - Control explícito sobre cuándo procesar contenido del grupo
  - Evita procesamiento accidental de contenido no deseado
  - Seguimiento de sesiones de carga con duración y administrador responsable
  - Notificaciones automáticas al grupo sobre el estado del modo

**Uso del comando:**
1. **Activar**: `/group_load` - Activa el modo y notifica al grupo
2. **Enviar contenido**: Envía archivos multimedia al grupo configurado
3. **Procesamiento automático**: El bot procesa cada archivo automáticamente
4. **Desactivar**: `/group_load` nuevamente - Desactiva el modo y muestra estadísticas

### 6. Configuración Actual del Bot

```python
# IDs de configuración
TOKEN = "7636379442:AAF1-xO0HCBpRhdaCYM3iRbXHzwnOn59O08"
ADMIN_IDS = [1742433244, 7588449861, 6866175814]
CHANNEL_ID = -1002584219284          # Canal principal
GROUP_ID = -1002688892136            # Chat para contenido automático
SEARCH_CHANNEL_ID = -1002302159104   # Canal de búsqueda
```

### 7. Formato Correcto del Comando /pedido

**FORMATO ACTUALIZADO**: `/pedido tipo año nombre_del_contenido`

**Ejemplos correctos**:
- `/pedido serie 2006 la que se avecina`
- `/pedido pelicula 2024 Avatar 3`
- `/pedido serie 2023 The Last of Us`

**Análisis IA Mejorado**:
- ✅ Detecta correctamente el tipo de contenido (serie/película)
- ✅ Valida el año (1900-2030)
- ✅ Analiza la calidad del nombre del contenido
- ✅ Proporciona recomendaciones específicas
- ✅ Mayor precisión en la confianza del análisis

### 8. Requisitos
- El bot debe ser administrador en el chat `-1002688892136`
- La automatización IA debe estar activada (`/ai_auto on`)
- El auto uploader debe estar activado (`/ai_uploader on`)
- Los archivos deben ser videos o documentos con nombres descriptivos

### 9. Solución de Problemas

#### Si el bot no responde al contenido multimedia:
1. Verificar que el bot es administrador del chat
2. Confirmar que `/ai_auto on` está activado
3. Confirmar que `/ai_uploader on` está activado
4. Verificar que el contenido es multimedia (video/documento/foto)

#### Si el análisis IA del /pedido falla:
1. Usar el formato correcto: `/pedido tipo año nombre`
2. Verificar que el año es numérico (1900-2030)
3. Usar nombres descriptivos sin caracteres especiales
4. Ejemplos válidos: `serie`, `pelicula`, `película`, `movie`

### 10. Notas Importantes
- Solo los administradores pueden activar/desactivar la automatización
- El bot procesará automáticamente contenido de cualquier usuario en el chat configurado
- La calidad del procesamiento automático depende de la claridad del nombre del archivo
- Se recomienda usar nombres descriptivos como "Película Nombre 2024" o "Serie Nombre S01E01"
- El formato del comando `/pedido` ha sido actualizado para mayor precisión del análisis IA
