import logging
import asyncio
import re
import aiohttp
import time
import requests
from datetime import datetime, timedelta
# Telegram imports
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    CallbackQuery
)
from telegram.constants import (
    ParseMode,
    ChatAction
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    PicklePersistence
)
from telegram.error import TelegramError
# Other imports remain the same
from database import Database
from plans import PLANS
from auto_uploader import AutoUploader
from ai_processor import AIProcessor
from content_detector import ContentDetector
from flask import Flask
from threading import Thread
from functools import wraps
from bs4 import BeautifulSoup
from io import BytesIO
from imdb import IMDb
import os
import tempfile
import traceback
import yt_dlp
from pathlib import Path
from urllib.parse import urlparse
import signal
import sys
from deep_translator import GoogleTranslator


def handle_exit(signum, frame):
    """Maneja señales de terminación"""
    print(f"Recibida señal de terminación {signum}. Saliendo...")
    sys.exit(0)

# Registrar manejadores de señales
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Mantener el bot activo en Render
app = Flask('')

@app.route('/')
def home():
    return "¡El bot está activo!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Constantes del bot
TOKEN = "7636379442:AAF1-xO0HCBpRhdaCYM3iRbXHzwnOn59O08"
ADMIN_IDS = [1742433244, 7588449861, 6866175814]  # Lista de IDS de administradores
CHANNEL_ID = -1002584219284
GROUP_ID = -1002585538833
SEARCH_CHANNEL_ID = -1002302159104

def is_admin(user_id: int) -> bool:
    """Verificar si un usuario es administrador"""
    return user_id in ADMIN_IDS
    
def clear_old_cache(self):
    """Limpiar caché antiguo (más de 30 días)"""
    try:
        expiry_time = datetime.now() - timedelta(days=30)
        self.search_cache.delete_many({"timestamp": {"$lt": expiry_time}})
        logger.info("Limpieza de caché antiguo (>30 días) completada")
    except Exception as e:
        logger.error(f"Error limpiando caché antiguo: {e}")    

# Add this at the top with other constants
PLANS_INFO = PLANS

# Constantes para el estado de /add
ADD_STATE_IDLE = 0        # No hay proceso activo
ADD_STATE_NAME = 1        # Esperando nombre después de /add
ADD_STATE_RECEIVING = 2   # Recibiendo capítulos
ADD_STATE_COVER = 3       # Esperando la portada

# Constantes para el sistema de series
UPSER_STATE_IDLE = 0        # No hay carga de serie en proceso
UPSER_STATE_RECEIVING = 1   # Recibiendo capítulos
UPSER_STATE_COVER = 2       # Esperando la portada con descripción

# Constantes para el sistema de carga masiva
LOAD_STATE_INACTIVE = 0     # No hay carga masiva en proceso
LOAD_STATE_WAITING_NAME = 1 # Esperando nombre del contenido
LOAD_STATE_WAITING_FILES = 2 # Esperando archivos después de recibir nombre

# Constantes para el sistema de carga de series con múltiples temporadas
MULTI_SEASONS_STATE_IDLE = 0        # No hay carga de temporadas en proceso
MULTI_SEASONS_STATE_RECEIVING = 1   # Recibiendo capítulos de temporada actual
MULTI_SEASONS_STATE_COVER = 2       # Esperando portada con descripción
MULTI_SEASONS_STATE_NEW_SEASON = 3  # Esperando nombre de nueva temporada

# Constantes para el comando ser
SER_STATE_IDLE = 'IDLE'
SER_STATE_WAITING_NAME = 'WAITING_NAME'
SER_STATE_RECEIVING = 'RECEIVING'
SER_STATE_COVER = 'COVER'

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Crear una instancia de IMDb
ia = IMDb()

# Initialize database
db = Database()

# Initialize AI Auto Uploader
auto_uploader = AutoUploader(CHANNEL_ID, SEARCH_CHANNEL_ID, db)

# Store the latest message ID
last_message_id = 0

# Cache for message content to avoid repeated requests
message_cache = {}

# Cache for search results to speed up repeated searches
search_cache = {}

# Cache expiration time (in seconds)
CACHE_EXPIRATION = 3600  # 1 hour

# Maximum number of messages to search
MAX_SEARCH_MESSAGES = 1000

# Maximum number of results to show
MAX_RESULTS = 10

# User preferences (store user settings)
user_preferences = {}

def truncate_description(description: str, max_length: int = 1000) -> str:
    """Trunca la descripción preservando las etiquetas HTML y estructura"""
    # Si el texto es más corto que el límite, agregar marca de agua si falta
    if len(description) <= max_length:
        if "Multimedia-TV 📺" not in description:
            description += f"\n\n🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
        return description
        
    # Asegurarse de preservar la marca de agua
    watermark = "🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
    
    # Remover la marca de agua temporalmente si existe
    temp_desc = description.replace(watermark, '')
    
    # Truncar el contenido principal
    max_content_length = max_length - len(watermark) - 4  # 4 para los saltos de línea
    truncated = temp_desc[:max_content_length]
    
    # Encontrar el último salto de línea completo
    last_newline = truncated.rfind('\n')
    if last_newline > max_content_length * 0.8:  # Si está en el último 20% del texto
        truncated = truncated[:last_newline]
    
    # Asegurarse de que todas las etiquetas HTML están cerradas
    open_tags = []
    for match in re.finditer(r'<(\w+)[^>]*>', truncated):
        open_tags.append(match.group(1))
    for match in re.finditer(r'</(\w+)>', truncated):
        if match.group(1) in open_tags:
            open_tags.remove(match.group(1))
    
    # Cerrar las etiquetas abiertas en orden inverso
    truncated += "..."
    for tag in reversed(open_tags):
        truncated += f"</{tag}>"
    
    # Agregar la marca de agua al final
    truncated += f"\n\n{watermark}"
    
    return truncated

# Función para verificar membresía al canal
async def is_channel_member(user_id, context):
    """Verifica si un usuario es miembro del canal principal."""
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except TelegramError as e:
        logger.error(f"Error verificando membresía: {e}")
        return False
        
# Decorador para verificar membresía en el canal
def check_channel_membership(func):
    """Decorador para verificar la membresía al canal antes de ejecutar comandos."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat.type == 'private':  # Solo verificar en chats privados
            user_id = update.effective_user.id
            
            # Verificar si el usuario ya está marcado como verificado recientemente (caché)
            verification_cache = context.bot_data.setdefault('verification_cache', {})
            cached_until = verification_cache.get(user_id)
            
            current_time = datetime.now()
            if cached_until and current_time < cached_until:
                # El usuario está en caché y la verificación es válida
                return await func(update, context, *args, **kwargs)
            
            # Verificar membresía
            is_member = await is_channel_member(user_id, context)
            
            if not is_member:
                # Usuario no es miembro, mostrar mensaje de suscripción
                keyboard = [
                    [InlineKeyboardButton("Unirse al Canal 📢", url=f"https://t.me/multimediatvOficial")],
                    [InlineKeyboardButton("Ya me uní ✅", callback_data="verify_membership")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.effective_message.reply_text(
                    "⚠️ Para usar el bot, debes unirte a nuestro canal principal.\n\n"
                    "1. Haz clic en el botón 'Unirse al Canal 📢'\n"
                    "2. Una vez unido, vuelve aquí y presiona 'Ya me uní ✅'",
                    reply_markup=reply_markup
                )
                return
            
            # Si llega aquí, el usuario es miembro, lo guardamos en caché para reducir verificaciones
            # Caché por 30 minutos
            verification_cache[user_id] = current_time + timedelta(minutes=30)
            
        # Si es un chat grupal o el usuario es miembro, ejecutar la función original
        return await func(update, context, *args, **kwargs)
    
    return wrapper

@check_channel_membership
# Lógica para el bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /start."""
    if update.message is None:
        return
        
    user = update.effective_user
    
    # Comprobar si es una solicitud de contenido específico
    if context.args and context.args[0].startswith('content_'):
        try:
            content_id = int(context.args[0].replace('content_', ''))
            user_data = db.get_user(user.id)
            can_forward = user_data and user_data.get('can_forward', False)
            
            # Mostrar acción de escribiendo mientras se procesa
            await context.bot.send_chat_action(
                chat_id=update.message.chat_id,
                action=ChatAction.TYPING
            )
            
            try:
                # Copiar el mensaje con los permisos adecuados
                await context.bot.copy_message(
                    chat_id=update.message.chat_id,
                    from_chat_id=SEARCH_CHANNEL_ID,
                    message_id=content_id,
                    protect_content=not can_forward
                )
                
                # Añadir después de cada copy_message:
                await send_content_message(update.message.chat_id, context, content_id)

                # Incrementar contador de búsquedas diarias
                db.increment_daily_usage(user.id)
                
                return  # Salir de la función después de enviar el contenido
                
            except Exception as e:
                logger.error(f"Error al enviar contenido específico: {e}")
                await update.message.reply_text(
                    "❌ No se pudo cargar el contenido solicitado. Es posible que ya no esté disponible.",
                    parse_mode=ParseMode.HTML
                )
                return
        except (ValueError, IndexError) as e:
            logger.error(f"Error procesando content_id: {e}")
            # Continuar con el flujo normal de start si falla.
    
    # Comprobar si es una solicitud de serie con múltiples temporadas
    if context.args and context.args[0].startswith('multiseries_'):
        try:
            series_id = int(context.args[0].replace('multiseries_', ''))
            await handle_multi_series_request(update, context, series_id)
            return
        except (ValueError, IndexError) as e:
            logger.error(f"Error procesando multiseries_id: {e}")
            
            # Mostrar acción de escribiendo mientras se procesa
            await context.bot.send_chat_action(
                chat_id=update.message.chat_id,
                action=ChatAction.TYPING
            )
            
            try:
                # Usar siempre copy_message con permisos diferentes
                await context.bot.copy_message(
                    chat_id=update.message.chat_id,
                    from_chat_id=SEARCH_CHANNEL_ID,
                    message_id=content_id,
                    protect_content=not can_forward  # False para Plus/Ultra, True para Básico/Pro
                )
                
                # Añadir después de cada copy_message:
                await send_content_message(update.message.chat_id, context, content_id)

                # Incrementar contador de búsquedas diarias
                db.increment_daily_usage(user.id)
                
                return  # Salir de la función después de enviar el contenido
            except Exception as e:
                logger.error(f"Error al enviar contenido específico: {e}")
                await update.message.reply_text(
                    "❌ No se pudo cargar el contenido solicitado. Es posible que ya no esté disponible."
                )
                # Continuar con el flujo normal de start si falla
        except (ValueError, IndexError) as e:
            logger.error(f"Error procesando content_id: {e}")
            # Continuar con el flujo normal de start si falla
    
    # Comprobar si es una solicitud de serie
    if context.args and context.args[0].startswith('series_'):
        try:
            series_id = int(context.args[0].replace('series_', ''))
            await handle_series_request(update, context, series_id)
            return
        except (ValueError, IndexError) as e:
            logger.error(f"Error procesando series_id: {e}")
            # Continuar con el flujo normal de start si falla
    
    # Check if this is a referral (código existente)
    if context.args and context.args[0].startswith('ref_'):
        ref_id = context.args[0].replace('ref_', '')
        try:
            ref_id = int(ref_id)
            if ref_id != user.id and db.user_exists(ref_id):
                # Add referral if not already added
                if not db.is_referred(user.id):
                    db.add_referral(ref_id, user.id)
                    await context.bot.send_message(
                        chat_id=ref_id,
                        text=f"¡Nuevo referido! {user.first_name} se ha unido usando tu enlace. Has ganado +1 💎"
                    )
        except ValueError:
            pass

    # Resto del código original de start...
    user_data = db.get_user(user.id)
    if not user_data:  # Registrar solo si el usuario no existe
        db.add_user(
            user.id,
            user.username,
            user.first_name,
            user.last_name
        )
    
    # Create main menu keyboard
    keyboard = [
        [
            InlineKeyboardButton("Multimedia Tv 📺", url=f"https://t.me/multimediatvOficial"),
            InlineKeyboardButton("Pedidos 📡", url=f"https://t.me/+X9S4pxF8c7plYjYx")
        ],
        [InlineKeyboardButton("Perfil 👤", callback_data="profile")],
        [InlineKeyboardButton("Planes 📜", callback_data="plans")],
        [InlineKeyboardButton("Información 📰", callback_data="info")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"¡Hola! {user.first_name}👋 te doy la bienvenida\n\n"
        f"<blockquote expandable>MultimediaTv un bot donde encontraras un amplio catálogo de películas y series, "
        f"las cuales puedes buscar o solicitar en caso de no estar en el catálogo</blockquote>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    
async def send_content_message(chat_id, context, msg_id):
    """Envía el mensaje estándar después de enviar contenido"""
    try:
        # Generar URL para compartir
        view_url = f"https://t.me/MultimediaTVbot?start=content_{msg_id}"
        
        # Crear el botón de compartir y el mensaje con el botón
        keyboard = [
            [InlineKeyboardButton(
                "🔗 Compartir", 
                url=f"https://t.me/share/url?url={view_url}&text=¡Mira este contenido en MultimediaTV!"
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Enviar mensaje con el texto estándar y el botón
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "📌 Muchas gracias por Preferirnos\n"
                "<blockquote expandable>En caso de que no puedas reenviar ni guardar el archivo en tu teléfono, "
                "quiere decir que no tienes un plan comprado. Por lo cual te recomiendo "
                "que adquieras los planes Medio o Ultra que le dan estas posibilidades.</blockquote>\n\n"
                "◈ Nota\n"
                "<blockquote>Adquiere un Plan y disfruta de todas las opciones</blockquote>\n\n"
                "Comparte con tus familiares y amigos el contenido anterior ☝️"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending content message: {e}")
        
async def handle_series_request(update: Update, context: ContextTypes.DEFAULT_TYPE, series_id: int) -> None:
    """Manejar la solicitud de visualización de una serie"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    # Verificar límites de búsqueda
    if not db.increment_daily_usage(user_id):
        # Mostrar mensaje de límite excedido y opciones de planes
        keyboard = []
        for plan_id, plan in PLANS_INFO.items():
            if plan_id != 'basic':
                keyboard.append([
                    InlineKeyboardButton(
                        f"{plan['name']} - {plan['price']}",
                        callback_data=f"buy_plan_{plan_id}"
                    )
                ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ Has alcanzado tu límite de búsquedas diarias.\n\n"
            "<blockquote>Para continuar viendo series, adquiere un plan premium:</blockquote>",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
    
    # Mostrar acción de escribiendo
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )
    
    # Obtener datos de la serie
    series = db.get_series(series_id)
    
    if not series:
        await update.message.reply_text(
            "❌ Serie no encontrada. Es posible que haya sido eliminada o que el enlace sea incorrecto.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Obtener capítulos
    episodes = db.get_series_episodes(series_id)
    
    if not episodes:
        await update.message.reply_text(
            "❌ Esta serie no tiene capítulos disponibles actualmente.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Obtener portada
    cover_message_id = series['cover_message_id']
    
    try:
        # Enviar portada
        await context.bot.copy_message(
            chat_id=update.effective_chat.id,
            from_chat_id=SEARCH_CHANNEL_ID,
            message_id=cover_message_id
        )
        
        # Crear botones para los capítulos
        keyboard = []
        
        # Añadir un botón para cada capítulo, organizados en filas de 3
        for i in range(0, len(episodes), 3):
            row = []
            for j in range(i, min(i + 3, len(episodes))):
                episode = episodes[j]
                row.append(
                    InlineKeyboardButton(
                        f"Capítulo {episode['episode_number']}",
                        callback_data=f"ep_{series_id}_{episode['episode_number']}"
                    )
                )
            keyboard.append(row)
        
        # Añadir botón para enviar todos los capítulos
        keyboard.append([
            InlineKeyboardButton(
                "Enviar todos los capítulos",
                callback_data=f"ep_all_{series_id}"
            )
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Enviar mensaje con botones
        msg = await update.message.reply_text(
            f"📺 <b>{series['title']}</b>\n\n"
            f"Selecciona un capítulo para ver o solicita todos los capítulos:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
        # Enviar mensaje estándar con botón de compartir
        await send_content_message(update.effective_chat.id, context, msg.message_id)
        
    except Exception as e:
        logger.error(f"Error enviando datos de serie: {e}")
        await update.message.reply_text(
            f"❌ Error al mostrar la serie: {str(e)[:100]}\n\n"
            f"Por favor, intenta más tarde.",
            parse_mode=ParseMode.HTML
        )      

async def ser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para administradores para subir series con múltiples temporadas"""
    try:
        user = update.effective_user
        if not user:
            return
    
    # Verificar que el usuario es administrador
        if not is_admin(user.id):
            return

        # Obtener el estado actual
        ser_state = context.user_data.get('ser_state', SER_STATE_IDLE)

        # Si estamos inactivos, iniciar el proceso
        if ser_state == SER_STATE_IDLE:
            try:
                # Inicializar estructura de datos
                context.user_data['ser_state'] = SER_STATE_WAITING_NAME
                context.user_data['current_series'] = {
                    'name': None,
                    'imdb_info': None,
                    'seasons': {},  # Diccionario para almacenar las temporadas
                    'current_season': None,  # Temporada actual
                    'cover_photo': None,
                    'description': None,
                    'total_episodes': 0,  # Contador total de episodios
                    'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'processed_seasons': set(),  # Para rastrear temporadas procesadas
                    'series_id': None  # Para mantener consistencia en los IDS
                }

                help_text = (
                    "📺 <b>Modo de carga de series multi-temporada activado</b>\n\n"
                    "<blockquote>"
                    "1️⃣ Envía primero el nombre exacto de la serie para buscar en TMDB\n"
                    "2️⃣ Luego envía /season 'número' para indicar la temporada\n"
                    "   Ejemplo: /season 1\n"
                    "3️⃣ Después envía todos los capítulos de esa temporada\n"
                    "4️⃣ Cuando termines una temporada, usa /season para la siguiente\n"
                    "5️⃣ Al terminar todas las temporadas, envía /ser para finalizar\n"
                    "</blockquote>\n\n"
                    "✨ Para cancelar el proceso, envía /cancelser\n"
                    "⚠️ Los capítulos se renombrarán automáticamente"
                )

                await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

                # Crear mensaje de estado
                status_msg = await update.message.reply_text(
                    "<blockquote>⏳ Esperando nombre de la serie...\n"
                    "Envía el nombre exacto para buscar en TMDB</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                context.user_data['status_message'] = status_msg

            except Exception as e:
                logger.error(f"Error iniciando modo de carga: {e}")
                await update.message.reply_text(
                    "<blockquote>❌ Error al iniciar el modo de carga. Por favor, intenta nuevamente.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                context.user_data['ser_state'] = SER_STATE_IDLE
                context.user_data.pop('current_series', None)

        else:
            try:
                # Verificar si hay datos para procesar
                current_series = context.user_data.get('current_series', {})
                if not current_series.get('seasons'):
                    await update.message.reply_text(
                        "<blockquote>⚠️ No hay temporadas para procesar.\n"
                        "Debes añadir al menos una temporada con capítulos antes de finalizar.</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    return

                # Mostrar resumen antes de finalizar
                seasons_info = []
                total_episodes = 0
                for season_num, episodes in sorted(current_series['seasons'].items(), key=lambda x: int(x[0])):
                    episode_count = len(episodes)
                    total_episodes += episode_count
                    seasons_info.append(f"Temporada {season_num}: {episode_count} capítulos")

                # Actualizar información en current_series
                current_series['total_episodes'] = total_episodes
                current_series['total_seasons'] = len(current_series['seasons'])
                current_series['seasons_info'] = seasons_info
                
                # Asignar series_id si no existe
                if not current_series.get('series_id'):
                    current_series['series_id'] = int(time.time())

                # Crear mensaje de resumen
                summary_text = (
                    f"📊 <b>Resumen de la serie:</b>\n\n"
                    f"Título: <b>{current_series.get('name', 'Sin título')}</b>\n"
                    f"Total temporadas: {len(current_series['seasons'])}\n"
                    f"Total episodios: {total_episodes}\n\n"
                    f"Desglose:\n{chr(10).join(seasons_info)}\n\n"
                    f"<blockquote>⏳ Iniciando proceso de subida...</blockquote>"
                )

                # Enviar resumen y comenzar proceso
                status_message = await update.message.reply_text(
                    summary_text,
                    parse_mode=ParseMode.HTML
                )

                # Guardar tiempo de inicio del proceso
                current_series['upload_start_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Finalizar el proceso y subir la serie
                # Pasar el status_message como tercer argumento
                await finalize_multi_series_upload(update, context, status_message)

            except Exception as e:
                logger.error(f"Error finalizando serie: {e}")
                await update.message.reply_text(
                    "<blockquote>❌ Error al finalizar la serie. Por favor, verifica los datos e intenta nuevamente.</blockquote>",
                    parse_mode=ParseMode.HTML
                )

    except Exception as e:
        logger.error(f"Error general en ser_command: {e}")
        await update.message.reply_text(
            "<blockquote>❌ Ocurrió un error inesperado. Por favor, intenta nuevamente.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['ser_state'] = SER_STATE_IDLE
        context.user_data.pop('current_series', None)

async def season_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para indicar la temporada actual"""
    try:
        user = update.effective_user
        if not user:
            return
    
    # Verificar que el usuario es administrador
        if not is_admin(user.id):
            return

        if context.user_data.get('ser_state') != SER_STATE_RECEIVING:
            await update.message.reply_text(
                "<blockquote>⚠️ Debes iniciar primero el proceso con /ser</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return

        if not context.args:
            await update.message.reply_text(
                "Uso: /season número\n"
                "Ejemplo: /season 1",
                parse_mode=ParseMode.HTML
            )
            return

        try:
            season_number = int(context.args[0])
            current_series = context.user_data.get('current_series', {})
            
            if not current_series.get('name'):
                await update.message.reply_text(
                    "<blockquote>⚠️ Primero debes especificar el nombre de la serie.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                return

            # Asegurar que existe la estructura de temporadas
            if 'seasons' not in current_series:
                current_series['seasons'] = {}

            # Convertir season_number a string para consistencia
            season_number = str(season_number)
            
            # Si la temporada no existe, inicializarla
            if season_number not in current_series['seasons']:
                current_series['seasons'][season_number] = []

            current_series['current_season'] = season_number
            
            # IMPORTANTE: Actualizar el contexto
            context.user_data['current_series'] = current_series
            
            # Mostrar estado actual de todas las temporadas
            seasons_info = "\n".join(f"Temporada {s}: {len(e)} episodios" 
                                   for s, e in current_series['seasons'].items())
            
            await update.message.reply_text(
                f"<blockquote>✅ Ahora trabajando en la Temporada {season_number}\n\n"
                f"Estado actual de la serie:\n{seasons_info}\n\n"
                f"Envía los capítulos de esta temporada.</blockquote>",
                parse_mode=ParseMode.HTML
            )

        except ValueError:
            await update.message.reply_text(
                "<blockquote>❌ El número de temporada debe ser un número entero.</blockquote>",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            "<blockquote>❌ Ocurrió un error. Por favor, intenta nuevamente.</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def handle_series_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar la recepción del nombre de la serie"""
    try:
        user = update.effective_user
        if not user:
            return
    
    # Verificar que el usuario es administrador
        if not is_admin(user.id):
            return

        # Verificar explícitamente el estado
        current_state = context.user_data.get('ser_state')
        if current_state != SER_STATE_WAITING_NAME:
            # Si no estamos esperando el nombre, ignorar el mensaje
            return

        series_name = update.message.text.strip()
        status_message = await update.message.reply_text(
            f"<blockquote>🔍 Buscando información para: <b>{series_name}</b>...</blockquote>",
            parse_mode=ParseMode.HTML
        )

        try:
            imdb_info = await search_imdb_info(series_name)
            
            # Guardar la información
            context.user_data['current_series'] = {
                'name': imdb_info['title'] if imdb_info else series_name,
                'imdb_info': imdb_info,
                'seasons': {},
                'current_season': None,
                'cover_photo': None,
                'description': None
            }
            
            if imdb_info:
                preview_text = (
                    f"✅ <b>{imdb_info['title']}</b> ({imdb_info.get('year', 'N/A')})\n\n"
                    f"⭐ <b>Calificación:</b> {imdb_info.get('rating', 'N/A')}/10\n"
                    f"🎭 <b>Género:</b> {imdb_info.get('genres', 'No disponible')}\n\n"
                    f"<blockquote>Ahora usa /season número para indicar la temporada\n"
                    f"Ejemplo: /season 1</blockquote>"
                )
                
                if imdb_info.get('poster_url'):
                    try:
                        poster_response = requests.get(imdb_info['poster_url'])
                        poster_response.raise_for_status()
                        poster_bytes = BytesIO(poster_response.content)
                        
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=poster_bytes,
                            caption=preview_text,
                            parse_mode=ParseMode.HTML
                        )
                        await status_message.delete()
                    except Exception as e:
                        logger.error(f"Error descargando póster: {e}")
                        await status_message.edit_text(preview_text, parse_mode=ParseMode.HTML)
                else:
                    await status_message.edit_text(preview_text, parse_mode=ParseMode.HTML)
            else:
                await status_message.edit_text(
                    f"<blockquote>⚠️ No se encontró información para {series_name}\n"
                    f"Continuando con información básica.\n"
                    f"Usa /season número para empezar con la primera temporada</blockquote>",
                    parse_mode=ParseMode.HTML
                )

            # Cambiar el estado a esperar archivos
            context.user_data['ser_state'] = SER_STATE_RECEIVING

        except Exception as e:
            logger.error(f"Error buscando información: {e}")
            await status_message.edit_text(
                f"<blockquote>❌ Error al buscar información: {str(e)[:100]}\n"
                f"Por favor, intenta nuevamente con /ser</blockquote>",
                parse_mode=ParseMode.HTML
            )
            # Reiniciar el estado
            context.user_data['ser_state'] = SER_STATE_IDLE

    except Exception as e:
        logger.error(f"Error en handle_series_name: {e}")
        await update.message.reply_text(
            "<blockquote>❌ Ocurrió un error. Por favor, intenta nuevamente con /ser</blockquote>",
            parse_mode=ParseMode.HTML
        )
        # Reiniciar el estado
        context.user_data['ser_state'] = SER_STATE_IDLE

async def cancel_ser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancelar el proceso de carga de series"""
    try:
        user = update.effective_user
        if not user:
            return
    
    # Verificar que el usuario es administrador
        if not is_admin(user.id):
            return        

        # Verificar si hay un proceso activo
        if context.user_data.get('ser_state', SER_STATE_IDLE) == SER_STATE_IDLE:
            await update.message.reply_text(
                "<blockquote>ℹ️ No hay ningún proceso de carga activo para cancelar.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return

        # Reiniciar el estado
        context.user_data['ser_state'] = SER_STATE_IDLE
        context.user_data.pop('current_series', None)
        context.user_data.pop('status_message', None)

        await update.message.reply_text(
            "<blockquote>❌ Proceso de carga de series cancelado.\n"
            "Todos los datos temporales han sido eliminados.</blockquote>",
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            "<blockquote>❌ Ocurrió un error al cancelar. El estado ha sido reiniciado.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        # Asegurar que el estado se reinicia incluso si hay un error
        context.user_data['ser_state'] = SER_STATE_IDLE
        context.user_data.pop('current_series', None)

async def handle_series_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar la recepción de capítulos durante el proceso de serie"""
    try:
        user = update.effective_user
        if not user:
            return
    
    # Verificar que el usuario es administrador
        if not is_admin(user.id):
            return

        # Inicializar la estructura de datos si no existe
        if 'current_series' not in context.user_data:
            context.user_data['current_series'] = {
                'name': None,
                'seasons': {},
                'current_season': None
            }

        current_series = context.user_data['current_series']
        current_season = current_series.get('current_season')

        if not current_season:
            await update.message.reply_text(
                "<blockquote>⚠️ Primero debes seleccionar una temporada con /season número</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return

        if update.message.video or update.message.document:
            message_id = update.message.message_id
            chat_id = update.effective_chat.id
            original_caption = update.message.caption or ""
            file_name = update.message.document.file_name if update.message.document else None

            # Inicializar la lista de episodios para la temporada actual si no existe
            if 'seasons' not in current_series:
                current_series['seasons'] = {}
            if current_season not in current_series['seasons']:
                current_series['seasons'][current_season] = []

            episode_num = len(current_series['seasons'][current_season]) + 1

            # Crear nuevo caption
            new_caption = f"{current_series['name']} - Temporada {current_season} Capítulo {episode_num}"

            try:
                # Reenviar con el nuevo caption
                if update.message.video:
                    file_id = update.message.video.file_id
                    new_message = await context.bot.send_video(
                        chat_id=chat_id,
                        video=file_id,
                        caption=new_caption
                    )
                else:
                    file_id = update.message.document.file_id
                    new_message = await context.bot.send_document(
                        chat_id=chat_id,
                        document=file_id,
                        caption=new_caption
                    )

                episode_data = {
                    'message_id': new_message.message_id,
                    'episode_number': episode_num,
                    'chat_id': chat_id,
                    'caption': new_caption
                }

                # Añadir el episodio a la temporada correcta
                current_series['seasons'][current_season].append(episode_data)
                
                # IMPORTANTE: Actualizar el contexto
                context.user_data['current_series'] = current_series

                # Mostrar resumen actual
                seasons_info = "\n".join([
                    f"Temporada {season}: {len(episodes)} episodios"
                    for season, episodes in current_series['seasons'].items()
                ])
                total_episodes = sum(len(episodes) for episodes in current_series['seasons'].values())

                await update.message.reply_text(
                    f"<blockquote>✅ Capítulo {episode_num} añadido a Temporada {current_season}\n\n"
                    f"Estado actual:\n{seasons_info}\n"
                    f"Total de episodios: {total_episodes}</blockquote>",
                    parse_mode=ParseMode.HTML
                )

            except Exception as e:
                logger.error(f"Error al procesar capítulo: {e}")
                await update.message.reply_text(
                    "<blockquote>❌ Error al procesar el capítulo. Por favor, intenta nuevamente.</blockquote>",
                    parse_mode=ParseMode.HTML
                )

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            "<blockquote>❌ Ocurrió un error. Por favor, intenta nuevamente.</blockquote>",
            parse_mode=ParseMode.HTML
        )
            
async def finalize_multi_series_upload(update, context, status_message=None):
    """Finalizar el proceso y subir la serie con múltiples temporadas"""
    # Inicialización de variables y contadores
    current_series = context.user_data.get('current_series', {})
    successfully_processed_seasons = []
    total_episodes = 0
    successful_episodes = 0  # Nuevo contador para episodios exitosos
    failed_episodes = 0
    successful_seasons = {}
    processed_seasons = 0

    # Verificación inicial de datos
    if not current_series or not current_series.get('seasons'):
        await update.message.reply_text(
            "<blockquote>❌ No hay datos suficientes para subir la serie.\n"
            "Debes añadir al menos una temporada con capítulos.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return

    # Verificar que todas las temporadas tengan episodios
    for season_num, episodes in current_series['seasons'].items():
        if not episodes:
            await update.message.reply_text(
                f"<blockquote>⚠️ La temporada {season_num} está vacía.\n"
                "Por favor, asegúrate de que todas las temporadas tengan episodios.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return

    if not status_message:
        status_message = await update.message.reply_text(
            "<blockquote>⏳ Procesando y subiendo la serie...</blockquote>",
            parse_mode=ParseMode.HTML
        )

    try:
        # 1. Crear ID único para la serie
        series_id = int(time.time())

        # ... [mantener el código existente hasta la parte de procesar temporadas] ...

        # 8. Procesar todas las temporadas
        # Ordenar temporadas numéricamente y convertir a lista para garantizar el orden
        seasons = [(int(season_num), episodes) for season_num, episodes in current_series['seasons'].items()]
        seasons.sort(key=lambda x: x[0])  # Ordenar por número de temporada
        total_seasons = len(seasons)
        total_expected_episodes = sum(len(episodes) for _, episodes in seasons)

        # Verificar temporadas antes de procesar
        await status_message.edit_text(
            f"<blockquote>📊 Iniciando procesamiento de {total_seasons} temporadas con {total_expected_episodes} episodios totales...</blockquote>",
            parse_mode=ParseMode.HTML
        )

        # Procesar cada temporada
        for season_idx, (season_num, episodes) in enumerate(seasons, 1):
            try:
                await status_message.edit_text(
                    f"<blockquote>⏳ Procesando Temporada {season_num} ({len(episodes)} episodios)\n"
                    f"Progreso: {season_idx}/{total_seasons}</blockquote>",
                    parse_mode=ParseMode.HTML
                )

                # Crear ID único para la temporada
                season_id = int(f"{series_id}{season_num:03d}")
                season_episodes = []

                # Registrar temporada en la base de datos con reintentos
                for db_attempt in range(3):
                    try:
                        db.add_season(
                            season_id=season_id,
                            series_id=series_id,
                            season_name=f"{current_series['name']} - Temporada {season_num}"
                        )
                        break
                    except Exception as db_error:
                        if db_attempt == 2:
                            raise db_error
                        await asyncio.sleep(1)

                # Procesar episodios en grupos pequeños
                episode_groups = [episodes[i:i+3] for i in range(0, len(episodes), 3)]  # Grupos más pequeños

                for group_idx, group in enumerate(episode_groups):
                    await status_message.edit_text(
                        f"<blockquote>⏳ Subiendo episodios de Temporada {season_num}\n"
                        f"Grupo {group_idx + 1}/{len(episode_groups)}\n"
                        f"Episodios exitosos: {successful_episodes}/{total_expected_episodes}</blockquote>",
                        parse_mode=ParseMode.HTML
                    )

                    for episode in group:
                        try:
                            # Intentar copiar el episodio hasta 3 veces
                            copied_msg = None
                            for copy_attempt in range(3):
                                try:
                                    copied_msg = await context.bot.copy_message(
                                        chat_id=SEARCH_CHANNEL_ID,
                                        from_chat_id=episode['chat_id'],
                                        message_id=episode['message_id'],
                                        disable_notification=True
                                    )
                                    break
                                except Exception as copy_error:
                                    if copy_attempt == 2:
                                        raise copy_error
                                    await asyncio.sleep(2)

                            if copied_msg:
                                # Registrar episodio en la base de datos con reintentos
                                for db_attempt in range(3):
                                    try:
                                        db.add_season_episode(
                                            season_id=season_id,
                                            episode_number=episode['episode_number'],
                                            message_id=copied_msg.message_id
                                        )
                                        break
                                    except Exception as db_error:
                                        if db_attempt == 2:
                                            raise db_error
                                        await asyncio.sleep(1)

                                season_episodes.append({
                                    'episode_number': episode['episode_number'],
                                    'message_id': copied_msg.message_id
                                })
                                successful_episodes += 1

                            await asyncio.sleep(1)  # Pausa entre episodios

                        except Exception as e:
                            logger.error(f"Error subiendo episodio {episode['episode_number']} de temporada {season_num}: {e}")
                            failed_episodes += 1
                            continue

                    await asyncio.sleep(2)  # Pausa entre grupos

                if season_episodes:  # Si se procesaron episodios exitosamente
                    successful_seasons[season_num] = season_episodes
                    successfully_processed_seasons.append(season_num)
                    processed_seasons += 1

                    await status_message.edit_text(
                        f"<blockquote>✅ Temporada {season_num} completada: {len(season_episodes)} episodios\n"
                        f"Progreso: {processed_seasons}/{total_seasons}</blockquote>",
                        parse_mode=ParseMode.HTML
                    )

                await asyncio.sleep(3)  # Pausa más larga entre temporadas

            except Exception as e:
                logger.error(f"Error procesando temporada {season_num}: {e}")
                await status_message.edit_text(
                    f"<blockquote>⚠️ Error en temporada {season_num}: {str(e)[:100]}\n"
                    f"Intentando continuar con la siguiente temporada...</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                await asyncio.sleep(2)
                continue

        # Verificar si se procesó al menos una temporada
        if not successfully_processed_seasons:
            raise Exception("No se pudo procesar ninguna temporada correctamente")

        # ... [mantener el resto del código igual] ...

        # 12. Informar resultado final con información más detallada
        success_message = (
            f"<blockquote>✅ Serie <b>{current_series['name']}</b> subida correctamente\n\n"
            f"📊 Detalles:\n"
            f"- Temporadas procesadas: {len(successfully_processed_seasons)} de {total_seasons}\n"
            f"- Episodios subidos: {successful_episodes} de {total_expected_episodes}\n"
        )

        if failed_episodes > 0:
            success_message += f"⚠️ {failed_episodes} episodios fallaron al subir\n"

        if len(successfully_processed_seasons) < total_seasons:
            success_message += f"⚠️ {total_seasons - len(successfully_processed_seasons)} temporadas no se procesaron\n"

        success_message += (
            f"- ID: {series_id}\n"
            f"- Canales: ✓ Principal y Búsqueda\n\n"
            f"Los usuarios pueden acceder a través del botón 'Ver ahora'</blockquote>"
        )

        await status_message.edit_text(success_message, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error finalizando serie: {e}")
        await status_message.edit_text(
            f"<blockquote>❌ Error al finalizar la serie: {str(e)[:100]}</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def fetch_image(url):
    """Descargar imagen de una URL"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return BytesIO(await response.read())
    return None

from deep_translator import GoogleTranslator

async def buscar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para buscar contenido en TMDB/IMDb y mostrar resultados detallados"""
    # Verificar que el usuario es administrador
    user = update.effective_user
    if not is_admin(user.id):
        return
    
    # Verificar que hay un término de búsqueda
    if not context.args:
        await update.message.reply_text(
            "Uso: /buscar nombre_del_contenido\n"
            "<blockquote>Ejemplo: /buscar Feliz día de tu muerte 2</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    query = " ".join(context.args)
    status_msg = await update.message.reply_text(
        f"<blockquote>🔍 Buscando información para: <b>{query}</b>...</blockquote>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Inicializar traductor
        translator = GoogleTranslator(source='en', target='es')
        
        # Configuración de TMDB API
        api_key = "ba7dc9b8dc85198f56a7b631a6519158"
        headers = {
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJiYTdkYzliOGRjODUxOThmNTZhN2I2MzFhNjUxOTE1OCIsInN1YiI6IjY4MWJiYTFiOWNkMjZiOTNhZTkzYWE4NiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.7DJM5c5k_FpRnN9-_6tkKSO1sZ2_dGGkPAQJhGIGSjQ",
            "Content-Type": "application/json;charset=utf-8"
        }

        # Buscar en TMDB (películas y series)
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={query}&language=es-ES"
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers) as response:
                search_data = await response.json()

        if not search_data.get('results'):
            await status_msg.edit_text(
                f"<blockquote>❌ No se encontraron resultados para: <b>{query}</b></blockquote>",
                parse_mode=ParseMode.HTML
            )
            return

        # Procesar cada resultado
        for result in search_data['results'][:5]:  # Limitamos a 5 resultados
            try:
                media_type = result.get('media_type')
                if media_type not in ['movie', 'tv']:
                    continue

                # Obtener detalles completos
                detail_url = f"https://api.themoviedb.org/3/{media_type}/{result['id']}?api_key={api_key}&language=es-ES&append_to_response=credits"
                async with aiohttp.ClientSession() as session:
                    async with session.get(detail_url, headers=headers) as response:
                        details = await response.json()

                # Obtener título en inglés
                detail_url_en = f"https://api.themoviedb.org/3/{media_type}/{result['id']}?api_key={api_key}&language=en-US"
                async with aiohttp.ClientSession() as session:
                    async with session.get(detail_url_en, headers=headers) as response:
                        details_en = await response.json()

                # Si la sinopsis en español está vacía, traducir desde inglés
                if not details.get('overview', '').strip() and details_en.get('overview'):
                    try:
                        translated_overview = translator.translate(details_en['overview'])
                        details['overview'] = translated_overview
                    except Exception as e:
                        logger.error(f"Error traduciendo sinopsis: {e}")
                        details['overview'] = details_en['overview']

                # Preparar la información
                content_type = "Serie 🎥" if media_type == 'tv' else "Película 🍿"
                spanish_title = details.get('title' if media_type == 'movie' else 'name', 'No disponible')
                english_title = details_en.get('original_title' if media_type == 'movie' else 'original_name', spanish_title)
                year = details.get('release_date', '')[:4] if media_type == 'movie' else details.get('first_air_date', '')[:4]
                rating = round(details.get('vote_average', 0), 1)
                genres = ", ".join([g['name'] for g in details.get('genres', [])])
                
                # Obtener director(es)
                directors = []
                if media_type == 'movie':
                    directors = [crew['name'] for crew in details.get('credits', {}).get('crew', []) if crew['job'] == 'Director']
                else:
                    directors = [crew['name'] for crew in details.get('credits', {}).get('crew', []) if crew['job'] in ['Creator', 'Executive Producer']]
                director_text = ", ".join(directors) if directors else "No disponible"

                # Obtener reparto principal
                cast = [actor['name'] for actor in details.get('credits', {}).get('cast', [])[:5]]
                cast_text = ", ".join(cast) if cast else "No disponible"

                # Información adicional para series
                additional_info = ""
                if media_type == 'tv':
                    status_map = {
                        'Returning Series': 'En emisión',
                        'Ended': 'Finalizada',
                        'Canceled': 'Cancelada'
                    }
                    series_status = status_map.get(details.get('status'), details.get('status', 'Desconocido'))
                    num_seasons = details.get('number_of_seasons', '?')
                    num_episodes = details.get('number_of_episodes', '?')
                    additional_info = f"\n📺 Estado: {series_status}\n🔢 {num_episodes} episodios en {num_seasons} temporadas"

                # Crear mensaje
                message = (
                    f"{content_type}\n"
                    f"{spanish_title} ✓\n"
                    f"{english_title} ✓\n\n"
                    f"📅 Año: {year}\n"
                    f"⭐ Calificación: {rating}/10\n"
                    f"🎭 Género: {genres}\n"
                    f"🎬 Director: {director_text}\n"
                    f"👥 Reparto: {cast_text}"
                    f"{additional_info}\n\n"
                    f"📝 Sinopsis:\n"
                    f"<blockquote expandable>{details.get('overview', 'No disponible')}</blockquote>\n\n"
                    f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
                )

                # Obtener y enviar póster
                if details.get('poster_path'):
                    poster_url = f"https://image.tmdb.org/t/p/original{details['poster_path']}"
                    try:
                        poster_bytes = await fetch_image(poster_url)
                        if poster_bytes:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=poster_bytes,
                                caption=message,
                                parse_mode=ParseMode.HTML
                            )
                        else:
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=f"{message}\n\n⚠️ No se pudo cargar el póster.",
                                parse_mode=ParseMode.HTML
                            )
                    except Exception as e:
                        logger.error(f"Error enviando póster: {e}")
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=message,
                            parse_mode=ParseMode.HTML
                        )

            except Exception as e:
                logger.error(f"Error procesando resultado: {e}")
                continue

        await status_msg.delete()

    except Exception as e:
        logger.error(f"Error en búsqueda: {e}")
        await status_msg.edit_text(
            f"<blockquote>❌ Error durante la búsqueda: {str(e)[:100]}</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def send_episode(query, context, series_id, episode_number):
    """Enviar un capítulo específico al usuario"""
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    can_forward = user_data and user_data.get('can_forward', False)
    
    await query.answer("Procesando tu solicitud...")
    
    # Mostrar acción de escribiendo
    await context.bot.send_chat_action(
        chat_id=query.message.chat_id,
        action=ChatAction.TYPING
    )
    
    try:
        # Obtener datos del capítulo
        episode = db.get_episode(series_id, episode_number)
        
        if not episode:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Capítulo {episode_number} no encontrado.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Enviar el capítulo
        await context.bot.copy_message(
            chat_id=query.message.chat_id,
            from_chat_id=SEARCH_CHANNEL_ID,
            message_id=episode['message_id'],
            protect_content=not can_forward  # Proteger según el plan
        )
        
        # Marcar el botón como seleccionado
        keyboard = query.message.reply_markup.inline_keyboard
        new_keyboard = []
        
        for row in keyboard:
            new_row = []
            for button in row:
                if button.callback_data == query.data:
                    # Marcar este botón como seleccionado
                    new_row.append(InlineKeyboardButton(
                        f"✅ {button.text}",
                        callback_data=button.callback_data
                    ))
                else:
                    new_row.append(button)
            new_keyboard.append(new_row)
        
        # Actualizar el mensaje con el nuevo teclado
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(new_keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error enviando capítulo: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Error al enviar el capítulo: {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )

@check_channel_membership
async def imdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Descarga y envía información de una película/serie desde un enlace de IMDb."""
    if not update.message:
        return
    
    # Verificar si el usuario proporcionó un enlace
    if not context.args:
        await update.message.reply_text(
            "Por favor, proporciona un enlace de IMDb.\n"
            "Ejemplo: /imdb https://www.imdb.com/title/tt14513804/",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Obtener el enlace
    imdb_url = context.args[0]
    
    # Mostrar acción de escribiendo mientras se procesa
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )
    
    # Verificar que es un enlace de IMDb válido
    if not re.match(r'https?://(www\.)?imdb\.com/title/tt\d+/?.*', imdb_url):
        await update.message.reply_text(
            "❌ El enlace proporcionado no es un enlace válido de IMDb.\n"
            "Debe tener el formato: https://www.imdb.com/title/tt??????/",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Extraer el ID de IMDb del enlace
    imdb_id = re.search(r'tt\d+', imdb_url).group(0)
    
    try:
        # Enviar mensaje de procesamiento
        processing_msg = await update.message.reply_text(
            "🔍 Procesando información de IMDb... Por favor espera.",
            parse_mode=ParseMode.HTML
        )
        
        # Método 1: Usar IMDbPY para obtener información
        try:
            # Obtener la película/serie por ID
            movie = ia.get_movie(imdb_id[2:])  # Eliminar 'tt' del ID
            
            # Extraer información básica
            title = movie.get('title', 'Título no disponible')
            year = movie.get('year', 'Año no disponible')
            rating = movie.get('rating', 'N/A')
            genres = ', '.join(movie.get('genres', ['Género no disponible']))
            plot = movie.get('plot outline', 'Sinopsis no disponible')
            
            # Obtener directores
            directors = []
            if 'directors' in movie:
                directors = [director['name'] for director in movie['directors'][:3]]
            directors_str = ', '.join(directors) if directors else 'No disponible'
            
            # Obtener actores principales
            cast = []
            if 'cast' in movie:
                cast = [actor['name'] for actor in movie['cast'][:5]]
            cast_str = ', '.join(cast) if cast else 'No disponible'
            
            # Construir mensaje
            message = (
                f"🎬 <b>{title}</b> ({year})\n\n"
                f"⭐ <b>Calificación:</b> {rating}/10\n"
                f"🎭 <b>Género:</b> {genres}\n"
                f"🎬 <b>Director:</b> {directors_str}\n"
                f"👥 <b>Reparto principal:</b> {cast_str}\n\n"
                f"📝 <b>Sinopsis:</b>\n<blockquote>{plot}</blockquote>\n\n"
                f"🔗 <a href='{imdb_url}'>Ver en IMDb</a>"
            )
            
            # Obtener URL del póster si está disponible
            poster_url = None
            if 'cover url' in movie:
                poster_url = movie['cover url']
            
        except Exception as e:
            logger.error(f"Error usando IMDbPY: {e}")
            
            # Si falla IMDbPY, usar web scraping como método alternativo
            try:
                # Realizar la solicitud HTTP
                response = requests.get(imdb_url, headers={'User-Agent': 'Mozilla/5.0'})
                response.raise_for_status()  # Verificar que la solicitud fue exitosa
                
                # Parsear el HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extraer información básica
                title_elem = soup.select_one('h1')
                title = title_elem.text.strip() if title_elem else 'Título no disponible'
                
                # Intentar obtener el año
                year_elem = soup.select_one('span.TitleBlockMetaData__ListItemText-sc-12ein40-2')
                year = year_elem.text.strip() if year_elem else 'Año no disponible'
                
                # Intentar obtener la calificación
                rating_elem = soup.select_one('span.AggregateRatingButton__RatingScore-sc-1ll29m0-1')
                rating = rating_elem.text.strip() if rating_elem else 'N/A'
                
                # Intentar obtener géneros
                genres_elems = soup.select('span.ipc-chip__text')
                genres = ', '.join([genre.text for genre in genres_elems[:3]]) if genres_elems else 'Género no disponible'
                
                # Intentar obtener la sinopsis
                plot_elem = soup.select_one('span.GenresAndPlot__TextContainerBreakpointXL-sc-cum89p-2')
                plot = plot_elem.text.strip() if plot_elem else 'Sinopsis no disponible'
                
                # Intentar obtener directores y reparto
                credits_elems = soup.select('a.StyledComponents__ActorName-sc-y9ygcu-1')
                cast_str = ', '.join([actor.text for actor in credits_elems[:5]]) if credits_elems else 'No disponible'
                
                # Construir mensaje
                message = (
                    f"🎬 <b>{title}</b> ({year})\n\n"
                    f"⭐ <b>Calificación:</b> {rating}/10\n"
                    f"🎭 <b>Género:</b> {genres}\n"
                    f"👥 <b>Reparto:</b> {cast_str}\n\n"
                    f"📝 <b>Sinopsis:</b>\n{plot}\n\n"
                    f"🔗 <a href='{imdb_url}'>Ver en IMDb</a>"
                )
                
                # Intentar obtener la URL del póster
                poster_elem = soup.select_one('img.ipc-image')
                poster_url = poster_elem['src'] if poster_elem and 'src' in poster_elem.attrs else None
                
            except Exception as scrape_error:
                logger.error(f"Error en web scraping: {scrape_error}")
                await processing_msg.edit_text(
                    f"❌ Error al obtener información de IMDb: {str(e)[:100]}\n\n"
                    f"Por favor, verifica que el enlace sea correcto y que IMDb esté accesible.",
                    parse_mode=ParseMode.HTML
                )
                return
        
        # Enviar mensaje y póster si está disponible
        if poster_url:
            try:
                # Descargar imagen del póster
                poster_response = requests.get(poster_url)
                poster_response.raise_for_status()
                
                # Enviar la imagen con la información como pie de foto
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=BytesIO(poster_response.content),
                    caption=message,
                    parse_mode=ParseMode.HTML
                )
                
                # Eliminar mensaje de procesamiento
                await processing_msg.delete()
                
            except Exception as img_error:
                logger.error(f"Error enviando imagen: {img_error}")
                # Si falla el envío de la imagen, enviar solo el texto
                await processing_msg.edit_text(
                    text=message,
                    parse_mode=ParseMode.HTML
                )
        else:
            # Si no hay póster, enviar solo el texto
            await processing_msg.edit_text(
                text=message,
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Error en comando imdb: {e}")
        await processing_msg.edit_text(
            f"❌ Error al procesar la información de IMDb: {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )

async def a_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para administradores para añadir series con múltiples temporadas"""
    # Verificar que el usuario es administrador
    user = update.effective_user
    if not user:
        return
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
    
    # Obtener el estado actual
    multi_state = context.user_data.get('multi_state', MULTI_SEASONS_STATE_IDLE)
    
    # Si estamos en estado IDLE, iniciar el proceso pidiendo el nombre de la serie
    if multi_state == MULTI_SEASONS_STATE_IDLE:
        # Verificar si el usuario proporcionó un nombre para la serie
        if not context.args:
            await update.message.reply_text(
                "Uso: /a nombre_de_la_serie\n"
                "Ejemplo: /a La que se avecina",
                parse_mode=ParseMode.HTML
            )
            return
            
        # Tomar el nombre de la serie de los argumentos
        series_name = " ".join(context.args)
        
        # Inicializar estructura de datos para la serie multi-temporada
        context.user_data['multi_seasons'] = {
            'series_name': series_name,
            'seasons': {},
            'current_season': None,
            'cover': None,
            'description': None
        }
        
        # Cambiar al estado de espera de nombre de la primera temporada
        context.user_data['multi_state'] = MULTI_SEASONS_STATE_NEW_SEASON
        
        await update.message.reply_text(
            f"📺 <b>Modo de carga de serie multi-temporada activado</b>\n\n"
            f"Serie: <b>{series_name}</b>\n\n"
            f"<blockquote>"
            f"1️⃣ Ahora envía el nombre de la primera temporada (ej: 'La que se avecina: Temporada 1')\n"
            f"2️⃣ Luego envía todos los capítulos de esa temporada\n"
            f"3️⃣ Para añadir otra temporada, envía nuevamente el comando /a seguido del nombre de la siguiente temporada\n"
            f"4️⃣ Cuando hayas terminado de enviar todas las temporadas, envía una imagen con la descripción\n"
            f"5️⃣ El bot procesará todo automáticamente\n"
            f"</blockquote>\n"
            f"Para cancelar el proceso, envía /cancelmulti",
            parse_mode=ParseMode.HTML
        )
    
    # Si estamos en estado recibiendo capítulos, significa que queremos añadir nueva temporada
    elif multi_state == MULTI_SEASONS_STATE_RECEIVING:
        # Verificar si el usuario proporcionó un nombre para la nueva temporada
        if not context.args:
            await update.message.reply_text(
                "Uso: /a nombre_de_la_temporada\n"
                "Ejemplo: /a La que se avecina: Temporada 2",
                parse_mode=ParseMode.HTML
            )
            return
            
        # Tomar el nombre de la temporada de los argumentos
        season_name = " ".join(context.args)
        
        # Guardar la temporada actual y prepararla para la nueva
        context.user_data['multi_state'] = MULTI_SEASONS_STATE_RECEIVING
        context.user_data['multi_seasons']['current_season'] = season_name
        
        # Inicializar lista de capítulos para esta temporada
        if season_name not in context.user_data['multi_seasons']['seasons']:
            context.user_data['multi_seasons']['seasons'][season_name] = []
        
        await update.message.reply_text(
            f"✅ <b>Nueva temporada iniciada:</b> {season_name}\n\n"
            f"<blockquote>"
            f"Ahora envía todos los capítulos de esta temporada en orden.\n"
            f"Cuando termines con esta temporada, envía nuevamente /a con el nombre de la siguiente temporada\n"
            f"o envía una imagen con descripción para finalizar la carga completa.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    
    # Si estamos en estado espera de nombre de nueva temporada
    elif multi_state == MULTI_SEASONS_STATE_NEW_SEASON:
        # Verificar si el usuario proporcionó un nombre para la temporada
        if not context.args:
            await update.message.reply_text(
                "Uso: /a nombre_de_la_temporada\n"
                "Ejemplo: /a La que se avecina: Temporada 1",
                parse_mode=ParseMode.HTML
            )
            return
            
        # Tomar el nombre de la temporada de los argumentos
        season_name = " ".join(context.args)
        
        # Guardar la temporada actual
        context.user_data['multi_state'] = MULTI_SEASONS_STATE_RECEIVING
        context.user_data['multi_seasons']['current_season'] = season_name
        
        # Inicializar lista de capítulos para esta temporada
        if season_name not in context.user_data['multi_seasons']['seasons']:
            context.user_data['multi_seasons']['seasons'][season_name] = []
        
        await update.message.reply_text(
            f"✅ <b>Temporada iniciada:</b> {season_name}\n\n"
            f"<blockquote>"
            f"Ahora envía todos los capítulos de esta temporada en orden.\n"
            f"Cuando termines con esta temporada, envía nuevamente /a con el nombre de la siguiente temporada\n"
            f"o envía una imagen con descripción para finalizar la carga completa.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    
    # Si estamos esperando la portada y ya la tenemos, finalizar
    elif multi_state == MULTI_SEASONS_STATE_COVER and context.user_data.get('multi_seasons', {}).get('cover'):
        await finalize_multi_seasons_upload(update, context)

async def cancel_multi_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancelar el proceso de carga de serie con múltiples temporadas"""
    # Verificar que el usuario es administrador
    user = update.effective_user
    if not user:
        return
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
    
    # Reiniciar el estado
    context.user_data['multi_state'] = MULTI_SEASONS_STATE_IDLE
    context.user_data.pop('multi_seasons', None)
    
    await update.message.reply_text(
        "<blockquote>❌ Proceso de carga de serie multi-temporada cancelado.\n\n"
        "Todos los datos temporales han sido eliminados.</blockquote>",
        parse_mode=ParseMode.HTML
    )

async def handle_multi_seasons_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar la recepción de capítulos y portada durante el proceso de carga de series multi-temporada"""
    # Verificar que update y effective_user no sean None
    if not update or not update.effective_user:
        return
        
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if user.id not in ADMIN_IDS:
        return
    
    # Verificar si estamos en modo de carga de series multi-temporada
    multi_state = context.user_data.get('multi_state', MULTI_SEASONS_STATE_IDLE)
    if multi_state == MULTI_SEASONS_STATE_IDLE:
        return  # No estamos en modo de carga de series multi-temporada
    
    # Si recibimos un mensaje con foto y estamos en modo de espera de capítulos o nueva temporada,
    # asumimos que es la portada final y cambiamos al estado final
    if update.message.photo and (multi_state == MULTI_SEASONS_STATE_RECEIVING or multi_state == MULTI_SEASONS_STATE_NEW_SEASON):
        # Cambiar al estado de espera de portada
        context.user_data['multi_state'] = MULTI_SEASONS_STATE_COVER
        
        # Guardar la portada y descripción
        context.user_data['multi_seasons']['cover'] = update.message.photo[-1].file_id
        context.user_data['multi_seasons']['description'] = update.message.caption or ""
        
        # Verificar si hay temporadas con capítulos
        seasons = context.user_data.get('multi_seasons', {}).get('seasons', {})
        valid_seasons = {name: chapters for name, chapters in seasons.items() if chapters}
        
        if not valid_seasons:
            await update.message.reply_text(
                "<blockquote>⚠️ No se ha recibido ningún capítulo para ninguna temporada.\n\n"
                "No se puede finalizar la carga sin capítulos.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return
        
        await update.message.reply_text(
            f"<blockquote>✅ Portada recibida correctamente.\n\n"
            f"Temporadas detectadas: {len(valid_seasons)}\n"
            f"Procesando la subida de la serie completa...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Finalizar la subida automáticamente
        await finalize_multi_seasons_upload(update, context)
        return
    
    # Si estamos en modo de recepción y recibimos un video/documento, es un capítulo
    if (update.message.video or update.message.document) and multi_state == MULTI_SEASONS_STATE_RECEIVING:
        # Verificar que tenemos una temporada actual seleccionada
        current_season = context.user_data.get('multi_seasons', {}).get('current_season')
        if not current_season:
            await update.message.reply_text(
                "<blockquote>⚠️ Error: No hay una temporada seleccionada actualmente.\n\n"
                "Envía primero '/a Nombre de la temporada' para seleccionar una temporada.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Obtener información del capítulo
        message_id = update.message.message_id
        chat_id = update.effective_chat.id
        original_caption = update.message.caption or ""
        file_name = update.message.document.file_name if update.message.document else None
        
        # Intentar extraer número de capítulo del nombre o caption
        episode_num = len(context.user_data['multi_seasons']['seasons'][current_season]) + 1
        caption_or_filename = original_caption or file_name or ""
        
        # Buscar patrón como Exx, Episodio xx, Capítulo xx
        episode_pattern = re.search(r'[Ee](\d+)|[Ee]pisod[ei]o\s*(\d+)|[Cc]ap[ií]tulo\s*(\d+)', caption_or_filename)
        if episode_pattern:
            # Usar el primer grupo que tenga valor
            for group in episode_pattern.groups():
                if group:
                    try:
                        episode_num = int(group)
                        break
                    except ValueError:
                        pass
        
        # Crear nuevo caption si es necesario
        if not original_caption or "Capítulo" not in original_caption:
            new_caption = f"{current_season} - Capítulo {episode_num}"
            
            # Reenviar el archivo con el nuevo caption
            try:
                if update.message.video:
                    file_id = update.message.video.file_id
                    # Borrar el mensaje original
                    await context.bot.delete_message(
                        chat_id=chat_id, 
                        message_id=message_id
                    )
                    # Enviar un nuevo mensaje con el caption correcto
                    new_message = await context.bot.send_video(
                        chat_id=chat_id,
                        video=file_id,
                        caption=new_caption
                    )
                    # Actualizar el message_id para guardarlo correctamente
                    message_id = new_message.message_id
                    caption = new_caption
                elif update.message.document:
                    file_id = update.message.document.file_id
                    # Borrar el mensaje original
                    await context.bot.delete_message(
                        chat_id=chat_id, 
                        message_id=message_id
                    )
                    # Enviar un nuevo mensaje con el caption correcto
                    new_message = await context.bot.send_document(
                        chat_id=chat_id,
                        document=file_id,
                        caption=new_caption
                    )
                    # Actualizar el message_id para guardarlo correctamente
                    message_id = new_message.message_id
                    caption = new_caption
            except Exception as e:
                logger.error(f"Error al reenviar con nuevo caption: {e}")
                caption = original_caption
        else:
            caption = original_caption
        
        # Guardar el capítulo con todos los datos
        episode_data = {
            'message_id': message_id,
            'episode_number': episode_num,
            'chat_id': chat_id,
            'caption': caption,
            'file_name': file_name
        }
        
        # Añadir a la lista de episodios de la temporada actual
        context.user_data['multi_seasons']['seasons'][current_season].append(episode_data)
        
        # Confirmar la recepción del capítulo
        await update.message.reply_text(
            f"<blockquote>✅ Capítulo {episode_num} recibido y guardado para <b>{current_season}</b>.\n"
            f"Total de capítulos en esta temporada: {len(context.user_data['multi_seasons']['seasons'][current_season])}</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def finalize_multi_seasons_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, status_message=None) -> None:
    """Finalizar el proceso de carga y subir la serie con múltiples temporadas a los canales"""
    # Obtener datos de la serie
    multi_seasons = context.user_data.get('multi_seasons', {})
    series_name = multi_seasons.get('series_name', 'Serie sin nombre')
    seasons = multi_seasons.get('seasons', {})
    cover_photo = multi_seasons.get('cover')
    description = multi_seasons.get('description', "")
    
    # Verificar que tenemos todos los datos necesarios
    valid_seasons = {name: chapters for name, chapters in seasons.items() if chapters}
    if not valid_seasons or not cover_photo:
        error_msg = "❌ No hay suficientes datos para subir la serie."
        if not valid_seasons:
            error_msg += " No hay temporadas con capítulos."
        if not cover_photo:
            error_msg += " No hay portada."
        
        if status_message:
            await status_message.edit_text(f"<blockquote>{error_msg}</blockquote>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(f"<blockquote>{error_msg}</blockquote>", parse_mode=ParseMode.HTML)
        return
    
    # Crear un mensaje de estado si no existe
    if not status_message:
        status_message = await update.message.reply_text(
            f"<blockquote>⏳ Procesando la serie <b>{series_name}</b> con {len(valid_seasons)} temporadas...</blockquote>",
            parse_mode=ParseMode.HTML
        )
    
    # Crear un diccionario para almacenar estadísticas de la subida
    upload_stats = {
        "total_seasons": len(valid_seasons),
        "total_episodes": sum(len(eps) for eps in valid_seasons.values()),
        "uploaded_episodes": 0,
        "failed_episodes": 0,
        "seasons_data": {}
    }
    
    try:
        # 1. Crear un identificador único para esta serie multi-temporada
        series_id = int(time.time())
        
        # 2. Formatear la descripción adecuadamente
        content_type_header = "<blockquote>Serie 🎥</blockquote>\n"

        # Verificar si hay información que procesar
        if not description:
            # Crear una descripción básica con el nombre de la serie
            description = f"{content_type_header}{series_name} ✓\n\n"
            description += f"📝 Sinopsis:\n<blockquote expandable>Información no disponible</blockquote>\n\n"
            description += f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
        else:
            # Si ya hay una descripción, asegurarse de que siga el formato correcto
            if content_type_header not in description:
                # Extraer el título si existe o usar el nombre de la serie
                title_match = re.search(r'<b>(.*?)</b>', description)
                title = title_match.group(1) if title_match else series_name
                
                # Reconstruir la descripción con el formato correcto
                english_title = ""
                if "original_title" in description or "Nombre en inglés" in description:
                    english_match = re.search(r'Nombre en inglés (.*?)✓', description)
                    if english_match:
                        english_title = f"{english_match.group(1)}✓\n"
                
                # Extraer la sinopsis si existe
                synopsis = "Información no disponible"
                synopsis_match = re.search(r'Sinopsis:(.*?)(?:\n\n|\Z)', description, re.DOTALL)
                if synopsis_match:
                    synopsis = synopsis_match.group(1).strip()
                
                # Reconstruir la descripción completamente
                new_description = (
                    f"{content_type_header}"
                    f"{title} ✓\n"
                    f"{english_title}\n"
                )
                
                # Copiar el resto de la información (año, calificación, etc.)
                fields = [
                    ('📅 Año:', r'📅 Año: (.*?)(?:\n)'),
                    ('⭐ Calificación:', r'⭐ Calificación: (.*?)(?:\n)'),
                    ('🎭 Género:', r'🎭 Género: (.*?)(?:\n)'),
                    ('🎬 Director:', r'🎬 Director: (.*?)(?:\n)'),
                    ('👥 Reparto:', r'👥 Reparto: (.*?)(?:\n)'),
                    ('📺 Estado:', r'📺 Estado: (.*?)(?:\n)'),
                    ('🔢', r'🔢 (.*?)(?:\n)')
                ]
                
                for prefix, pattern in fields:
                    match = re.search(pattern, description)
                    if match:
                        if prefix == '🔢':
                            new_description += f"🔢 {match.group(1)}\n"
                        else:
                            new_description += f"{prefix} {match.group(1)}\n"
                
                # Añadir la sinopsis en formato expandible
                new_description += f"\n📝 Sinopsis:\n<blockquote expandable>{synopsis}</blockquote>\n\n"
                
                # Añadir la marca de agua
                new_description += f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
                
                description = new_description
        
        # 3. Subir la portada al canal de búsqueda
        await status_message.edit_text(
            f"<blockquote>⏳ Subiendo portada de <b>{series_name}</b> al canal de búsqueda...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Intentar subir la portada hasta 3 veces
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            try:
                sent_cover = await context.bot.send_photo(
                    chat_id=SEARCH_CHANNEL_ID,
                    photo=cover_photo,
                    caption=description,
                    parse_mode=ParseMode.HTML
                )
                search_channel_cover_id = sent_cover.message_id
                break
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    await status_message.edit_text(
                        f"<blockquote>❌ Error al subir la portada al canal de búsqueda después de {max_retries} intentos: {str(e)[:100]}</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    return
                await asyncio.sleep(3)  # Esperar 3 segundos antes de reintentar
        
        # 4. Generar URL para el botón "Ver ahora"
        view_url = f"https://t.me/MultimediaTVbot?start=multiseries_{series_id}"
        
        # 5. Crear un botón para la portada
        keyboard = [
            [InlineKeyboardButton("Ver ahora", url=view_url)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 6. Actualizar la portada en el canal de búsqueda con el botón
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=SEARCH_CHANNEL_ID,
                message_id=search_channel_cover_id,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error al añadir botón a la portada: {e}")
        
        # 7. Guardar la serie principal en la base de datos
        try:
            db.add_multi_series(
                series_id,
                series_name,
                description,
                search_channel_cover_id,
                update.effective_user.id
            )
        except Exception as db_error:
            logger.error(f"Error guardando serie en la base de datos: {db_error}")
            # Continuar a pesar del error
        
        # 8. Procesar y subir cada temporada y sus capítulos
        season_data = {}  # Para almacenar la información estructurada
        
        # **AQUÍ ESTÁ EL CÓDIGO REEMPLAZADO**
        for season_idx, (season_name, episodes) in enumerate(valid_seasons.items(), 1):
            await status_message.edit_text(
                f"<blockquote>⏳ Procesando temporada <b>{season_name}</b>...</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            # Generar un ID único para la temporada usando índice garantizado único
            # Formato: series_id + número secuencial de 3 dígitos (001, 002, etc.)
            season_id = int(f"{series_id}{season_idx:03d}")
            
            logger.info(f"Generando ID para temporada {season_name}: {season_id}")
            
            # Guardar la temporada en la base de datos con manejo explícito de errores
            try:
                db.add_season(season_id, series_id, season_name)
                logger.info(f"Temporada guardada en DB: {season_id} - {season_name}")
            except Exception as season_db_error:
                logger.error(f"Error guardando temporada {season_name} (ID: {season_id}) en la base de datos: {season_db_error}")
                await status_message.edit_text(
                    f"<blockquote>⚠️ Error al guardar temporada {season_name} en la base de datos. Intentando continuar...</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                await asyncio.sleep(2)
            
            season_data[season_name] = []
            upload_stats["seasons_data"][season_name] = {
                "total": len(episodes),
                "uploaded": 0,
                "failed": 0
            }
            
            # Subir los capítulos de esta temporada en grupos más pequeños para evitar problemas
            episode_groups = [episodes[i:i+3] for i in range(0, len(episodes), 3)]
            
            for group_index, group in enumerate(episode_groups):
                await status_message.edit_text(
                    f"<blockquote>⏳ Subiendo capítulos de <b>{season_name}</b>... ({group_index*3+1}-{min((group_index+1)*3, len(episodes))}/{len(episodes)})</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                
                for episode in group:
                    # Enviar cada capítulo al canal de búsqueda con reintentos
                    retry_count = 0
                    uploaded = False
                    
                    while retry_count < max_retries and not uploaded:
                        try:
                            original_message = await context.bot.copy_message(
                                chat_id=SEARCH_CHANNEL_ID,
                                from_chat_id=episode['chat_id'],
                                message_id=episode['message_id'],
                                disable_notification=True
                            )
                            
                            # Guardar el episodio en la base de datos
                            try:
                                db.add_season_episode(
                                    season_id, 
                                    episode['episode_number'], 
                                    original_message.message_id
                                )
                            except Exception as ep_db_error:
                                logger.error(f"Error guardando episodio en la base de datos: {ep_db_error}")
                            
                            # Guardar la información del capítulo subido
                            season_data[season_name].append({
                                'message_id': original_message.message_id,
                                'episode_number': episode['episode_number']
                            })
                            
                            upload_stats["uploaded_episodes"] += 1
                            upload_stats["seasons_data"][season_name]["uploaded"] += 1
                            uploaded = True
                            
                        except Exception as e:
                            retry_count += 1
                            logger.error(f"Error copiando episodio {episode['episode_number']} al canal de búsqueda (intento {retry_count}/{max_retries}): {e}")
                            
                            if retry_count >= max_retries:
                                upload_stats["failed_episodes"] += 1
                                upload_stats["seasons_data"][season_name]["failed"] += 1
                                await status_message.edit_text(
                                    f"<blockquote>⚠️ Error al subir capítulo {episode['episode_number']} de {season_name} después de {max_retries} intentos. Continuando con el siguiente...</blockquote>",
                                    parse_mode=ParseMode.HTML
                                )
                                await asyncio.sleep(2)
                            else:
                                # Esperar más tiempo entre reintentos
                                await asyncio.sleep(5)
                    
                    # Esperar más tiempo entre capítulos para evitar rate limiting
                    await asyncio.sleep(2)
                
                # Esperar más tiempo entre grupos de capítulos
                await asyncio.sleep(3)
        
        # 9. Subir portada al canal principal
        await status_message.edit_text(
            f"<blockquote>⏳ Subiendo portada al canal principal...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        try:
            sent_cover_main = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=cover_photo,
                caption=description,
                parse_mode=ParseMode.HTML
            )
            
            # Actualizar la portada en el canal principal con el botón
            await context.bot.edit_message_reply_markup(
                chat_id=CHANNEL_ID,
                message_id=sent_cover_main.message_id,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error enviando portada al canal principal: {e}")
            await status_message.edit_text(
                f"<blockquote>⚠️ Error al enviar portada al canal principal, pero la serie ya está en el canal de búsqueda.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(2)
        
        # 10. Verificar integridad de la subida
        actual_uploaded_episodes = sum(len(episodes) for episodes in season_data.values())
        if actual_uploaded_episodes < upload_stats["total_episodes"]:
            # Hay discrepancia entre lo que se intentó subir y lo que realmente se subió
            logger.warning(f"Discrepancia en episodios subidos: {actual_uploaded_episodes} de {upload_stats['total_episodes']}")
        
        # 11. Reiniciar el estado
        context.user_data['multi_state'] = MULTI_SEASONS_STATE_IDLE
        context.user_data.pop('multi_seasons', None)
        
        # 12. Informar al administrador del éxito con detalles sobre posibles fallos
        success_message = f"<blockquote>✅ Serie <b>{series_name}</b> completada\n\n"
        success_message += f"📊 Detalles:\n"
        success_message += f"- Temporadas: {upload_stats['total_seasons']}\n"
        success_message += f"- Total de capítulos: {actual_uploaded_episodes}/{upload_stats['total_episodes']}\n"
        
        # Añadir detalles por temporada
        for season_name, stats in upload_stats["seasons_data"].items():
            success_message += f"  - {season_name}: {stats['uploaded']}/{stats['total']} capítulos subidos\n"
        
        if upload_stats["failed_episodes"] > 0:
            success_message += f"⚠️ {upload_stats['failed_episodes']} capítulos no pudieron ser subidos\n"
        
        success_message += f"- Subida a canal principal: ✓\n"
        success_message += f"- Subida a canal de búsqueda: ✓\n"
        success_message += f"- ID de la serie: {series_id}\n\n"
        success_message += f"Los usuarios pueden acceder a través del botón 'Ver ahora'.</blockquote>"
        
        await status_message.edit_text(success_message, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error en finalize_multi_seasons_upload: {e}")
        await status_message.edit_text(
            f"<blockquote>❌ Error al procesar la serie: {str(e)[:100]}</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def handle_multi_series_request(update: Update, context: ContextTypes.DEFAULT_TYPE, series_id: int) -> None:
    """Manejar la solicitud de visualización de una serie con múltiples temporadas"""
    try:
        # Convertir series_id a int y registrar para debug
        series_id = int(series_id)
        logger.info(f"Procesando solicitud para series_id: {series_id}")

        # Obtener datos de la serie multi-temporada
        series = db.get_multi_series(series_id)
        if not series:
            await update.message.reply_text(
                "❌ Serie no encontrada. Es posible que haya sido eliminada.",
                parse_mode=ParseMode.HTML
            )
            return

        # Obtener todas las temporadas directamente de la base de datos
        seasons_cursor = db.db.seasons.find({'series_id': series_id})
        all_seasons = list(seasons_cursor)
        
        # Debug: mostrar todas las temporadas encontradas
        logger.info(f"Total de temporadas encontradas en DB: {len(all_seasons)}")
        for season in all_seasons:
            logger.info(f"Temporada encontrada: ID={season['season_id']}, Nombre={season['season_name']}")

        if not all_seasons:
            await update.message.reply_text(
                f"❌ Esta serie no tiene temporadas disponibles.",
                parse_mode=ParseMode.HTML
            )
            return

        # Obtener episodios para cada temporada y filtrar las que tienen episodios
        seasons_with_episodes = []
        for season in all_seasons:
            season_id = season['season_id']
            episodes = list(db.db.season_episodes.find({'season_id': season_id}))
            if episodes:
                season['episode_count'] = len(episodes)
                seasons_with_episodes.append(season)
                logger.info(f"Temporada {season['season_name']}: {len(episodes)} episodios")

        if not seasons_with_episodes:
            await update.message.reply_text(
                "❌ No se encontraron capítulos para ninguna temporada.",
                parse_mode=ParseMode.HTML
            )
            return

        # Ordenar temporadas numéricamente
        for season in seasons_with_episodes:
            try:
                # Intentar extraer el número de temporada del nombre
                match = re.search(r'temporada\s*(\d+)', season['season_name'].lower())
                if match:
                    season['sort_num'] = int(match.group(1))
                else:
                    season['sort_num'] = 999
            except Exception as e:
                logger.error(f"Error al extraer número de temporada: {e}")
                season['sort_num'] = 999

        # Ordenar por número de temporada
        seasons_with_episodes.sort(key=lambda x: x.get('sort_num', 999))

        # Enviar la portada
        cover_message_id = series['cover_message_id']
        await context.bot.copy_message(
            chat_id=update.effective_chat.id,
            from_chat_id=SEARCH_CHANNEL_ID,
            message_id=cover_message_id
        )

        # Crear botones para las temporadas
        keyboard = []
        for i in range(0, len(seasons_with_episodes), 2):
            row = []
            # Tomar hasta 2 temporadas para cada fila
            slice_end = min(i + 2, len(seasons_with_episodes))
            for season in seasons_with_episodes[i:slice_end]:
                button_text = f"{season['season_name']} ({season.get('episode_count', 0)} caps)"
                row.append(
                    InlineKeyboardButton(
                        text=button_text,
                        callback_data=f"season_{season['season_id']}"
                    )
                )
            keyboard.append(row)

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Enviar mensaje con botones
        await update.message.reply_text(
            f"📺 <b>{series['title']}</b>\n\n"
            f"Se encontraron {len(seasons_with_episodes)} temporadas disponibles.\n"
            f"Selecciona una temporada para ver sus capítulos:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Error en handle_multi_series_request: {e}")
        await update.message.reply_text(
            "❌ Error al mostrar las temporadas. Por favor, intenta más tarde.",
            parse_mode=ParseMode.HTML
        )
        
async def handle_season_selection(query, context, season_id):
    """Manejar la selección de una temporada"""
    user_id = query.from_user.id
    
    await query.answer("Cargando capítulos...")
    
    try:
        # Obtener información de la temporada
        season = db.get_season(season_id)
        
        if not season:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Temporada no encontrada.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Obtener capítulos de la temporada
        episodes = db.get_season_episodes(season_id)
        
        if not episodes:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Esta temporada no tiene capítulos disponibles.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Obtener el series_id para el botón de volver
        series_id = season['series_id']
        
        # Crear botones para los capítulos
        keyboard = []
        
        # Añadir botones para cada capítulo, organizados en filas de 3
        for i in range(0, len(episodes), 3):
            row = []
            for j in range(i, min(i + 3, len(episodes))):
                episode = episodes[j]
                row.append(
                    InlineKeyboardButton(
                        f"Capítulo {episode['episode_number']}",
                        callback_data=f"multi_ep_{episode['message_id']}"
                    )
                )
            keyboard.append(row)
        
        # Añadir botón para enviar todos los capítulos
        keyboard.append([
            InlineKeyboardButton(
                "Enviar todos los capítulos",
                callback_data=f"multi_ep_all_{season_id}"
            )
        ])
        
        # Añadir botón para volver a la lista de temporadas
        keyboard.append([
            InlineKeyboardButton(
                "Volver a temporadas ↩️",
                callback_data=f"back_to_seasons_{series_id}"
            )
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Enviar mensaje con botones
        await query.edit_message_text(
            f"📺 <b>{season['season_name']}</b>\n\n"
            f"Selecciona un capítulo para ver o solicita todos los capítulos:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error en handle_season_selection: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Error al mostrar los capítulos: {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )

async def handle_back_to_seasons(query, context, series_id):
    """Manejar el botón de volver a las temporadas"""
    await query.answer("Volviendo a temporadas...")
    
    try:
        # Obtener datos de la serie
        series = db.get_multi_series(series_id)
        
        if not series:
            await query.edit_message_text(
                "❌ Serie no encontrada.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Obtener las temporadas de la serie
        seasons = db.get_seasons(series_id)
        
        if not seasons:
            await query.edit_message_text(
                "❌ Esta serie no tiene temporadas disponibles.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Crear botones para las temporadas
        keyboard = []
        
        # Añadir un botón para cada temporada, organizados en filas de 2
        for i in range(0, len(seasons), 2):
            row = []
            for j in range(i, min(i + 2, len(seasons))):
                season = seasons[j]
                row.append(
                    InlineKeyboardButton(
                        f"{season['season_name']}",
                        callback_data=f"season_{season['season_id']}"
                    )
                )
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Editar mensaje con botones
        await query.edit_message_text(
            f"📺 <b>{series['title']}</b>\n\n"
            f"Selecciona una temporada para ver sus capítulos:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error en handle_back_to_seasons: {e}")
        await query.edit_message_text(
            f"❌ Error al mostrar las temporadas: {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )

async def send_multi_episode(query, context, message_id):
    """Enviar un capítulo específico de una serie multi-temporada"""
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    can_forward = user_data and user_data.get('can_forward', False)
    
    await query.answer("Procesando tu solicitud...")
    
    # Mostrar acción de escribiendo
    await context.bot.send_chat_action(
        chat_id=query.message.chat_id,
        action=ChatAction.TYPING
    )
    
    try:
        # Enviar el capítulo
        await context.bot.copy_message(
            chat_id=query.message.chat_id,
            from_chat_id=SEARCH_CHANNEL_ID,
            message_id=message_id,
            protect_content=not can_forward  # Proteger según el plan
        )
        
        # Marcar el botón como seleccionado
        keyboard = query.message.reply_markup.inline_keyboard
        new_keyboard = []
        
        for row in keyboard:
            new_row = []
            for button in row:
                if button.callback_data == query.data:
                    # Marcar este botón como seleccionado
                    new_row.append(InlineKeyboardButton(
                        f"✅ {button.text}",
                        callback_data=button.callback_data
                    ))
                else:
                    new_row.append(button)
            new_keyboard.append(new_row)
        
        # Actualizar el mensaje con el nuevo teclado
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(new_keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error enviando capítulo multi-serie: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Error al enviar el capítulo: {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )

async def send_all_multi_episodes(query, context, season_id):
    """Enviar todos los capítulos de una temporada"""
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    can_forward = user_data and user_data.get('can_forward', False)
    
    await query.answer("Enviando todos los capítulos...")
    
    # Mostrar acción de escribiendo
    await context.bot.send_chat_action(
        chat_id=query.message.chat_id,
        action=ChatAction.TYPING
    )
    
    try:
        # Obtener todos los capítulos de la temporada
        episodes = db.get_season_episodes(season_id)
        
        if not episodes:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ No se encontraron capítulos para esta temporada.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Obtener el nombre de la temporada
        season = db.get_season(season_id)
        season_name = season['season_name'] if season else "Temporada"
        
        # Enviar mensaje de inicio
        status_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"⏳ Enviando {len(episodes)} capítulos de <b>{season_name}</b>... Por favor, espera.",
            parse_mode=ParseMode.HTML
        )
        
        # Enviar cada capítulo
        for i, episode in enumerate(episodes):
            try:
                # Actualizar estado periódicamente
                if i % 5 == 0 and i > 0:
                    await status_message.edit_text(
                        f"⏳ Enviando capítulos... ({i}/{len(episodes)})",
                        parse_mode=ParseMode.HTML
                    )
                
                # Enviar capítulo
                await context.bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=SEARCH_CHANNEL_ID,
                    message_id=episode['message_id'],
                    protect_content=not can_forward,  # Proteger según el plan
                    disable_notification=(i < len(episodes) - 1)  # Solo notificar el último
                )
                
                # Pequeña pausa para no sobrecargar
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error enviando capítulo {i+1} de temporada multi-serie: {e}")
                continue
        
        # Actualizar mensaje de estado
        await status_message.edit_text(
            f"✅ Se han enviado todos los capítulos de <b>{season_name}</b> ({len(episodes)}).",
            parse_mode=ParseMode.HTML
        )
        
        # Marcar el botón como seleccionado
        keyboard = query.message.reply_markup.inline_keyboard
        new_keyboard = []
        
        for row in keyboard:
            new_row = []
            for button in row:
                if button.callback_data == query.data:
                    # Marcar este botón como seleccionado
                    new_row.append(InlineKeyboardButton(
                        f"✅ {button.text}",
                        callback_data=button.callback_data
                    ))
                else:
                    new_row.append(button)
            new_keyboard.append(new_row)
        
        # Actualizar el mensaje con el nuevo teclado
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(new_keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error general enviando todos los capítulos de temporada multi-serie: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Error al enviar los capítulos: {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para administradores para añadir contenido sin búsqueda en IMDb"""
    # Verificar que el usuario es administrador
    user = update.effective_user
    if not user:
        return
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
    
    # Obtener el estado actual
    add_state = context.user_data.get('add_state', ADD_STATE_IDLE)
    
    # Si estamos en estado IDLE, iniciar el proceso pidiendo el nombre
    if add_state == ADD_STATE_IDLE:
        # Inicializar o reiniciar la estructura de datos
        context.user_data['add_episodes'] = []
        context.user_data['add_state'] = ADD_STATE_NAME
        context.user_data['add_cover'] = None
        context.user_data['add_description'] = None
        context.user_data['add_title'] = None
        context.user_data['add_series_pattern'] = None
        
        await update.message.reply_text(
            "📺 <b>Modo de añadir contenido activado</b>\n\n"
            "<blockquote>"
            "1️⃣ Envía primero el nombre del contenido (ej: 'La que se avecina: Temporada 1')\n"
            "2️⃣ Luego envía todos los capítulos en orden\n"
            "3️⃣ El bot renombrará automáticamente los capítulos basándose en el primer nombre\n"
            "4️⃣ Cuando termines de enviar los capítulos, envía una imagen con descripción\n"
            "5️⃣ El bot procesará todo automáticamente\n"
            "</blockquote>\n"
            "Para cancelar el proceso, envía /canceladd",
            parse_mode=ParseMode.HTML
        )
    
    # Si estamos esperando capítulos y recibimos nuevamente /add, pasar al estado de espera de portada
    elif add_state == ADD_STATE_RECEIVING:
        episodes = context.user_data.get('add_episodes', [])
        if not episodes:
            await update.message.reply_text(
                "<blockquote>⚠️ No has enviado ningún capítulo todavía.\n\n"
                "Envía al menos un capítulo antes de continuar.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Cambiar al estado de espera de portada
        context.user_data['add_state'] = ADD_STATE_COVER
        
        await update.message.reply_text(
            "<blockquote>✅ Capítulos recibidos.\n\n"
            "Ahora envía una imagen para usar como portada con la descripción completa como pie de foto.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    
    # Si estamos esperando la portada y ya la tenemos, finalizar
    elif add_state == ADD_STATE_COVER and context.user_data.get('add_cover'):
        await finalize_add_upload(update, context)
    
    # Cualquier otro estado (no debería ocurrir)
    else:
        await update.message.reply_text(
            "<blockquote>❌ Error en el estado actual. Reinicia el proceso con /add.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['add_state'] = ADD_STATE_IDLE

async def cancel_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancelar el proceso de añadir contenido"""
    # Verificar que el usuario es administrador
    user = update.effective_user
    if not user:
        return
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
    
    # Reiniciar el estado
    context.user_data['add_state'] = ADD_STATE_IDLE
    context.user_data['add_episodes'] = []
    context.user_data['add_cover'] = None
    context.user_data['add_description'] = None
    context.user_data['add_title'] = None
    context.user_data['add_series_pattern'] = None
    
    await update.message.reply_text(
        "<blockquote>❌ Proceso de añadir contenido cancelado.\n\n"
        "Todos los datos temporales han sido eliminados.</blockquote>",
        parse_mode=ParseMode.HTML
    )

async def handle_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar recepción del nombre del contenido en el proceso de /add"""
    # Verificar que el usuario es administrador
    user = update.effective_user
    if not user:
        return
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
    
    # Verificar si estamos esperando el nombre del contenido
    add_state = context.user_data.get('add_state', ADD_STATE_IDLE)
    if add_state != ADD_STATE_NAME:
        return  # No estamos esperando el nombre
    
    # Obtener el nombre
    content_name = update.message.text.strip()
    
    # Guardar el título
    context.user_data['add_title'] = content_name
    
    # Detectar si el nombre tiene formato de serie (contiene "temporada", "season", etc.)
    is_series = re.search(r'temporada|season|t\d+|s\d+', content_name.lower()) is not None
    
    # Extraer nombre base para usar como patrón en los capítulos
    if is_series:
        # Intentar extraer el nombre base de la serie sin la parte de temporada
        base_match = re.search(r'(.+?)(?:\s*(?:temporada|season|t|s)\s*\d+)', content_name.lower())
        if base_match:
            base_name = base_match.group(1).strip()
        else:
            base_name = content_name
            
        # Intentar extraer el número de temporada
        season_match = re.search(r'(?:temporada|season|t|s)\s*(\d+)', content_name.lower())
        if season_match:
            season_num = int(season_match.group(1))
        else:
            season_num = 1
        
        # Guardar el patrón para los capítulos
        context.user_data['add_series_pattern'] = {
            'base_name': base_name,
            'season_num': season_num,
            'current_episode': 0,
            'is_series': True
        }
        
        await update.message.reply_text(
            f"<blockquote>✅ Nombre de serie registrado: <b>{content_name}</b>\n"
            f"Nombre base detectado: <b>{base_name}</b>\n"
            f"Temporada detectada: {season_num}\n\n"
            f"Los capítulos que envíes serán renombrados automáticamente siguiendo este patrón.\n"
            f"Ahora envía los capítulos en orden.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    else:
        # Es una película u otro contenido
        context.user_data['add_series_pattern'] = {
            'base_name': content_name,
            'is_series': False
        }
        
        await update.message.reply_text(
            f"<blockquote>✅ Nombre de contenido registrado: <b>{content_name}</b>\n\n"
            f"Ahora envía el archivo de la película o contenido.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    
    # Cambiar al estado de recibir capítulos/archivos
    context.user_data['add_state'] = ADD_STATE_RECEIVING

async def handle_add_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar la recepción de capítulos durante el proceso de /add"""
    # Verificar que el usuario es administrador
    user = update.effective_user
    if not user:
        return
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
    
    # Verificar si estamos en modo de añadir contenido
    add_state = context.user_data.get('add_state', ADD_STATE_IDLE)
    
    # Si recibimos un mensaje con foto y estamos en modo de espera de portada, es la portada
    if update.message.photo and add_state == ADD_STATE_COVER:
        # Guardar la portada y descripción
        context.user_data['add_cover'] = update.message.photo[-1].file_id
        context.user_data['add_description'] = update.message.caption or ""
        
        # Finalizar automáticamente el proceso
        await update.message.reply_text(
            "<blockquote>✅ Portada recibida correctamente.\n"
            "Procesando la subida del contenido...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Procesar la subida
        await finalize_add_upload(update, context)
        return
    
    # Si estamos en modo de recepción y recibimos un video/documento, es un capítulo
    if (update.message.video or update.message.document) and add_state == ADD_STATE_RECEIVING:
        # Obtener información del capítulo
        message_id = update.message.message_id
        chat_id = update.effective_chat.id
        original_caption = update.message.caption or ""
        file_name = update.message.document.file_name if update.message.document else None
        
        # Obtener el patrón de serie
        series_pattern = context.user_data.get('add_series_pattern', {})
        
        # Por defecto, usar el caption original
        caption = original_caption
        
        # Si es una serie, renombrar los capítulos
        if series_pattern.get('is_series', False):
            base_name = series_pattern['base_name']
            season_num = series_pattern['season_num']
            
            # Incrementar el número de episodio
            episode_num = series_pattern['current_episode'] + 1
            series_pattern['current_episode'] = episode_num
            
            # Crear nuevo caption
            new_caption = f"{base_name} {season_num:02d}x{episode_num:02d}"
            
            # Verificar si necesitamos actualizar el caption
            if base_name.lower() not in original_caption.lower():
                try:
                    # Obtener el file_id del archivo actual
                    if update.message.video:
                        file_id = update.message.video.file_id
                        # Borrar el mensaje original
                        await context.bot.delete_message(
                            chat_id=chat_id, 
                            message_id=message_id
                        )
                        # Enviar un nuevo mensaje con el caption correcto
                        new_message = await context.bot.send_video(
                            chat_id=chat_id,
                            video=file_id,
                            caption=new_caption
                        )
                        # Actualizar el message_id para guardarlo correctamente
                        message_id = new_message.message_id
                    elif update.message.document:
                        file_id = update.message.document.file_id
                        # Borrar el mensaje original
                        await context.bot.delete_message(
                            chat_id=chat_id, 
                            message_id=message_id
                        )
                        # Enviar un nuevo mensaje con el caption correcto
                        new_message = await context.bot.send_document(
                            chat_id=chat_id,
                            document=file_id,
                            caption=new_caption
                        )
                        # Actualizar el message_id para guardarlo correctamente
                        message_id = new_message.message_id
                    
                    # Notificar el cambio de nombre
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"<blockquote>✅ Nombre actualizado: <b>{new_caption}</b></blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Usar el nuevo caption
                    caption = new_caption
                except Exception as e:
                    logger.error(f"Error al reenviar con nuevo caption: {e}")
                    caption = original_caption
            else:
                caption = original_caption
            
            # Guardar con el número de episodio
            episode_data = {
                'message_id': message_id,
                'episode_number': episode_num,
                'chat_id': chat_id,
                'caption': caption,
                'file_name': file_name
            }
        else:
            # Para contenido que no es serie
            episode_data = {
                'message_id': message_id,
                'episode_number': 1,  # Solo hay un "episodio" para películas
                'chat_id': chat_id,
                'caption': caption,
                'file_name': file_name
            }
        
        # Añadir a la lista de episodios
        context.user_data.setdefault('add_episodes', []).append(episode_data)
        
        # Mensaje de confirmación
        if series_pattern.get('is_series', False):
            await update.message.reply_text(
                f"<blockquote>✅ Capítulo {episode_data['episode_number']} recibido y guardado.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"<blockquote>✅ Archivo recibido y guardado.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            # Si es una película u otro contenido individual, pasar automáticamente al siguiente paso
            if len(context.user_data.get('add_episodes', [])) == 1:
                context.user_data['add_state'] = ADD_STATE_COVER
                await update.message.reply_text(
                    "<blockquote>Ahora envía una imagen para usar como portada con la descripción como pie de foto.</blockquote>",
                    parse_mode=ParseMode.HTML
                )

async def finalize_add_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Finalizar el proceso y subir el contenido a los canales"""
    # Obtener los datos necesarios
    episodes = context.user_data.get('add_episodes', [])
    cover_photo = context.user_data.get('add_cover')
    description = context.user_data.get('add_description', "")
    title = context.user_data.get('add_title', "")
    series_pattern = context.user_data.get('add_series_pattern', {})
    
    # Verificar que tenemos todos los datos necesarios
    if not episodes or not cover_photo:
        await update.message.reply_text(
            "<blockquote>❌ No hay suficientes datos para subir el contenido.\n\n"
            "Debes enviar al menos un archivo y una imagen de portada.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Crear un mensaje de estado para seguir el progreso
    status_message = await update.message.reply_text(
        "<blockquote>⏳ Procesando y subiendo el contenido a los canales...</blockquote>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Determinar si es una serie o película
        is_series = series_pattern.get('is_series', False)
        
        # 1. Crear un identificador único
        content_id = int(time.time())
        
        # 2. Crear la estructura del mensaje basada en la descripción proporcionada
        if not description:
            description = f"<b>{title}</b>"
        elif "<b>" not in description and title:
            description = f"<b>{title}</b>\n\n{description}"
        
        # 3. Subir la portada con descripción al canal de búsqueda
        await status_message.edit_text(
            "<blockquote>⏳ Subiendo portada al canal de búsqueda...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        sent_cover = await context.bot.send_photo(
            chat_id=SEARCH_CHANNEL_ID,
            photo=cover_photo,
            caption=description,
            parse_mode=ParseMode.HTML
        )
        
        search_channel_cover_id = sent_cover.message_id
        
        # 4. Subir todos los episodios al canal de búsqueda
        await status_message.edit_text(
            f"<blockquote>⏳ Subiendo {len(episodes)} archivo(s) al canal de búsqueda...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        search_channel_episode_IDS = []
        
        # Procesar los episodios en grupos para evitar timeouts
        episode_groups = [episodes[i:i+5] for i in range(0, len(episodes), 5)]
        
        for group_index, group in enumerate(episode_groups):
            # Actualizar estado
            await status_message.edit_text(
                f"<blockquote>⏳ Subiendo archivos al canal de búsqueda... ({group_index*5+1}-{min((group_index+1)*5, len(episodes))}/{len(episodes)})</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            for episode in group:
                try:
                    original_message = await context.bot.copy_message(
                        chat_id=SEARCH_CHANNEL_ID,
                        from_chat_id=episode['chat_id'],
                        message_id=episode['message_id'],
                        disable_notification=True
                    )
                    
                    search_channel_episode_IDS.append(original_message.message_id)
                    
                    # Pequeña pausa para evitar rate limiting
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error copiando episodio al canal de búsqueda: {e}")
                    await status_message.edit_text(
                        f"<blockquote>⚠️ Error al subir el archivo {group_index*5 + len(search_channel_episode_IDS) + 1}. Continuando con el siguiente...</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    await asyncio.sleep(1)
        
        # 5. Generar URL para el botón "Ver ahora"
        if is_series:
            view_url = f"https://t.me/MultimediaTVbot?start=series_{content_id}"
        else:
            # Si es película, usar el ID del primer mensaje
            view_url = f"https://t.me/MultimediaTVbot?start=content_{search_channel_episode_IDS[0]}"
        
        # 6. Crear botón para la portada
        keyboard = [
            [InlineKeyboardButton("Ver ahora", url=view_url)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 7. Actualizar la portada con el botón
        await context.bot.edit_message_reply_markup(
            chat_id=SEARCH_CHANNEL_ID,
            message_id=search_channel_cover_id,
            reply_markup=reply_markup
        )
        
        # 8. Subir portada al canal principal
        await status_message.edit_text(
            "<blockquote>⏳ Subiendo portada al canal principal...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        try:
            sent_cover_main = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=cover_photo,
                caption=description,
                parse_mode=ParseMode.HTML
            )
            
            # 9. Actualizar la portada en el canal principal con el botón
            await context.bot.edit_message_reply_markup(
                chat_id=CHANNEL_ID,
                message_id=sent_cover_main.message_id,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error enviando portada al canal principal: {e}")
            await status_message.edit_text(
                f"<blockquote>⚠️ Error al enviar portada al canal principal, pero el contenido ya está en el canal de búsqueda.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        
        # 10. Si es una serie, guardar en la base de datos
        if is_series:
            await status_message.edit_text(
                "<blockquote>⏳ Guardando información en la base de datos...</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            try:
                # Guardar la serie
                db.add_series(
                    series_id=content_id,
                    title=title,
                    description=description,
                    cover_message_id=search_channel_cover_id,
                    added_by=update.effective_user.id
                )
                
                # Guardar cada episodio
                for i, (episode, msg_id) in enumerate(zip(episodes, search_channel_episode_IDS)):
                    episode_num = episode.get('episode_number', i + 1)
                    db.add_episode(
                        series_id=content_id,
                        episode_number=episode_num,
                        message_id=msg_id
                    )
            except Exception as db_error:
                logger.error(f"Error guardando en la base de datos: {db_error}")
                await status_message.edit_text(
                    f"<blockquote>⚠️ El contenido se subió a los canales pero hubo un error al guardarlo en la base de datos: {str(db_error)[:100]}</blockquote>",
                    parse_mode=ParseMode.HTML
                )
        
        # 11. Reiniciar el estado
        context.user_data['add_state'] = ADD_STATE_IDLE
        context.user_data['add_episodes'] = []
        context.user_data['add_cover'] = None
        context.user_data['add_description'] = None
        context.user_data['add_title'] = None
        context.user_data['add_series_pattern'] = None
        
        # 12. Informar éxito
        content_type = "Serie" if is_series else "Película"
        await status_message.edit_text(
            f"<blockquote>✅ <b>{title}</b> subido correctamente\n\n"
            f"📊 Detalles:\n"
            f"- Tipo: {content_type}\n"
            f"- Archivos: {len(episodes)}\n"
            f"- Subido a canal principal: ✓\n"
            f"- Subido a canal de búsqueda: ✓\n\n"
            f"El contenido ya está disponible con el botón 'Ver ahora'.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    
    except Exception as e:
        logger.error(f"Error en finalize_add_upload: {e}")
        await status_message.edit_text(
            f"<blockquote>❌ Error al procesar la subida: {str(e)[:100]}</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def load_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para iniciar/finalizar la carga masiva de contenido"""
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if user.id not in ADMIN_IDS:
        return
    
    # Obtener el estado actual de carga
    load_state = context.bot_data.get('load_state', LOAD_STATE_INACTIVE)
    
    # Si estamos inactivos, iniciar el proceso
    if load_state == LOAD_STATE_INACTIVE:
        # Inicializar estructura de datos para carga masiva
        context.bot_data['load_state'] = LOAD_STATE_WAITING_NAME
        context.bot_data['current_content'] = {
            'name': None,
            'imdb_info': None,
            'files': [],
            'content_type': 'movie',  # Por defecto película, puede cambiar
            'season_num': None,
            'title': None,
            'custom_filename': None  # Nuevo campo para el nombre personalizado
        }
        
        await update.message.reply_text(
            "<blockquote>📥 <b>Modo de carga masiva activado</b>\n\n"
            "1️⃣ Envía primero el nombre exacto del contenido tal como lo quieres buscar en IMDb\n"
            "2️⃣ El bot buscará información en IMDb y traducirá automáticamente la sinopsis\n"
            "3️⃣ Luego envía todos los archivos de la película o capítulos de la serie\n"
            "4️⃣ Al enviar el archivo, éste será renombrado con el mismo nombre del contenido que buscaste\n"
            "5️⃣ Para continuar con otro contenido, simplemente envía el nombre del siguiente\n"
            "6️⃣ Para finalizar el modo de carga masiva, envía /load nuevamente\n\n"
            "✅ El bot procesará todo con efectos visuales como el comando /upser</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Crear mensaje de estado que se actualizará
        status_msg = await update.message.reply_text(
            "<blockquote>⏳ Esperando nombre del primer contenido...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Guardar referencia al mensaje de estado
        context.bot_data['load_status_message'] = status_msg
    
    # Si ya estamos en proceso, finalizar modo carga
    else:
        # Verificar si hay contenido pendiente por procesar
        current_content = context.bot_data.get('current_content', {})
        if current_content.get('files'):
            # Procesar el contenido pendiente antes de finalizar
            await finalize_current_content(update, context)
        
        # Finalizar el modo de carga
        context.bot_data['load_state'] = LOAD_STATE_INACTIVE
        
        # Informar sobre resultado final
        await update.message.reply_text(
            "<blockquote>✅ <b>Modo de carga masiva finalizado</b>\n\n"
            "Puedes iniciar una nueva sesión de carga con /load cuando lo necesites.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Limpiar datos
        if 'load_status_message' in context.bot_data:
            try:
                status_msg = context.bot_data['load_status_message']
                await status_msg.edit_text(
                    "<blockquote>✅ Proceso de carga masiva completado y finalizado.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error al actualizar mensaje de estado final: {e}")
        
        context.bot_data.pop('current_content', None)
        context.bot_data.pop('load_status_message', None)

async def handle_content_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar recepción de nombre de contenido en modo carga masiva"""
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if user.id not in ADMIN_IDS:
        return
    
    # Verificar si estamos en modo de carga masiva
    load_state = context.bot_data.get('load_state', LOAD_STATE_INACTIVE)
    if load_state == LOAD_STATE_INACTIVE:
        return  # No estamos en modo carga masiva
    
    # Obtener el nombre enviado por el administrador
    content_name = update.message.text.strip()
    
    # Verificar si ya hay contenido pendiente (automáticamente finalizar lo anterior)
    current_content = context.bot_data.get('current_content', {})
    if load_state == LOAD_STATE_WAITING_FILES and current_content.get('files'):
        # Hay un contenido pendiente con archivos, procesarlo primero
        await update.message.reply_text(
            f"<blockquote>⚙️ Detectado nuevo nombre: <b>{content_name}</b>\n"
            f"Primero procesaré el contenido anterior: <b>{current_content.get('title', 'Contenido sin título')}</b></blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Procesar el contenido pendiente
        await finalize_current_content(update, context)
    
    # Crear un mensaje de estado para este proceso específico
    status_msg = await update.message.reply_text(
        f"<blockquote>🔍 Buscando información en TMDB para: <b>{content_name}</b>...</blockquote>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Buscar información solo en TMDB/IMDb
        imdb_info = await search_imdb_info(content_name)
        
        # Inicializar el contenido actual sin buscar en canales
        current_content = {
            'name': content_name,
            'imdb_info': imdb_info or {},
            'files': [],
            'content_type': 'movie',  # Por defecto película, puede cambiar
            'season_num': None,
            'title': content_name,
            'custom_filename': content_name  # Usar el nombre exacto que el admin proporcionó
        }
        
        context.bot_data['current_content'] = current_content
        
        if not imdb_info:
            # No se encontró información en TMDB
            await status_msg.edit_text(
                f"<blockquote>⚠️ No se encontró información en TMDB para <b>{content_name}</b>.\n"
                f"Continuaremos con información básica.\n"
                f"Los archivos se renombrarán como <b>{content_name}</b>.\n"
                f"Ahora envía los archivos del contenido.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        else:
            # Se encontró información en TMDB
            await status_msg.edit_text(
                f"<blockquote>✅ Información encontrada: <b>{imdb_info['title']} ({imdb_info['year']})</b>\n"
                f"⭐ Calificación: {imdb_info['rating']}/10\n"
                f"🔍 Buscando póster de alta calidad...\n"
                f"Los archivos se renombrarán como <b>{content_name}</b>.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            # Actualizar el título en el contenido actual
            current_content['title'] = imdb_info['title']
            
            # Preparar mensaje para el administrador
            if imdb_info['poster_url']:
                try:
                    # Descargar póster para mostrar
                    poster_response = requests.get(imdb_info['poster_url'])
                    poster_response.raise_for_status()
                    poster_bytes = BytesIO(poster_response.content)
                    
                    # Enviar póster con información como vista previa
                    preview_text = (
                        f"✅ <b>{imdb_info['title']}</b> ({imdb_info['year']})\n\n"
                        f"⭐ <b>Calificación:</b> {imdb_info['rating']}/10\n"
                        f"🎭 <b>Género:</b> {imdb_info['genres']}\n\n"
                        f"<blockquote>Ahora envía los archivos del contenido.\n"
                        f"Los archivos se renombrarán como <b>{content_name}</b>.\n"
                        f"Cuando termines, envía el nombre del siguiente contenido.</blockquote>"
                    )
                    
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_bytes,
                        caption=preview_text,
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Eliminar mensaje de estado
                    await status_msg.delete()
                    
                except Exception as e:
                    logger.error(f"Error descargando póster para vista previa: {e}")
                    await status_msg.edit_text(
                        f"<blockquote>✅ Información encontrada: <b>{imdb_info['title']} ({imdb_info['year']})</b>\n"
                        f"⚠️ No se pudo descargar póster para vista previa\n"
                        f"Los archivos se renombrarán como <b>{content_name}</b>.\n"
                        f"Ahora envía los archivos del contenido.</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
            else:
                await status_msg.edit_text(
                    f"<blockquote>✅ Información encontrada: <b>{imdb_info['title']} ({imdb_info['year']})</b>\n"
                    f"⚠️ No se encontró póster para este contenido\n"
                    f"Los archivos se renombrarán como <b>{content_name}</b>.\n"
                    f"Ahora envía los archivos del contenido.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
        
        # Cambiar estado a esperar archivos
        context.bot_data['load_state'] = LOAD_STATE_WAITING_FILES
        
        # Actualizar mensaje de estado general
        await update_load_status_message(update, context)
        
    except Exception as e:
        logger.error(f"Error buscando información para {content_name}: {e}")
        await status_msg.edit_text(
            f"<blockquote>❌ Error al buscar información para <b>{content_name}</b>: {str(e)[:100]}\n"
            f"Continuaremos con información básica.\n"
            f"Los archivos se renombrarán como <b>{content_name}</b>.\n"
            f"Ahora envía los archivos del contenido.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Inicializar contenido actual con información básica
        context.bot_data['current_content'] = {
            'name': content_name,
            'imdb_info': {},
            'files': [],
            'content_type': 'movie',
            'season_num': None,
            'title': content_name,
            'custom_filename': content_name
        }
        
        # Cambiar estado a esperar archivos
        context.bot_data['load_state'] = LOAD_STATE_WAITING_FILES

async def handle_load_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar la recepción de archivos durante el modo de carga masiva"""
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if user.id not in ADMIN_IDS:
        return
    
    # Verificar si estamos en modo de carga masiva esperando archivos
    load_state = context.bot_data.get('load_state', LOAD_STATE_INACTIVE)
    if load_state != LOAD_STATE_WAITING_FILES:
        return  # No estamos esperando archivos
    
    # Detectar si es un video, documento u otro contenido multimedia
    if update.message.video or update.message.document:
        # Extraer información del archivo
        message_id = update.message.message_id
        chat_id = update.effective_chat.id
        original_caption = update.message.caption or ""
        file_name = update.message.document.file_name if update.message.document else None
        
        # Obtener el contenido actual
        current_content = context.bot_data.get('current_content', {})
        if not current_content:
            await update.message.reply_text(
                "<blockquote>❌ Error: No hay información de contenido actual.\n"
                "Inicia el proceso nuevamente con /load.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Determinar si esto es una serie basado en patrones en el nombre del archivo o caption
        season_episode_pattern = re.search(r'S(\d+)E(\d+)|(\d+)x(\d+)', file_name or original_caption or '', re.IGNORECASE)
        
        if "#serie" in original_caption.lower() or "#series" in original_caption.lower() or season_episode_pattern:
            current_content['content_type'] = 'series'
            
            # Extraer temporada y episodio si están disponibles
            season_num = 1
            episode_num = len(current_content['files']) + 1  # Por defecto, siguiente número
            
            if season_episode_pattern:
                # Formato S01E01
                if season_episode_pattern.group(1) and season_episode_pattern.group(2):
                    season_num = int(season_episode_pattern.group(1))
                    episode_num = int(season_episode_pattern.group(2))
                # Formato 1x01
                elif season_episode_pattern.group(3) and season_episode_pattern.group(4):
                    season_num = int(season_episode_pattern.group(3))
                    episode_num = int(season_episode_pattern.group(4))
            
            # Actualizar número de temporada en el contenido actual
            if 'season_num' not in current_content or current_content['season_num'] is None:
                current_content['season_num'] = season_num
        
        # Limpiar caption de links y otros elementos
        clean_caption = clean_content_metadata(original_caption)
        
        # Obtener el nombre personalizado del administrador
        custom_filename = current_content.get('custom_filename', current_content.get('title', 'Sin título'))
        
        # Crear nuevo caption con el nombre personalizado
        if current_content['content_type'] == 'series':
            new_caption = f"{custom_filename} {season_num:02d}x{episode_num:02d}"
        else:
            new_caption = custom_filename
        
        # Reemplazar el mensaje original con el nuevo caption
        try:
            # Obtener el file_id del archivo actual
            if update.message.video:
                file_id = update.message.video.file_id
                # Borrar el mensaje original
                await context.bot.delete_message(
                    chat_id=chat_id, 
                    message_id=message_id
                )
                # Enviar un nuevo mensaje con el caption correcto
                new_message = await context.bot.send_video(
                    chat_id=chat_id,
                    video=file_id,
                    caption=new_caption
                )
                # Actualizar el message_id para guardarlo correctamente
                message_id = new_message.message_id
            elif update.message.document:
                file_id = update.message.document.file_id
                # Borrar el mensaje original
                await context.bot.delete_message(
                    chat_id=chat_id, 
                    message_id=message_id
                )
                # Enviar un nuevo mensaje con el caption correcto
                new_message = await context.bot.send_document(
                    chat_id=chat_id,
                    document=file_id,
                    caption=new_caption
                )
                # Actualizar el message_id para guardarlo correctamente
                message_id = new_message.message_id
            
            # Usar el nuevo caption
            clean_caption = new_caption
        except Exception as e:
            logger.error(f"Error al reenviar con nuevo caption: {e}")
            # Si falla, mantener el caption original
        
        # Crear objeto para este archivo
        file_data = {
            'message_id': message_id,
            'chat_id': chat_id,
            'caption': clean_caption,
            'file_name': file_name,
            'episode_num': episode_num if current_content['content_type'] == 'series' else None
        }
        
        # Añadir a los archivos del contenido actual
        current_content['files'].append(file_data)
        
        # Informar al administrador
        if current_content['content_type'] == 'series':
            await update.message.reply_text(
                f"<blockquote>📥 Capítulo {episode_num} recibido para: <b>{current_content['title']}</b>\n"
                f"Renombrado como: <b>{clean_caption}</b>\n"
                f"Total de capítulos: {len(current_content['files'])}\n\n"
                f"Envía más capítulos o el nombre de otro contenido para continuar.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"<blockquote>📥 Archivo recibido para: <b>{current_content['title']}</b>\n"
                f"Renombrado como: <b>{clean_caption}</b>\n"
                f"Total de archivos: {len(current_content['files'])}\n\n"
                f"Envía más partes o el nombre de otro contenido para continuar.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        
        # Actualizar mensaje de estado
        await update_load_status_message(update, context)


async def finalize_current_content(update, context):
    """Finalizar y procesar el contenido actual"""
    # Obtener el contenido actual
    current_content = context.bot_data.get('current_content', {})
    
    if not current_content or not current_content.get('files'):
        await update.message.reply_text(
            "<blockquote>⚠️ No hay archivos para procesar.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Crear un mensaje de estado para este procesamiento
    status_message = await update.message.reply_text(
        f"<blockquote>⏳ Procesando <b>{current_content['title']}</b>...</blockquote>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Obtener información de IMDb
        imdb_info = current_content.get('imdb_info', {})
        
        # Determinar el tipo de contenido
        content_type_header = "<blockquote>Serie 🎬</blockquote>\n" if current_content['content_type'] == 'series' else "<blockquote>Película 🍿</blockquote>\n"
        
        # Crear descripción según la información disponible
        if imdb_info:
            # Obtener títulos en español e inglés
            spanish_title = imdb_info.get('title', current_content['title'])
            english_title = imdb_info.get('original_title', spanish_title)
            
            # Evitar repetición si los títulos son idénticos
            english_title_display = f"{english_title} ✓\n" if spanish_title.lower() != english_title.lower() else ""
            
            # Determinar información adicional para series
            content_type_info = ""
            if current_content['content_type'] == 'series':
                status_map = {
                    'Returning Series': 'En emisión',
                    'Ended': 'Finalizada',
                    'Canceled': 'Cancelada'
                }
                series_status = status_map.get(imdb_info.get('status'), 'Desconocido')
                episodes_info = imdb_info.get('total_episodes', '?')
                seasons_info = imdb_info.get('number_of_seasons', '?')
                content_type_info = f"📺 Estado: {series_status}\n🔢 {episodes_info} episodios en {seasons_info} temporadas\n"
            
            # Construir la descripción completa
            description = (
                f"{content_type_header}"
                f"{spanish_title} ✓\n"
                f"{english_title_display}\n"
                f"📅 Año: {imdb_info.get('year', 'N/A')}\n"
                f"⭐ Calificación: {imdb_info.get('rating', 'N/A')}/10\n"
                f"{content_type_info}"
                f"🎭 Género: {imdb_info.get('genres', 'No disponible')}\n"
                f"🎬 Director: {imdb_info.get('directors', 'No disponible')}\n"
                f"👥 Reparto: {imdb_info.get('cast', 'No disponible')}\n\n"
                f"📝 Sinopsis:\n<blockquote expandable>{imdb_info.get('plot', 'No disponible')}</blockquote>\n\n"
                f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
            )
        else:
            # Crear descripción básica si no hay información de IMDb
            description = (
                f"{content_type_header}"
                f"{current_content.get('title', 'Sin título')} ✓\n\n"
                f"📝 Sinopsis:\n<blockquote expandable>No se encontró información adicional para este contenido.</blockquote>\n\n"
                f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
            )
        
        # Asegurar que la marca de agua esté presente
        if "Multimedia-TV 📺" not in description:
            description += f"\n\n🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
        
        # Truncar la descripción si es muy larga
        description = truncate_description(description)
        
        # Descargar póster si está disponible
        cover_photo = None
        
        if imdb_info and imdb_info.get('poster_url'):
            await status_message.edit_text(
                f"<blockquote>📥 Descargando póster para <b>{current_content['title']}</b>...</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            try:
                poster_response = requests.get(imdb_info['poster_url'])
                poster_response.raise_for_status()
                poster_bytes = BytesIO(poster_response.content)
                
                # Enviar temporalmente para obtener el file_id
                temp_cover = await update.effective_chat.send_photo(
                    photo=poster_bytes,
                    caption="Imagen temporal para obtener ID",
                    disable_notification=True
                )
                
                # Guardar el file_id y eliminar el mensaje temporal
                cover_photo = temp_cover.photo[-1].file_id
                await temp_cover.delete()
                
            except Exception as e:
                logger.error(f"Error descargando póster: {e}")
                await status_message.edit_text(
                    f"<blockquote>⚠️ Error al descargar póster para {current_content['title']}\n"
                    f"Continuando sin póster...</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                return
        
        if not cover_photo:
            await status_message.edit_text(
                f"<blockquote>⚠️ No se pudo obtener póster para <b>{current_content['title']}</b>\n"
                f"No se puede continuar sin imagen de portada.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Crear un identificador único para este contenido
        unique_id = int(time.time())
        
        # Determinar si es serie o película
        is_series = current_content['content_type'] == 'series'
        
        await status_message.edit_text(
            f"<blockquote>📤 Subiendo <b>{current_content['title']}</b> a los canales...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # 1. Subir la portada con descripción al canal de búsqueda
        sent_cover = await context.bot.send_photo(
            chat_id=SEARCH_CHANNEL_ID,
            photo=cover_photo,
            caption=description,
            parse_mode=ParseMode.HTML
        )
        
        search_channel_cover_id = sent_cover.message_id
        
        # 2. Subir todos los archivos al canal de búsqueda
        search_message_IDS = []
        for i, file in enumerate(current_content['files']):
            # Obtener el mensaje original
            search_message = await context.bot.copy_message(
                chat_id=SEARCH_CHANNEL_ID,
                from_chat_id=file['chat_id'],
                message_id=file['message_id'],
                disable_notification=True
            )
            
            search_message_IDS.append(search_message.message_id)
        
        # 3. Generar URL para botón "Ver ahora"
        if is_series:
            view_url = f"https://t.me/MultimediaTVbot?start=series_{unique_id}"
        else:
            # Si es película, usar el ID del primer mensaje
            view_url = f"https://t.me/MultimediaTVbot?start=content_{search_message_IDS[0]}"
        
        # 4. Crear botón para la portada
        keyboard = [
            [InlineKeyboardButton("Ver ahora", url=view_url)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 5. Actualizar la portada en el canal de búsqueda con el botón
        await context.bot.edit_message_reply_markup(
            chat_id=SEARCH_CHANNEL_ID,
            message_id=search_channel_cover_id,
            reply_markup=reply_markup
        )
        
        # 6. Subir portada al canal principal
        sent_cover_main = await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=cover_photo,
            caption=description,
            parse_mode=ParseMode.HTML
        )
        
        # 7. Actualizar la portada en el canal principal con el mismo botón
        await context.bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=sent_cover_main.message_id,
            reply_markup=reply_markup
        )
        
        # 8. Si es una serie, guardar en la base de datos
        if is_series:
            # Guardar la serie
            db.add_series(
                series_id=unique_id,
                title=imdb_info.get('title', current_content['title']),
                description=description,
                cover_message_id=search_channel_cover_id,
                added_by=update.effective_user.id
            )
            
            # Guardar cada episodio
            for i, (file, msg_id) in enumerate(zip(current_content['files'], search_message_IDS)):
                episode_num = file.get('episode_num', i + 1)
                db.add_episode(
                    series_id=unique_id,
                    episode_number=episode_num,
                    message_id=msg_id
                )
        
        # 9. Reiniciar el contenido actual
        context.bot_data['current_content'] = {
            'name': None,
            'imdb_info': None,
            'files': [],
            'content_type': 'movie',
            'season_num': None,
            'title': None,
            'custom_filename': None
        }
        
        # 10. Informar éxito
        await status_message.edit_text(
            f"<blockquote>✅ <b>{current_content['title']}</b> procesado correctamente\n"
            f"Tipo: {'Serie' if is_series else 'Película'}\n"
            f"Archivos: {len(current_content['files'])}\n"
            f"✅ Portada subida a canal principal\n"
            f"✅ Todo el contenido subido a canal de búsqueda</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error en finalize_current_content: {e}")
        await status_message.edit_text(
            f"<blockquote>❌ Error procesando el contenido: {str(e)[:100]}\n"
            f"Intenta nuevamente.</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def update_load_status_message(update, context):
    """Actualizar el mensaje de estado con la información actual del proceso"""
    # Obtener datos actuales
    current_content = context.bot_data.get('current_content', {})
    load_state = context.bot_data.get('load_state', LOAD_STATE_INACTIVE)
    
    # Crear mensaje de estado
    status = "<blockquote>📊 <b>Estado de la carga masiva</b>\n\n"
    
    if load_state == LOAD_STATE_WAITING_NAME:
        status += "⏳ <b>Esperando:</b> Nombre del próximo contenido\n\n"
    elif load_state == LOAD_STATE_WAITING_FILES:
        title = current_content.get('title', 'Desconocido')
        files_count = len(current_content.get('files', []))
        content_type = "Serie" if current_content.get('content_type') == 'series' else "Película"
        
        status += f"📝 <b>Contenido actual:</b> {title}\n"
        status += f"📂 <b>Tipo:</b> {content_type}\n"
        status += f"🔢 <b>Archivos recibidos:</b> {files_count}\n\n"
        
        if files_count > 0:
            status += "⏳ <b>Esperando:</b> Más archivos o /load para finalizar este contenido\n\n"
        else:
            status += "⏳ <b>Esperando:</b> Primer archivo del contenido\n\n"
    
    status += "</blockquote>"
    
    # Actualizar el mensaje de estado
    try:
        status_msg = context.bot_data.get('load_status_message')
        if status_msg:
            await status_msg.edit_text(status, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error al actualizar mensaje de estado: {e}")

async def process_load_queue(update, context):
    """Procesar la cola de contenido pendiente"""
    try:
        while True:
            # Verificar si hay elementos en la cola
            queue = context.bot_data.get('load_queue', [])
            if not queue:
                # No hay más elementos, terminar procesamiento
                context.bot_data['load_processing'] = False
                await update_load_status_message(update, context)
                break
            
            # Tomar el primer elemento de la cola
            content = queue.pop(0)
            context.bot_data['current_content'] = content
            
            # Actualizar estado
            await update_load_status_message(update, context)
            
            # Crear un mensaje de estado para este contenido específico
            content_status = await update.effective_chat.send_message(
                f"<blockquote>🔍 Procesando: <b>{content.get('title', 'Desconocido')}</b>...</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            try:
                # Extraer información de IMDb que ya teníamos
                imdb_info = content.get('imdb_info', {})
                
                # Verificar si tenemos información válida
                if not imdb_info or not imdb_info.get('found', False):
                    await content_status.edit_text(
                        f"<blockquote>⚠️ No hay información completa para <b>{content.get('title')}</b>.\n"
                        f"Se usará información básica.</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Si no tenemos información, intentar buscar nuevamente
                    if not imdb_info:
                        await content_status.edit_text(
                            f"<blockquote>🔍 Buscando información para <b>{content.get('title')}</b>...</blockquote>",
                            parse_mode=ParseMode.HTML
                        )
                        
                        # Intentar buscar información basada en el título
                        new_imdb_info = await search_imdb_info(content.get('title', ''))
                        if new_imdb_info:
                            imdb_info = new_imdb_info
                            content['imdb_info'] = new_imdb_info
                            await content_status.edit_text(
                                f"<blockquote>✅ Información encontrada para <b>{imdb_info['title']}</b>\n"
                                f"Continuando procesamiento...</blockquote>",
                                parse_mode=ParseMode.HTML
                            )
                
                # Crear descripción con la información encontrada
                if 'title' in imdb_info:
                    description = (
                        f"<b>{imdb_info['title']}</b> ({imdb_info.get('year', 'N/A')})\n\n"
                        f"⭐ <b>Calificación:</b> {imdb_info.get('rating', 'N/A')}/10\n"
                        f"🎭 <b>Género:</b> {imdb_info.get('genres', 'No disponible')}\n"
                        f"🎬 <b>Director:</b> {imdb_info.get('directors', 'No disponible')}\n"
                        f"👥 <b>Reparto:</b> {imdb_info.get('cast', 'No disponible')}\n\n"
                        f"📝 <b>Sinopsis:</b>\n<blockquote expandable>{imdb_info.get('plot', 'No disponible')}</blockquote>\n\n"                      
                    f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
                    )
                    
                else:
                    # Crear descripción básica si no hay información
                    description = (
                        f"<b>{content.get('title', 'Contenido sin título')}</b>\n\n"
                        f"<blockquote>No se encontró información adicional para este contenido.</blockquote>"
                    )
                
                # Descargar póster si está disponible
                cover_photo = None
                
                if imdb_info and imdb_info.get('poster_url'):
                    await content_status.edit_text(
                        f"<blockquote>📥 Descargando póster para <b>{content.get('title')}</b>...</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    
                    try:
                        poster_response = requests.get(imdb_info['poster_url'])
                        poster_response.raise_for_status()
                        poster_bytes = BytesIO(poster_response.content)
                        
                        # Enviar temporalmente para obtener el file_id
                        temp_cover = await update.effective_chat.send_photo(
                            photo=poster_bytes,
                            caption="Imagen temporal para obtener ID",
                            disable_notification=True
                        )
                        
                        # Guardar el file_id y eliminar el mensaje temporal
                        cover_photo = temp_cover.photo[-1].file_id
                        await temp_cover.delete()
                        
                    except Exception as e:
                        logger.error(f"Error descargando póster: {e}")
                        await content_status.edit_text(
                            f"<blockquote>⚠️ Error al descargar póster para {content.get('title')}\n"
                            f"Continuando sin póster...</blockquote>",
                            parse_mode=ParseMode.HTML
                        )
                
                if not cover_photo:
                    # Si no logramos obtener el póster, intentar procesar sin él
                    context.bot_data.setdefault('load_failed', []).append(content)
                    await content_status.edit_text(
                        f"<blockquote>⚠️ No se pudo obtener póster para <b>{content.get('title')}</b>\n"
                        f"Este elemento será postergado para procesamiento manual.</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    continue
                
                # Subir a los canales
                await content_status.edit_text(
                    f"<blockquote>📤 Subiendo <b>{content.get('title')}</b> a los canales...</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                
                # 1. Subir la portada con descripción al canal de búsqueda
                sent_cover = await context.bot.send_photo(
                    chat_id=SEARCH_CHANNEL_ID,
                    photo=cover_photo,
                    caption=description,
                    parse_mode=ParseMode.HTML
                )
                
                search_channel_cover_id = sent_cover.message_id
                
                # 2. Subir el contenido al canal de búsqueda
                content_message = await context.bot.copy_message(
                    chat_id=SEARCH_CHANNEL_ID,
                    from_chat_id=content['chat_id'],
                    message_id=content['message_id'],
                    disable_notification=True
                )
                
                # 3. Crear identificador único
                unique_id = int(time.time())
                
                # 4. Generar URL para botón "Ver ahora"
                if content['content_type'] == 'series':
                    view_url = f"https://t.me/MultimediaTVbot?start=series_{unique_id}"
                else:
                    view_url = f"https://t.me/MultimediaTVbot?start=content_{content_message.message_id}"
                
                # 5. Crear botón para la portada
                keyboard = [
                    [InlineKeyboardButton("Ver ahora", url=view_url)]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # 6. Actualizar la portada con el botón
                await context.bot.edit_message_reply_markup(
                    chat_id=SEARCH_CHANNEL_ID,
                    message_id=search_channel_cover_id,
                    reply_markup=reply_markup
                )
                
                # 7. Repetir el proceso para el canal principal
                sent_cover_main = await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=cover_photo,
                    caption=description,
                    parse_mode=ParseMode.HTML
                )
                
                content_message_main = await context.bot.copy_message(
                    chat_id=CHANNEL_ID,
                    from_chat_id=content['chat_id'],
                    message_id=content['message_id'],
                    disable_notification=True
                )
                
                # 8. Actualizar la portada en el canal principal
                await context.bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID,
                    message_id=sent_cover_main.message_id,
                    reply_markup=reply_markup
                )
                
                # 9. Si es una serie, guardarla en la base de datos
                if content['content_type'] == 'series':
                    db.add_series(
                        series_id=unique_id,
                        title=imdb_info.get('title', content.get('title')),
                        description=description,
                        cover_message_id=search_channel_cover_id,
                        added_by=update.effective_user.id
                    )
                    
                    # Guardar el episodio
                    db.add_episode(
                        series_id=unique_id,
                        episode_number=content.get('episode_num', 1),  # Usar el número de episodio detectado
                        message_id=content_message.message_id
                    )
                
                # Informar éxito
                await content_status.edit_text(
                    f"<blockquote>✅ <b>{content.get('title')}</b> procesado correctamente\n"
                    f"Tipo: {'Serie' if content['content_type'] == 'series' else 'Película'}\n"
                    f"Subido a ambos canales con botón 'Ver ahora'</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                
            except Exception as e:
                logger.error(f"Error procesando contenido {content.get('title')}: {e}")
                context.bot_data.setdefault('load_failed', []).append(content)
                await content_status.edit_text(
                    f"<blockquote>❌ Error al procesar <b>{content.get('title')}</b>: {str(e)[:100]}\n"
                    f"Este elemento será postergado para procesamiento manual.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
            
            finally:
                # Marcar que hemos terminado con este contenido
                context.bot_data['current_content'] = None
                await update_load_status_message(update, context)
                
                # Pequeña pausa para evitar saturar la API de Telegram
                await asyncio.sleep(1)
        
    except Exception as e:
        logger.error(f"Error general en process_load_queue: {e}")
        context.bot_data['load_processing'] = False
        await update_load_status_message(update, context)

def clean_content_metadata(text):
    """Limpiar metadata, links y otros elementos innecesarios del texto"""
    if not text:
        return ""
    
    # Eliminar URLs
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    
    # Eliminar etiquetas comunes
    text = re.sub(r'#\w+', '', text)
    
    # Eliminar información de calidad común
    text = re.sub(r'\b(1080p|720p|4K|UHD|HDR|REMUX|BluRay|WEB-DL|WEBRip|BDRip|DVDRip)\b', '', text, flags=re.IGNORECASE)
    
    # Eliminar información de codecs
    text = re.sub(r'\b(x264|x265|HEVC|AVC|AAC|MP3|AC3|DTS)\b', '', text, flags=re.IGNORECASE)
    
    # Eliminar información de release groups
    text = re.sub(r'[\[\(]([A-Za-z0-9._-]+)[\]\)]', '', text)
    
    # Eliminar caracteres especiales extra
    text = re.sub(r'[_\-\.]+', ' ', text)
    
    # Eliminar espacios múltiples y espacios al inicio/final
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def extract_title_from_content(caption, file_name):
    """Extraer el título probable del contenido a partir del caption y/o nombre de archivo"""
    potential_title = ""
    
    # Intentar extraer del caption primero
    if caption:
        # Buscar lo que parece un título (primera línea o antes del primer signo de puntuación)
        lines = caption.split('\n')
        first_line = lines[0].strip() if lines else ""
        
        if first_line:
            # Si la primera línea parece razonable como título, usarla
            if 5 <= len(first_line) <= 100:  # Longitud razonable para un título
                potential_title = first_line
        
        # Si no obtuvimos título de la primera línea, buscar en todo el caption
        if not potential_title:
            # Buscar patrones comunes como "Título (Año)" o "Título - Información"
            match = re.search(r'^([^(|\-]+)', caption)
            if match:
                potential_title = match.group(1).strip()
    
    # Si aún no tenemos título y tenemos nombre de archivo, intentar extraerlo de ahí
    if not potential_title and file_name:
        # Quitar extensión
        name_without_ext = os.path.splitext(file_name)[0]
        # Limpiar
        clean_name = clean_content_metadata(name_without_ext)
        
        # Extraer lo que parece un título
        match = re.search(r'^([^(|\-|\.]+)', clean_name)
        if match:
            potential_title = match.group(1).strip()
        else:
            potential_title = clean_name
    
    # Si seguimos sin título, usar un valor genérico
    if not potential_title:
        potential_title = "Contenido sin título"
    
    return potential_title
                        
async def send_all_episodes(query, context, series_id):
    """Enviar todos los capítulos de una serie al usuario"""
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    can_forward = user_data and user_data.get('can_forward', False)
    
    await query.answer("Enviando todos los capítulos...")
    
    # Mostrar acción de escribiendo
    await context.bot.send_chat_action(
        chat_id=query.message.chat_id,
        action=ChatAction.TYPING
    )
    
    try:
        # Obtener todos los capítulos
        episodes = db.get_series_episodes(series_id)
        
        if not episodes:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ No se encontraron capítulos para esta serie.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Enviar mensaje de inicio
        status_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"⏳ Enviando {len(episodes)} capítulos... Por favor, espera.",
            parse_mode=ParseMode.HTML
        )
        
        # Enviar cada capítulo
        for i, episode in enumerate(episodes):
            try:
                # Actualizar estado periódicamente
                if i % 5 == 0 and i > 0:
                    await status_message.edit_text(
                        f"⏳ Enviando capítulos... ({i}/{len(episodes)})",
                        parse_mode=ParseMode.HTML
                    )
                
                # Enviar capítulo
                await context.bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=SEARCH_CHANNEL_ID,
                    message_id=episode['message_id'],
                    protect_content=not can_forward,  # Proteger según el plan
                    disable_notification=(i < len(episodes) - 1)  # Solo notificar el último
                )
                
                # Pequeña pausa para no sobrecargar
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error enviando capítulo {i+1}: {e}")
                continue
        
        # Actualizar mensaje de estado
        await status_message.edit_text(
            f"✅ Se han enviado todos los capítulos ({len(episodes)}).",
            parse_mode=ParseMode.HTML
        )
        
        # Marcar el botón como seleccionado
        keyboard = query.message.reply_markup.inline_keyboard
        new_keyboard = []
        
        for row in keyboard:
            new_row = []
            for button in row:
                if button.callback_data == query.data:
                    # Marcar este botón como seleccionado
                    new_row.append(InlineKeyboardButton(
                        f"✅ {button.text}",
                        callback_data=button.callback_data
                    ))
                else:
                    new_row.append(button)
            new_keyboard.append(new_row)
        
        # Actualizar el mensaje con el nuevo teclado
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(new_keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error general enviando todos los capítulos: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Error al enviar los capítulos: {str(e)[:100]}",
            parse_mode=ParseMode.HTML
        )

# Función para buscar información de una película o serie en IMDb
async def search_imdb_info(title):
    """Buscar información de una película o serie en TMDB por título"""
    try:
        # Configuración de TMDB API
        api_key = "ba7dc9b8dc85198f56a7b631a6519158"
        headers = {
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJiYTdkYzliOGRjODUxOThmNTZhN2I2MzFhNjUxOTE1OCIsInN1YiI6IjY4MWJiYTFiOWNkMjZiOTNhZTkzYWE4NiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.mYyI0IG4WIX907N6ZXJ6cQU77CQHPP8OGZTZOPBa0Rw",
            "Content-Type": "application/json;charset=utf-8"
        }

        # Buscar por título (en español primero)
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={title}&language=es-ES"
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        search_data = response.json()

        if not search_data.get('results') or len(search_data['results']) == 0:
            logger.info(f"No se encontraron resultados en TMDB para: {title}")
            return None

        # Tomar el primer resultado
        first_result = search_data['results'][0]
        media_type = first_result.get('media_type', 'movie')
        media_id = first_result.get('id')

        # Si el resultado es una persona, intentar encontrar otro resultado
        if media_type == 'person':
            if len(search_data['results']) > 1:
                for result in search_data['results']:
                    if result.get('media_type') in ['movie', 'tv']:
                        media_type = result.get('media_type')
                        media_id = result.get('id')
                        break
            else:
                return None

        # Obtener información detallada en español
        detail_url = f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={api_key}&language=es-ES&append_to_response=credits"
        detail_response = requests.get(detail_url, headers=headers)
        detail_response.raise_for_status()
        item = detail_response.json()

        # Obtener información en inglés para el título original
        detail_url_en = f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={api_key}&language=en-US"
        detail_response_en = requests.get(detail_url_en, headers=headers)
        detail_response_en.raise_for_status()
        item_en = detail_response_en.json()

        # Determinar títulos y año según el tipo de contenido
        if media_type == 'movie':
            spanish_title = item.get('title', 'Título no disponible')
            english_title = item_en.get('original_title', item.get('original_title', spanish_title))
            release_date = item.get('release_date', '')
            year = release_date[:4] if release_date else 'N/A'
        else:  # tv
            spanish_title = item.get('name', 'Título no disponible')
            english_title = item_en.get('original_name', item.get('original_name', spanish_title))
            first_air_date = item.get('first_air_date', '')
            year = first_air_date[:4] if first_air_date else 'N/A'

        # Si los títulos son iguales (ignorando mayúsculas/minúsculas), usar solo el español
        if spanish_title.lower() == english_title.lower():
            english_title = spanish_title

        # Recopilar información
        info = {
            'title': spanish_title,
            'original_title': english_title,
            'year': year,
            'rating': round(item.get('vote_average', 0), 1),
            'plot': item.get('overview', 'Sinopsis no disponible'),
            'url': f"https://www.themoviedb.org/{media_type}/{media_id}",
            'poster_url': None,
            'is_series': media_type == 'tv'
        }

        # Obtener géneros
        if item.get('genres'):
            info['genres'] = ', '.join(genre['name'] for genre in item['genres'][:3])
        else:
            info['genres'] = 'No disponible'

        # Obtener URL del póster en alta resolución
        if item.get('poster_path'):
            info['poster_url'] = f"https://image.tmdb.org/t/p/original{item['poster_path']}"

        # Obtener directores
        directors = []
        if media_type == 'movie':
            if item.get('credits', {}).get('crew'):
                directors = [member['name'] for member in item['credits']['crew'] 
                           if member['job'] == 'Director'][:3]
        else:
            if item.get('credits', {}).get('crew'):
                directors = [member['name'] for member in item['credits']['crew']
                           if member['job'] in ['Creator', 'Executive Producer']][:3]
        info['directors'] = ', '.join(directors) if directors else 'No disponible'

        # Obtener actores principales
        if item.get('credits', {}).get('cast'):
            cast = [actor['name'] for actor in item['credits']['cast'][:5]]
            info['cast'] = ', '.join(cast)
        else:
            info['cast'] = 'No disponible'

        # Información adicional para series
        if media_type == 'tv':
            # Mapear el estado de la serie al español
            status_map = {
                'Returning Series': 'En emisión',
                'Ended': 'Finalizada',
                'Canceled': 'Cancelada',
                'In Production': 'En producción',
                'Planned': 'Planificada'
            }
            status = item.get('status', 'Desconocido')
            info['series_status'] = status_map.get(status, status)
            
            # Información sobre episodios y temporadas
            num_seasons = item.get('number_of_seasons', '?')
            num_episodes = item.get('number_of_episodes', '?')
            info['total_episodes'] = f"{num_episodes} episodios en {num_seasons} temporadas"
            info['content_type'] = 'series'
        else:
            info['content_type'] = 'movie'

        logger.info(f"Información encontrada en TMDB para '{title}': {spanish_title} ({year})")
        return info

    except Exception as e:
        logger.error(f"Error buscando en TMDB: {e}")
        return None

@check_channel_membership
async def search_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search for content in the channel based on user query."""
    if not update.message:
        return
        
    user_id = update.effective_user.id
    
    # Get search query from command arguments
    if not context.args:
        await update.message.reply_text(
            "Por favor, proporciona el nombre de la película o serie que deseas buscar.\n"
            "Ejemplo: /search Stranger Things",
            parse_mode=ParseMode.HTML
        )
        return
    
    query = " ".join(context.args).lower()
    
    # Check user's search limits
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text(
            "❌ Error: Usuario no registrado. Usa /start para registrarte.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user can make more searches today
    if not db.increment_daily_usage(user_id):
        # Show purchase plans if limit exceeded
        keyboard = []
        for plan_id, plan in PLANS_INFO.items():
            if plan_id != 'basic':
                keyboard.append([
                    InlineKeyboardButton(
                        f"{plan['name']} - {plan['price']}",
                        callback_data=f"buy_plan_{plan_id}"
                    )
                ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ Has alcanzado tu límite de búsquedas diarias.\n\n"
            "<blockquote>Para continuar buscando, adquiere un plan premium:</blockquote>",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
    
    # Show typing action
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )
    
    # Initialize user preferences if not exist
    if user_id not in user_preferences:
        user_preferences[user_id] = {
            "max_results": 100,
            "show_previews": True,
            "sort_by_date": True
        }
    
    # Get user preferences
    max_results = user_preferences[user_id]["max_results"]
    
    # Check if we have cached results in MongoDB
    cached_results = db.get_search_cache(query)
    if cached_results:
        # Usar resultados en caché
        await send_search_results(
            update, 
            context, 
            query, 
            cached_results["results"],
            footer_text="\n\n<i>📌 Resultados almacenados en caché para búsquedas más rápidas</i>"
        )
        return
    
    # Send initial message
    status_message = await update.message.reply_text(
        f"🔍 Buscando '{query}' en el canal... Por favor espera.",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Get the latest message ID if we don't have it
        if not last_message_id:
            try:
                latest_id = await get_latest_message_id(context)
            except Exception as e:
                logger.error(f"Error getting latest message ID: {e}")
                await status_message.edit_text(
                    f"❌ Error al buscar en el canal. Por favor, intenta más tarde.",
                    parse_mode=ParseMode.HTML
                )
                return
        else:
            latest_id = last_message_id
        
        # We'll search through messages more efficiently
        num_messages = min(latest_id, MAX_SEARCH_MESSAGES)
        
        # Create a list of message IDS to check
        # We'll prioritize recent messages and use a smarter search pattern
        message_IDS = []
        
        # First, check the most recent 100 messages
        recent_start = max(1, latest_id - 100)
        message_IDS.extend(range(latest_id, recent_start - 1, -1))
        
        # Then, check older messages with a larger step to cover more ground quickly
        if recent_start > 1:
            # Calculate how many more messages we can check
            remaining = MAX_SEARCH_MESSAGES - len(message_IDS)
            if remaining > 0:
                # Determine step size based on remaining messages
                step = max(1, (recent_start - 1) // remaining)
                older_IDS = list(range(recent_start - 1, 0, -step))[:remaining]
                message_IDS.extend(older_IDS)
        
        # Keep track of potential matches
        potential_matches = []
        
        # Update status message
        await status_message.edit_text(
            f"🔍 Buscando '{query}'... 0% completado",
            parse_mode=ParseMode.HTML
        )
        
        # Parse special search filters
        movie_filter = "#película" in query or "#pelicula" in query
        series_filter = "#serie" in query or "#series" in query
        
        # Extract year filter if present
        year_match = re.search(r'\+(\d{4})', query)
        year_filter = int(year_match.group(1)) if year_match else None
        
        # Clean query from filters
        clean_query = query
        if movie_filter:
            clean_query = clean_query.replace("#película", "").replace("#pelicula", "")
        if series_filter:
            clean_query = clean_query.replace("#serie", "").replace("#series", "")
        if year_filter:
            clean_query = re.sub(r'\+\d{4}', "", clean_query)
        
        clean_query = clean_query.strip()
        
        # Search through messages in batches to update progress
        batch_size = 20
        total_batches = (len(message_IDS) + batch_size - 1) // batch_size
        
        for batch_index in range(0, len(message_IDS), batch_size):
            batch = message_IDS[batch_index:batch_index + batch_size]
            
            # Process batch in parallel for speed
            tasks = []
            for msg_id in batch:
                task = asyncio.create_task(get_message_content(context, update.effective_chat.id, msg_id))
                tasks.append((msg_id, task))
            
            # Wait for all tasks to complete
            for msg_id, task in tasks:
                try:
                    message_content = await task
                    
                    if message_content:
                        # Check if the message contains the query
                        full_content = message_content['full_content'].lower()
                        
                        # Apply filters
                        if movie_filter and "#serie" in full_content:
                            continue
                        if series_filter and "#película" in full_content:
                            continue
                        
                        # Apply year filter
                        if year_filter and not re.search(r'\b' + str(year_filter) + r'\b', full_content):
                            continue
                        
                        # Check if message matches the query
                        if clean_query in full_content:
                            # Calculate relevance score
                            relevance = 0
                            
                            # Exact match gets higher score
                            if clean_query == full_content:
                                relevance += 100
                            # Title match gets higher score
                            elif re.search(r'^' + re.escape(clean_query), full_content):
                                relevance += 50
                            # Word boundary match gets higher score
                            elif re.search(r'\b' + re.escape(clean_query) + r'\b', full_content):
                                relevance += 25
                            # Otherwise, just a substring match
                            else:
                                relevance += 10
                                
                            # Media content gets higher score
                            if message_content['has_media']:
                                relevance += 15
                                
                            # Recent messages get higher score
                            recency_score = min(10, (msg_id / latest_id) * 10)
                            relevance += recency_score
                            
                            # Add to potential matches
                            potential_matches.append({
                                'id': msg_id,
                                'preview': message_content['preview'],
                                'has_media': message_content['has_media'],
                                'relevance': relevance
                            })
                            
                            # If we have enough matches, we can stop searching
                            if len(potential_matches) >= max_results * 3:  # Get more than needed to sort by relevance
                                break
                
                except Exception as e:
                    logger.error(f"Error processing message {msg_id}: {e}")
                    continue
            
            # Update progress
            progress = min(100, int((batch_index + len(batch)) / len(message_IDS) * 100))
            if progress % 10 == 0:  # Update every 10%
                await status_message.edit_text(
                    f"🔍 Buscando '{query}'... {progress}% completado",
                    parse_mode=ParseMode.HTML
                )
            
            # If we have enough matches, stop searching
            if len(potential_matches) >= max_results * 3:
                break
            
            # Avoid hitting rate limits
            await asyncio.sleep(0.01)
        
        # Sort matches by relevance
        if user_id in user_preferences and user_preferences[user_id]["sort_by_date"]:
            # Sort by message ID (date) if user prefers
            potential_matches.sort(key=lambda x: x['id'], reverse=True)
        else:
            # Sort by relevance score
            potential_matches.sort(key=lambda x: x['relevance'], reverse=True)
        
        # Limit to max results
        potential_matches = potential_matches[:max_results]
        
        # Cuando encuentres resultados, guárdalos en el caché de MongoDB
        if potential_matches:
            cache_data = {
                "query": query,
                "results": potential_matches,
                "timestamp": datetime.now(),
                "cache_version": "1.0",
                "result_count": len(potential_matches)
            }
            db.save_search_cache(query, cache_data)
        
        # Send results to user
        await send_search_results(update, context, query, potential_matches, status_message)
    
    except Exception as e:
        logger.error(f"Error searching content: {e}")
        await status_message.edit_text(
            f"❌ Ocurrió un error al buscar: {str(e)[:100]}\n\nPor favor intenta más tarde.",
            parse_mode=ParseMode.HTML
        )

# Modificación para handle_search
@check_channel_membership
async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle direct message searches."""
    # Verificar que update.message no sea None
    if not update.message:
        return
    
    # Verificar si estamos en modo de carga masiva para el administrador
    load_state = context.bot_data.get('load_state', LOAD_STATE_INACTIVE)
    if update.effective_user.id == ADMIN_IDS and load_state != LOAD_STATE_INACTIVE:
        # Si el admin está en modo de carga masiva, no procesar como búsqueda
        return
        
    user_id = update.effective_user.id
    query = update.message.text.lower()
    
    # Asignar el texto como argumentos para search_content
    context.args = query.split()
    await search_content(update, context)

async def get_latest_message_id(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Get the latest message ID from the channel."""
    global last_message_id

    try:
        # Verificar primero si el canal existe y el bot tiene acceso
        try:
            await context.bot.get_chat(chat_id=SEARCH_CHANNEL_ID)
        except Exception as e:
            logger.error(f"Error accessing the search channel: {e}")
            raise

        # Send a temporary message to get the latest message ID
        temp_msg = await context.bot.send_message(chat_id=SEARCH_CHANNEL_ID, text=".")
        latest_id = temp_msg.message_id
        
        # Delete the temporary message
        try:
            await context.bot.delete_message(chat_id=SEARCH_CHANNEL_ID, message_id=latest_id)
        except Exception as e:
            logger.error(f"Error deleting temporary message: {e}")
        
        last_message_id = latest_id
        return latest_id
    except Exception as e:
        logger.error(f"Error getting latest message ID: {e}")
        # Return a default value instead of raising an exception
        return last_message_id or 1

async def get_message_content(context: ContextTypes.DEFAULT_TYPE, user_chat_id: int, msg_id: int) -> dict:
    """Get message content efficiently with caching."""
    # Check if we have this message in cache
    if msg_id in message_cache:
        return message_cache[msg_id]
    
    # Try to get message content
    try:
        # Use getMessages API method if available (faster)
        try:
            message = await context.bot.forward_message(
                chat_id=user_chat_id,
                from_chat_id=SEARCH_CHANNEL_ID,
                message_id=msg_id,
                disable_notification=True
            )
            
            # Extract content
            text = message.text if hasattr(message, 'text') and message.text else ""
            caption = message.caption if hasattr(message, 'caption') and message.caption else ""
            has_media = hasattr(message, 'photo') or hasattr(message, 'video') or hasattr(message, 'document')
            
            # Create preview
            full_content = (text + " " + caption).strip()
            preview = full_content[:50] + "..." if len(full_content) > 50 else full_content
            
            # Delete the forwarded message
            await context.bot.delete_message(
                chat_id=user_chat_id,
                message_id=message.message_id
            )
            
            # Create content object
            message_content = {
                'text': text,
                'caption': caption,
                'has_media': has_media,
                'preview': preview,
                'full_content': full_content
            }
            
            # Cache the content
            message_cache[msg_id] = message_content
            
            return message_content
            
        except Exception as e:
            # If forwarding fails, try copying
            try:
                message = await context.bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=SEARCH_CHANNEL_ID,
                    message_id=msg_id,
                    disable_notification=True
                )
                
                # Extract content
                text = message.text if hasattr(message, 'text') and message.text else ""
                caption = message.caption if hasattr(message, 'caption') and message.caption else ""
                has_media = hasattr(message, 'photo') or hasattr(message, 'video') or hasattr(message, 'document')
                
                # Create preview
                full_content = (text + " " + caption).strip()
                preview = full_content[:50] + "..." if len(full_content) > 50 else full_content
                
                # Delete the copied message
                await context.bot.delete_message(
                    chat_id=user_chat_id,
                    message_id=message.message_id
                )
                
                # Create content object
                message_content = {
                    'text': text,
                    'caption': caption,
                    'has_media': has_media,
                    'preview': preview,
                    'full_content': full_content
                }
                
                # Cache the content
                message_cache[msg_id] = message_content
                
                return message_content
                
            except Exception as inner_e:
                # If both methods fail, return None
                logger.error(f"Error getting content for message {msg_id}: {inner_e}")
                return None
    
    except Exception as e:
        logger.error(f"Error processing message {msg_id}: {e}")
        return None

async def send_search_results(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, results: list, status_message=None, footer_text=None):
    """Send search results to the user."""
    if not status_message:
        status_message = await update.message.reply_text(
            f"🔍 Procesando resultados para '{query}'..."
        )
    
    if results:
        # Create a message with buttons for each match
        keyboard = []
        for i, match in enumerate(results):
            media_icon = "🎬" if match['has_media'] else "📝"
            keyboard.append([
                InlineKeyboardButton(
                    f"{i+1}. {media_icon} {match['preview']}",
                    callback_data=f"send_{match['id']}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Crear mensaje base
        message_text = (
            f"✅ Encontré {len(results)} resultados para '<b>{query}</b>'.\n\n"
            f"Selecciona uno para verlo:"
        )
        
        # Añadir footer si existe
        if footer_text:
            message_text += footer_text
        
        await status_message.edit_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    else:
        # Content not found, offer to make a request
        keyboard = [
            [
                InlineKeyboardButton("Película 🎞️", callback_data=f"req_movie_{query}"),
                InlineKeyboardButton("Serie 📺", callback_data=f"req_series_{query}")
            ],
            [InlineKeyboardButton("Hacer Pedido 📡", callback_data="make_request")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_message.edit_text(
            f"No se encontraron resultados para '{query}'.\n\n"
            f"Comprueba que escribes el nombre correctamente o utiliza variaciones del mismo. "
            f"Prueba escribiendo el nombre en el idioma oficial o español o solamente pon una palabra clave.\n"
            f"¿Quieres hacer un pedido?\n"
            f"Selecciona el tipo y haz clic en 'Hacer pedido'.",
            reply_markup=reply_markup
        )

async def clear_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually clear the search cache"""
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
        
    try:
        db.clear_old_cache()
        await update.message.reply_text(
            "<blockquote>✅ Caché limpiado correctamente.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(
            f"<blockquote>❌ Error al limpiar caché: {str(e)[:100]}</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def send_additional_messages(context, chat_id, msg_id, can_forward):
    """Send additional messages after sending the main content."""
    try:
        # Generar URL para compartir
        view_url = f"https://t.me/MultimediaTVbot?start=content_{msg_id}"

        # Crear el botón de compartir
        share_keyboard = [
            [InlineKeyboardButton("Compartir 🔗", url=f"https://t.me/share/url?url={view_url}&text=¡Mira%20este%20contenido%20en%20MultimediaTV!")]
        ]
        share_markup = InlineKeyboardMarkup(share_keyboard)

        # Enviar mensaje con toda la información y el botón de compartir
        await context.bot.send_message(
            chat_id=chat_id,
            text="📌 Muchas gracias por Preferirnos\n"
                 "<blockquote expandable>En caso de que no puedas reenviar ni guardar el archivo en tu teléfono, "
                 "quiere decir que no tienes un plan comprado. Por lo cual te recomiendo "
                 "que adquieras los planes Medio o Ultra que le dan estas posibilidades.\n\n</blockquote>"
                 "◈ Nota\n"
                 "<blockquote expandable>Adquiere un Plan y disfruta de todas las opciones</blockquote>\n\n"
                 "Comparte con tus familiares y amigos el contenido anterior ☝️",
            reply_markup=share_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error sending additional messages: {e}")

async def handle_send_callback(query, context, msg_id):
    """Handle send content callback."""
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    can_forward = user_data and user_data.get('can_forward', False)

    try:
        # Show typing action
        await context.bot.send_chat_action(
            chat_id=query.message.chat_id,
            action=ChatAction.TYPING
        )

        try:
            # Primero, verificar si este mensaje pertenece a una serie
            series_info = db.find_series_by_cover_message_id(msg_id)
            if series_info:
                # Es un mensaje de portada de serie
                series_id = series_info['series_id']
                
                # Obtener el mensaje original del canal para extraer el botón exacto
                try:
                    # Intentamos obtener el mensaje original
                    original_message = None
                    
                    # Intentar obtener del canal SEARCH_CHANNEL_ID
                    try:
                        original_message = await context.bot.forward_message(
                            chat_id=context.bot.id,  # Forward al mismo bot temporalmente
                            from_chat_id=SEARCH_CHANNEL_ID,
                            message_id=msg_id,
                            disable_notification=True
                        )
                        # Borrar el mensaje temporal
                        await context.bot.delete_message(
                            chat_id=context.bot.id,
                            message_id=original_message.message_id
                        )
                    except Exception as forward_error:
                        logger.error(f"Error obteniendo mensaje original: {forward_error}")
                
                    # URL para el botón de serie
                    view_url = f"https://t.me/MultimediaTVbot?start=series_{series_id}"
                    
                except Exception as e:
                    logger.error(f"Error obteniendo mensaje original: {e}")
                    # Si falla, usar la URL estándar
                    view_url = f"https://t.me/MultimediaTVbot?start=series_{series_id}"

                # Copiar mensaje
                message = await context.bot.copy_message(
                    chat_id=query.message.chat_id,
                    from_chat_id=SEARCH_CHANNEL_ID,
                    message_id=msg_id,
                    protect_content=not can_forward
                )

                # Agregar el botón "Ver ahora" con la URL correcta
                keyboard = [
                    [InlineKeyboardButton("Ver ahora", url=view_url)]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                try:
                    # Editar el mensaje enviado para añadir el botón
                    await context.bot.edit_message_reply_markup(
                        chat_id=query.message.chat_id,
                        message_id=message.message_id,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Error añadiendo botón 'Ver ahora': {e}")

                # Enviar mensaje adicional
                await send_additional_messages(context, query.message.chat_id, msg_id, can_forward)

            else:
                # Verificar si es un episodio de serie
                episode_info = db.find_episode_by_message_id(msg_id)

                if episode_info:
                    # Es un episodio, obtener la serie
                    series_id = episode_info['series_id']
                    
                    # URL para ver toda la serie
                    view_url = f"https://t.me/MultimediaTVbot?start=series_{series_id}"

                    # Enviar el episodio
                    message = await context.bot.copy_message(
                        chat_id=query.message.chat_id,
                        from_chat_id=SEARCH_CHANNEL_ID,
                        message_id=msg_id,
                        protect_content=not can_forward
                    )
                    
                    # Agregar el botón "Ver ahora" que lleva a la serie completa
                    keyboard = [
                        [InlineKeyboardButton("Ver ahora", url=view_url)]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    try:
                        # Editar el mensaje enviado para añadir el botón
                        await context.bot.edit_message_reply_markup(
                            chat_id=query.message.chat_id,
                            message_id=message.message_id,
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Error añadiendo botón 'Ver ahora' al episodio: {e}")

                    # Enviar mensaje adicional
                    await send_additional_messages(context, query.message.chat_id, msg_id, can_forward)

                else:
                    # Es contenido normal (película u otro)
                    # URL para acceder directamente al contenido
                    view_url = f"https://t.me/MultimediaTVbot?start=content_{msg_id}"

                    # Copiar mensaje
                    message = await context.bot.copy_message(
                        chat_id=query.message.chat_id,
                        from_chat_id=SEARCH_CHANNEL_ID,
                        message_id=msg_id,
                        protect_content=not can_forward
                    )
                    
                    # Agregar el botón "Ver ahora" con la URL correcta
                    keyboard = [
                        [InlineKeyboardButton("Ver ahora", url=view_url)]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    try:
                        # Editar el mensaje enviado para añadir el botón
                        await context.bot.edit_message_reply_markup(
                            chat_id=query.message.chat_id,
                            message_id=message.message_id,
                            reply_markup=reply_markup
                        )
                    except Exception as e:
                        logger.error(f"Error añadiendo botón 'Ver ahora' al contenido: {e}")

                    # Enviar mensaje adicional
                    await send_additional_messages(context, query.message.chat_id, msg_id, can_forward)

            # Answer the callback query
            await query.answer("Contenido enviado")

            # Update the original message to show which content was selected
            keyboard = query.message.reply_markup.inline_keyboard
            new_keyboard = []
            for row in keyboard:
                new_row = []
                for button in row:
                    if button.callback_data == query.data:
                        # Mark this button as selected
                        new_row.append(InlineKeyboardButton(
                            f"✅ {button.text}",
                            callback_data=button.callback_data
                        ))
                    else:
                        new_row.append(button)
                new_keyboard.append(new_row)

            # Update the message with the new keyboard
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(new_keyboard)
            )

        except Exception as e:
            logger.error(f"Error sending content: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"<blockquote>❌ Error al enviar el contenido: {str(e)[:100]}\n\n"
                     f"Es posible que el canal de búsqueda no esté accesible o que el mensaje ya no exista.</blockquote>",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error handling send callback: {e}")
        await query.answer(f"Error: {str(e)[:200]}")


async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle profile button click with real-time limit information"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await query.edit_message_text(
            "Error al obtener datos del perfil. Intenta con /start",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get user plan details
    plan_type = user_data.get('plan_type', 'basic')
    plan_name = PLANS_INFO.get(plan_type, PLANS_INFO['basic'])['name']
    
    # Calculate expiration date if not on basic plan
    expiration_text = ""
    if plan_type != 'basic':
        if 'plan_expiry' in user_data and user_data['plan_expiry']:
            # Verificar si plan_expiry es una cadena o un objeto datetime
            if isinstance(user_data['plan_expiry'], str):
                try:
                    expiry_date = datetime.strptime(user_data['plan_expiry'], '%Y-%m-%d %H:%M:%S')
                    # Calcular días restantes
                    days_left = (expiry_date - datetime.now()).days
                    expiration_text = f"Expira: {expiry_date.strftime('%d/%m/%Y')} ({days_left} días)\n"
                except ValueError:
                    expiration_text = f"Expira: {user_data['plan_expiry']}\n"
            else:
                days_left = (user_data['plan_expiry'] - datetime.now()).days
                expiration_text = f"Expira: {user_data['plan_expiry'].strftime('%d/%m/%Y')} ({days_left} días)\n"
    
    # Get search and request limits based on plan
    plan_info = PLANS_INFO.get(plan_type, PLANS_INFO['basic'])
    content_limit = plan_info['searches_per_day']
    request_limit = plan_info['requests_per_day']
    
    # Get current usage
    current_searches = user_data.get('daily_searches', 0)
    current_requests = user_data.get('daily_requests', 0)
    
    # Calculate remaining searches and requests
    if content_limit == float('inf'):
        searches_remaining_text = "Ilimitado"
    else:
        searches_remaining = max(0, content_limit - current_searches)
        searches_remaining_text = f"{searches_remaining}/{content_limit}"
    
    if request_limit == float('inf'):
        requests_remaining_text = "Ilimitado"
    else:
        requests_remaining = max(0, request_limit - current_requests)
        requests_remaining_text = f"{requests_remaining}/{request_limit}"
    
    # Calculate next reset time (midnight)
    now = datetime.now()
    next_reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    time_until_reset = next_reset - now
    hours, remainder = divmod(time_until_reset.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    reset_text = f"{hours:02d}:{minutes:02d}"
    
    # Get referral count
    referral_count = db.get_referral_count(user_id)
    
    # Format join date
    join_date = user_data.get('join_date', now.strftime('%Y-%m-%d %H:%M:%S'))
    if isinstance(join_date, str):
        try:
            join_date = datetime.strptime(join_date, '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y')
        except ValueError:
            join_date = now.strftime('%d/%m/%Y')
    elif isinstance(join_date, datetime):
        join_date = join_date.strftime('%d/%m/%Y')
    else:
        join_date = now.strftime('%d/%m/%Y')
    
    # Create profile message with real-time limits
    profile_text = (
        f"👤 <b>Perfil de Usuario</b>\n\n"
        f"<blockquote>Nombre: {query.from_user.first_name}\n"
        f"Saldo: {user_data.get('balance', 0)} 💎\n"
        f"ID: {user_id}\n"
        f"Plan: {plan_name}\n"
        f"{expiration_text}"
        f"Pedidos restantes: {requests_remaining_text}\n"
        f"Búsquedas restantes: {searches_remaining_text}\n"
        f"Fecha de Unión: {join_date}\n"
        f"Referidos: {referral_count}\n</blockquote>"
        f"Reinicio en: {reset_text}\n\n"
        f"🎁 Comparte tu enlace de referido y gana diamantes!"
    )
    
    # Create buttons
    keyboard = [
        [InlineKeyboardButton("Compartir Enlace de referencia 🔗", 
                             url=f"https://t.me/share/url?url=https://t.me/MultimediaTVbot?start=ref_{user_id}&text=¡Únete%20y%20ve%20películas%20conmigo!")],
        [InlineKeyboardButton("Volver 🔙", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=profile_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def handle_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plans button click"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await query.edit_message_text(
            "Error al obtener datos del usuario. Intenta con /start",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get user plan details
    plan_type = user_data.get('plan_type', 'basic')
    plan_name = PLANS_INFO.get(plan_type, PLANS_INFO['basic'])['name']
    
    # Create plans message
    plans_text = (
        f"▧ Planes de Suscripción ▧\n\n"
        f"Tu saldo actual: {user_data.get('balance', 0)} 💎\n"
        f"Plan actual: {plan_name}\n\n"
        f"<blockquote>📋 Planes Disponibles:\n\n</blockquote>"
        f"Pro ✨\n"
        f"150 CUP (Transferencia)\n"
        f"180 CUP (Saldo)\n"
        f"0.49 USD\n\n"
        f"Plus ⭐\n"
        f"600 CUP (Transferencia)\n"
        f"700 CUP (Saldo)\n"
        f"1.99 USD\n\n"
        f"Ultra 🌟\n"
        f"950 CUP (Transferencia)\n"
        f"1100 CUP (Saldo)\n"
        f"2.99 USD\n\n"
        f"<blockquote>Pulsa los botones de debajo para mas info de los planes y formas de pago.</blockquote>"
    )
    
    # Create buttons
    keyboard = [
        [
            InlineKeyboardButton("Plan pro ✨", callback_data="plan_pro"),
            InlineKeyboardButton("Plan plus ⭐", callback_data="plan_plus"),
            InlineKeyboardButton("Plan ultra 🌟", callback_data="plan_ultra")
        ],
        [InlineKeyboardButton("Volver 🔙", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=plans_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def handle_plan_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plan details button clicks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    callback_data = query.data
    
    if not user_data:
        await query.edit_message_text(
            "Error al obtener datos del usuario. Intenta con /start",
            parse_mode=ParseMode.HTML
        )
        return
    
    plan_details = ""
    if callback_data == "plan_pro":
        plan_details = (
            f"💫 <b>Plan Pro - Detalles</b> 💫\n\n"
            f"<blockquote>"
            f"Precio: 150\n"
            f"Duración: 30 días\n\n"
            f"Beneficios:\n"
            f"└ 2 pedidos diarios\n"
            f"└ 15 películas o series al día\n"
            f"└ No puede reenviar contenido ni guardarlo\n\n"
            f"</blockquote>"
            f"Tu saldo actual: {user_data.get('balance', 0)} 💎"
        )
    elif callback_data == "plan_plus":
        plan_details = (
            f"💫 <b>Plan Plus - Detalles</b> 💫\n\n"
            f"<blockquote>"
            f"Precio: 500\n"
            f"Duración: 30 días\n\n"
            f"Beneficios:\n"
            f"└ 10 pedidos diarios\n"
            f"└ 50 películas o series al día\n"
            f"└ Soporte prioritario\n"
            f"└ Enlaces directos de descarga\n"
            f"└ Acceso a contenido exclusivo\n\n"
            f"</blockquote>"
            f"Tu saldo actual: {user_data.get('balance', 0)} 💎"
        )
    elif callback_data == "plan_ultra":
        plan_details = (
            f"⭐ <b>Plan Ultra - Detalles</b> ⭐\n\n"
            f"<blockquote>"
            f"Precio: 950\n"
            f"Duración: 30 días\n\n"
            f"Beneficios:\n"
            f"└ Pedidos ilimitados\n"
            f"└ Sin restricciones de contenido\n"
            f"└ Reenvío y guardado permitido\n"
            f"└ Enlaces directos de descarga\n"
            f"└ Soporte VIP\n"
            f"└ Acceso anticipado a nuevo contenido\n\n"
            f"</blockquote>"
            f"Tu saldo actual: {user_data.get('balance', 0)} 💎"
        )
    
    # Create buttons
    keyboard = [
        [
            InlineKeyboardButton("Cup (Cuba 🇨🇺)", callback_data=f"{callback_data}_cup"),
            InlineKeyboardButton("Crypto", callback_data=f"{callback_data}_crypto")
        ],
        [InlineKeyboardButton("Volver 🔙", callback_data="plans")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=plan_details,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment method selection"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    plan_type, payment_method = callback_data.rsplit('_', 1)
    
    payment_info = ""
    if payment_method == "cup":
        if plan_type == "plan_pro":
            payment_info = (
                f"<blockquote><b>Pago en CUP (Transferencia)</b>\n"
                f"Precio: 150 CUP\n</blockquote>"
                f"<blockquote><b>Pago en CUP (Saldo)</b>\n"
                f"Precio: 180 CUP\n</blockquote>"
                f"Detalles de pago:\n"
                f"Número: <code>9205 1299 7736 4067\n</code>"
                f"Telef: <code>55068190\n\n</code>"
                f"<blockquote>⚠️ Después de realizar el pago, mandar captura del pago a @osvaldo20032 para activar tu plan.</blockquote>"
            )
        elif plan_type == "plan_plus":
            payment_info = (
                f"<blockquote><b>Pago en CUP (Transferencia)</b>\n"
                f"Precio: 600 CUP\n</blockquote>"
                f"<blockquote><b>Pago en CUP (Saldo)</b>\n"
                f"Precio: 700 CUP\n</blockquote>"
                f"Detalles de pago:\n"
                f"Número: <code>9205 1299 7736 4067\n</code>"
                f"Telef: <code>55068190\n\n</code>"
                f"<blockquote>⚠️ Después de realizar el pago, mandar captura del pago a @osvaldo20032 para activar tu plan.</blockquote>"
            )
        elif plan_type == "plan_ultra":
            payment_info = (
                f"<blockquote><b>Pago en CUP (Transferencia)</b>\n"
                f"Precio: 950 CUP\n</blockquote>"
                f"<blockquote><b>Pago en CUP (Saldo)</b>\n"
                f"Precio: 1100 CUP\n</blockquote>"
                f"Detalles de pago:\n"
                f"Número: <code>9205 1299 7736 4067\n</code>"
                f"Telef: <code>55068190\n\n</code>"
                f"<blockquote>⚠️ Después de realizar el pago, mandar captura del pago a @osvaldo20032 para activar tu plan.</blockquote>"
            )
    elif payment_method == "crypto":
        if plan_type == "plan_pro":
            payment_info = (
                f"<blockquote><b>Pago con USDT (BEP 20)</b>\n"
                f"Precio: 0.49 USDTT\n</blockquote>"
                f"Detalles de pago:\n"
                f"Dirección: <code>0x26d89897c4e452C7BD3a0B8Aa79dD84E516BD4c6\n\n</code>"
                f"<blockquote>⚠️ Después de realizar el pago, mandar captura del pago a @osvaldo20032 para activar tu plan.</blockquote>"
            )
        elif plan_type == "plan_plus":
            payment_info = (
                f"<blockquote><b>Pago con USDT (BEP 20)</b>\n"
                f"Precio: 1.99 USDTT\n</blockquote>"
                f"Detalles de pago:\n"
                f"Dirección: <code>0x26d89897c4e452C7BD3a0B8Aa79dD84E516BD4c6\n\n</code>"
                f"<blockquote>⚠️ Después de realizar el pago, mandar captura del pago a @osvaldo20032 para activar tu plan.</blockquote>"
            )
        elif plan_type == "plan_ultra":
            payment_info = (
                f"<blockquote><b>Pago con USDT (BEP 20)</b>\n"
                f"Precio: 2.99 USDTT\n</blockquote>"
                f"Detalles de pago:\n"
                f"Dirección: <code>0x26d89897c4e452C7BD3a0B8Aa79dD84E516BD4c6\n\n</code>"
                f"<blockquote>⚠️ Después de realizar el pago, mandar captura del pago a @osvaldo20032 para activar tu plan.</blockquote>"
            )
    
    # Create back button
    keyboard = [
        [InlineKeyboardButton("Volver 🔙", callback_data=plan_type)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=payment_info,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def handle_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle info button click"""
    query = update.callback_query
    await query.answer()
    
    info_text = (
        "🤖 Funcionamiento del bot:\n\n"
        "<b>Comandos:</b>\n"
        "📎 <code>/start</code> - Inicia el bot y muestra el menú principal\n"
        "🔍 <code>/search</code> [texto] - Busca películas o series\n"
        "📝 <code>/pedido</code> [año] [nombre] - Realiza una solicitud de contenido (ej: /pedido 2024 Avatar 3)\n"
        "🎁 <code>/gift_code</code> [código] - Canjea un código de regalo para obtener un plan premium\n\n"
        "<blockquote>📌 Notas importantes:\n"
        "• Si el contenido no se encuentra, podrás hacer un pedido\n"
        "• Plan básico: 3 búsquedas y 1 pedido diario\n"
        "• Sin plan premium, no podrás reenviar contenido</blockquote>"
    )
    
    # Create back button
    keyboard = [
        [InlineKeyboardButton("Volver 🔙", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=info_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def handle_request_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle request type selection"""
    query = update.callback_query
    await query.answer()
    
    # Obtener el tipo de pedido y nombre del contenido
    _, content_type, content_name = query.data.split('_', 2)
    
    # Guardar el tipo y nombre en el contexto del usuario
    context.user_data['request_type'] = content_type
    context.user_data['request_content'] = content_name
    
    # Crear nuevo teclado con el botón seleccionado marcado
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Película 🎞️" if content_type == 'movie' else "Película 🎞️",
                callback_data=f"req_movie_{content_name}"
            ),
            InlineKeyboardButton(
                "✅ Serie 📺" if content_type == 'series' else "Serie 📺",
                callback_data=f"req_series_{content_name}"
            )
        ],
        [InlineKeyboardButton("Hacer Pedido 📡", callback_data="make_request")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Actualizar mensaje con el botón seleccionado
    await query.edit_message_text(
        text=f"Has seleccionado: <b>{content_type.capitalize()}</b>\n"
             f"Contenido: <b>{content_name}</b>\n\n"
             f"<blockquote>Ahora haz clic en 'Hacer Pedido 📡' para enviar tu solicitud.</blockquote>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def handle_make_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle make request button click"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await query.edit_message_text(
            "❌ Error: Usuario no registrado. Usa /start para registrarte.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Verificar que se haya seleccionado un tipo de contenido
    request_type = context.user_data.get('request_type')
    content_name = context.user_data.get('request_content')
    
    if not request_type or not content_name:
        await query.edit_message_text(
            "❌ Error: Debes seleccionar primero el tipo de contenido (Película o Serie).",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Verificar límites de pedidos
    requests_left = db.get_requests_left(user_id)
    if requests_left <= 0:
        # Mostrar opciones de planes si se alcanzó el límite
        keyboard = []
        for plan_id, plan in PLANS_INFO.items():
            if plan_id != 'basic':
                keyboard.append([
                    InlineKeyboardButton(
                        f"{plan['name']} - {plan['price']}",
                        callback_data=f"buy_plan_{plan_id}"
                    )
                ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❌ Has alcanzado tu límite de pedidos diarios.\n\n"
            "<blockquote>Para realizar más pedidos, adquiere un plan premium:</blockquote>",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        # Actualizar contador de pedidos
        db.update_request_count(user_id)
        
        # Crear botón de aceptar para el admin
        keyboard = [
            [InlineKeyboardButton("Aceptar ✅", callback_data=f"accept_req_{user_id}_{content_name}")]
        ]
        admin_markup = InlineKeyboardMarkup(keyboard)
        
        # Obtener año actual si no se especifica
        current_year = datetime.now().year
        
        # Enviar pedido a los administradores
        admin_messages_sent = False
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"<blockquote>📩 <b>Nuevo Pedido</b>\n\n</blockquote>"
                         f"Usuario: {query.from_user.first_name} (@{query.from_user.username})\n"
                         f"ID: {user_id}\n"
                         f"Tipo: {request_type.capitalize()}\n"
                         f"Año: {current_year}\n"  # Usando el año actual
                         f"Nombre: {content_name}",
                    reply_markup=admin_markup,
                    parse_mode=ParseMode.HTML
                )
                admin_messages_sent = True
            except Exception as e:
                logger.error(f"Error enviando pedido al admin {admin_id}: {e}")
                continue
        
        if not admin_messages_sent:
            raise Exception("No se pudo enviar el mensaje a ningún administrador")
        
        # Confirmar al usuario
        await query.edit_message_text(
            f"✅ Tu pedido ha sido enviado correctamente:\n\n"
            f"<blockquote>Tipo: {request_type.capitalize()}\n"
            f"Nombre: {content_name}\n"
            f"Te quedan {requests_left-1} pedidos hoy.\n\n"
            f"Te notificaremos cuando el contenido esté disponible.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error procesando pedido: {e}")
        await query.edit_message_text(
            "❌ Error al procesar el pedido. Por favor, intenta nuevamente.",
            parse_mode=ParseMode.HTML
        )

async def handle_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin accepting a content request"""
    query = update.callback_query
    await query.answer()
    
    # Verificar que el usuario es administrador
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("⚠️ Solo los administradores pueden aceptar pedidos.", show_alert=True)
        return
    
    try:
        # Extraer información del callback_data
        # Formato: accept_req_USER_ID_CONTENT_NAME
        parts = query.data.split('_', 3)  # Dividir en máximo 4 partes
        if len(parts) < 4:
            raise ValueError("Formato de callback inválido")
            
        user_id = int(parts[2])
        content_name = parts[3]
        
        # Notificar al usuario que su pedido fue aceptado
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ ¡Buenas noticias! Tu solicitud para '<b>{content_name}</b>' ha sido aceptada.\n\n"
                     f"<blockquote>El contenido estará disponible pronto en el bot.\n"
                     f"Podrás encontrarlo usando /search {content_name}</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            # Actualizar el mensaje del admin
            new_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Pedido Aceptado", callback_data="dummy")
            ]])
            
            await query.edit_message_text(
                text=f"{query.message.text}\n\n"
                     f"<blockquote>✅ Pedido aceptado y usuario notificado</blockquote>",
                reply_markup=new_keyboard,
                parse_mode=ParseMode.HTML
            )
            
        except Exception as e:
            logger.error(f"Error notificando al usuario {user_id}: {e}")
            await query.edit_message_text(
                text=f"{query.message.text}\n\n"
                     f"<blockquote>⚠️ Pedido aceptado pero no se pudo notificar al usuario</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
    except Exception as e:
        logger.error(f"Error handling accept request: {e}")
        await query.edit_message_text(
            text=f"{query.message.text}\n\n"
            f"<blockquote>❌ Error al procesar la aceptación del pedido: {str(e)[:100]}</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def set_user_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to set a user's plan"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    # Check arguments
    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso: /plan @username número_de_plan\n"
            "1 - Plan Pro\n"
            "2 - Plan Plus\n"
            "3 - Plan Ultra",
            parse_mode=ParseMode.HTML
        )
        return
    
    username = context.args[0].replace('@', '')
    try:
        plan_number = int(context.args[1])
        if plan_number not in [1, 2, 3]:
            raise ValueError("Número de plan inválido")
        
        plan_map = {1: 'pro', 2: 'plus', 3: 'ultra'}
        plan_type = plan_map[plan_number]
        
        # Get user_id from username
        user_id = db.get_user_id_by_username(username)
        if not user_id:
            await update.message.reply_text(f"Usuario @{username} no encontrado en la base de datos.",
                                          parse_mode=ParseMode.HTML)
            return
        
        # Update user's plan
        expiry_date = datetime.now() + timedelta(days=30)
        db.update_plan(user_id, plan_type, expiry_date)
        
        # Notify user about plan change
        plan_name = PLANS_INFO[plan_type]['name']
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 ¡Felicidades! Tu plan ha sido actualizado a <b>{plan_name}</b>.\n"
                     f"<blockquote>Expira el: {expiry_date.strftime('%d/%m/%Y')}\n"
                     f"Disfruta de todos los beneficios de tu nuevo plan.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error notifying user about plan change: {e}")
        
        await update.message.reply_text(
            f"Plan de @{username} actualizado a <b>{plan_name}</b>.\n"
            f"Expira el: {expiry_date.strftime('%d/%m/%Y')}",
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await update.message.reply_text(
            "Número de plan inválido. Debe ser 1, 2 o 3.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error setting user plan: {e}")
        await update.message.reply_text(
            "Error al actualizar el plan del usuario.",
            parse_mode=ParseMode.HTML
        )
        
async def download_high_quality_image(url):
    """Descarga imagen en alta calidad y devuelve los bytes"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Verificar que realmente es una imagen
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            raise ValueError(f"El contenido no es una imagen: {content_type}")
            
        return BytesIO(response.content)
    except Exception as e:
        logger.error(f"Error descargando imagen: {e}")
        return None

async def add_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to create a gift code"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    # Check arguments
    if len(context.args) < 3:
        await update.message.reply_text(
            "Uso: /addgift_code código plan_number max_uses\n"
            "<blockquote>Ejemplo: /addgift_code 2432 3 1\n"
            "1 - Plan Pro\n"
            "2 - Plan Plus\n"
            "3 - Plan Ultra</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        code = context.args[0]
        plan_number = int(context.args[1])
        max_uses = int(context.args[2])
        
        if plan_number not in [1, 2, 3]:
            raise ValueError("Número de plan inválido")
        
        plan_map = {1: 'pro', 2: 'plus', 3: 'ultra'}
        plan_type = plan_map[plan_number]
        
        # Add gift code to database
        db.add_gift_code(code, plan_type, max_uses)
        
        await update.message.reply_text(
            f"Código de regalo '<b>{code}</b>' creado para el plan <b>{PLANS_INFO[plan_type]['name']}</b>.\n"
            f"Usos máximos: {max_uses}",
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await update.message.reply_text(
            "Formato inválido. Usa /addgift_code código plan_number max_uses",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error adding gift code: {e}")
        await update.message.reply_text(
            "Error al crear el código de regalo.",
            parse_mode=ParseMode.HTML
        )

async def redeem_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to redeem a gift code"""
    user_id = update.effective_user.id
    
    # Check arguments
    if not context.args:
        await update.message.reply_text(
            "Uso: /gift_code código\n"
            "Uso: /gift_code código\n"
            "Ejemplo: /gift_code 2432",
            parse_mode=ParseMode.HTML
        )
        return
    
    code = context.args[0]
    
    try:
        # Check if code exists and is valid
        gift_code_data = db.get_gift_code(code)
        if not gift_code_data:
            await update.message.reply_text(
                "Código de regalo inválido o ya ha sido utilizado.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Update user's plan
        plan_type = gift_code_data['plan_type']
        expiry_date = datetime.now() + timedelta(days=30)
        db.update_plan(user_id, plan_type, expiry_date)
        
        # Update gift code usage
        db.update_gift_code_usage(code)
        
        # Notify user
        plan_name = PLANS_INFO[plan_type]['name']
        await update.message.reply_text(
            f"🎉 ¡Felicidades! Has canjeado un código de regalo.\n"
            f"<blockquote>Tu plan ha sido actualizado a <b>{plan_name}</b>.\n"
            f"Expira el: {expiry_date.strftime('%d/%m/%Y')}\n"
            f"Disfruta de todos los beneficios de tu nuevo plan.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error redeeming gift code: {e}")
        await update.message.reply_text(
            "Error al canjear el código de regalo. Intenta más tarde.",
            parse_mode=ParseMode.HTML
        )

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to ban a user"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    # Check arguments
    if not context.args:
        await update.message.reply_text(
            "Uso: /ban @username o /ban user_id",
            parse_mode=ParseMode.HTML
        )
        return
    
    target = context.args[0]
    
    try:
        # Check if target is username or user_id
        if target.startswith('@'):
            username = target.replace('@', '')
            user_id = db.get_user_id_by_username(username)
            if not user_id:
                await update.message.reply_text(f"Usuario {target} no encontrado.",
                                              parse_mode=ParseMode.HTML)
                return
        else:
            try:
                user_id = int(target)
                if not db.user_exists(user_id):
                    await update.message.reply_text(f"Usuario con ID {user_id} no encontrado.",
                                                  parse_mode=ParseMode.HTML)
                    return
            except ValueError:
                await update.message.reply_text("Formato inválido. Usa /ban @username o /ban user_id",
                                              parse_mode=ParseMode.HTML)
                return
        
        # Ban user
        db.ban_user(user_id)
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⛔ Has sido baneado del bot MultimediaTv. Si crees que es un error, contacta al administrador.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error notifying banned user: {e}")
        
        await update.message.reply_text(f"Usuario con ID {user_id} ha sido baneado.",
                                      parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        await update.message.reply_text(
            "Error al banear al usuario.",
            parse_mode=ParseMode.HTML
        )

async def upload_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to upload content to both search and main channels"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    # Check if message is a reply to a media message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "Este comando debe ser usado respondiendo a un mensaje que contenga "
            "la película, serie o imagen con su descripción.",
            parse_mode=ParseMode.HTML
        )
        return
    
    original_message = update.message.reply_to_message
    status_message = await update.message.reply_text("Procesando subida a múltiples canales...",
                                                   parse_mode=ParseMode.HTML)
    
    try:
        # Resultados para informar al admin
        results = []
        content_IDS = []
        
        # 1. Verificar acceso a los canales
        try:
            await context.bot.get_chat(chat_id=SEARCH_CHANNEL_ID)
            await context.bot.get_chat(chat_id=CHANNEL_ID)
        except Exception as e:
            await status_message.edit_text(
                f"❌ Error al acceder a los canales. Verifica que el bot sea administrador de ambos canales.\n"
                f"Error: {str(e)}",
                parse_mode=ParseMode.HTML
            )
            return
        
        # 2. Enviar al canal de búsqueda (SEARCH_CHANNEL_ID)
        try:
            search_msg = await context.bot.copy_message(
                chat_id=SEARCH_CHANNEL_ID,
                from_chat_id=update.effective_chat.id,
                message_id=original_message.message_id
            )
            
            content_IDS.append(search_msg.message_id)
            results.append(f"✅ Canal de búsqueda: Enviado (ID: #{search_msg.message_id})")
            
            # Generar URL y botón para el canal de búsqueda
            share_url = f"https://t.me/MultimediaTVbot?start=content_{search_msg.message_id}"
            keyboard = [
                [InlineKeyboardButton("Ver", url=share_url)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Añadir botón al mensaje en el canal de búsqueda
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=SEARCH_CHANNEL_ID,
                    message_id=search_msg.message_id,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Error añadiendo botón al canal de búsqueda: {e}")
                results.append(f"⚠️ Canal de búsqueda: Enviado pero sin botón 'Ver'")
        
        except Exception as e:
            logger.error(f"Error enviando al canal de búsqueda: {e}")
            results.append(f"❌ Canal de búsqueda: Error al enviar - {str(e)[:50]}")
        
        # 3. Enviar al canal principal (CHANNEL_ID)
        try:
            channel_msg = await context.bot.copy_message(
                chat_id=CHANNEL_ID,
                from_chat_id=update.effective_chat.id,
                message_id=original_message.message_id
            )
            
            content_IDS.append(channel_msg.message_id)
            results.append(f"✅ Canal principal: Enviado (ID: #{channel_msg.message_id})")
            
            # Usar el mismo botón para el canal principal si se envió correctamente al canal de búsqueda
            if len(content_IDS) > 0:
                share_url = f"https://t.me/MultimediaTVbot?start=content_{content_IDS[0]}"
                keyboard = [
                    [InlineKeyboardButton("Ver", url=share_url)]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Añadir botón al mensaje en el canal principal
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=CHANNEL_ID,
                        message_id=channel_msg.message_id,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Error añadiendo botón al canal principal: {e}")
                    results.append(f"⚠️ Canal principal: Enviado pero sin botón 'Ver'")
            
        except Exception as e:
            logger.error(f"Error enviando al canal principal: {e}")
            results.append(f"❌ Canal principal: Error al enviar - {str(e)[:50]}")
        
        # 4. Informar al administrador del resultado
        result_text = "📤 <b>Resultado de la subida:</b>\n\n" + "\n".join(results)
        
        if len(content_IDS) > 0:
            result_text += "\n\n✅ Contenido subido a " + str(len(content_IDS)) + " canal(es)"
            if len(content_IDS) == 2:
                result_text += "\n\nEl botón 'Ver' utilizará el ID del canal de búsqueda en ambos mensajes."
        else:
            result_text += "\n\n❌ Error: No se pudo subir el contenido a ningún canal"
        
        await status_message.edit_text(result_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error general en upload_content: {e}")
        await status_message.edit_text(
            f"❌ Error general al procesar la subida: {str(e)}\nIntenta más tarde.",
            parse_mode=ParseMode.HTML
        )

async def request_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to request a specific movie or series"""
    user_id = update.effective_user.id
    
    # Check arguments
    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso: /pedido Tipo (Pelicula o Serie) año nombre_del_contenido\n"
            "<blockquote>Ejemplo: /pedido Pelicula 2024 Avatar 3</blockquote>"
            "<blockquote>Debes enviar el Formato correcto, de lo contrario su solicitud no sera atendida</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user is banned
    if db.is_user_banned(user_id):
        await update.message.reply_text(
            "<blockquote>❌ No puedes realizar pedidos porque has sido baneado del bot.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user has requests left
    requests_left = db.get_requests_left(user_id)
    if requests_left <= 0:
        keyboard = []
        for plan_id, plan in PLANS_INFO.items():
            if plan_id != 'basic':
                keyboard.append([
                    InlineKeyboardButton(
                        f"{plan['name']} - {plan['price']}",
                        callback_data=f"buy_plan_{plan_id}"
                    )
                ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ Has alcanzado el límite de pedidos diarios para tu plan.\n"
            "<blockquote>Considera actualizar tu plan para obtener más pedidos:</blockquote>",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
    
    year = context.args[0]
    content_name = " ".join(context.args[1:])
    
    # Update user's request count
    db.update_request_count(user_id)
    
    try:
        # Try AI automation first if enabled
        global AI_AUTO_ENABLED
        ai_processed = False
        if AI_AUTO_ENABLED:
            ai_processed = await auto_process_request(update, context, user_id, year, content_name)
        
        # If AI didn't auto-accept or AI is disabled, send to admins for manual review
        if not ai_processed:
            # Crear botones para administrador
            keyboard = [
                [InlineKeyboardButton("Aceptar ✅", callback_data=f"accept_req_{user_id}_{content_name}")]
            ]
            admin_markup = InlineKeyboardMarkup(keyboard)
            
            # Enviar solicitud a cada administrador
            admin_messages_sent = False
            for admin_id in ADMIN_IDS:  # ADMIN_IDS es una lista definida al inicio
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"<blockquote>📩 <b>Nuevo Pedido</b>\n\n</blockquote>"
                             f"Usuario: {update.effective_user.first_name} (@{update.effective_user.username})\n"
                             f"ID: {user_id}\n"
                             f"Año: {year}\n"
                             f"Nombre: {content_name}",
                        reply_markup=admin_markup,
                        parse_mode=ParseMode.HTML
                    )
                    admin_messages_sent = True
                except Exception as e:
                    logger.error(f"Error enviando mensaje al admin {admin_id}: {e}")
                    continue
            
            if not admin_messages_sent:
                raise Exception("No se pudo enviar el mensaje a ningún administrador")
        
        # Confirm to user (different message if AI processed)
        if ai_processed:
            await update.message.reply_text(
                f"🤖 Tu pedido '<b>{content_name}</b>' ({year}) ha sido procesado automáticamente por IA.\n"
                f"<blockquote>✅ El pedido fue aceptado automáticamente.\n"
                f"🔍 Buscaremos el contenido y te notificaremos cuando esté disponible.\n"
                f"Te quedan {requests_left-1} pedidos hoy.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"✅ Tu pedido '<b>{content_name}</b>' ({year}) ha sido enviado al administrador.\n"
                f"<blockquote>Te notificaremos cuando esté disponible.\n"
                f"Te quedan {requests_left-1} pedidos hoy.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        
    except Exception as e:
        logger.error(f"Error al enviar la solicitud al administrador: {e}")
        await update.message.reply_text(
            "<blockquote>❌ Error al enviar el pedido. Por favor, intenta más tarde.</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to show all available commands"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    help_text = (
        "<b>📋 Comandos de Administrador 📋</b>\n\n"
        "Gestión de Usuarios:\n"
        "/plan @username número_plan - Asigna un plan a un usuario\n"
        "   1 - Plan Pro\n"
        "   2 - Plan Plus\n"
        "   3 - Plan Ultra\n\n"
        "/ban @username - Banea a un usuario\n\n"
        "Gestión de Contenido:\n"
        "/up - Responde a un mensaje con este comando para subirlo al canal\n\n"
        "Códigos de Regalo:\n"
        "/addgift_code código plan_number max_uses - Crea un código de regalo\n"
        "   Ejemplo: /addgift_code 2432 3 1\n\n"
        "Estadísticas:\n"
        "/stats - Muestra estadísticas del bot\n\n"
        "Comunicación:\n"
        "/broadcast mensaje - Envía un mensaje a todos los usuarios\n\n"
        "🤖 Automatización IA:\n"
        "/ai_auto on/off - Activa/desactiva la automatización IA\n"
        "/ai_status - Muestra el estado de la automatización IA\n"
        "/ai_config - Configura parámetros de la IA"
    )
    
    await update.message.reply_text(text=help_text, parse_mode=ParseMode.HTML)

# AI Automation System
AI_AUTO_ENABLED = False
AI_CONFIG = {
    'auto_accept_threshold': 0.8,  # Umbral de confianza para auto-aceptar
    'auto_search_enabled': True,   # Búsqueda automática en IMDb
    'auto_notify_enabled': True,   # Notificaciones automáticas
    'processing_delay': 2          # Delay en segundos entre procesamiento
}

async def ai_auto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to enable/disable AI automation"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    global AI_AUTO_ENABLED
    
    if not context.args:
        await update.message.reply_text(
            "Uso: /ai_auto on/off\n"
            f"Estado actual: {'🟢 Activado' if AI_AUTO_ENABLED else '🔴 Desactivado'}",
            parse_mode=ParseMode.HTML
        )
        return
    
    action = context.args[0].lower()
    
    if action == 'on':
        AI_AUTO_ENABLED = True
        await update.message.reply_text(
            "🤖 <b>Automatización IA Activada</b>\n\n"
            "<blockquote>✅ El sistema ahora procesará automáticamente:\n"
            "• Análisis de pedidos con IA\n"
            "• Búsqueda automática en IMDb\n"
            "• Aceptación automática de pedidos válidos\n"
            "• Notificaciones inteligentes</blockquote>",
            parse_mode=ParseMode.HTML
        )
    elif action == 'off':
        AI_AUTO_ENABLED = False
        await update.message.reply_text(
            "🔴 <b>Automatización IA Desactivada</b>\n\n"
            "<blockquote>❌ El sistema vuelve al modo manual:\n"
            "• Los pedidos requerirán aprobación manual\n"
            "• No habrá búsqueda automática\n"
            "• Todas las acciones serán manuales</blockquote>",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            "❌ Opción inválida. Usa: /ai_auto on/off",
            parse_mode=ParseMode.HTML
        )

async def ai_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to show AI automation status"""
    global AI_AUTO_ENABLED, AI_CONFIG
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    status_icon = "🟢" if AI_AUTO_ENABLED else "🔴"
    status_text = "Activado" if AI_AUTO_ENABLED else "Desactivado"
    
    config_text = (
        f"🤖 <b>Estado de Automatización IA</b>\n\n"
        f"Estado: {status_icon} <b>{status_text}</b>\n\n"
        f"<b>Configuración Actual:</b>\n"
        f"• Umbral de auto-aceptación: {AI_CONFIG['auto_accept_threshold']*100}%\n"
        f"• Búsqueda automática: {'✅' if AI_CONFIG['auto_search_enabled'] else '❌'}\n"
        f"• Notificaciones automáticas: {'✅' if AI_CONFIG['auto_notify_enabled'] else '❌'}\n"
        f"• Delay de procesamiento: {AI_CONFIG['processing_delay']}s\n\n"
        f"<blockquote>💡 Usa /ai_config para modificar la configuración</blockquote>"
    )
    
    await update.message.reply_text(text=config_text, parse_mode=ParseMode.HTML)

async def ai_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to configure AI automation parameters"""
    global AI_CONFIG
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    if not context.args:
        await update.message.reply_text(
            "<b>🔧 Configuración de IA</b>\n\n"
            "Comandos disponibles:\n"
            "/ai_config threshold 0.8 - Establece umbral de confianza (0.1-1.0)\n"
            "/ai_config search on/off - Activa/desactiva búsqueda automática\n"
            "/ai_config notify on/off - Activa/desactiva notificaciones automáticas\n"
            "/ai_config delay 2 - Establece delay de procesamiento (1-10s)\n\n"
            "<blockquote>Ejemplo: /ai_config threshold 0.9</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Faltan parámetros. Usa /ai_config sin argumentos para ver la ayuda.",
            parse_mode=ParseMode.HTML
        )
        return
    
    param = context.args[0].lower()
    value = context.args[1].lower()
    
    try:
        if param == 'threshold':
            threshold = float(value)
            if 0.1 <= threshold <= 1.0:
                AI_CONFIG['auto_accept_threshold'] = threshold
                await update.message.reply_text(
                    f"✅ Umbral de auto-aceptación establecido en {threshold*100}%",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    "❌ El umbral debe estar entre 0.1 y 1.0",
                    parse_mode=ParseMode.HTML
                )
        
        elif param == 'search':
            if value in ['on', 'off']:
                AI_CONFIG['auto_search_enabled'] = value == 'on'
                status = "activada" if value == 'on' else "desactivada"
                await update.message.reply_text(
                    f"✅ Búsqueda automática {status}",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    "❌ Usa 'on' o 'off' para la búsqueda automática",
                    parse_mode=ParseMode.HTML
                )
        
        elif param == 'notify':
            if value in ['on', 'off']:
                AI_CONFIG['auto_notify_enabled'] = value == 'on'
                status = "activadas" if value == 'on' else "desactivadas"
                await update.message.reply_text(
                    f"✅ Notificaciones automáticas {status}",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    "❌ Usa 'on' o 'off' para las notificaciones automáticas",
                    parse_mode=ParseMode.HTML
                )
        
        elif param == 'delay':
            delay = int(value)
            if 1 <= delay <= 10:
                AI_CONFIG['processing_delay'] = delay
                await update.message.reply_text(
                    f"✅ Delay de procesamiento establecido en {delay} segundos",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    "❌ El delay debe estar entre 1 y 10 segundos",
                    parse_mode=ParseMode.HTML
                )
        
        else:
            await update.message.reply_text(
                "❌ Parámetro desconocido. Usa /ai_config para ver la ayuda.",
                parse_mode=ParseMode.HTML
            )
    
    except ValueError:
        await update.message.reply_text(
            "❌ Valor inválido. Verifica el formato del parámetro.",
            parse_mode=ParseMode.HTML
        )

async def analyze_request_with_ai(content_name: str, year: str) -> dict:
    """Analyze a content request using AI logic"""
    try:
        # Simulated AI analysis - In a real implementation, this would use actual AI
        confidence_score = 0.0
        analysis_result = {
            'confidence': confidence_score,
            'is_valid': False,
            'content_type': 'unknown',
            'normalized_name': content_name.strip(),
            'recommendations': []
        }
        
        # Basic validation rules
        if len(content_name.strip()) < 2:
            analysis_result['recommendations'].append("Nombre muy corto")
            return analysis_result
        
        # Check if year is valid
        try:
            year_int = int(year)
            if 1900 <= year_int <= 2030:
                confidence_score += 0.3
            else:
                analysis_result['recommendations'].append("Año inválido")
        except:
            analysis_result['recommendations'].append("Año no numérico")
        
        # Check content name patterns
        content_lower = content_name.lower()
        
        # Movie indicators
        movie_keywords = ['pelicula', 'movie', 'film']
        series_keywords = ['serie', 'series', 'temporada', 'season']
        
        if any(keyword in content_lower for keyword in movie_keywords):
            analysis_result['content_type'] = 'movie'
            confidence_score += 0.2
        elif any(keyword in content_lower for keyword in series_keywords):
            analysis_result['content_type'] = 'series'
            confidence_score += 0.2
        
        # Check for common valid patterns
        if len(content_name.split()) >= 2:  # At least 2 words
            confidence_score += 0.2
        
        # Check for special characters that might indicate spam
        spam_chars = ['@', '#', 'http', 'www', '.com']
        if any(char in content_lower for char in spam_chars):
            confidence_score -= 0.5
            analysis_result['recommendations'].append("Contiene caracteres sospechosos")
        
        # Final confidence calculation
        analysis_result['confidence'] = max(0.0, min(1.0, confidence_score))
        analysis_result['is_valid'] = analysis_result['confidence'] >= AI_CONFIG['auto_accept_threshold']
        
        return analysis_result
        
    except Exception as e:
        logger.error(f"Error in AI analysis: {e}")
        return {
            'confidence': 0.0,
            'is_valid': False,
            'content_type': 'unknown',
            'normalized_name': content_name,
            'recommendations': ['Error en análisis']
        }

async def auto_process_request(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, year: str, content_name: str):
    """Automatically process a request using AI"""
    global AI_AUTO_ENABLED, AI_CONFIG
    if not AI_AUTO_ENABLED:
        return False
    
    try:
        # Add processing delay
        await asyncio.sleep(AI_CONFIG['processing_delay'])
        
        # Analyze request with AI
        analysis = await analyze_request_with_ai(content_name, year)
        
        # Send analysis to admins
        analysis_text = (
            f"🤖 <b>Análisis IA del Pedido</b>\n\n"
            f"Usuario: {update.effective_user.first_name} (@{update.effective_user.username})\n"
            f"Contenido: {content_name} ({year})\n\n"
            f"<b>Resultados del Análisis:</b>\n"
            f"• Confianza: {analysis['confidence']*100:.1f}%\n"
            f"• Tipo: {analysis['content_type']}\n"
            f"• Válido: {'✅' if analysis['is_valid'] else '❌'}\n"
        )
        
        if analysis['recommendations']:
            analysis_text += f"\n<b>Recomendaciones:</b>\n"
            for rec in analysis['recommendations']:
                analysis_text += f"• {rec}\n"
        
        # Auto-accept if confidence is high enough
        if analysis['is_valid'] and AI_CONFIG['auto_search_enabled']:
            analysis_text += f"\n🟢 <b>PEDIDO AUTO-ACEPTADO</b>"
            
            # Auto-notify user
            if AI_CONFIG['auto_notify_enabled']:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🤖 <b>Pedido Procesado Automáticamente</b>\n\n"
                             f"Tu pedido '<b>{content_name}</b>' ({year}) ha sido aceptado automáticamente por nuestro sistema IA.\n"
                             f"<blockquote>✅ Confianza del análisis: {analysis['confidence']*100:.1f}%\n"
                             f"🔍 Buscaremos el contenido y te notificaremos cuando esté disponible.</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error notifying user about auto-acceptance: {e}")
        else:
            analysis_text += f"\n🟡 <b>REQUIERE REVISIÓN MANUAL</b>"
        
        # Send analysis to admins
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=analysis_text,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error sending AI analysis to admin {admin_id}: {e}")
        
        return analysis['is_valid']
        
    except Exception as e:
        logger.error(f"Error in auto-processing request: {e}")
        return False

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to show bot statistics"""
    user = update.effective_user
    
    # Check if user is admin
    if user.id not in ADMIN_IDS:
        return
    
    try:
        total_users = db.get_total_users()
        active_users = db.get_active_users()
        premium_users = db.get_premium_users()
        total_searches = db.get_total_searches()
        total_requests = db.get_total_requests()
        
        stats_text = (
            "<blockquote><b>📊 Estadísticas del Bot 📊</b>\n\n</blockquote>"
            f"👥 <b>Usuarios:</b>\n"
            f"- Total: {total_users}\n"
            f"- Activos (últimos 7 días): {active_users}\n"
            f"- Con plan premium: {premium_users}\n\n"
            f"🔍 <b>Actividad:</b>\n"
            f"- Búsquedas totales: {total_searches}\n"
            f"- Pedidos totales: {total_requests}\n\n"
            f"📈 <b>Distribución de Planes:</b>\n"
            f"- Básico: {db.get_users_by_plan('basic')}\n"
            f"- Pro: {db.get_users_by_plan('pro')}\n"
            f"- Plus: {db.get_users_by_plan('plus')}\n"
            f"- Ultra: {db.get_users_by_plan('ultra')}"
        )
        
        await update.message.reply_text(text=stats_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await update.message.reply_text(
            "Error al obtener estadísticas.",
            parse_mode=ParseMode.HTML
        )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to broadcast a message to all users"""
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if not is_admin(user.id):
        return
    
    # Verificar argumentos
    if not context.args:
        await update.message.reply_text(
            "Uso: /broadcast mensaje",
            parse_mode=ParseMode.HTML
        )
        return
    
    message = " ".join(context.args)
    
    try:
        # Obtener todos los usuarios usando el método correcto
        # Asumiendo que el método se llama get_all_users() y devuelve una lista de diccionarios
        all_users = db.get_all_users()  # Este método debe existir en tu clase Database
        user_ids = [user['user_id'] for user in all_users]  # Extraer solo los IDs
        
        sent_count = 0
        failed_count = 0
        
        await update.message.reply_text(
            f"<blockquote>📢 Iniciando difusión a {len(user_ids)} usuarios...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        for user_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"<blockquote>📢 <b>Anuncio Oficial</b></blockquote>\n{message}",
                    parse_mode=ParseMode.HTML
                )
                sent_count += 1
                
                # Pequeña pausa para evitar límites de rate
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Error enviando broadcast a {user_id}: {e}")
                failed_count += 1
        
        await update.message.reply_text(
            f"<blockquote>📊 <b>Difusión completada:</b>\n"
            f"✅ Enviados: {sent_count}\n"
            f"❌ Fallidos: {failed_count}</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error en broadcast: {e}")
        await update.message.reply_text(
            "<blockquote>❌ Error al realizar la difusión. Por favor, intenta más tarde.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    
async def upser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para administradores para iniciar/finalizar la carga de series"""
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if user.id not in ADMIN_IDS:
        return
    
    # Obtener el estado actual
    upser_state = context.user_data.get('upser_state', UPSER_STATE_IDLE)
    
    # Si estamos en estado IDLE, iniciar el proceso
    if upser_state == UPSER_STATE_IDLE:
        # Inicializar o reiniciar la estructura de datos para la serie
        context.user_data['upser_episodes'] = []
        context.user_data['upser_state'] = UPSER_STATE_RECEIVING
        context.user_data['upser_cover'] = None
        context.user_data['upser_description'] = None
        context.user_data['upser_title'] = None  # Para guardar el título detectado
        context.user_data['upser_series_pattern'] = None  # Para guardar el patrón de nombre de la serie
        
        await update.message.reply_text(
            "📺 <b>Modo de carga de series activado</b>\n\n"
            "<blockquote>"
    		"1️⃣ Envía los capítulos en orden uno por uno\n"
    		"2️⃣ Si el primer capítulo tiene formato como 'La que se avecina 01x02', el bot reconocerá el patrón\n"
            "3️⃣ Los siguientes capítulos se nombrarán automáticamente incrementando el número\n"
    		"4️⃣ Al finalizar el envío de los capítulos, envía /upser nuevamente para subir la serie\n"
    		"El bot automáticamente buscará la información y portada de la serie\n"
            "</blockquote>\n"
            "Para cancelar el proceso, envía /cancelupser",
            parse_mode=ParseMode.HTML
        )
    
    # Si estamos recibiendo capítulos, finalizamos y buscamos la información automáticamente
    elif upser_state == UPSER_STATE_RECEIVING:
        # Verificar que hay capítulos recibidos
        episodes = context.user_data.get('upser_episodes', [])
        if not episodes:
            await update.message.reply_text(
                "<blockquote>⚠️ No has enviado ningún capítulo todavía.\n\n"
                "Envía al menos un capítulo antes de finalizar el proceso.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return
            
        # Intentar obtener el título a partir del primer capítulo
        first_episode = episodes[0]
        title_text = ""
        if 'caption' in first_episode and first_episode['caption']:
            title_text = first_episode['caption']
        elif 'file_name' in first_episode and first_episode['file_name']:
            title_text = first_episode['file_name']
        
        # Verificar si tenemos un patrón de serie guardado
        series_pattern = context.user_data.get('upser_series_pattern')
        if series_pattern:
            # Usar el título base de la serie como nombre de búsqueda
            clean_title = series_pattern['base_name']
        else:
            # Limpiar el título para búsqueda si no tenemos patrón
            clean_title = re.sub(r'[\._\-]', ' ', title_text)
            clean_title = re.sub(r'S\d+E\d+|Episode\s*\d+|Cap[ií]tulo\s*\d+|\d+x\d+', '', clean_title, flags=re.IGNORECASE)
            clean_title = clean_title.strip()
        
        # Mensaje de estado para seguir el progreso
        status_message = await update.message.reply_text(
            f"<blockquote>🔍 Buscando información para: <b>{clean_title}</b>...\n"
            f"Por favor, espera mientras procesamos tu serie.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        # Buscar información en IMDb
        try:
            imdb_info = await search_imdb_info(clean_title)
            
            if imdb_info:
                # Guardar la información encontrada
                context.user_data['upser_title'] = imdb_info['title']
                context.user_data['upser_description'] = (
                    f"<b>{imdb_info['title']}</b> ({imdb_info['year']})\n\n"
                    f"⭐ <b>Calificación:</b> {imdb_info['rating']}/10\n"
                    f"🎭 <b>Género:</b> {imdb_info['genres']}\n"
                    f"🎬 <b>Director:</b> {imdb_info['directors']}\n"
                    f"👥 <b>Reparto:</b> {imdb_info['cast']}\n\n"
                    f"📝 <b>Sinopsis:</b>\n<blockquote expandable>{imdb_info['plot']}</blockquote>\n\n"                    
                    f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
                )
                
                # Si encontramos un póster, descargarlo
                if imdb_info['poster_url']:
                    try:
                        await status_message.edit_text(
                            f"<blockquote>✅ Información encontrada para <b>{imdb_info['title']}</b>\n"
                            f"📥 Descargando póster...</blockquote>",
                            parse_mode=ParseMode.HTML
                        )
                        
                        # Descargar la imagen del póster
                        poster_response = requests.get(imdb_info['poster_url'])
                        poster_response.raise_for_status()
                        poster_bytes = BytesIO(poster_response.content)
                        
                        # Enviar la imagen con la información como pie de foto
                        cover_msg = await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=poster_bytes,
                            caption=context.user_data['upser_description'],
                            parse_mode=ParseMode.HTML
                        )
                        
                        # Guardar la portada
                        context.user_data['upser_cover'] = cover_msg.photo[-1].file_id
                        
                        # Continuar con la finalización
                        await status_message.edit_text(
                            "<blockquote>✅ Información y póster encontrados correctamente.\n"
                            "⏳ Procesando la subida de la serie...</blockquote>",
                            parse_mode=ParseMode.HTML
                        )
                        
                        # Finalizar la subida
                        await finalize_series_upload(update, context, status_message)
                        
                    except Exception as poster_error:
                        logger.error(f"Error descargando póster: {poster_error}")
                        await status_message.edit_text(
                            f"<blockquote>✅ Información encontrada para <b>{imdb_info['title']}</b>\n"
                            f"❌ Error al descargar el póster: {str(poster_error)[:100]}\n"
                            f"Por favor, sube manualmente una imagen para la serie.</blockquote>",
                            parse_mode=ParseMode.HTML
                        )
                        # Cambiar al estado de espera de portada
                        context.user_data['upser_state'] = UPSER_STATE_COVER
                else:
                    # No hay póster, pedir al usuario que lo suba
                    await status_message.edit_text(
                        f"<blockquote>✅ Información encontrada para <b>{imdb_info['title']}</b>\n"
                        f"⚠️ No se encontró póster para la serie.\n"
                        f"Por favor, envía una imagen para usar como portada de la serie.</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    # Cambiar al estado de espera de portada
                    context.user_data['upser_state'] = UPSER_STATE_COVER
            else:
                # No se encontró información, pedir al usuario que lo proporcione
                await status_message.edit_text(
                    f"<blockquote>❌ No se encontró información para <b>{clean_title}</b> en IMDb.\n"
                    f"Por favor, envía una imagen para usar como portada y proporciona la descripción como pie de foto.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                # Cambiar al estado de espera de portada
                context.user_data['upser_state'] = UPSER_STATE_COVER
        except Exception as e:
            logger.error(f"Error buscando información en IMDb: {e}")
            await status_message.edit_text(
                f"<blockquote>❌ Error al buscar información: {str(e)[:100]}\n"
                f"Por favor, envía una imagen para usar como portada y proporciona la descripción como pie de foto.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            # Cambiar al estado de espera de portada
            context.user_data['upser_state'] = UPSER_STATE_COVER
    
    # Si estamos esperando la portada y ya la tenemos, finalizar
    elif upser_state == UPSER_STATE_COVER and context.user_data.get('upser_cover'):
        await finalize_series_upload(update, context)
    
    # Cualquier otro estado (no debería ocurrir)
    else:
        await update.message.reply_text(
            "<blockquote>❌ Error en el estado de carga de series. Reinicia el proceso con /upser.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        context.user_data['upser_state'] = UPSER_STATE_IDLE

async def cancel_upser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancelar el proceso de carga de series"""
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if user.id not in ADMIN_IDS:
        return
    
    # Reiniciar el estado
    context.user_data['upser_state'] = UPSER_STATE_IDLE
    context.user_data['upser_episodes'] = []
    context.user_data['upser_cover'] = None
    context.user_data['upser_description'] = None
    context.user_data['upser_title'] = None
    
    await update.message.reply_text(
        "❌ Proceso de carga de series cancelado.\n\n"
        "Todos los datos temporales han sido eliminados.",
        parse_mode=ParseMode.HTML
    )

async def handle_upser_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar la recepción de capítulos y portada durante el proceso de carga de series"""
    # Verificar que update y effective_user no sean None
    if not update or not update.effective_user:
        return
        
    user = update.effective_user
    
    # Verificar que el usuario es administrador
    if user.id not in ADMIN_IDS:
        return
    
    # Verificar si estamos en modo de carga de series
    upser_state = context.user_data.get('upser_state', UPSER_STATE_IDLE)
    if upser_state == UPSER_STATE_IDLE:
        return  # No estamos en modo de carga de series
    
    # Si recibimos un mensaje con foto y estamos en modo de espera de portada, es la portada
    if update.message.photo and upser_state == UPSER_STATE_COVER:
        # Guardar la portada y descripción
        context.user_data['upser_cover'] = update.message.photo[-1].file_id
        context.user_data['upser_description'] = update.message.caption or "Sin descripción"
        
        await update.message.reply_text(
            "<blockquote>✅ Portada recibida correctamente.\n\n"
            "Ahora envía /upser nuevamente para finalizar y subir la serie.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Si estamos en modo de recepción y recibimos un video/documento, es un capítulo
    if (update.message.video or update.message.document) and upser_state == UPSER_STATE_RECEIVING:
        # Obtener información del capítulo
        message_id = update.message.message_id
        chat_id = update.effective_chat.id
        original_caption = update.message.caption or ""
        file_name = update.message.document.file_name if update.message.document else None
        
        # Por defecto, el caption será el original
        caption = original_caption
        episode_num = None
        
        # Si es el primer capítulo, detectar el nombre de la serie
        series_pattern = context.user_data.get('upser_series_pattern')
        if not series_pattern:
            # Extraer el nombre base y patrón del primer capítulo
            caption_or_filename = original_caption or file_name or ""
            
            # Buscar patrón como "Nombre Serie 01x02"
            pattern_match = re.search(r'(.+?)\s+(\d+)[xX](\d+)', caption_or_filename)
            
            if pattern_match:
                base_name = pattern_match.group(1).strip()
                season_num = int(pattern_match.group(2))
                episode_num = int(pattern_match.group(3))
                
                # Guardar el patrón
                context.user_data['upser_series_pattern'] = {
                    'base_name': base_name,
                    'season_num': season_num,
                    'current_episode': episode_num
                }
                
                # Informar al administrador
                await update.message.reply_text(
                    f"<blockquote>✅ Detectado nombre de serie: <b>{base_name}</b>\n"
                    f"Temporada: {season_num}\n"
                    f"Primer episodio: {episode_num}\n"
                    f"Todos los capítulos usarán este nombre.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
            else:
                # No se detectó un patrón claro en el primer capítulo
                await update.message.reply_text(
                    "<blockquote>⚠️ No se pudo detectar un patrón claro en el primer capítulo.\n"
                    "Por favor, asegúrate de que el primer capítulo tenga un formato como 'Nombre Serie 01x01'</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                # Usar un patrón predeterminado
                context.user_data['upser_series_pattern'] = {
                    'base_name': 'Serie',
                    'season_num': 1,
                    'current_episode': 1
                }
                episode_num = 1
        else:
            # Ya tenemos el patrón, extraer temporada y episodio del mensaje actual
            caption_or_filename = original_caption or file_name or ""
            num_pattern = re.search(r'(\d+)[xX](\d+)', caption_or_filename)
            
            if num_pattern:
                # Hay números en el formato 01x02
                current_season = int(num_pattern.group(1))
                episode_num = int(num_pattern.group(2))
            else:
                # No hay números claros, incrementar el último episodio
                current_season = series_pattern['season_num']
                episode_num = series_pattern['current_episode'] + 1
                series_pattern['current_episode'] = episode_num
            
            # Usar el nombre base guardado para crear un nuevo caption
            base_name = series_pattern['base_name']
            new_caption = f"{base_name} {current_season:02d}x{episode_num:02d}"
            
            # Verificar si el caption necesita ser actualizado
            if base_name not in original_caption:
                # No tiene el nombre de la serie, reemplazar el mensaje
                try:
                    # Obtener el file_id del archivo actual
                    if update.message.video:
                        file_id = update.message.video.file_id
                        # Borrar el mensaje original
                        await context.bot.delete_message(
                            chat_id=chat_id, 
                            message_id=message_id
                        )
                        # Enviar un nuevo mensaje con el caption correcto
                        new_message = await context.bot.send_video(
                            chat_id=chat_id,
                            video=file_id,
                            caption=new_caption
                        )
                        # Actualizar el message_id para guardarlo correctamente
                        message_id = new_message.message_id
                    elif update.message.document:
                        file_id = update.message.document.file_id
                        # Borrar el mensaje original
                        await context.bot.delete_message(
                            chat_id=chat_id, 
                            message_id=message_id
                        )
                        # Enviar un nuevo mensaje con el caption correcto
                        new_message = await context.bot.send_document(
                            chat_id=chat_id,
                            document=file_id,
                            caption=new_caption
                        )
                        # Actualizar el message_id para guardarlo correctamente
                        message_id = new_message.message_id
                    
                    # Notificar el cambio de nombre
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"<blockquote>✅ Nombre actualizado: <b>{new_caption}</b></blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Usar el nuevo caption
                    caption = new_caption
                except Exception as e:
                    logger.error(f"Error al reenviar con nuevo caption: {e}")
                    caption = original_caption
            else:
                caption = original_caption
        
        # Asegurar que episode_num tenga un valor
        if episode_num is None:
            episode_num = len(context.user_data.get('upser_episodes', [])) + 1
        
        # Guardar el capítulo con todos los datos
        episode_data = {
            'message_id': message_id,
            'episode_number': episode_num,
            'chat_id': chat_id,
            'caption': caption,
            'file_name': file_name
        }
        
        # Añadir a la lista de episodios
        context.user_data.setdefault('upser_episodes', []).append(episode_data)
        
        # Confirmar la recepción del capítulo
        await update.message.reply_text(
            f"<blockquote>✅ Capítulo {episode_num} recibido y guardado.</blockquote>",
            parse_mode=ParseMode.HTML
        )

async def finalize_series_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, status_message=None) -> None:
    """Finalizar el proceso de carga y subir la serie a los canales"""
    try:
        # Obtener datos de la serie
        current_series = context.user_data.get('current_series', {})
        if not current_series:
            raise ValueError("No hay datos de serie para procesar")

        # Verificar que tenemos los datos necesarios
        episodes = current_series.get('episodes', [])
        imdb_info = current_series.get('imdb_info', {})
        title = current_series.get('title', 'Serie sin título')
        media_type = current_series.get('media_type', 'tv')  # Asumir 'tv' como predeterminado

        if not episodes:
            raise ValueError("No hay episodios para procesar")

        # Crear o actualizar mensaje de estado
        if not status_message:
            status_message = await update.message.reply_text(
                "<blockquote>⏳ Procesando serie...</blockquote>",
                parse_mode=ParseMode.HTML
            )

        # 1. Obtener o descargar la portada
        cover_photo = None
        if imdb_info and imdb_info.get('poster_url'):
            try:
                await status_message.edit_text(
                    f"<blockquote>📥 Descargando póster para {title}...</blockquote>",
                    parse_mode=ParseMode.HTML
                )
                
                # Descargar póster
                poster_response = requests.get(imdb_info['poster_url'])
                poster_response.raise_for_status()
                poster_bytes = BytesIO(poster_response.content)
                
                # Enviar temporalmente para obtener el file_id
                temp_msg = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=poster_bytes,
                    caption="Descargando portada..."
                )
                
                cover_photo = temp_msg.photo[-1].file_id
                await temp_msg.delete()
                
            except Exception as e:
                logger.error(f"Error descargando póster: {e}")
                # No lanzar error, continuaremos sin póster

        # Si no tenemos portada, pedirla al usuario
        if not cover_photo:
            await status_message.edit_text(
                "<blockquote>⚠️ No se pudo obtener la portada automáticamente.\n"
                "Por favor, envía una imagen para usar como portada de la serie.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            context.user_data['upser_state'] = UPSER_STATE_COVER
            return

        # 2. Generar descripción
        description = current_series.get('description')
        if not description and imdb_info:
            # Determinar tipo de contenido
            content_type_header = "<blockquote>Serie 🎥</blockquote>\n" if media_type == 'tv' else "<blockquote>Película 🍿</blockquote>\n"

            # Obtener títulos en español e inglés
            spanish_title = imdb_info.get('title', title)
            english_title = imdb_info.get('original_title', spanish_title)

            # Evitar repetición si los títulos son idénticos
            english_title_display = f"{english_title} ✓\n" if spanish_title.lower() != english_title.lower() else ""

            # Crear descripción con el formato correcto
            description = (
                f"{content_type_header}"
                f"{spanish_title} ✓\n"
                f"{english_title_display}\n"
                f"📅 Año: {imdb_info.get('year', 'N/A')}\n"
                f"⭐ Calificación: {imdb_info.get('rating', 'N/A')}/10\n"
                f"🎭 Género: {imdb_info.get('genres', 'No disponible')}\n"
                f"🎬 Director: {imdb_info.get('directors', 'No disponible')}\n"
                f"👥 Reparto: {imdb_info.get('cast', 'No disponible')}"
            )

            # Agregar información adicional para series
            if media_type == 'tv':
                status_map = {
                    'Returning Series': 'En emisión',
                    'Ended': 'Finalizada',
                    'Canceled': 'Cancelada'
                }
                series_status = status_map.get(imdb_info.get('status'), 'Desconocido')
                num_seasons = imdb_info.get('number_of_seasons', '?')
                num_episodes = imdb_info.get('number_of_episodes', '?')
                description += f"\n📺 Estado: {series_status}\n🔢 {num_episodes} episodios en {num_seasons} temporadas"

            # Agregar sinopsis en formato de cita expandible
            description += (
                f"\n\n📝 Sinopsis:\n"
                f"<blockquote expandable>{imdb_info.get('plot', 'No disponible')}</blockquote>\n\n"
            )

            # Agregar marca de agua con enlace
            description += f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
        else:
            # Si no hay información de IMDb, crear una descripción básica
            content_type_header = "<blockquote>Serie 🎥</blockquote>\n" if media_type == 'tv' else "<blockquote>Película 🍿</blockquote>\n"
            description = (
                f"{content_type_header}"
                f"{title} ✓\n\n"
                f"📝 Sinopsis:\n<blockquote expandable>No se encontró información adicional para este contenido.</blockquote>\n\n"
                f"🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
            )
        
        # 3. Subir la portada con descripción al canal de búsqueda
        await status_message.edit_text(
            f"<blockquote>⏳ Subiendo portada para <b>{title}</b> al canal de búsqueda...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        sent_cover = await context.bot.send_photo(
            chat_id=SEARCH_CHANNEL_ID,
            photo=cover_photo,
            caption=description,
            parse_mode=ParseMode.HTML
        )
        
        search_channel_cover_id = sent_cover.message_id
        
        # 4. Generar URL para el botón "Ver ahora"
        view_url = f"https://t.me/MultimediaTVbot?start=series_{series_id}"
        
        # 5. Crear un botón para la portada
        keyboard = [
            [InlineKeyboardButton("Ver ahora", url=view_url)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 6. Actualizar la portada en el canal de búsqueda con el botón
        await context.bot.edit_message_reply_markup(
            chat_id=SEARCH_CHANNEL_ID,
            message_id=search_channel_cover_id,
            reply_markup=reply_markup
        )
        
        # 7. Subir todos los capítulos al canal de búsqueda (en grupos para evitar timeout)
        await status_message.edit_text(
            f"<blockquote>⏳ Subiendo {len(episodes)} capítulos al canal de búsqueda...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        search_channel_episode_IDS = []
        
        # Procesar los capítulos en grupos más pequeños
        episode_groups = [episodes[i:i+5] for i in range(0, len(episodes), 5)]
        
        for group_index, group in enumerate(episode_groups):
            # Actualizar estado
            await status_message.edit_text(
                f"<blockquote>⏳ Subiendo capítulos al canal de búsqueda... ({group_index*5+1}-{min((group_index+1)*5, len(episodes))}/{len(episodes)})</blockquote>",
                parse_mode=ParseMode.HTML
            )
            
            for episode in group:
                # Obtener el mensaje original
                try:
                    original_message = await context.bot.copy_message(
                        chat_id=SEARCH_CHANNEL_ID,
                        from_chat_id=episode['chat_id'],
                        message_id=episode['message_id'],
                        disable_notification=True
                    )
                    
                    search_channel_episode_IDS.append(original_message.message_id)
                    
                    # Pequeña pausa para evitar problemas de rate limiting
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error copiando episodio al canal de búsqueda: {e}")
                    await status_message.edit_text(
                        f"<blockquote>⚠️ Error al subir el capítulo {episode['episode_number']}. Continuando con el siguiente...</blockquote>",
                        parse_mode=ParseMode.HTML
                    )
                    await asyncio.sleep(1)
        
        # 8. Repetir el proceso para el canal principal (solo la portada)
        await status_message.edit_text(
            f"<blockquote>⏳ Subiendo portada al canal principal...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        try:
            sent_cover_main = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=cover_photo,
                caption=description,
                parse_mode=ParseMode.HTML
            )
            
            # 9. Actualizar la portada en el canal principal con el mismo botón
            await context.bot.edit_message_reply_markup(
                chat_id=CHANNEL_ID,
                message_id=sent_cover_main.message_id,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error enviando portada al canal principal: {e}")
            await status_message.edit_text(
                f"<blockquote>⚠️ Error al enviar portada al canal principal, pero la serie ya está en el canal de búsqueda.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(1)
        
        # 10. Guardar los datos en la base de datos
        await status_message.edit_text(
            f"<blockquote>⏳ Guardando información de la serie en la base de datos...</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
        try:
            # Guardar la serie en la base de datos
            db.add_series(
                series_id=series_id,
                title=title,
                description=description,
                cover_message_id=search_channel_cover_id,
                added_by=update.effective_user.id
            )
            
            # Guardar los capítulos en la base de datos
            for i, episode_id in enumerate(search_channel_episode_IDS):
                try:
                    episode_number = episodes[i]['episode_number'] if 'episode_number' in episodes[i] else (i + 1)
                except IndexError:
                    episode_number = i + 1
                
                db.add_episode(
                    series_id=series_id,
                    episode_number=episode_number,
                    message_id=episode_id
                )
            
            logger.info(f"Serie guardada correctamente en la base de datos: ID={series_id}, Título={title}, Episodios={len(search_channel_episode_IDS)}")
            
        except Exception as db_error:
            logger.error(f"Error guardando serie en la base de datos: {db_error}")
            await status_message.edit_text(
                f"<blockquote>⚠️ La serie se ha subido a los canales pero no se pudo guardar en la base de datos: {str(db_error)[:100]}\n\n"
                f"Algunos botones podrían no funcionar correctamente.</blockquote>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # 11. Reiniciar el estado
        context.user_data['upser_state'] = UPSER_STATE_IDLE
        context.user_data['upser_episodes'] = []
        context.user_data['upser_cover'] = None
        context.user_data['upser_description'] = None
        context.user_data['upser_title'] = None
        context.user_data['upser_series_pattern'] = None
        
        # 12. Informar al administrador
        await status_message.edit_text(
            f"<blockquote>✅ Serie <b>{title}</b> subida correctamente a los canales.\n\n"
            f"📊 Detalles:\n"
            f"- Capítulos: {len(episodes)}\n"
            f"- ID de serie: {series_id}\n"
            f"- Canal de búsqueda: ✓\n"
            f"- Canal principal: ✓\n\n"
            f"Los usuarios pueden acceder a la serie con el botón 'Ver ahora'.</blockquote>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error subiendo serie: {e}")
        await status_message.edit_text(
            f"<blockquote>❌ Error al subir la serie: {str(e)[:100]}\n\n"
            f"Por favor, intenta nuevamente.</blockquote>",
            parse_mode=ParseMode.HTML
        )


async def verify_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifica la membresía del usuario cuando presiona el botón 'Ya me uní'."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    
    # Verificar membresía en tiempo real
    is_member = await is_channel_member(user_id, context)
    
    if is_member:
        # Asegurarse de que el usuario esté registrado
        if not db.user_exists(user_id):
            db.add_user(
                user_id,
                user.username,
                user.first_name,
                user.last_name
            )
        
        # Actualizar caché de verificación
        verification_cache = context.bot_data.setdefault('verification_cache', {})
        verification_cache[user_id] = datetime.now() + timedelta(minutes=30)
        
        # Mostrar mensaje de éxito y redirigir al menú principal
        keyboard = [
            [
                InlineKeyboardButton("Multimedia Tv 📺", url=f"https://t.me/multimediatvOficial"),
                InlineKeyboardButton("Pedidos 📡", url=f"https://t.me/+X9S4pxF8c7plYjYx")
            ],
            [InlineKeyboardButton("Perfil 👤", callback_data="profile")],
            [InlineKeyboardButton("Planes 📜", callback_data="plans")],
            [InlineKeyboardButton("Información 📰", callback_data="info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ ¡Verificación exitosa! Gracias por unirte a nuestro canal.\n\n"
            f"Ya puedes disfrutar de todas las funcionalidades del bot.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    else:
        # Mostrar mensaje de error si aún no se ha unido
        keyboard = [
            [InlineKeyboardButton("Unirse al Canal 📢", url=f"https://t.me/multimediatvOficial")],
            [InlineKeyboardButton("Verificar nuevamente 🔄", callback_data="verify_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❌ No se ha detectado tu membresía en el canal.\n\n"
            "Por favor, asegúrate de:\n"
            "1. Hacer clic en 'Unirse al Canal 📢'\n"
            "2. Aceptar unirte al canal\n"
            "3. Volver aquí y presionar 'Verificar nuevamente 🔄'",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline buttons"""
    query = update.callback_query
    data = query.data
    
    # Manejar callback de verificación de membresía
    if data == "verify_membership":
        await verify_channel_membership(update, context)
        return
    
    # Manejar selección de temporada en series multi-temporada
    if data.startswith("season_"):
        try:
            season_id = int(data.replace("season_", ""))
            await handle_season_selection(query, context, season_id)
            return
        except Exception as e:
            logger.error(f"Error procesando selección de temporada: {e}")
            await query.answer(f"Error: {str(e)[:200]}")
            return
    
    # Manejar botón de volver a temporadas
    if data.startswith("back_to_seasons_"):
        try:
            series_id = int(data.replace("back_to_seasons_", ""))
            await handle_back_to_seasons(query, context, series_id)
            return
        except Exception as e:
            logger.error(f"Error procesando botón volver: {e}")
            await query.answer(f"Error: {str(e)[:200]}")
            return
    
    # Manejar solicitudes de capítulos de series multi-temporada
    if data.startswith("multi_ep_") and not data.startswith("multi_ep_all_"):
        try:
            message_id = int(data.replace("multi_ep_", ""))
            await send_multi_episode(query, context, message_id)
            return
        except Exception as e:
            logger.error(f"Error procesando solicitud de capítulo multi-serie: {e}")
            await query.answer(f"Error: {str(e)[:200]}")
            return
    
    # Manejar solicitud de todos los capítulos de una temporada
    if data.startswith("multi_ep_all_"):
        try:
            season_id = int(data.replace("multi_ep_all_", ""))
            await send_all_multi_episodes(query, context, season_id)
            return
        except Exception as e:
            logger.error(f"Error procesando solicitud de todos los capítulos: {e}")
            await query.answer(f"Error: {str(e)[:200]}")
            return
    
    # Manejar solicitudes de capítulos individuales
    if data.startswith("ep_") and not data.startswith("ep_all_"):
        try:
            # Formato: ep_[series_id]_[episode_number]
            _, series_id, episode_number = data.split("_")
            series_id = int(series_id)
            episode_number = int(episode_number)
            
            await send_episode(query, context, series_id, episode_number)
            return
        except Exception as e:
            logger.error(f"Error procesando solicitud de capítulo: {e}")
            await query.answer(f"Error: {str(e)[:200]}")
            return

    # Manejar solicitudes de todos los capítulos
    elif data.startswith("ep_all_"):
        try:
            # Formato: ep_all_[series_id]
            _, series_id = data.split("_all_")
            series_id = int(series_id)
            
            await send_all_episodes(query, context, series_id)
            return
        except Exception as e:
            logger.error(f"Error procesando solicitud de todos los capítulos: {e}")
            await query.answer(f"Error: {str(e)[:200]}")
            return
    
    # Verificar membresía antes de procesar otros callbacks
    user_id = query.from_user.id
    is_member = await is_channel_member(user_id, context)
    
    if not is_member and data not in ["verify_membership"]:
        # Usuario no es miembro, mostrar mensaje de suscripción
        keyboard = [
            [InlineKeyboardButton("Unirse al Canal 📢", url=f"https://t.me/multimediatvOficial")],
            [InlineKeyboardButton("Ya me uní ✅", callback_data="verify_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⚠️ Para usar el bot, debes unirte a nuestro canal principal.\n\n"
            "1. Haz clic en el botón 'Unirse al Canal 📢'\n"
            "2. Una vez unido, vuelve aquí y presiona 'Ya me uní ✅'",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return
        
    if data == "profile":
        await handle_profile(update, context)
    elif data == "plans":
        await handle_plans(update, context)
    elif data == "info":
        await handle_info(update, context)
    elif data == "main_menu":
        # Recrear el mensaje de menú principal sin usar start
        user = query.from_user
        keyboard = [
            [
                InlineKeyboardButton("Multimedia Tv 📺", url=f"https://t.me/multimediatvOficial"),
                InlineKeyboardButton("Pedidos 📡", url=f"https://t.me/+X9S4pxF8c7plYjYx")
            ],
            [InlineKeyboardButton("Perfil 👤", callback_data="profile")],
            [InlineKeyboardButton("Planes 📜", callback_data="plans")],
            [InlineKeyboardButton("Información 📰", callback_data="info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                f"¡Hola! {user.first_name}👋 te doy la bienvenida\n\n"
                f"<blockquote expandable>MultimediaTv un bot donde encontraras un amplio catálogo de películas y series, "
                f"las cuales puedes buscar o solicitar en caso de no estar en el catálogo</blockquote>",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error returning to main menu: {e}")
            # Si falla el edit_message, intentamos enviar un nuevo mensaje
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat.id,
                    text=f"¡Hola! {user.first_name}👋 te doy la bienvenida\n\n"
                         f"<blockquote expandable>MultimediaTv un bot donde encontraras un amplio catálogo de películas y series, "
                         f"las cuales puedes buscar o solicitar en caso de no estar en el catálogo</blockquote>",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except Exception as inner_e:
                logger.error(f"Error sending new main menu message: {inner_e}")
                await query.answer("Error al mostrar el menú principal. Intenta con /start")
                
    elif data in ["plan_pro", "plan_plus", "plan_ultra"]:
        await handle_plan_details(update, context)
    elif "_cup" in data or "_crypto" in data:
        await handle_payment_method(update, context)
    elif data.startswith("req_"):
        await handle_request_type(update, context)
    elif data == "make_request":
        await handle_make_request(update, context)
    elif data.startswith("accept_req_"):
        await handle_accept_request(update, context)
    elif data.startswith("send_"):
        # Get the message ID from the callback data
        try:
            msg_id = int(data.split("_")[1])
            await handle_send_callback(query, context, msg_id)
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing send callback data: {e}")
            await query.answer("Error: formato de datos inválido")
    else:
        await query.answer("Opción no disponible.")

async def check_plan_expiry(context: ContextTypes.DEFAULT_TYPE):
    """Background task to check for expired plans"""
    try:
        # Get users with expired plans
        expired_users = db.get_expired_plans()
        
        for user_id in expired_users:
            # Reset user to basic plan
            db.update_plan(user_id, 'basic', None)
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ Tu plan premium ha expirado. Has sido cambiado al plan básico.\n"
                         "<blockquote>Para renovar tu plan, utiliza el botón 'Planes 📜' en el menú principal.</blockquote>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error notifying user {user_id} about plan expiry: {e}")
    except Exception as e:
        logger.error(f"Error in plan expiry check: {e}")

async def reset_daily_limits(context: ContextTypes.DEFAULT_TYPE):
    """Background task to reset daily limits at midnight"""
    try:
        # Reset daily limits
        db.reset_daily_limits()
        logger.info("Daily limits reset")
    except Exception as e:
        logger.error(f"Error in daily limits reset: {e}")

async def error_handler(update, context):
    """Handle errors in the dispatcher"""
    logger.error(f"Exception while handling an update: {context.error}")

    # Log the error before we do anything else
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # Send a message to the user
    if update and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text="Ocurrió un error al procesar tu solicitud. Por favor, intenta nuevamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error sending error message: {e}")
            
async def check_channel_memberships(context: ContextTypes.DEFAULT_TYPE):
    """Tarea periódica para verificar membresías y limpiar el caché."""
    try:
        verification_cache = context.bot_data.get('verification_cache', {})
        current_time = datetime.now()
        
        # Limpiar entradas expiradas del caché
        expired_keys = [k for k, v in verification_cache.items() if current_time > v]
        for key in expired_keys:
            verification_cache.pop(key, None)
            
        logger.info(f"Limpieza de caché de verificación: {len(expired_keys)} entradas eliminadas")
    except Exception as e:
        logger.error(f"Error en check_channel_memberships: {e}")
        
async def send_keepalive_message(context: ContextTypes.DEFAULT_TYPE):
    """Send periodic message to keep the bot active."""
    try:
        await context.bot.send_message(
            chat_id="-1002685140729",  # Your channel ID
            text="🤖 Bot activo y funcionando correctamente."
        )
    except Exception as e:
        logger.error(f"Error sending keepalive message: {e}")

# Mantener el servidor Flask activo
def main() -> None:
    """Start the bot."""
    # Create the Application
    persistence = PicklePersistence(filepath="multimedia_tv_bot_data.pickle")
    
    # Create the Application with persistence
    application = Application.builder().token(TOKEN).persistence(persistence).build()
    
    application.bot_data['verification_cache'] = {}

    # Register error handler
    application.add_error_handler(error_handler)

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search_content))
    application.add_handler(CommandHandler("imdb", imdb_command))
    application.add_handler(CommandHandler("plan", set_user_plan))
    application.add_handler(CommandHandler("a", a_command))
    application.add_handler(CommandHandler("cancelmulti", cancel_multi_command))
    application.add_handler(CommandHandler("load", load_command))
    application.add_handler(CommandHandler("cancelmulti", cancel_multi_command))
    application.add_handler(CommandHandler("upser", upser_command))
    application.add_handler(CommandHandler("cancelupser", cancel_upser_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("canceladd", cancel_add_command))
    application.add_handler(CommandHandler("addgift_code", add_gift_code))
    application.add_handler(CommandHandler("gift_code", redeem_gift_code))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("up", upload_content))
    application.add_handler(CommandHandler("pedido", request_content))
    application.add_handler(CommandHandler("admin_help", admin_help))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("clearcache", clear_cache_command))
    
    # AI Automation command handlers
    application.add_handler(CommandHandler("ai_auto", ai_auto_command))
    application.add_handler(CommandHandler("ai_status", ai_status_command))
    application.add_handler(CommandHandler("ai_config", ai_config_command))

    # Handlers para el nuevo comando ser
    application.add_handler(CommandHandler("ser", ser_command))
    application.add_handler(CommandHandler("season", season_command))
    application.add_handler(CommandHandler("cancelser", cancel_ser_command))
    application.add_handler(CommandHandler("buscar", buscar_command))

    # Add periodic keepalive message
    application.job_queue.run_repeating(
        send_keepalive_message,
        interval=600,
        first=10
    )
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Handlers organizados por prioridad (grupos)
    # Grupo -12: Handlers para el comando ser (mayor prioridad)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(user_id=ADMIN_IDS),
        handle_series_name
    ), group=-15)

    application.add_handler(MessageHandler(
        (filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND & filters.User(user_id=ADMIN_IDS),
        handle_series_content
    ), group=-15)

    # Grupo -11: Handlers para el comando add
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(user_id=ADMIN_IDS),
        handle_add_name
    ), group=-11)
    
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND & filters.User(user_id=ADMIN_IDS),
        handle_add_content
    ), group=-11)
    
    # Grupo -10: Handlers para carga masiva (load)
    application.add_handler(MessageHandler(
        filters.TEXT 
        & ~filters.COMMAND 
        & filters.User(user_id=ADMIN_IDS) 
        & filters.ChatType.PRIVATE,
        handle_content_name,
        block=True
    ), group=-10)

    application.add_handler(MessageHandler(
        (filters.VIDEO | filters.Document.ALL) 
        & ~filters.COMMAND 
        & filters.User(user_id=ADMIN_IDS),
        handle_load_content,
        block=True
    ), group=-10)
    
    # Grupo -5: Handler para upser
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
        handle_upser_input,
    ), group=-5)
    
    # Grupo -4: Handler para multi-temporadas
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
        handle_multi_seasons_input,
    ), group=-4)
    
    # Tareas periódicas
    application.job_queue.run_repeating(
        check_plan_expiry,
        interval=24*60*60,  # 24 horas
        first=60
    )
    
    application.job_queue.run_repeating(
        check_channel_memberships,
        interval=6*60*60,  # 6 horas
        first=600  # 10 minutos
    )
    
    application.job_queue.run_repeating(
        reset_daily_limits,
        interval=24*60*60,  # 24 horas
        first=120
    )
    
    # Mantener el servidor Flask activo
    keep_alive()
    
    # Start the Bot
    application.run_polling()

if __name__ == "__main__":
    main()
