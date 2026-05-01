import unittest
from email.message import Message

from autotiangong.config import AppConfig, LoginConfig
from autotiangong.http_client import HttpResponse
from autotiangong.portal import _classify_login_response, _derive_logout_url


class PortalClassificationTest(unittest.TestCase):
    def test_quota_limit_marker_is_classified_separately(self):
        config = AppConfig(
            portal_url="http://172.23.4.5/",
            login=LoginConfig(
                failure_markers=["authfail"],
                quota_limit_markers=["流量已达上限"],
            ),
        )
        response = HttpResponse(
            status=200,
            url="http://172.23.4.5:801/eportal/",
            body="账号流量已达上限".encode("utf-8"),
            headers=Message(),
        )

        result = _classify_login_response(response, config, "success", "authfail")

        self.assertFalse(result.ok)
        self.assertTrue(result.quota_limited)
        self.assertIn("quota limit", result.message)

    def test_derives_drcom_logout_url_from_login_url(self):
        logout_url = _derive_logout_url("http://172.23.4.5:801/eportal/?c=ACSetting&a=Login&url=drappall")

        self.assertEqual(logout_url, "http://172.23.4.5:801/eportal/?c=ACSetting&a=Logout&url=drappall")


if __name__ == "__main__":
    unittest.main()
