import unittest

from recon_app.server import is_file_upload_path


class ServerRequestLimitTests(unittest.TestCase):
    def test_excel_uploads_use_file_limit(self):
        self.assertTrue(is_file_upload_path("/api/tasks/T1/files"))
        self.assertTrue(
            is_file_upload_path("/api/tasks/T1/platform-balance-files")
        )
        self.assertTrue(
            is_file_upload_path("/api/tasks/T1/pending-settlement-files")
        )
        self.assertTrue(
            is_file_upload_path(
                "/api/tasks/T1/operating-evidence/erp_cost/files"
            )
        )
        self.assertTrue(
            is_file_upload_path("/api/configuration/templates/V1/test")
        )

    def test_json_routes_do_not_use_file_limit(self):
        self.assertFalse(is_file_upload_path("/api/tasks"))
        self.assertFalse(
            is_file_upload_path("/api/tasks/T1/platform-balance-results")
        )


if __name__ == "__main__":
    unittest.main()
