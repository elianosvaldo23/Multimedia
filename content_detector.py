import re
import logging
from typing import Dict, List, Optional, Tuple
from guessit import guessit
from fuzzywuzzy import fuzz
import asyncio

logger = logging.getLogger(__name__)

class ContentDetector:
    """Detecta y analiza contenido multimedia automáticamente"""
    
    def __init__(self):
        # Patrones comunes para detectar series y películas
        self.series_patterns = [
            r'(?i)s(\d{1,2})e(\d{1,2})',  # S01E01
            r'(?i)(\d{1,2})x(\d{1,2})',   # 1x01
            r'(?i)temporada\s*(\d+)',     # Temporada 1
            r'(?i)season\s*(\d+)',        # Season 1
            r'(?i)cap(?:itulo)?\s*(\d+)', # Capitulo 1
            r'(?i)episode\s*(\d+)',       # Episode 1
            r'(?i)ep\s*(\d+)',            # Ep 1
        ]
        
        self.movie_indicators = [
            'pelicula', 'movie', 'film', 'cinema', 'cine',
            'bluray', 'dvdrip', 'webrip', 'hdtv', 'cam',
            '1080p', '720p', '480p', '4k', 'uhd'
        ]
        
        self.series_indicators = [
            'serie', 'series', 'temporada', 'season', 'capitulo',
            'episode', 'cap', 'ep', 'show', 'tv'
        ]
        
        # Palabras a ignorar en títulos
        self.ignore_words = [
            'latino', 'spanish', 'english', 'subtitulado', 'doblado',
            'hd', 'full', 'completa', 'mega', 'mediafire', 'drive',
            'link', 'descargar', 'download', 'ver', 'online',
            'gratis', 'free', 'pelicula', 'serie'
        ]
    
    async def detect_content_from_message(self, message_text: str, filename: str = None) -> Dict:
        """
        Detecta contenido desde un mensaje de Telegram
        
        Args:
            message_text: Texto del mensaje
            filename: Nombre del archivo (si existe)
            
        Returns:
            Dict con información del contenido detectado
        """
        try:
            # Combinar texto del mensaje y nombre del archivo
            full_text = f"{message_text or ''} {filename or ''}".strip()
            
            if not full_text:
                return self._empty_result()
            
            # Usar guessit para análisis inicial
            guess_result = guessit(full_text)
            
            # Detectar tipo de contenido
            content_type = self._detect_content_type(full_text, guess_result)
            
            # Extraer información específica
            if content_type == 'series':
                return await self._analyze_series(full_text, guess_result)
            elif content_type == 'movie':
                return await self._analyze_movie(full_text, guess_result)
            else:
                return self._empty_result()
                
        except Exception as e:
            logger.error(f"Error detectando contenido: {e}")
            return self._empty_result()
    
    def _detect_content_type(self, text: str, guess_result: Dict) -> str:
        """Detecta si es serie o película"""
        text_lower = text.lower()
        
        # Verificar patrones de series
        for pattern in self.series_patterns:
            if re.search(pattern, text):
                return 'series'
        
        # Verificar indicadores de series
        series_score = sum(1 for indicator in self.series_indicators 
                          if indicator in text_lower)
        
        # Verificar indicadores de películas
        movie_score = sum(1 for indicator in self.movie_indicators 
                         if indicator in text_lower)
        
        # Usar guessit como referencia
        if guess_result.get('type') == 'episode':
            return 'series'
        elif guess_result.get('type') == 'movie':
            return 'movie'
        
        # Decidir basado en puntuación
        if series_score > movie_score:
            return 'series'
        elif movie_score > series_score:
            return 'movie'
        
        # Por defecto, asumir película si no hay indicadores claros
        return 'movie'
    
    async def _analyze_series(self, text: str, guess_result: Dict) -> Dict:
        """Analiza contenido de serie"""
        result = {
            'type': 'series',
            'confidence': 0.7,
            'title': self._extract_title(text, guess_result),
            'season': guess_result.get('season'),
            'episode': guess_result.get('episode'),
            'year': guess_result.get('year'),
            'quality': guess_result.get('screen_size'),
            'language': self._detect_language(text),
            'raw_text': text,
            'normalized_title': '',
            'search_query': ''
        }
        
        # Normalizar título
        result['normalized_title'] = self._normalize_title(result['title'])
        
        # Crear query de búsqueda
        result['search_query'] = self._create_search_query(result)
        
        # Calcular confianza
        result['confidence'] = self._calculate_confidence(result, text)
        
        return result
    
    async def _analyze_movie(self, text: str, guess_result: Dict) -> Dict:
        """Analiza contenido de película"""
        result = {
            'type': 'movie',
            'confidence': 0.6,
            'title': self._extract_title(text, guess_result),
            'year': guess_result.get('year'),
            'quality': guess_result.get('screen_size'),
            'language': self._detect_language(text),
            'raw_text': text,
            'normalized_title': '',
            'search_query': ''
        }
        
        # Normalizar título
        result['normalized_title'] = self._normalize_title(result['title'])
        
        # Crear query de búsqueda
        result['search_query'] = self._create_search_query(result)
        
        # Calcular confianza
        result['confidence'] = self._calculate_confidence(result, text)
        
        return result
    
    def _extract_title(self, text: str, guess_result: Dict) -> str:
        """Extrae el título del contenido"""
        # Intentar obtener título de guessit
        title = guess_result.get('title', '')
        
        if not title:
            # Extraer manualmente
            # Remover patrones comunes
            clean_text = text
            for pattern in self.series_patterns:
                clean_text = re.sub(pattern, '', clean_text, flags=re.IGNORECASE)
            
            # Remover palabras de calidad y formato
            words = clean_text.split()
            filtered_words = []
            
            for word in words:
                word_lower = word.lower()
                if (word_lower not in self.ignore_words and 
                    not re.match(r'^\d{4}$', word) and  # Años
                    not re.match(r'^\d+p$', word_lower) and  # Resoluciones
                    len(word) > 1):
                    filtered_words.append(word)
            
            title = ' '.join(filtered_words[:5])  # Máximo 5 palabras
        
        return title.strip()
    
    def _normalize_title(self, title: str) -> str:
        """Normaliza el título para búsqueda"""
        if not title:
            return ''
        
        # Remover caracteres especiales
        normalized = re.sub(r'[^\w\s]', ' ', title)
        
        # Remover espacios múltiples
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized.strip().title()
    
    def _create_search_query(self, result: Dict) -> str:
        """Crea query optimizada para búsqueda en IMDb"""
        query_parts = []
        
        if result['normalized_title']:
            query_parts.append(result['normalized_title'])
        
        if result.get('year'):
            query_parts.append(str(result['year']))
        
        return ' '.join(query_parts)
    
    def _detect_language(self, text: str) -> str:
        """Detecta el idioma del contenido"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['latino', 'spanish', 'español']):
            return 'spanish'
        elif any(word in text_lower for word in ['english', 'ingles']):
            return 'english'
        
        return 'unknown'
    
    def _calculate_confidence(self, result: Dict, original_text: str) -> float:
        """Calcula la confianza del análisis"""
        confidence = 0.5  # Base
        
        # Bonus por tener título
        if result.get('normalized_title'):
            confidence += 0.2
        
        # Bonus por tener año
        if result.get('year'):
            confidence += 0.1
        
        # Bonus para series con temporada/episodio
        if result['type'] == 'series':
            if result.get('season') or result.get('episode'):
                confidence += 0.2
        
        # Penalty por texto muy corto
        if len(original_text.split()) < 2:
            confidence -= 0.3
        
        # Penalty por muchos números/caracteres especiales
        special_ratio = len(re.findall(r'[^\w\s]', original_text)) / max(len(original_text), 1)
        if special_ratio > 0.3:
            confidence -= 0.2
        
        return max(0.0, min(1.0, confidence))
    
    def _empty_result(self) -> Dict:
        """Resultado vacío cuando no se detecta contenido"""
        return {
            'type': 'unknown',
            'confidence': 0.0,
            'title': '',
            'normalized_title': '',
            'search_query': '',
            'raw_text': ''
        }
    
    async def batch_analyze_messages(self, messages: List[Dict]) -> List[Dict]:
        """Analiza múltiples mensajes en lote"""
        results = []
        
        for message in messages:
            text = message.get('text', '')
            filename = message.get('filename', '')
            
            result = await self.detect_content_from_message(text, filename)
            result['message_id'] = message.get('message_id')
            result['chat_id'] = message.get('chat_id')
            
            results.append(result)
        
        return results
    
    def is_valid_content(self, analysis_result: Dict, min_confidence: float = 0.6) -> bool:
        """Verifica si el contenido detectado es válido"""
        return (analysis_result.get('confidence', 0) >= min_confidence and
                analysis_result.get('type') != 'unknown' and
                bool(analysis_result.get('normalized_title', '').strip()))
