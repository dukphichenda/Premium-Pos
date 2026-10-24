import os
import unittest
from unittest.mock import patch
from services.backup_service import (
    _save_to_local_gdrive_folder,
    test_gdrive_config,
    save_backup_settings,
    get_backup_settings,
    ensure_backup_tables
)
from database import execute, query_one

class TestGDriveVPSProtection(unittest.TestCase):
    def setUp(self):
        ensure_backup_tables()

    def test_save_to_local_gdrive_on_linux_rejects_windows_path(self):
        # When running on Linux, a path like G:\My Drive\inFlow_Backups must be rejected with helpful notice
        with patch('os.name', 'posix'):
            res = _save_to_local_gdrive_folder(
                '/tmp/dummy.sql',
                'dummy.sql',
                r'G:\My Drive\inFlow_Backups'
            )
            self.assertFalse(res['success'])
            self.assertIn('Cloud Server Notice', res['error'])
            self.assertIn('Hostinger VPS', res['error'])
            self.assertIn('Download', res['error'])

    def test_test_gdrive_config_on_linux_rejects_windows_path(self):
        with patch('os.name', 'posix'):
            res = test_gdrive_config(
                mode='local_sync',
                local_path=r'G:\My Drive\inFlow_Backups'
            )
            self.assertFalse(res['success'])
            self.assertIn('Cloud Server Notice', res['error'])

    def test_save_backup_settings_preserves_service_account_json(self):
        # Save credentials initially
        dummy_json = '{"client_email": "test@serviceaccount.com", "private_key": "dummy"}'
        save_backup_settings({
            'gdrive_mode': 'cloud_api',
            'gdrive_service_account_json': dummy_json,
            'gdrive_folder_id': 'folder123'
        })
        s1 = get_backup_settings()
        self.assertEqual(s1.get('gdrive_service_account_json'), dummy_json)

        # Update without providing service account JSON (e.g. updating retention count)
        save_backup_settings({
            'retention_count': 20,
            'gdrive_service_account_json': ''
        })
        s2 = get_backup_settings()
        # It must keep the existing credentials!
        self.assertEqual(s2.get('gdrive_service_account_json'), dummy_json)
        self.assertEqual(s2.get('retention_count'), 20)

if __name__ == '__main__':
    unittest.main()
