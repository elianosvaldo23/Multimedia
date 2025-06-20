import pymongo
from datetime import datetime, timedelta
import logging
import os
import re
from bson.objectid import ObjectId

# Configuración del registro
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Database:
    """Clase para manejar todas las operaciones de base de datos con MongoDB"""
    
    def __init__(self):
        """Inicializar conexión a MongoDB"""
        # Obtener la URL de conexión desde variables de entorno o usar valor por defecto
        mongo_url = os.environ.get('MONGODB_URI', 'mongodb+srv://multimediatv_admin:multimediatv@cluster0.3at13js.mongodb.net/multimediatv_bot?retryWrites=true&w=majority&appName=Cluster0')
        
        try:
            # Conectar a MongoDB
            self.client = pymongo.MongoClient(mongo_url)
            
            # Crear o acceder a la base de datos
            self.db = self.client['multimedia_tv_bot']
            
            # Crear o acceder a las colecciones
            self.users = self.db['users']
            self.series = self.db['series']
            self.episodes = self.db['episodes']
            self.gift_codes = self.db['gift_codes']
            self.stats = self.db['stats']
            # Colecciones para series multi-temporada
            self.multi_series = self.db['multi_series']
            self.seasons = self.db['seasons']
            self.season_episodes = self.db['season_episodes']
            
            # Añadir colección para el caché de búsquedas
            self.search_cache = self.db['search_cache']
            
            # Crear índices para mejorar el rendimiento
            self._create_indexes()
            
            logger.info("Conexión a MongoDB establecida correctamente")
            
        except Exception as e:
            logger.error(f"Error al conectar con MongoDB: {e}")
            raise e
    
    def _create_indexes(self):
        """Crear índices para optimizar consultas"""
        try:
            # Primero, limpiar documentos con valores nulos en campos únicos
            self.seasons.delete_many({"season_id": None})
            self.multi_series.delete_many({"series_id": None})
            self.series.delete_many({"series_id": None})
            
            # Índices para usuarios
            self.users.create_index("user_id", unique=True)
            self.users.create_index("username")
            
            # Índices para series
            self.series.create_index("series_id", unique=True)
            self.series.create_index("title")
            
            # Índices para episodios
            self.episodes.create_index([("series_id", pymongo.ASCENDING), 
                                       ("episode_number", pymongo.ASCENDING)], 
                                       unique=True)
            
            # Índices para códigos de regalo
            self.gift_codes.create_index("code", unique=True)
            
            # Índices para series multi-temporada
            self.multi_series.create_index("series_id", unique=True)
            
            # Índice compuesto para temporadas (series_id + season_number debe ser único)
            self.seasons.create_index([
                ("series_id", pymongo.ASCENDING),
                ("season_number", pymongo.ASCENDING)
            ], unique=True)
            
            # Índice simple para season_id
            self.seasons.create_index("season_id", unique=True)
            
            self.season_episodes.create_index("season_id")
            
            # Crear índice TTL para el caché de búsquedas (30 días = 2592000 segundos)
            self.search_cache.create_index("timestamp", expireAfterSeconds=2592000)
            self.search_cache.create_index("query")
            
            logger.info("Índices de MongoDB creados correctamente")
        except Exception as e:
            logger.error(f"Error creando índices: {e}")
    
    def add_user(self, user_id, username, first_name, last_name):
        """Agregar un nuevo usuario a la base de datos"""
        try:
            user = {
                "user_id": user_id,
                "username": username or "",
                "first_name": first_name or "",
                "last_name": last_name or "",
                "plan_type": "basic",
                "plan_expiry": None,
                "daily_searches": 0,
                "daily_requests": 0,
                "total_searches": 0,
                "total_requests": 0,
                "balance": 0,
                "banned": False,
                "join_date": datetime.now(),
                "last_active": datetime.now()
            }
            
            # Insertar o actualizar si ya existe
            self.users.update_one(
                {"user_id": user_id},
                {"$set": user},
                upsert=True
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al añadir usuario: {e}")
            return False
    
    def get_user(self, user_id):
        """Obtener información de un usuario por ID"""
        try:
            user = self.users.find_one({"user_id": user_id})
            
            # Actualizar última actividad
            if user:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"last_active": datetime.now()}}
                )
                
            return user
        except Exception as e:
            logger.error(f"Error al obtener usuario: {e}")
            return None
    
    def user_exists(self, user_id):
        """Comprobar si un usuario existe en la base de datos"""
        try:
            return self.users.count_documents({"user_id": user_id}) > 0
        except Exception as e:
            logger.error(f"Error al comprobar existencia de usuario: {e}")
            return False
    
    def update_plan(self, user_id, plan_type, expiry_date=None):
        """Actualizar el plan de un usuario"""
        try:
            update_data = {
                "plan_type": plan_type,
                "plan_expiry": expiry_date
            }
            
            # Actualizar permisos según el plan
            if plan_type == 'plus' or plan_type == 'ultra':
                update_data["can_forward"] = True
            else:
                update_data["can_forward"] = False
            
            self.users.update_one(
                {"user_id": user_id},
                {"$set": update_data}
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al actualizar plan: {e}")
            return False
    
    def increment_daily_usage(self, user_id):
        """Incrementar el contador de búsquedas diarias y verificar límites"""
        try:
            # Obtener datos del usuario
            user_data = self.get_user(user_id)
            
            if not user_data:
                return False
                
            # Verificar si el usuario está baneado
            if user_data.get('banned', False):
                return False
            
            # Obtener plan y límites
            plan_type = user_data.get('plan_type', 'basic')
            from plans import PLANS  # Importar planes desde el módulo correspondiente
            
            daily_limit = PLANS.get(plan_type, PLANS['basic']).get('searches_per_day', 3)
            current_searches = user_data.get('daily_searches', 0)
            
            # Verificar si ha alcanzado el límite
            if current_searches >= daily_limit and daily_limit != float('inf'):
                return False
            
            # Incrementar contador
            self.users.update_one(
                {"user_id": user_id},
                {
                    "$inc": {
                        "daily_searches": 1,
                        "total_searches": 1
                    }
                }
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al incrementar uso diario: {e}")
            return False
    
    def get_requests_left(self, user_id):
        """Obtener el número de pedidos restantes para un usuario"""
        try:
            user_data = self.get_user(user_id)
            
            if not user_data:
                return 0
            
            # Obtener plan y límites
            plan_type = user_data.get('plan_type', 'basic')
            from plans import PLANS
            
            daily_limit = PLANS.get(plan_type, PLANS['basic']).get('requests_per_day', 1)
            current_requests = user_data.get('daily_requests', 0)
            
            # Si el límite es infinito
            if daily_limit == float('inf'):
                return float('inf')
                
            return max(0, daily_limit - current_requests)
        except Exception as e:
            logger.error(f"Error al obtener pedidos restantes: {e}")
            return 0
    
    def update_request_count(self, user_id):
        """Incrementar el contador de pedidos diarios"""
        try:
            self.users.update_one(
                {"user_id": user_id},
                {
                    "$inc": {
                        "daily_requests": 1,
                        "total_requests": 1
                    }
                }
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al actualizar contador de pedidos: {e}")
            return False
    
    def add_referral(self, referrer_id, referred_id):
        """Añadir un nuevo referido y actualizar balance"""
        try:
            # Comprobar que no sea auto-referencia
            if referrer_id == referred_id:
                return False
                
            # Comprobar que el usuario referido no haya sido referido antes
            if self.is_referred(referred_id):
                return False
                
            # Añadir referencia
            self.users.update_one(
                {"user_id": referred_id},
                {"$set": {"referred_by": referrer_id}}
            )
            
            # Incrementar balance del referente
            self.users.update_one(
                {"user_id": referrer_id},
                {"$inc": {"balance": 1}}
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al añadir referido: {e}")
            return False
    
    def is_referred(self, user_id):
        """Comprobar si un usuario ya ha sido referido"""
        try:
            user_data = self.get_user(user_id)
            return user_data and 'referred_by' in user_data
        except Exception as e:
            logger.error(f"Error al comprobar si el usuario ha sido referido: {e}")
            return False
    
    def get_referral_count(self, user_id):
        """Obtener el número de referidos de un usuario"""
        try:
            return self.users.count_documents({"referred_by": user_id})
        except Exception as e:
            logger.error(f"Error al obtener conteo de referidos: {e}")
            return 0
    
    def ban_user(self, user_id):
        """Banear a un usuario"""
        try:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"banned": True}}
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al banear usuario: {e}")
            return False
    
    def is_user_banned(self, user_id):
        """Comprobar si un usuario está baneado"""
        try:
            user_data = self.get_user(user_id)
            return user_data and user_data.get('banned', False)
        except Exception as e:
            logger.error(f"Error al comprobar si el usuario está baneado: {e}")
            return False
    
    def get_user_id_by_username(self, username):
        """Obtener el ID de un usuario por su nombre de usuario"""
        try:
            user = self.users.find_one({"username": username})
            return user['user_id'] if user else None
        except Exception as e:
            logger.error(f"Error al obtener ID de usuario por nombre: {e}")
            return None
    
    def add_gift_code(self, code, plan_type, max_uses):
        """Añadir un nuevo código de regalo"""
        try:
            gift_code = {
                "code": code,
                "plan_type": plan_type,
                "max_uses": max_uses,
                "used": 0,
                "created_at": datetime.now()
            }
            
            self.gift_codes.update_one(
                {"code": code},
                {"$set": gift_code},
                upsert=True
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al añadir código de regalo: {e}")
            return False
    
    def get_gift_code(self, code):
        """Obtener información de un código de regalo"""
        try:
            gift_code = self.gift_codes.find_one({"code": code})
            
            # Verificar si el código es válido y tiene usos disponibles
            if gift_code and gift_code['used'] < gift_code['max_uses']:
                return gift_code
                
            return None
        except Exception as e:
            logger.error(f"Error al obtener código de regalo: {e}")
            return None
    
    def update_gift_code_usage(self, code):
        """Actualizar el uso de un código de regalo"""
        try:
            self.gift_codes.update_one(
                {"code": code},
                {"$inc": {"used": 1}}
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al actualizar uso de código de regalo: {e}")
            return False
    
    def reset_daily_limits(self):
        """Reiniciar los contadores diarios de todos los usuarios"""
        try:
            self.users.update_many(
                {},
                {"$set": {
                    "daily_searches": 0,
                    "daily_requests": 0
                }}
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al reiniciar límites diarios: {e}")
            return False
    
    def get_expired_plans(self):
        """Obtener lista de usuarios con planes expirados"""
        try:
            now = datetime.now()
            
            # Buscar usuarios con plan expirado
            expired_users = self.users.find({
                "plan_expiry": {"$lt": now},
                "plan_type": {"$ne": "basic"}
            })
            
            return [user['user_id'] for user in expired_users]
        except Exception as e:
            logger.error(f"Error al obtener planes expirados: {e}")
            return []
    
    def get_total_users(self):
        """Obtener el número total de usuarios"""
        try:
            return self.users.count_documents({})
        except Exception as e:
            logger.error(f"Error al obtener total de usuarios: {e}")
            return 0
    
    def get_active_users(self, days=7):
        """Obtener el número de usuarios activos en los últimos X días"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            return self.users.count_documents({
                "last_active": {"$gte": cutoff_date}
            })
        except Exception as e:
            logger.error(f"Error al obtener usuarios activos: {e}")
            return 0
    
    def get_premium_users(self):
        """Obtener el número de usuarios con planes premium"""
        try:
            return self.users.count_documents({
                "plan_type": {"$ne": "basic"}
            })
        except Exception as e:
            logger.error(f"Error al obtener usuarios premium: {e}")
            return 0
    
    def get_total_searches(self):
        """Obtener el número total de búsquedas realizadas"""
        try:
            pipeline = [
                {"$group": {
                    "_id": None,
                    "total_searches": {"$sum": "$total_searches"}
                }}
            ]
            
            result = list(self.users.aggregate(pipeline))
            
            if result:
                return result[0]["total_searches"]
                
            return 0
        except Exception as e:
            logger.error(f"Error al obtener total de búsquedas: {e}")
            return 0
    
    def get_total_requests(self):
        """Obtener el número total de pedidos realizados"""
        try:
            pipeline = [
                {"$group": {
                    "_id": None,
                    "total_requests": {"$sum": "$total_requests"}
                }}
            ]
            
            result = list(self.users.aggregate(pipeline))
            
            if result:
                return result[0]["total_requests"]
                
            return 0
        except Exception as e:
            logger.error(f"Error al obtener total de pedidos: {e}")
            return 0
    
    def get_users_by_plan(self, plan_type):
        """Obtener el número de usuarios con un plan específico"""
        try:
            return self.users.count_documents({
                "plan_type": plan_type
            })
        except Exception as e:
            logger.error(f"Error al obtener usuarios por plan: {e}")
            return 0
    
    def get_all_users(self):
        """Obtener todos los IDs de usuarios"""
        try:
            users = list(self.db.users.find({}, {'user_id': 1}))
            return users
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def add_series(self, series_id, title, description, cover_message_id, added_by):
        """Añadir una nueva serie a la base de datos"""
        try:
            series = {
                "series_id": series_id,
                "title": title,
                "description": description,
                "cover_message_id": cover_message_id,
                "added_by": added_by,
                "created_at": datetime.now()
            }
            
            self.series.update_one(
                {"series_id": series_id},
                {"$set": series},
                upsert=True
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al añadir serie: {e}")
            return False
    
    def find_series_by_cover_message_id(self, cover_message_id):
        """Buscar una serie por su ID de mensaje de portada"""
        try:
            series = self.series.find_one({"cover_message_id": cover_message_id})
            return series
        except Exception as e:
            logger.error(f"Error buscando serie por ID de mensaje de portada: {e}")
            return None

    def find_episode_by_message_id(self, message_id):
        """Buscar un episodio por su ID de mensaje"""
        try:
            episode = self.episodes.find_one({"message_id": message_id})
            return episode
        except Exception as e:
            logger.error(f"Error buscando episodio por ID de mensaje: {e}")
            return None
    
    def add_episode(self, series_id, episode_number, message_id):
        """Añadir un episodio a una serie"""
        try:
            episode = {
                "series_id": series_id,
                "episode_number": episode_number,
                "message_id": message_id,
                "added_at": datetime.now()
            }
            
            self.episodes.update_one(
                {
                    "series_id": series_id,
                    "episode_number": episode_number
                },
                {"$set": episode},
                upsert=True
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al añadir episodio: {e}")
            return False
    
    def get_series(self, series_id):
        """Obtener información de una serie por ID"""
        try:
            return self.series.find_one({"series_id": series_id})
        except Exception as e:
            logger.error(f"Error al obtener serie: {e}")
            return None
    
    def get_episode(self, series_id, episode_number):
        """Obtener un episodio específico de una serie"""
        try:
            return self.episodes.find_one({
                "series_id": series_id,
                "episode_number": episode_number
            })
        except Exception as e:
            logger.error(f"Error al obtener episodio: {e}")
            return None
    
    def get_series_episodes(self, series_id):
        """Obtener todos los episodios de una serie"""
        try:
            episodes = self.episodes.find({"series_id": series_id}).sort("episode_number", 1)
            return list(episodes)
        except Exception as e:
            logger.error(f"Error al obtener episodios de serie: {e}")
            return []
    
    def add_multi_series(self, series_id, title, description, cover_message_id, added_by):
        """Añadir una serie con múltiples temporadas"""
        try:
            series_data = {
                'series_id': series_id,
                'title': title,
                'description': description,
                'cover_message_id': cover_message_id,
                'added_by': added_by,
                'added_date': datetime.now()
            }
            self.db.multi_series.insert_one(series_data)
            return series_id
        except Exception as e:
            logger.error(f"Error al añadir serie multi-temporada: {e}")
            return None

    def add_season(self, season_id, series_id, season_name):
        """Añadir una temporada a una serie"""
        try:
            # Convertir IDs a enteros para garantizar consistencia
            season_id = int(season_id)
            series_id = int(series_id)
            
            # Extraer número de temporada del nombre usando expresión regular
            season_number = None
            match = re.search(r'temporada\s*(\d+)', season_name.lower())
            if match:
                season_number = int(match.group(1))
            else:
                # Si no encuentra el número en el nombre, usar un contador
                existing_seasons = self.db.seasons.find({'series_id': series_id}).sort('season_number', -1).limit(1)
                last_season = next(existing_seasons, None)
                season_number = (last_season.get('season_number', 0) if last_season else 0) + 1

            # Verificar si ya existe una temporada con este ID
            existing_season = self.db.seasons.find_one({
                'series_id': series_id,
                'season_number': season_number
            })
            
            if existing_season:
                # Actualizar la temporada existente
                self.db.seasons.update_one(
                    {'_id': existing_season['_id']},
                    {'$set': {
                        'season_id': season_id,
                        'season_name': season_name,
                        'updated_date': datetime.now()
                    }}
                )
            else:
                # Insertar nueva temporada
                season_data = {
                    'season_id': season_id,
                    'series_id': series_id,
                    'season_name': season_name,
                    'season_number': season_number,  # Añadir número de temporada
                    'added_date': datetime.now()
                }
                self.db.seasons.insert_one(season_data)
            
            logger.info(f"Temporada {season_number} añadida/actualizada para serie {series_id}: {season_name}")
            return season_id
            
        except Exception as e:
            logger.error(f"Error en add_season: {e}")
            raise

    def add_season_episode(self, season_id, episode_number, message_id):
        """Añadir un episodio a una temporada"""
        try:
            episode_data = {
                'season_id': season_id,
                'episode_number': episode_number,
                'message_id': message_id
            }
            self.db.season_episodes.insert_one(episode_data)
            return True
        except Exception as e:
            logger.error(f"Error al añadir episodio de temporada: {e}")
            return False

    def get_multi_series(self, series_id):
        """Obtener información de una serie multi-temporada"""
        try:
            return self.db.multi_series.find_one({'series_id': series_id})
        except Exception as e:
            logger.error(f"Error al obtener serie multi-temporada: {e}")
            return None

    def get_seasons(self, series_id):
        """Obtener todas las temporadas de una serie"""
        try:
            # Asegurar que series_id es un entero
            series_id = int(series_id)
            
            # Buscar todas las temporadas que coincidan exactamente con el series_id
            seasons = self.db.seasons.find({'series_id': series_id})
            
            # Convertir el cursor a lista y registrar para debug
            seasons_list = list(seasons)
            logger.info(f"get_seasons: Encontradas {len(seasons_list)} temporadas para series_id {series_id}")
            
            # Ordenar por nombre de temporada
            seasons_list.sort(key=lambda x: x.get('season_number', 0))
            
            return seasons_list
        except Exception as e:
            logger.error(f"Error en get_seasons: {e}")
            return []

    def get_season(self, season_id):
        """Obtener información de una temporada específica"""
        try:
            return self.db.seasons.find_one({'season_id': season_id})
        except Exception as e:
            logger.error(f"Error al obtener temporada: {e}")
            return None

    def get_season_episodes(self, season_id):
        """Obtener todos los episodios de una temporada"""
        try:
            return list(self.db.season_episodes.find({'season_id': season_id}).sort('episode_number', 1))
        except Exception as e:
            logger.error(f"Error al obtener episodios de temporada: {e}")
            return []

    def save_search_cache(self, query, cache_data):
        """Guardar resultados de búsqueda en caché"""
        try:
            # Asegurar que los datos del caché tienen el formato correcto
            cache_entry = {
                "query": query,
                "results": cache_data["results"],
                "timestamp": datetime.now(),
                "cache_version": cache_data.get("cache_version", "1.0"),
                "result_count": cache_data.get("result_count", len(cache_data["results"]))
            }
            
            # Actualizar o insertar en la colección de caché
            self.search_cache.update_one(
                {"query": query},
                {"$set": cache_entry},
                upsert=True
            )
            
            logger.info(f"Caché guardado para query: {query}")
            return True
        except Exception as e:
            logger.error(f"Error guardando caché de búsqueda: {e}")
            return False

    def get_search_cache(self, query):
        """Obtener resultados de búsqueda desde caché"""
        try:
            cache_data = self.search_cache.find_one({"query": query})
            
            if cache_data:
                # Verificar si el caché está dentro del período de validez (30 días)
                cache_time = cache_data.get('timestamp')
                if cache_time:
                    age = datetime.now() - cache_time
                    if age.days <= 30:  # Caché válido por 30 días
                        logger.info(f"Caché encontrado para query: {query}")
                        return cache_data
                
                # Si el caché es muy antiguo, eliminarlo
                self.search_cache.delete_one({"query": query})
                
            return None
        except Exception as e:
            logger.error(f"Error obteniendo caché de búsqueda: {e}")
            return None

    def clear_search_cache(self):
        """Limpiar todo el caché de búsquedas"""
        try:
            result = self.search_cache.delete_many({})
            logger.info(f"Caché limpiado: {result.deleted_count} entradas eliminadas")
            return True
        except Exception as e:
            logger.error(f"Error limpiando caché de búsqueda: {e}")
            return False

    def clear_old_cache(self):
        """Limpiar caché antiguo (más de 30 días)"""
        try:
            expiry_date = datetime.now() - timedelta(days=30)
            result = self.search_cache.delete_many({
                "timestamp": {"$lt": expiry_date}
            })
            logger.info(f"Caché antiguo limpiado: {result.deleted_count} entradas eliminadas")
            return True
        except Exception as e:
            logger.error(f"Error limpiando caché antiguo: {e}")
            return False

    def get_cache_stats(self):
        """Obtener estadísticas del caché"""
        try:
            total_entries = self.search_cache.count_documents({})
            
            # Calcular espacio usado (aproximado)
            stats = self.search_cache.aggregate([
                {
                    "$group": {
                        "_id": None,
                        "total_results": {"$sum": "$result_count"},
                        "avg_results": {"$avg": "$result_count"}
                    }
                }
            ])
            
            stats = list(stats)
            if stats:
                stats = stats[0]
                return {
                    "total_entries": total_entries,
                    "total_results": stats["total_results"],
                    "avg_results_per_query": round(stats["avg_results"], 2)
                }
            
            return {
                "total_entries": total_entries,
                "total_results": 0,
                "avg_results_per_query": 0
            }
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas del caché: {e}")
            return {
                "total_entries": 0,
                "total_results": 0,
                "avg_results_per_query": 0
            }
