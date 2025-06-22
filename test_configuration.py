#!/usr/bin/env python3
"""
Test script to validate the automatic content uploading configuration
"""

import sys
import os

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_group_configuration():
    """Test that the GROUP_ID is correctly configured"""
    print("🔍 Testing Group Configuration...")
    
    try:
        # Import the app module to check constants
        import app
        
        # Check GROUP_ID
        expected_group_id = -1002688892136
        actual_group_id = app.GROUP_ID
        
        print(f"Expected GROUP_ID: {expected_group_id}")
        print(f"Actual GROUP_ID: {actual_group_id}")
        
        if actual_group_id == expected_group_id:
            print("✅ GROUP_ID is correctly configured!")
            return True
        else:
            print("❌ GROUP_ID is NOT correctly configured!")
            return False
            
    except ImportError as e:
        print(f"❌ Error importing app module: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_auto_uploader_integration():
    """Test that AutoUploader is properly initialized"""
    print("\n🔍 Testing AutoUploader Integration...")
    
    try:
        import app
        
        # Check if auto_uploader is initialized
        if hasattr(app, 'auto_uploader'):
            print("✅ AutoUploader is initialized")
            
            # Check if it has the correct channel IDs
            uploader = app.auto_uploader
            print(f"Channel ID: {uploader.channel_id}")
            print(f"Search Channel ID: {uploader.search_channel_id}")
            
            # Check if it has the required methods
            required_methods = [
                'process_message_automatically',
                'update_config',
                'get_config',
                'get_queue_status'
            ]
            
            missing_methods = []
            for method in required_methods:
                if not hasattr(uploader, method):
                    missing_methods.append(method)
            
            if missing_methods:
                print(f"❌ Missing methods: {missing_methods}")
                return False
            else:
                print("✅ All required methods are available")
                return True
        else:
            print("❌ AutoUploader is not initialized")
            return False
            
    except Exception as e:
        print(f"❌ Error testing AutoUploader: {e}")
        return False

def test_ai_automation_handler():
    """Test that the AI automation handler is properly configured"""
    print("\n🔍 Testing AI Automation Handler...")
    
    try:
        import app
        
        # Check if handle_ai_automation function exists
        if hasattr(app, 'handle_ai_automation'):
            print("✅ handle_ai_automation function exists")
            
            # Check AI_AUTO_ENABLED variable
            if hasattr(app, 'AI_AUTO_ENABLED'):
                print(f"AI_AUTO_ENABLED: {app.AI_AUTO_ENABLED}")
                print("✅ AI_AUTO_ENABLED variable exists")
            else:
                print("❌ AI_AUTO_ENABLED variable not found")
                return False
            
            return True
        else:
            print("❌ handle_ai_automation function not found")
            return False
            
    except Exception as e:
        print(f"❌ Error testing AI automation handler: {e}")
        return False

def test_command_handlers():
    """Test that required command handlers are available"""
    print("\n🔍 Testing Command Handlers...")
    
    try:
        import app
        
        required_functions = [
            'ai_auto_command',
            'ai_uploader_command',
            'ai_status_command',
            'load_command'
        ]
        
        missing_functions = []
        for func_name in required_functions:
            if hasattr(app, func_name):
                print(f"✅ {func_name} exists")
            else:
                print(f"❌ {func_name} missing")
                missing_functions.append(func_name)
        
        if missing_functions:
            print(f"❌ Missing functions: {missing_functions}")
            return False
        else:
            print("✅ All required command handlers are available")
            return True
            
    except Exception as e:
        print(f"❌ Error testing command handlers: {e}")
        return False

def test_constants():
    """Test that all required constants are properly set"""
    print("\n🔍 Testing Constants...")
    
    try:
        import app
        
        constants_to_check = {
            'TOKEN': str,
            'ADMIN_IDS': list,
            'CHANNEL_ID': int,
            'GROUP_ID': int,
            'SEARCH_CHANNEL_ID': int
        }
        
        all_good = True
        for const_name, expected_type in constants_to_check.items():
            if hasattr(app, const_name):
                value = getattr(app, const_name)
                if isinstance(value, expected_type):
                    print(f"✅ {const_name}: {value} (type: {type(value).__name__})")
                else:
                    print(f"❌ {const_name}: Wrong type. Expected {expected_type.__name__}, got {type(value).__name__}")
                    all_good = False
            else:
                print(f"❌ {const_name}: Not found")
                all_good = False
        
        return all_good
        
    except Exception as e:
        print(f"❌ Error testing constants: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Starting Configuration Tests...")
    print("=" * 50)
    
    tests = [
        test_group_configuration,
        test_auto_uploader_integration,
        test_ai_automation_handler,
        test_command_handlers,
        test_constants
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("📊 Test Results Summary:")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    for i, (test, result) in enumerate(zip(tests, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{i+1}. {test.__name__}: {status}")
    
    print(f"\n🎯 Overall Result: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Configuration is ready for automatic content uploading.")
        print("\n📋 Next Steps:")
        print("1. Make the bot administrator in group -1002688892136")
        print("2. Run /ai_auto on to enable AI automation")
        print("3. Run /ai_uploader on to enable automatic uploading")
        print("4. Send multimedia content to the group to test!")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review the configuration.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
