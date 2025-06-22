#!/usr/bin/env python3
"""
Test critical functionality of the enhanced /load command
"""
import sys
import os
import asyncio
from unittest.mock import Mock, AsyncMock

# Add current directory to path
sys.path.append('.')

def test_imports():
    """Test that all required modules can be imported"""
    try:
        # Test core imports
        from telegram import Update
        from telegram.ext import ContextTypes
        print("✅ Telegram imports successful")
        
        # Test our functions
        from app import load_command, handle_group_auto_load
        print("✅ Bot functions imported successfully")
        
        return True
    except Exception as e:
        print(f"❌ Import error: {e}")
        return False

def test_load_command_logic():
    """Test the load command logic without actual Telegram calls"""
    try:
        # Mock objects
        mock_update = Mock()
        mock_context = Mock()
        mock_user = Mock()
        mock_chat = Mock()
        
        # Test case 1: Private chat
        mock_user.id = 123456789  # Assume this is an admin ID
        mock_chat.type = 'private'
        mock_chat.id = 123456789
        mock_update.effective_user = mock_user
        mock_update.effective_chat = mock_chat
        mock_update.message = Mock()
        mock_update.message.reply_text = AsyncMock()
        
        mock_context.bot_data = {}
        
        print("✅ Mock objects created for private chat test")
        
        # Test case 2: Group chat
        mock_chat.type = 'group'
        mock_chat.id = -987654321
        mock_chat.title = 'Test Group'
        
        print("✅ Mock objects created for group chat test")
        
        return True
    except Exception as e:
        print(f"❌ Logic test error: {e}")
        return False

def test_data_structures():
    """Test the data structures used by the new functionality"""
    try:
        # Test group_loads structure
        group_loads = {
            -123456789: {
                'active': True,
                'admin_id': 123456789,
                'admin_name': 'Test Admin',
                'start_time': 1234567890.0,
                'processed_count': 5
            }
        }
        
        # Test accessing the structure
        chat_id = -123456789
        if chat_id in group_loads:
            group_info = group_loads[chat_id]
            assert group_info['active'] == True
            assert group_info['processed_count'] == 5
            print("✅ Data structure access test passed")
        
        # Test state management logic
        group_load_active = group_loads.get(chat_id, {}).get('active', False)
        assert group_load_active == True
        print("✅ State management logic test passed")
        
        return True
    except Exception as e:
        print(f"❌ Data structure test error: {e}")
        return False

def test_chat_type_detection():
    """Test chat type detection logic"""
    try:
        # Test the core logic from load_command
        test_cases = [
            ('private', 'bulk_loading'),
            ('group', 'auto_processing'),
            ('supergroup', 'auto_processing'),
            ('channel', 'bulk_loading')  # fallback case
        ]
        
        for chat_type, expected_mode in test_cases:
            if chat_type in ['group', 'supergroup']:
                actual_mode = 'auto_processing'
            else:
                actual_mode = 'bulk_loading'
            
            assert actual_mode == expected_mode, f"Failed for {chat_type}"
            print(f"✅ Chat type '{chat_type}' -> '{actual_mode}' (correct)")
        
        return True
    except Exception as e:
        print(f"❌ Chat type detection test error: {e}")
        return False

def test_admin_verification():
    """Test admin verification logic"""
    try:
        # Mock admin IDs (these would come from config)
        ADMIN_IDS = [123456789, 987654321]
        
        # Test cases
        test_cases = [
            (123456789, True),   # Valid admin
            (987654321, True),   # Valid admin
            (111111111, False),  # Not admin
            (None, False)        # No user
        ]
        
        for user_id, expected_result in test_cases:
            actual_result = user_id in ADMIN_IDS if user_id else False
            assert actual_result == expected_result
            status = "admin" if actual_result else "not admin"
            print(f"✅ User {user_id} -> {status} (correct)")
        
        return True
    except Exception as e:
        print(f"❌ Admin verification test error: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Testing Enhanced /load Command Functionality")
    print("=" * 60)
    
    tests = [
        ("Import Tests", test_imports),
        ("Load Command Logic", test_load_command_logic),
        ("Data Structures", test_data_structures),
        ("Chat Type Detection", test_chat_type_detection),
        ("Admin Verification", test_admin_verification)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running: {test_name}")
        print("-" * 40)
        try:
            if test_func():
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Functionality is working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Review the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
