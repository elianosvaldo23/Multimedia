import logging
import asyncio
import aiohttp
import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import re

logger = logging.getLogger(__name__)

class AIProcessor:
    """Procesador de IA para análisis avanzado de contenido multimedia"""
    
    def __init__(self):
        # Configuración de APIs de IA
        self.openai_api_key = os.environ.get('OPENAI_API_KEY')
        self.gemini_api_key = os.environ.get('GEMINI_API_KEY')
        
        # URLs de APIs
        self.openai_url = "https://api.openai.com/v1/chat/completions"
        self.gemini_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
        
        # Configuración
        self.max_retries = 3
        self.timeout = 30
        
        # Prompts para diferentes tipos de análisis
        self.content_analysis_prompt = """
Analiza el siguiente texto que puede contener información sobre una película o serie de TV.
Extrae la siguiente información en formato JSON:

{
    "title": "título limpio sin calidad ni formato",
    "type": "movie" o "series",
    "year": año si está presente,
    "season": número de temporada si es serie,
    "episode": número de episodio si es serie,
    "language": "spanish", "english" o "unknown",
    "quality": calidad de video si está presente,
    "confidence": número entre 0 y 1 indicando confianza,
    "is_valid_content": true/false,
    "search_query": "query optimizada para búsqueda en IMDb"
}

Texto a analizar: "{text}"

Responde SOLO con el JSON, sin explicaciones adicionales.
"""
        
        self.imdb_search_prompt = """
Basándote en la siguiente información de contenido multimedia, genera una consulta de búsqueda optimizada para IMDb/TMDB.

Información del contenido:
- Título: {title}
- Tipo: {content_type}
- Año: {year}
- Idioma: {language}

Genera una consulta de búsqueda que sea:
1. Precisa para encontrar el contenido correcto
2. Sin información técnica (calidad, formato, etc.)
3. En el idioma apropiado para la búsqueda

Responde solo con la consulta de búsqueda, sin explicaciones.
"""
    
    async def analyze_content_with_ai(self, text: str, use_openai: bool = True) -> Dict:
        """
        Analiza contenido usando IA (OpenAI o Gemini)
        
        Args:
            text: Texto a analizar
            use_openai: Si usar OpenAI (True) o Gemini (False)
            
        Returns:
            Dict con análisis del contenido
        """
        try:
            if use_openai and self.openai_api_key:
                return await self._analyze_with_openai(text)
            elif self.gemini_api_key:
                return await self._analyze_with_gemini(text)
            else:
                logger.warning("No hay claves de API configuradas para IA")
                return await self._fallback_analysis(text)
                
        except Exception as e:
            logger.error(f"Error en análisis con IA: {e}")
            return await self._fallback_analysis(text)
    
    async def _analyze_with_openai(self, text: str) -> Dict:
        """Analiza contenido usando OpenAI GPT"""
        try:
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "user",
                        "content": self.content_analysis_prompt.format(text=text)
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.1
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(self.openai_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        
                        # Intentar parsear JSON
                        try:
                            result = json.loads(content)
                            result['ai_provider'] = 'openai'
                            return result
                        except json.JSONDecodeError:
                            logger.error(f"Error parseando respuesta de OpenAI: {content}")
                            return await self._fallback_analysis(text)
                    else:
                        logger.error(f"Error en API de OpenAI: {response.status}")
                        return await self._fallback_analysis(text)
                        
        except Exception as e:
            logger.error(f"Error con OpenAI: {e}")
            return await self._fallback_analysis(text)
    
    async def _analyze_with_gemini(self, text: str) -> Dict:
        """Analiza contenido usando Google Gemini"""
        try:
            url = f"{self.gemini_url}?key={self.gemini_api_key}"
            
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": self.content_analysis_prompt.format(text=text)
                            }
                        ]
                    }
                ]
            }
            
            headers = {
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['candidates'][0]['content']['parts'][0]['text']
                        
                        # Intentar parsear JSON
                        try:
                            result = json.loads(content)
                            result['ai_provider'] = 'gemini'
                            return result
                        except json.JSONDecodeError:
                            logger.error(f"Error parseando respuesta de Gemini: {content}")
                            return await self._fallback_analysis(text)
                    else:
                        logger.error(f"Error en API de Gemini: {response.status}")
                        return await self._fallback_analysis(text)
                        
        except Exception as e:
            logger.error(f"Error con Gemini: {e}")
            return await self._fallback_analysis(text)
    
    async def _fallback_analysis(self, text: str) -> Dict:
        """Análisis de respaldo sin IA"""
        # Análisis básico usando reglas
        text_lower = text.lower()
        
        # Detectar tipo
        series_indicators = ['s0', 'x0', 'temporada', 'season', 'capitulo', 'episode']
        is_series = any(indicator in text_lower for indicator in series_indicators)
        
        # Extraer año
        year_match = re.search(r'(19|20)\d{2}', text)
        year = int(year_match.group()) if year_match else None
        
        # Extraer título básico
        title = re.sub(r'[^\w\s]', ' ', text)
        title = re.sub(r'\s+', ' ', title).strip()
        
        # Detectar idioma
        language = 'spanish' if any(word in text_lower for word in ['latino', 'español']) else 'unknown'
        
        return {
            'title': title[:50],  # Limitar longitud
            'type': 'series' if is_series else 'movie',
            'year': year,
            'season': None,
            'episode': None,
            'language': language,
            'quality': None,
            'confidence': 0.5,
            'is_valid_content': len(title.split()) >= 2,
            'search_query': title[:30],
            'ai_provider': 'fallback'
        }
    
    async def generate_search_query(self, content_info: Dict) -> str:
        """Genera query de búsqueda optimizada usando IA"""
        try:
            title = content_info.get('title', '')
            content_type = content_info.get('type', 'movie')
            year = content_info.get('year', '')
            language = content_info.get('language', 'unknown')
            
            if not title:
                return ''
            
            # Intentar con IA primero
            if self.openai_api_key:
                query = await self._generate_query_openai(title, content_type, year, language)
                if query:
                    return query
            
            # Fallback: generar query básica
            query_parts = [title]
            if year:
                query_parts.append(str(year))
            
            return ' '.join(query_parts)
            
        except Exception as e:
            logger.error(f"Error generando query de búsqueda: {e}")
            return content_info.get('title', '')
    
    async def _generate_query_openai(self, title: str, content_type: str, year: str, language: str) -> str:
        """Genera query usando OpenAI"""
        try:
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "user",
                        "content": self.imdb_search_prompt.format(
                            title=title,
                            content_type=content_type,
                            year=year or 'desconocido',
                            language=language
                        )
                    }
                ],
                "max_tokens": 100,
                "temperature": 0.1
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(self.openai_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content'].strip()
                        
        except Exception as e:
            logger.error(f"Error generando query con OpenAI: {e}")
        
        return ''
    
    async def enhance_content_metadata(self, basic_info: Dict, imdb_data: Dict = None) -> Dict:
        """Mejora metadatos usando IA y datos de IMDb"""
        try:
            enhanced = basic_info.copy()
            
            # Si tenemos datos de IMDb, usarlos para mejorar
            if imdb_data:
                enhanced.update({
                    'imdb_title': imdb_data.get('title', ''),
                    'imdb_year': imdb_data.get('year', ''),
                    'imdb_rating': imdb_data.get('rating', ''),
                    'imdb_plot': imdb_data.get('plot', ''),
                    'imdb_genres': imdb_data.get('genres', []),
                    'imdb_directors': imdb_data.get('directors', []),
                    'imdb_cast': imdb_data.get('cast', [])
                })
                
                # Mejorar confianza si hay coincidencia con IMDb
                if imdb_data.get('title'):
                    enhanced['confidence'] = min(1.0, enhanced.get('confidence', 0.5) + 0.3)
            
            # Generar descripción mejorada
            if self.openai_api_key and imdb_data:
                enhanced_description = await self._generate_enhanced_description(enhanced)
                if enhanced_description:
                    enhanced['ai_description'] = enhanced_description
            
            return enhanced
            
        except Exception as e:
            logger.error(f"Error mejorando metadatos: {e}")
            return basic_info
    
    async def _generate_enhanced_description(self, content_info: Dict) -> str:
        """Genera descripción mejorada usando IA"""
        try:
            prompt = f"""
Genera una descripción atractiva en español para el siguiente contenido:

Título: {content_info.get('imdb_title', content_info.get('title', ''))}
Año: {content_info.get('imdb_year', content_info.get('year', ''))}
Tipo: {content_info.get('type', '')}
Géneros: {', '.join(content_info.get('imdb_genres', []))}
Sinopsis: {content_info.get('imdb_plot', '')}

Genera una descripción de máximo 200 palabras que sea:
1. Atractiva y promocional
2. En español
3. Sin spoilers
4. Que invite a ver el contenido

Responde solo con la descripción, sin explicaciones adicionales.
"""
            
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.7
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.post(self.openai_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content'].strip()
                        
        except Exception as e:
            logger.error(f"Error generando descripción: {e}")
        
        return ''
    
    async def validate_content_quality(self, content_analysis: Dict) -> bool:
        """Valida si el contenido analizado es de calidad suficiente"""
        try:
            # Criterios de validación
            min_confidence = 0.6
            min_title_length = 2
            
            confidence = content_analysis.get('confidence', 0)
            title = content_analysis.get('title', '')
            is_valid = content_analysis.get('is_valid_content', False)
            
            # Verificaciones básicas
            if confidence < min_confidence:
                return False
            
            if len(title.split()) < min_title_length:
                return False
            
            if not is_valid:
                return False
            
            # Verificar que no sea spam
            spam_indicators = ['@', 'http', 'www', '.com', 'telegram', 'whatsapp']
            title_lower = title.lower()
            if any(indicator in title_lower for indicator in spam_indicators):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validando calidad: {e}")
            return False
    
    def is_ai_available(self) -> bool:
        """Verifica si hay APIs de IA disponibles"""
        return bool(self.openai_api_key or self.gemini_api_key)
    
    def get_ai_status(self) -> Dict:
        """Obtiene estado de las APIs de IA"""
        return {
            'openai_available': bool(self.openai_api_key),
            'gemini_available': bool(self.gemini_api_key),
            'any_available': self.is_ai_available()
        }
