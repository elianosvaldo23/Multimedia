#!/usr/bin/env python3
"""
Test script para verificar los módulos de IA
"""

import asyncio
import sys
import os

# Agregar el directorio actual al path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from content_detector import ContentDetector
from ai_processor import AIProcessor

async def test_content_detector():
    """Test del detector de contenido"""
    print("🔍 Probando Content Detector...")
    
    detector = ContentDetector()
    
    # Test cases
    test_cases = [
        {
            'text': 'Avengers Endgame 2019 1080p BluRay',
            'filename': 'Avengers.Endgame.2019.1080p.BluRay.x264.mkv',
            'expected_type': 'movie'
        },
        {
            'text': 'Breaking Bad S01E01 Pilot',
            'filename': 'Breaking.Bad.S01E01.Pilot.720p.mkv',
            'expected_type': 'series'
        },
        {
            'text': 'The Office Temporada 1 Capitulo 5',
            'filename': 'The.Office.1x05.mp4',
            'expected_type': 'series'
        },
        {
            'text': 'Inception pelicula 2010',
            'filename': 'Inception.2010.mp4',
            'expected_type': 'movie'
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n  Test {i}: {test_case['text']}")
        
        result = await detector.detect_content_from_message(
            test_case['text'], 
            test_case['filename']
        )
        
        print(f"    Tipo detectado: {result.get('type', 'unknown')}")
        print(f"    Título: {result.get('title', 'N/A')}")
        print(f"    Confianza: {result.get('confidence', 0):.2f}")
        print(f"    Válido: {detector.is_valid_content(result)}")
        
        # Verificar si el tipo es correcto
        if result.get('type') == test_case['expected_type']:
            print(f"    ✅ Tipo correcto")
        else:
            print(f"    ❌ Tipo incorrecto (esperado: {test_case['expected_type']})")

async def test_ai_processor():
    """Test del procesador de IA"""
    print("\n🤖 Probando AI Processor...")
    
    processor = AIProcessor()
    
    # Verificar estado de APIs
    status = processor.get_ai_status()
    print(f"  OpenAI disponible: {status['openai_available']}")
    print(f"  Gemini disponible: {status['gemini_available']}")
    print(f"  Alguna IA disponible: {status['any_available']}")
    
    # Test de análisis básico (fallback)
    test_text = "Avengers Endgame 2019 1080p BluRay"
    print(f"\n  Analizando: {test_text}")
    
    result = await processor.analyze_content_with_ai(test_text, use_openai=False)
    
    print(f"    Proveedor: {result.get('ai_provider', 'unknown')}")
    print(f"    Título: {result.get('title', 'N/A')}")
    print(f"    Tipo: {result.get('type', 'unknown')}")
    print(f"    Año: {result.get('year', 'N/A')}")
    print(f"    Confianza: {result.get('confidence', 0):.2f}")
    print(f"    Válido: {result.get('is_valid_content', False)}")
    
    # Test de validación
    is_valid = await processor.validate_content_quality(result)
    print(f"    Pasa validación: {is_valid}")

async def test_integration():
    """Test de integración entre módulos"""
    print("\n🔗 Probando integración de módulos...")
    
    detector = ContentDetector()
    processor = AIProcessor()
    
    test_text = "The Matrix 1999 4K UHD BluRay"
    filename = "The.Matrix.1999.4K.UHD.BluRay.x265.mkv"
    
    print(f"  Procesando: {test_text}")
    
    # Paso 1: Detección básica
    detection_result = await detector.detect_content_from_message(test_text, filename)
    print(f"    Detección básica - Confianza: {detection_result.get('confidence', 0):.2f}")
    
    # Paso 2: Análisis con IA
    ai_result = await processor.analyze_content_with_ai(f"{test_text} {filename}")
    print(f"    Análisis IA - Confianza: {ai_result.get('confidence', 0):.2f}")
    
    # Paso 3: Combinar resultados (usar el mejor)
    if ai_result.get('confidence', 0) > detection_result.get('confidence', 0):
        final_result = ai_result
        print(f"    Usando resultado de IA")
    else:
        final_result = detection_result
        print(f"    Usando resultado de detección básica")
    
    # Paso 4: Validación final
    is_valid = await processor.validate_content_quality(final_result)
    print(f"    Resultado final válido: {is_valid}")
    
    if is_valid:
        print(f"    ✅ El contenido sería procesado automáticamente")
    else:
        print(f"    ❌ El contenido requeriría revisión manual")

async def main():
    """Función principal de test"""
    print("🚀 Iniciando tests de módulos de IA\n")
    
    try:
        await test_content_detector()
        await test_ai_processor()
        await test_integration()
        
        print("\n✅ Todos los tests completados")
        
    except Exception as e:
        print(f"\n❌ Error durante los tests: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
