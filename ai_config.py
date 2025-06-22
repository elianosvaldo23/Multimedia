"""
Configuration file for AI Automation System
"""

import os
from typing import Dict, Any

class AIConfig:
    """Configuration manager for AI automation system"""
    
    def __init__(self):
        # AI API Configuration
        self.OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
        self.GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
        
        # Content API Configuration
        self.TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')
        self.OMDB_API_KEY = os.environ.get('OMDB_API_KEY', '')
        
        # AI Automation Settings
        self.AI_AUTO_CONFIG = {
            'enabled': False,
            'auto_accept_threshold': 0.8,
            'auto_search_enabled': True,
            'auto_notify_enabled': True,
            'processing_delay': 2,
            'max_retries': 3
        }
        
        # Content Detection Settings
        self.CONTENT_DETECTION_CONFIG = {
            'min_confidence': 0.6,
            'enable_ai_enhancement': True,
            'fallback_to_basic': True,
            'spam_filter_enabled': True
        }
        
        # Auto Uploader Settings
        self.AUTO_UPLOADER_CONFIG = {
            'enabled': False,
            'min_confidence': 0.7,
            'auto_search_imdb': True,
            'auto_generate_description': True,
            'auto_download_poster': True,
            'processing_delay': 2,
            'max_queue_size': 50,
            'max_retries': 3
        }
        
        # Channel Configuration
        self.CHANNEL_CONFIG = {
            'main_channel_id': -1002584219284,
            'search_channel_id': -1002302159104,
            'group_id': -1002585538833
        }
    
    def get_ai_status(self) -> Dict[str, Any]:
        """Get current AI configuration status"""
        return {
            'openai_configured': bool(self.OPENAI_API_KEY),
            'gemini_configured': bool(self.GEMINI_API_KEY),
            'tmdb_configured': bool(self.TMDB_API_KEY),
            'omdb_configured': bool(self.OMDB_API_KEY),
            'ai_auto_enabled': self.AI_AUTO_CONFIG['enabled'],
            'auto_uploader_enabled': self.AUTO_UPLOADER_CONFIG['enabled']
        }
    
    def update_config(self, section: str, updates: Dict[str, Any]) -> bool:
        """Update configuration section"""
        try:
            if section == 'ai_auto':
                self.AI_AUTO_CONFIG.update(updates)
            elif section == 'content_detection':
                self.CONTENT_DETECTION_CONFIG.update(updates)
            elif section == 'auto_uploader':
                self.AUTO_UPLOADER_CONFIG.update(updates)
            elif section == 'channels':
                self.CHANNEL_CONFIG.update(updates)
            else:
                return False
            return True
        except Exception:
            return False
    
    def get_config_summary(self) -> str:
        """Get formatted configuration summary"""
        status = self.get_ai_status()
        
        summary = "🤖 **AI Automation Configuration**\n\n"
        
        # API Status
        summary += "**APIs Configuradas:**\n"
        summary += f"• OpenAI: {'✅' if status['openai_configured'] else '❌'}\n"
        summary += f"• Gemini: {'✅' if status['gemini_configured'] else '❌'}\n"
        summary += f"• TMDB: {'✅' if status['tmdb_configured'] else '❌'}\n"
        summary += f"• OMDB: {'✅' if status['omdb_configured'] else '❌'}\n\n"
        
        # System Status
        summary += "**Estado del Sistema:**\n"
        summary += f"• AI Auto: {'🟢 Activado' if status['ai_auto_enabled'] else '🔴 Desactivado'}\n"
        summary += f"• Auto Uploader: {'🟢 Activado' if status['auto_uploader_enabled'] else '🔴 Desactivado'}\n\n"
        
        # Configuration Details
        summary += "**Configuración Actual:**\n"
        summary += f"• Confianza mínima: {self.AUTO_UPLOADER_CONFIG['min_confidence']*100}%\n"
        summary += f"• Búsqueda automática: {'✅' if self.AUTO_UPLOADER_CONFIG['auto_search_imdb'] else '❌'}\n"
        summary += f"• Descarga de posters: {'✅' if self.AUTO_UPLOADER_CONFIG['auto_download_poster'] else '❌'}\n"
        summary += f"• Delay de procesamiento: {self.AUTO_UPLOADER_CONFIG['processing_delay']}s\n"
        
        return summary

# Global configuration instance
ai_config = AIConfig()

# Environment setup helper
def setup_environment():
    """Setup environment variables for AI automation"""
    env_template = """
# AI Automation Environment Variables
# Copy this to your .env file and fill in your API keys

# AI APIs (Optional - system works without them)
OPENAI_API_KEY=your_openai_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# Content APIs (Optional - for enhanced metadata)
TMDB_API_KEY=your_tmdb_api_key_here
OMDB_API_KEY=your_omdb_api_key_here

# How to get API keys:
# 1. OpenAI: https://platform.openai.com/api-keys
# 2. Gemini: https://makersuite.google.com/app/apikey
# 3. TMDB: https://www.themoviedb.org/settings/api
# 4. OMDB: http://www.omdbapi.com/apikey.aspx
"""
    
    with open('.env.template', 'w') as f:
        f.write(env_template)
    
    print("📝 Environment template created: .env.template")
    print("📋 Copy this file to .env and add your API keys")

if __name__ == "__main__":
    # Create environment template
    setup_environment()
    
    # Show current configuration
    config = AIConfig()
    print(config.get_config_summary())
