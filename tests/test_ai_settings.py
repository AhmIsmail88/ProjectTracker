import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from ai import settings, openrouter_client


class AISettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.user_file = self.root / 'user' / 'ai-settings.json'
        for context in (patch.dict(os.environ, {}, clear=True),
                        patch('ai.settings.get_app_dir', return_value=str(self.root)),
                        patch('ai.settings.settings_path', return_value=self.user_file)):
            context.start()
            self.addCleanup(context.stop)

    def test_clean_install_has_no_key_and_default_router(self):
        self.assertFalse(openrouter_client.is_configured())
        self.assertEqual(openrouter_client.get_model(), 'openrouter/free')

    def test_removing_portable_key_does_not_leave_stale_environment_credentials(self):
        env = self.root / '.env'
        env.write_text('OPENROUTER_API_KEY=test-key\n', encoding='utf-8')
        self.assertTrue(openrouter_client.is_configured())
        env.unlink()
        self.assertFalse(openrouter_client.is_configured())
        self.assertNotIn('OPENROUTER_API_KEY', os.environ)

    def test_settings_survive_app_move_and_blank_key_keeps_saved_key(self):
        settings.save_settings('test-key', 'test/model')
        other = self.root / 'moved-app'
        other.mkdir()
        with patch('ai.settings.get_app_dir', return_value=str(other)):
            settings.save_settings('', 'second/model')
            self.assertEqual(settings.read_settings(), {'api_key': 'test-key', 'model': 'second/model'})
        self.assertFalse((self.root / '.env').exists())

    def test_empty_or_invalid_key_does_not_write_settings(self):
        for key in ('', 'contains spaces'):
            with self.assertRaises(ValueError):
                settings.save_settings(key, '')
        self.assertFalse(self.user_file.exists())

    def test_chat_uses_current_user_settings_and_accepts_text_blocks(self):
        settings.save_settings('test-key', 'test/model')
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'message': {'content': [{'type': 'text', 'text': 'OK'}]}}]}
        with patch('ai.openrouter_client.requests.post', return_value=response) as post:
            self.assertEqual(openrouter_client.chat([{'role': 'user', 'content': 'Test'}]), 'OK')
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-key')
            self.assertEqual(json.loads(post.call_args.kwargs['data'])['model'], 'test/model')

    def test_error_does_not_echo_credential(self):
        settings.save_settings('test-key', 'test/model')
        response = Mock(status_code=401, text='Invalid test-key')
        with patch('ai.openrouter_client.requests.post', return_value=response):
            with self.assertRaises(openrouter_client.OpenRouterError) as error:
                openrouter_client.chat([])
        self.assertNotIn('test-key', str(error.exception))
