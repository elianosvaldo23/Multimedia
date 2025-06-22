import logging
import asyncio
import aiohttp
import tempfile
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from telegram import Update, InputMediaPhoto
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes
from telegram.error import TelegramError
import requests
from io import BytesIO
from PIL import Image
import re

from content_detector import ContentDetector
from ai_processor import AIProcessor

logger = logging.getLogger(__name__)

class AutoUploader:
    """Sistema de subida automática de contenido multimedia"""
    
    def __init__(self, channel_id: int, search_channel_id: int, database):
        self.channel_id = channel_id
        self.search_channel_id = search_channel_id
        self.db = database
        
        # Inicializar componentes de IA
        self.content_detector = ContentDetector()
        self.ai_processor = AIProcessor()
        
        # Configuración
        self.processing_queue = []
        self.is_processing = False
        self.max_queue_size = 50
        
        # APIs para búsqueda de contenido
        self.tmdb_api_key = os.environ.get('TMDB_API_KEY', 'tu_api_key_aqui')
        self.omdb_api_key = os.environ.get('OMDB_API_KEY', 'tu_api_key_aqui')
        
        # Configuración de procesamiento
        self.auto_config = {
            'enabled': False,
            'min_confidence': 0.7,
            'auto_search_imdb': True,
            'auto_generate_description': True,
            'auto_download_poster': True,
            'processing_delay': 2,
            'max_retries': 3
        }
    
    async def process_message_automatically(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Procesa un mensaje automáticamente si contiene contenido multimedia
        
        Returns:
            bool: True si se procesó automáticamente, False si no
        """
        try:
            if not self.auto_config['enabled']:
                return False
            
            # Verificar si el mensaje contiene archivos multimedia
            message = update.message
            if not message:
                return False
            
            # Extraer información del mensaje
            message_info = await self._extract_message_info(message)
            if not message_info:
                return False
            
            # Detectar contenido
            content_analysis = await self.content_detector.detect_content_from_message(
                message_info['text'], 
                message_info['filename']
            )
            
            # Verificar si es contenido válido
            if not self.content_detector.is_valid_content(content_analysis, self.auto_config['min_confidence']):
                logger.info(f"Contenido no válido o confianza insuficiente: {content_analysis.get('confidence', 0)}")
                return False
            
            # Mejorar análisis con IA si está disponible
            if self.ai_processor.is_ai_available():
                ai_analysis = await self.ai_processor.analyze_content_with_ai(
                    f"{message_info['text']} {message_info['filename']}"
                )
                
                # Combinar análisis
                if ai_analysis.get('confidence', 0) > content_analysis.get('confidence', 0):
                    content_analysis.update(ai_analysis)
            
            # Validar calidad final
            if not await self.ai_processor.validate_content_quality(content_analysis):
                logger.info("Contenido no pasó validación de calidad")
                return False
            
            # Agregar a cola de procesamiento
            await self._add_to_processing_queue({
                'message': message,
                'context': context,
                'content_analysis': content_analysis,
                'message_info': message_info,
                'timestamp': datetime.now()
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error en procesamiento automático: {e}")
            return False
    
    async def _extract_message_info(self, message) -> Optional[Dict]:
        """Extrae información relevante del mensaje"""
        try:
            info = {
                'text': message.text or message.caption or '',
                'filename': '',
                'file_id': None,
                'file_type': None,
                'file_size': 0
            }
            
            # Verificar diferentes tipos de archivos
            if message.document:
                info['filename'] = message.document.file_name or ''
                info['file_id'] = message.document.file_id
                info['file_type'] = 'document'
                info['file_size'] = message.document.file_size or 0
            elif message.video:
                info['filename'] = message.video.file_name or ''
                info['file_id'] = message.video.file_id
                info['file_type'] = 'video'
                info['file_size'] = message.video.file_size or 0
            elif message.audio:
                info['filename'] = message.audio.file_name or ''
                info['file_id'] = message.audio.file_id
                info['file_type'] = 'audio'
                info['file_size'] = message.audio.file_size or 0
            
            # Solo procesar si hay archivo o texto relevante
            if info['file_id'] or (info['text'] and len(info['text'].split()) >= 2):
                return info
            
            return None
            
        except Exception as e:
            logger.error(f"Error extrayendo info del mensaje: {e}")
            return None
    
    async def _add_to_processing_queue(self, item: Dict):
        """Agrega item a la cola de procesamiento"""
        try:
            if len(self.processing_queue) >= self.max_queue_size:
                logger.warning("Cola de procesamiento llena, descartando item más antiguo")
                self.processing_queue.pop(0)
            
            self.processing_queue.append(item)
            
            # Iniciar procesamiento si no está activo
            if not self.is_processing:
                asyncio.create_task(self._process_queue())
                
        except Exception as e:
            logger.error(f"Error agregando a cola: {e}")
    
    async def _process_queue(self):
        """Procesa la cola de elementos pendientes"""
        if self.is_processing:
            return
        
        self.is_processing = True
        
        try:
            while self.processing_queue:
                item = self.processing_queue.pop(0)
                
                try:
                    await self._process_single_item(item)
                    
                    # Delay entre procesamiento
                    await asyncio.sleep(self.auto_config['processing_delay'])
                    
                except Exception as e:
                    logger.error(f"Error procesando item: {e}")
                    continue
                    
        finally:
            self.is_processing = False
    
    async def _process_single_item(self, item: Dict):
        """Procesa un elemento individual"""
        try:
            message = item['message']
            context = item['context']
            content_analysis = item['content_analysis']
            message_info = item['message_info']
            
            # Notificar inicio de procesamiento
            status_message = await context.bot.send_message(
                chat_id=message.chat_id,
                text="🤖 <b>Procesamiento Automático Iniciado</b>\n\n"
                     f"📝 Contenido detectado: <b>{content_analysis['title']}</b>\n"
                     f"🎯 Tipo: {content_analysis['type']}\n"
                     f"📊 Confianza: {content_analysis['confidence']*100:.1f}%\n\n"
                     "⏳ Buscando información en IMDb...",
                parse_mode=ParseMode.HTML
            )
            
            # Buscar información en IMDb/TMDB
            imdb_data = None
            if self.auto_config['auto_search_imdb']:
                imdb_data = await self._search_content_info(content_analysis)
                
                if imdb_data:
                    await status_message.edit_text(
                        "🤖 <b>Procesamiento Automático</b>\n\n"
                        f"✅ Información encontrada: <b>{imdb_data.get('title', 'N/A')}</b>\n"
                        f"📅 Año: {imdb_data.get('year', 'N/A')}\n"
                        f"⭐ Rating: {imdb_data.get('rating', 'N/A')}\n\n"
                        "⏳ Generando descripción...",
                        parse_mode=ParseMode.HTML
                    )
            
            # Mejorar metadatos con IA
            enhanced_content = await self.ai_processor.enhance_content_metadata(
                content_analysis, imdb_data
            )
            
            # Generar descripción final
            description = await self._generate_final_description(enhanced_content, imdb_data)
            
            # Descargar poster si está disponible
            poster_data = None
            if self.auto_config['auto_download_poster'] and imdb_data and imdb_data.get('poster_url'):
                poster_data = await self._download_poster(imdb_data['poster_url'])
                
                await status_message.edit_text(
                    "🤖 <b>Procesamiento Automático</b>\n\n"
                    "✅ Información procesada\n"
                    "✅ Descripción generada\n"
                    "✅ Poster descargado\n\n"
                    "⏳ Subiendo al canal...",
                    parse_mode=ParseMode.HTML
                )
            
            # Subir contenido a los canales
            upload_result = await self._upload_to_channels(
                message, context, enhanced_content, description, poster_data
            )
            
            if upload_result['success']:
                await status_message.edit_text(
                    "🤖 <b>✅ Procesamiento Completado</b>\n\n"
                    f"📺 Contenido: <b>{enhanced_content['title']}</b>\n"
                    f"🎯 Tipo: {enhanced_content['type']}\n"
                    f"📊 Confianza: {enhanced_content['confidence']*100:.1f}%\n\n"
                    "✅ Subido al canal principal\n"
                    "✅ Subido al canal de búsqueda\n"
                    "✅ Guardado en base de datos",
                    parse_mode=ParseMode.HTML
                )
                
                # Guardar en base de datos
                await self._save_to_database(enhanced_content, upload_result)
                
            else:
                await status_message.edit_text(
                    "🤖 <b>❌ Error en Procesamiento</b>\n\n"
                    f"Error: {upload_result.get('error', 'Error desconocido')}\n\n"
                    "El contenido no se pudo subir automáticamente.",
                    parse_mode=ParseMode.HTML
                )
            
        except Exception as e:
            logger.error(f"Error procesando item individual: {e}")
            raise
    
    async def _search_content_info(self, content_analysis: Dict) -> Optional[Dict]:
        """Busca información del contenido en APIs externas"""
        try:
            search_query = content_analysis.get('search_query', content_analysis.get('title', ''))
            
            if not search_query:
                return None
            
            # Intentar con TMDB primero
            tmdb_result = await self._search_tmdb(search_query, content_analysis.get('type', 'movie'))
            if tmdb_result:
                return tmdb_result
            
            # Fallback a OMDB
            omdb_result = await self._search_omdb(search_query)
            if omdb_result:
                return omdb_result
            
            return None
            
        except Exception as e:
            logger.error(f"Error buscando información: {e}")
            return None
    
    async def _search_tmdb(self, query: str, content_type: str) -> Optional[Dict]:
        """Busca en TMDB"""
        try:
            if self.tmdb_api_key == 'tu_api_key_aqui':
                return None
            
            # Determinar endpoint según tipo
            endpoint = 'movie' if content_type == 'movie' else 'tv'
            url = f"https://api.themoviedb.org/3/search/{endpoint}"
            
            params = {
                'api_key': self.tmdb_api_key,
                'query': query,
                'language': 'es-ES'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get('results', [])
                        
                        if results:
                            result = results[0]  # Tomar el primer resultado
                            
                            return {
                                'title': result.get('title') or result.get('name', ''),
                                'year': (result.get('release_date') or result.get('first_air_date', ''))[:4],
                                'plot': result.get('overview', ''),
                                'rating': result.get('vote_average', ''),
                                'poster_url': f"https://image.tmdb.org/t/p/w500{result.get('poster_path', '')}" if result.get('poster_path') else None,
                                'genres': [genre['name'] for genre in result.get('genre_ids', [])],
                                'source': 'tmdb'
                            }
            
            return None
            
        except Exception as e:
            logger.error(f"Error buscando en TMDB: {e}")
            return None
    
    async def _search_omdb(self, query: str) -> Optional[Dict]:
        """Busca en OMDB"""
        try:
            if self.omdb_api_key == 'tu_api_key_aqui':
                return None
            
            url = "http://www.omdbapi.com/"
            params = {
                'apikey': self.omdb_api_key,
                't': query,
                'plot': 'full'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('Response') == 'True':
                            return {
                                'title': data.get('Title', ''),
                                'year': data.get('Year', ''),
                                'plot': data.get('Plot', ''),
                                'rating': data.get('imdbRating', ''),
                                'poster_url': data.get('Poster') if data.get('Poster') != 'N/A' else None,
                                'genres': data.get('Genre', '').split(', '),
                                'directors': data.get('Director', '').split(', '),
                                'cast': data.get('Actors', '').split(', '),
                                'source': 'omdb'
                            }
            
            return None
            
        except Exception as e:
            logger.error(f"Error buscando en OMDB: {e}")
            return None
    
    async def _download_poster(self, poster_url: str) -> Optional[BytesIO]:
        """Descarga poster desde URL"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(poster_url) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        return BytesIO(image_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Error descargando poster: {e}")
            return None
    
    async def _generate_final_description(self, content_info: Dict, imdb_data: Dict = None) -> str:
        """Genera descripción final para el contenido"""
        try:
            # Usar descripción de IA si está disponible
            if content_info.get('ai_description'):
                description = content_info['ai_description']
            elif imdb_data and imdb_data.get('plot'):
                description = imdb_data['plot']
            else:
                # Descripción básica
                title = content_info.get('title', 'Contenido')
                content_type = 'Serie' if content_info.get('type') == 'series' else 'Película'
                year = content_info.get('year') or imdb_data.get('year', '') if imdb_data else ''
                
                description = f"🎬 {content_type}: {title}"
                if year:
                    description += f" ({year})"
                
                if imdb_data and imdb_data.get('rating'):
                    description += f"\n⭐ Rating: {imdb_data['rating']}/10"
                
                if imdb_data and imdb_data.get('genres'):
                    description += f"\n🎭 Géneros: {', '.join(imdb_data['genres'][:3])}"
            
            # Agregar watermark
            description += "\n\n🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
            
            return description
            
        except Exception as e:
            logger.error(f"Error generando descripción: {e}")
            return "🎬 Contenido multimedia\n\n🔗 <a href='https://t.me/multimediatvOficial'>Multimedia-TV 📺</a>"
    
    async def _upload_to_channels(self, message, context, content_info: Dict, description: str, poster_data: BytesIO = None) -> Dict:
        """Sube contenido a los canales"""
        try:
            result = {
                'success': False,
                'main_channel_message_id': None,
                'search_channel_message_id': None,
                'error': None
            }
            
            # Subir archivo al canal de búsqueda primero
            if message.document or message.video or message.audio:
                search_msg = await context.bot.copy_message(
                    chat_id=self.search_channel_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id
                )
                result['search_channel_message_id'] = search_msg.message_id
            
            # Subir poster al canal principal
            if poster_data:
                poster_data.seek(0)
                main_msg = await context.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=poster_data,
                    caption=description,
                    parse_mode=ParseMode.HTML
                )
                result['main_channel_message_id'] = main_msg.message_id
            else:
                # Si no hay poster, enviar solo texto
                main_msg = await context.bot.send_message(
                    chat_id=self.channel_id,
                    text=description,
                    parse_mode=ParseMode.HTML
                )
                result['main_channel_message_id'] = main_msg.message_id
            
            result['success'] = True
            return result
            
        except Exception as e:
            logger.error(f"Error subiendo a canales: {e}")
            result['error'] = str(e)
            return result
    
    async def _save_to_database(self, content_info: Dict, upload_result: Dict):
        """Guarda información en la base de datos"""
        try:
            # Determinar si es serie o película
            if content_info.get('type') == 'series':
                # Guardar como serie
                series_id = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                self.db.add_series(
                    series_id=series_id,
                    title=content_info.get('title', ''),
                    description=content_info.get('ai_description', ''),
                    cover_message_id=upload_result.get('main_channel_message_id'),
                    added_by=0,  # Sistema automático
                    auto_processed=True
                )
                
                # Agregar episodio si hay archivo
                if upload_result.get('search_channel_message_id'):
                    self.db.add_episode(
                        series_id=series_id,
                        episode_number=content_info.get('episode', 1),
                        message_id=upload_result['search_channel_message_id']
                    )
            
            logger.info(f"Contenido guardado en BD: {content_info.get('title', 'Sin título')}")
            
        except Exception as e:
            logger.error(f"Error guardando en BD: {e}")
    
    def update_config(self, new_config: Dict):
        """Actualiza configuración del auto uploader"""
        self.auto_config.update(new_config)
        logger.info(f"Configuración actualizada: {self.auto_config}")
    
    def get_config(self) -> Dict:
        """Obtiene configuración actual"""
        return self.auto_config.copy()
    
    def get_queue_status(self) -> Dict:
        """Obtiene estado de la cola de procesamiento"""
        return {
            'queue_size': len(self.processing_queue),
            'is_processing': self.is_processing,
            'max_queue_size': self.max_queue_size
        }
