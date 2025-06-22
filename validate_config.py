#!/usr/bin/env python3
"""
Simple configuration validator that checks the GROUP_ID without importing telegram
"""

import re

def validate_group_id():
    """Validate that GROUP_ID is correctly set in app.py"""
    print("🔍 Validating GROUP_ID in app.py...")
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Search for GROUP_ID assignment
        group_id_pattern = r'GROUP_ID\s*=\s*(-?\d+)'
        matches = re.findall(group_id_pattern, content)
        
        if matches:
            group_id = int(matches[0])
            expected_group_id = -1002688892136
            
            print(f"Found GROUP_ID: {group_id}")
            print(f"Expected GROUP_ID: {expected_group_id}")
            
            if group_id == expected_group_id:
                print("✅ GROUP_ID is correctly configured!")
                return True
            else:
                print("❌ GROUP_ID is NOT correctly configured!")
                return False
        else:
            print("❌ GROUP_ID not found in app.py")
            return False
            
    except FileNotFoundError:
        print("❌ app.py file not found")
        return False
    except Exception as e:
        print(f"❌ Error reading app.py: {e}")
        return False

def validate_ai_automation_handler():
    """Validate that handle_ai_automation function checks the correct GROUP_ID"""
    print("\n🔍 Validating AI automation handler...")
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Check if handle_ai_automation function exists
        if 'async def handle_ai_automation' in content:
            print("✅ handle_ai_automation function found")
            
            # Check if it references GROUP_ID in the chat_id check (updated format)
            if 'update.message.chat_id not in [GROUP_ID, CHANNEL_ID, SEARCH_CHANNEL_ID]' in content:
                print("✅ Function correctly checks GROUP_ID for message filtering")
                return True
            elif 'update.message.chat_id not in [GROUP_ID, CHANNEL_ID]' in content:
                print("✅ Function correctly checks GROUP_ID for message filtering (legacy format)")
                return True
            else:
                print("❌ Function does not properly check GROUP_ID")
                return False
        else:
            print("❌ handle_ai_automation function not found")
            return False
            
    except Exception as e:
        print(f"❌ Error validating AI automation handler: {e}")
        return False

def validate_auto_uploader_initialization():
    """Validate that AutoUploader is properly initialized"""
    print("\n🔍 Validating AutoUploader initialization...")
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Check if AutoUploader is imported
        if 'from auto_uploader import AutoUploader' in content:
            print("✅ AutoUploader import found")
            
            # Check if auto_uploader is initialized
            if 'auto_uploader = AutoUploader(CHANNEL_ID, SEARCH_CHANNEL_ID, db)' in content:
                print("✅ AutoUploader is properly initialized")
                return True
            else:
                print("❌ AutoUploader initialization not found")
                return False
        else:
            print("❌ AutoUploader import not found")
            return False
            
    except Exception as e:
        print(f"❌ Error validating AutoUploader: {e}")
        return False

def validate_command_handlers():
    """Validate that required command handlers exist"""
    print("\n🔍 Validating command handlers...")
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        required_handlers = [
            'async def ai_auto_command',
            'async def ai_uploader_command', 
            'async def ai_status_command',
            'async def load_command'
        ]
        
        missing_handlers = []
        for handler in required_handlers:
            if handler in content:
                print(f"✅ {handler.split()[-1]} found")
            else:
                print(f"❌ {handler.split()[-1]} missing")
                missing_handlers.append(handler)
        
        return len(missing_handlers) == 0
        
    except Exception as e:
        print(f"❌ Error validating command handlers: {e}")
        return False

def validate_message_handler_registration():
    """Validate that the AI automation handler is registered"""
    print("\n🔍 Validating message handler registration...")
    
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Check if the AI automation handler is registered
        if 'handle_ai_automation' in content and 'group=-1' in content:
            print("✅ AI automation handler is registered with correct priority")
            return True
        else:
            print("❌ AI automation handler registration not found")
            return False
            
    except Exception as e:
        print(f"❌ Error validating handler registration: {e}")
        return False

def main():
    """Run all validation tests"""
    print("🚀 Starting Configuration Validation...")
    print("=" * 60)
    
    tests = [
        validate_group_id,
        validate_ai_automation_handler,
        validate_auto_uploader_initialization,
        validate_command_handlers,
        validate_message_handler_registration
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("📊 Validation Results Summary:")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    test_names = [
        "GROUP_ID Configuration",
        "AI Automation Handler", 
        "AutoUploader Initialization",
        "Command Handlers",
        "Message Handler Registration"
    ]
    
    for i, (name, result) in enumerate(zip(test_names, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{i+1}. {name}: {status}")
    
    print(f"\n🎯 Overall Result: {passed}/{total} validations passed")
    
    if passed == total:
        print("\n🎉 All validations passed! Configuration is ready!")
        print("\n📋 Next Steps to Enable Automatic Uploading:")
        print("1. Make the bot administrator in group -1002688892136")
        print("2. Run /ai_auto on to enable AI automation")
        print("3. Run /ai_uploader on to enable automatic uploading")
        print("4. Send multimedia content to the group to test!")
        print("\n💡 The bot will automatically process multimedia files sent to the configured group.")
        return True
    else:
        print(f"\n⚠️  {total - passed} validation(s) failed. Please review the configuration.")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
