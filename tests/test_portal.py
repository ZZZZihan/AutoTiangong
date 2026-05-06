import unittest
from email.message import Message

from autotiangong.config import AppConfig, LoginConfig
from autotiangong.http_client import HttpResponse
from autotiangong.portal import (
    _classify_kernel_login_response,
    _classify_login_response,
    _derive_logout_url,
    _extract_session_uid,
)


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
            url="http://172.23.4.5:801/eportal/?DDDDD=alice&upass=secret&keep=1",
            body="账号流量已达上限".encode("utf-8"),
            headers=Message(),
        )

        result = _classify_login_response(response, config, "success", "authfail")

        self.assertFalse(result.ok)
        self.assertTrue(result.quota_limited)
        self.assertTrue(result.account_unavailable)
        self.assertEqual(result.reason, "quota_limited")
        self.assertIn("quota limit", result.message)
        self.assertEqual(result.url, "http://172.23.4.5:801/eportal/?DDDDD=%2A%2A%2A&upass=%2A%2A%2A&keep=1")

    def test_account_unavailable_marker_is_classified_for_switching(self):
        config = AppConfig(
            portal_url="http://172.23.4.5/",
            login=LoginConfig(
                failure_markers=["authfail"],
                account_unavailable_markers=["password error"],
            ),
        )
        response = HttpResponse(
            status=200,
            url="http://172.23.4.5:801/eportal/",
            body=b"Password Error",
            headers=Message(),
        )

        result = _classify_login_response(response, config, "success", "authfail")

        self.assertFalse(result.ok)
        self.assertTrue(result.account_unavailable)
        self.assertEqual(result.reason, "account_unavailable")

    def test_derives_drcom_logout_url_from_login_url(self):
        logout_url = _derive_logout_url("http://172.23.4.5:801/eportal/?c=ACSetting&a=Login&url=drappall")

        self.assertEqual(logout_url, "http://172.23.4.5:801/eportal/?c=ACSetting&a=Logout&url=drappall")

    def test_kernel_jsonp_result_one_is_success(self):
        response = HttpResponse(
            status=200,
            url="http://172.23.4.5:9002/drcom/login?DDDDD=alice&upass=secret",
            body=b'dr1003({"result":1,"uid":"alice"})',
            headers=Message(),
        )

        result = _classify_kernel_login_response(response, {"DDDDD", "upass"})

        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "success")
        self.assertNotIn("alice", result.url or "")
        self.assertNotIn("secret", result.url or "")

    def test_kernel_jsonp_result_zero_is_auth_failure_and_unavailable(self):
        response = HttpResponse(
            status=200,
            url="http://172.23.4.5/drcom/login?DDDDD=alice&upass=secret",
            body='dr1003({"result":0,"msg":"password error"})'.encode("utf-8"),
            headers=Message(),
        )

        result = _classify_kernel_login_response(response, {"DDDDD", "upass"})

        self.assertFalse(result.ok)
        self.assertTrue(result.account_unavailable)
        self.assertEqual(result.reason, "auth_failed")

    def test_extracts_drcom_session_uid_from_portal_html(self):
        self.assertEqual(_extract_session_uid("uid='2210610014';"), "2210610014")
        self.assertEqual(_extract_session_uid('{"uid":"2210920829"}'), "2210920829")
        self.assertEqual(_extract_session_uid("http://172.23.4.5/?uid=2510650220"), "2510650220")

    def test_missing_drcom_session_uid_is_not_authenticated(self):
        self.assertIsNone(_extract_session_uid("<!--Dr.COMWebLoginID_0.htm--><input name='DDDDD'>"))


if __name__ == "__main__":
    unittest.main()
