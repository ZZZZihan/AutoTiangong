import unittest

from autotiangong.drcom import build_login_params, parse_drcom_settings


SAMPLE_HTML = """
<script>
authloginport=801;
authloginpath='/eportal/?c=ACSetting&a=Login';
authloginparam='url=drappall';
authuserfield='DDDDD';
authpassfield='upass';
authsuccess='Dr.COMWebLoginID_3.htm';
authfail='Dr.COMWebLoginID_2.htm';
charset='gb2312';
</script>
"""


class DrcomSettingsTest(unittest.TestCase):
    def test_parse_settings_from_portal_html(self):
        settings = parse_drcom_settings("http://172.23.4.5/", SAMPLE_HTML)

        self.assertEqual(settings.host, "172.23.4.5")
        self.assertEqual(settings.login_port, 801)
        self.assertEqual(settings.login_url, "http://172.23.4.5:801/eportal/?c=ACSetting&a=Login")
        self.assertEqual(settings.login_params, {"url": "drappall"})
        self.assertEqual(settings.username_field, "DDDDD")
        self.assertEqual(settings.password_field, "upass")
        self.assertEqual(settings.charset, "gb2312")

    def test_build_login_params_keeps_secret_fields_configurable(self):
        settings = parse_drcom_settings("http://172.23.4.5/", SAMPLE_HTML)
        params = build_login_params(settings, "user1", "secret", {"R1": "0", "0MKKey": "123456"})

        self.assertEqual(params["DDDDD"], "user1")
        self.assertEqual(params["upass"], "secret")
        self.assertEqual(params["url"], "drappall")
        self.assertEqual(params["R1"], "0")
        self.assertEqual(params["0MKKey"], "123456")
        self.assertIn("v", params)


if __name__ == "__main__":
    unittest.main()

