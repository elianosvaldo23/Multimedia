#!/usr/bin/env python3
"""
Integration test for the enhanced /load command with actual bot functionality
"""
import sys
import os
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch

# Add current directory to path
sys.path.append('.')

async def test_load_command_private_chat():
    """Test load command in private chat"""
    try:
        from app import load_command, ADMIN_IDS
        
        # Mock objects for private chat
        mock_update = Mock()
        mock_context = Mock()
        mock_user = Mock()
        mock_chat = Mock()
        mock_message = Mock()
        
        # Setup private chat scenario
        mock_user.id = list(ADMIN_IDS)[0] if ADMIN_IDS else 123456789
        mock_chat.type = 'private'
        mock_chat.id = mock_user.id
        mock_update.effective_user = mock_user
        mock_update.effective_chat = mock_chat
        mock_update.message = mock_message
        mock_message.reply_text = AsyncMock()
        
        # Setup context
        mock_context.bot_data = {}
        
        # Test activation
        await load_command(mock_update, mock_context)
        
        # Verify private chat mode was activated
        assert 'load_state' in mock_context.bot_data
        assert mock_context.bot_data['load_state'] == 1  # LOAD_STATE_WAITING_NAME
        assert 'current_content' in mock_context.bot_data
        
        print("✅ Private chat load command activation test passed")
        
        # Test deactivation
        mock_context.bot_data['load_state'] = 1
        await load_command(mock_update, mock_context)
        
        assert mock_context.bot_data['load_state'] == 0  # LOAD_STATE_INACTIVE
        print("✅ Private chat load command deactivation test passed")
        
        return True
    except Exception as e:
        print(f"❌ Private chat test error: {e}")
        return False

async def test_load_command_group_chat():
    """Test load command in group chat"""
    try:
        from app import load_command, ADMIN_IDS
        
        # Mock objects for group chat
        mock_update = Mock()
        mock_context = Mock()
        mock_user = Mock()
        mock_chat = Mock()
        mock_message = Mock()
        
        # Setup group chat scenario
        mock_user.id = list(ADMIN_IDS)[0] if ADMIN_IDS else 123456789
        mock_user.first_name = "Test Admin"
        mock_chat.type = 'group'
        mock_chat.id = -987654321
        mock_chat.title = "Test Group"
        mock_update.effective_user = mock_user
        mock_update.effective_chat = mock_chat
        mock_update.message = mock_message
        mock_message.reply_text = AsyncMock()
        
        # Setup context
        mock_context.bot_data = {}
        
        # Test activation
        await load_command(mock_update, mock_context)
        
        # Verify group auto mode was activated
        assert 'group_loads' in mock_context.bot_data
        assert mock_chat.id in mock_context.bot_data['group_loads']
        group_info = mock_context.bot_data['group_loads'][mock_chat.id]
        assert group_info['active'] == True
        assert group_info['admin_id'] == mock_user.id
        assert group_info['processed_count'] == 0
        
        print("✅ Group chat load command activation test passed")
        
        # Test deactivation
        await load_command(mock_update, mock_context)
        
        # Verify deactivation
        assert mock_chat.id not in mock_context.bot_data['group_loads']
        print("✅ Group chat load command deactivation test passed")
        
        return True
    except Exception as e:
        print(f"❌ Group chat test error: {e}")
        return False

async def test_group_auto_load_handler():
    """Test the group auto load handler"""
    try:
        from app import handle_group_auto_load, ADMIN_IDS
        
        # Mock objects
        mock_update = Mock()
        mock_context = Mock()
        mock_user = Mock()
        mock_chat = Mock()
        mock_message = Mock()
        mock_video = Mock()
        
        # Setup scenario
        mock_user.id = list(ADMIN_IDS)[0] if ADMIN_IDS else 123456789
        mock_user.first_name = "Test Admin"
        mock_chat.id = -987654321
        mock_update.effective_user = mock_user
        mock_update.effective_chat = mock_chat
        mock_update.message = mock_message
        mock_message.reply_text = AsyncMock()
        mock_message.video = mock_video
        mock_message.document = None
        mock_message.caption = "Test video"
        
        # Setup video object
        mock_video.file_id = "test_file_id"
        mock_video.file_size = 1024000
        
        # Setup context with active group load
        mock_context.bot_data = {
            'group_loads': {
                mock_chat.id: {
                    'active': True,
                    'admin_id': mock_user.id,
                    'admin_name': mock_user.first_name,
                    'start_time': time.time(),
                    'processed_count': 0
                }
            }
        }
        
        # Mock auto_uploader
        with patch('app.auto_uploader') as mock_auto_uploader:
            mock_auto_uploader.get_config.return_value = {'enabled': True}
            mock_auto_uploader.process_content = AsyncMock()
            
            # Test handler
            await handle_group_auto_load(mock_update, mock_context)
            
            # Verify processing
            assert mock_context.bot_data['group_loads'][mock_chat.id]['processed_count'] == 1
            mock_auto_uploader.process_content.assert_called_once()
            
        print("✅ Group auto load handler test passed")
        return True
    except Exception as e:
        print(f"❌ Group auto load handler test error: {e}")
        return False

async def test_admin_verification():
    """Test admin verification in both functions"""
    try:
        from app import load_command, handle_group_auto_load, ADMIN_IDS
        
        # Mock non-admin user
        mock_update = Mock()
        mock_context = Mock()
        mock_user = Mock()
        mock_chat = Mock()
        mock_message = Mock()
        
        mock_user.id = 999999999  # Non-admin ID
        mock_chat.type = 'group'
        mock_chat.id = -123456789
        mock_update.effective_user = mock_user
        mock_update.effective_chat = mock_chat
        mock_update.message = mock_message
        mock_message.reply_text = AsyncMock()
        
        mock_context.bot_data = {}
        
        # Test load_command with non-admin (should return early)
        await load_command(mock_update, mock_context)
        
        # Should not have created any group_loads entry
        assert 'group_loads' not in mock_context.bot_data
        print("✅ Admin verification in load_command test passed")
        
        # Test handle_group_auto_load with non-admin
        mock_message.video = Mock()
        mock_message.document = None
        await handle_group_auto_load(mock_update, mock_context)
        
        # Should not have processed anything
        assert 'group_loads' not in mock_context.bot_data
        print("✅ Admin verification in handle_group_auto_load test passed")
        
        return True
    except Exception as e:
        print(f"❌ Admin verification test error: {e}")
        return False

async def test_integration_flow():
    """Test complete integration flow"""
    try:
        from app import load_command, handle_group_auto_load, ADMIN_IDS
        
        # Mock objects
        mock_update = Mock()
        mock_context = Mock()
        mock_user = Mock()
        mock_chat = Mock()
        mock_message = Mock()
        
        # Setup admin user and group
        mock_user.id = list(ADMIN_IDS)[0] if ADMIN_IDS else 123456789
        mock_user.first_name = "Test Admin"
        mock_chat.type = 'group'
        mock_chat.id = -555555555
        mock_chat.title = "Integration Test Group"
        mock_update.effective_user = mock_user
        mock_update.effective_chat = mock_chat
        mock_update.message = mock_message
        mock_message.reply_text = AsyncMock()
        
        mock_context.bot_data = {}
        
        # Step 1: Activate group load mode
        await load_command(mock_update, mock_context)
        
        # Verify activation
        assert 'group_loads' in mock_context.bot_data
        assert mock_chat.id in mock_context.bot_data['group_loads']
        assert mock_context.bot_data['group_loads'][mock_chat.id]['active'] == True
        print("✅ Step 1: Group load mode activated")
        
        # Step 2: Send multimedia content
        mock_message.video = Mock()
        mock_message.video.file_id = "integration_test_file"
        mock_message.video.file_size = 2048000
        mock_message.document = None
        mock_message.caption = "Integration test video"
        
        with patch('app.auto_uploader') as mock_auto_uploader:
            mock_auto_uploader.get_config.return_value = {'enabled': True}
            mock_auto_uploader.process_content = AsyncMock()
            
            await handle_group_auto_load(mock_update, mock_context)
            
            # Verify processing
            assert mock_context.bot_data['group_loads'][mock_chat.id]['processed_count'] == 1
            print("✅ Step 2: Multimedia content processed")
        
        # Step 3: Send more content
        await handle_group_auto_load(mock_update, mock_context)
        assert mock_context.bot_data['group_loads'][mock_chat.id]['processed_count'] == 2
        print("✅ Step 3: Additional content processed")
        
        # Step 4: Deactivate group load mode
        mock_message.video = None  # Reset for command
        await load_command(mock_update, mock_context)
        
        # Verify deactivation
        assert mock_chat.id not in mock_context.bot_data['group_loads']
        print("✅ Step 4: Group load mode deactivated")
        
        print("✅ Complete integration flow test passed")
        return True
    except Exception as e:
        print(f"❌ Integration flow test error: {e}")
        return False

async def main():
    """Run all integration tests"""
    print("🧪 Testing Enhanced /load Command Integration")
    print("=" * 60)
    
    tests = [
        ("Load Command Private Chat", test_load_command_private_chat),
        ("Load Command Group Chat", test_load_command_group_chat),
        ("Group Auto Load Handler", test_group_auto_load_handler),
        ("Admin Verification", test_admin_verification),
        ("Integration Flow", test_integration_flow)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running: {test_name}")
        print("-" * 40)
        try:
            if await test_func():
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
    
    print("\n" + "=" * 60)
    print(f"📊 Integration Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All integration tests passed! Bot functionality is working correctly.")
        return True
    else:
        print("⚠️  Some integration tests failed. Review the implementation.")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
