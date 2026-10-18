"""Public-source transport recovery must not weaken access or TLS checks."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import ssl
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import requests
from urllib3.exceptions import MaxRetryError, SSLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import source_http as http

URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"


def wrapped_ssl(error):
    return requests.exceptions.SSLError(MaxRetryError(None, URL, SSLError(error)))


class SourceHttpTests(unittest.TestCase):
    def setUp(self):
        local = patch.object(http, "_LOCAL", threading.local())
        local.start()
        self.addCleanup(local.stop)

    def test_sessions_reuse_connections_per_thread_and_preserve_security_defaults(self):
        main = http._session()
        self.addCleanup(main.close)
        self.assertIs(main, http._session())
        self.assertTrue(main.verify)
        self.assertTrue(main.trust_env)
        barrier = threading.Barrier(2)

        def get_session(_):
            session = http._session()
            barrier.wait(timeout=2)
            session.close()
            return session

        with ThreadPoolExecutor(2) as pool:
            first, second = list(pool.map(get_session, range(2)))
        self.assertIsNot(first, second)
        self.assertIsNot(first, main)

    def test_nested_tls_eof_and_timeout_recover_once(self):
        eof = wrapped_ssl(ssl.SSLEOFError(8, "connection closed"))
        for error in (eof, requests.ReadTimeout()):
            session = Mock()
            response = Mock(status_code=200)
            session.get.side_effect = [error, response]
            with self.subTest(error=type(error).__name__), patch.object(http, "_session", return_value=session), \
                    patch.object(http.time, "sleep"):
                self.assertIs(http.get_response(URL), response)
                self.assertEqual(session.get.call_count, 2)

    def test_repeated_transient_error_stops_after_two_requests(self):
        session = Mock()
        session.get.side_effect = requests.ReadTimeout()
        with patch.object(http, "_session", return_value=session), patch.object(http.time, "sleep"), \
                self.assertRaises(requests.ReadTimeout):
            http.get_response(URL)
        self.assertEqual(session.get.call_count, 2)

    def test_certificate_and_unclassified_ssl_errors_are_never_retried(self):
        errors = (wrapped_ssl(ssl.SSLCertVerificationError(1, "verification failed")),
                  requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING"))
        for error in errors:
            session = Mock()
            session.get.side_effect = error
            with self.subTest(error=type(error).__name__), patch.object(http, "_session", return_value=session), \
                    patch.object(http.time, "sleep") as sleep, self.assertRaises(requests.exceptions.SSLError):
                http.get_response(URL)
            self.assertEqual(session.get.call_count, 1)
            sleep.assert_not_called()
        self.assertEqual(http.failure_reason(errors[0]), "tls_certificate")
        self.assertIsNone(http.failure_reason(errors[1]))

    def test_http_access_restrictions_and_not_found_are_never_retried(self):
        for code in (401, 403, 404, 412, 429):
            session = Mock()
            session.get.return_value = Mock(status_code=code)
            with self.subTest(code=code), patch.object(http, "_session", return_value=session), \
                    patch.object(http.time, "sleep") as sleep:
                self.assertEqual(http.get_response(URL).status_code, code)
            self.assertEqual(session.get.call_count, 1)
            sleep.assert_not_called()

    def test_server_errors_retry_once_and_close_the_failed_response(self):
        session = Mock()
        first, second = Mock(status_code=503), Mock(status_code=503)
        session.get.side_effect = [first, second]
        with patch.object(http, "_session", return_value=session), patch.object(http.time, "sleep"):
            self.assertIs(http.get_response(URL), second)
        self.assertEqual(session.get.call_count, 2)
        first.close.assert_called_once()
        second.close.assert_not_called()

    def test_steam_requests_have_at_most_two_active_connections(self):
        lock, both_started, release = threading.Lock(), threading.Event(), threading.Event()
        active = peak = 0

        def request(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    both_started.set()
            release.wait(timeout=2)
            with lock:
                active -= 1
            return Mock(status_code=200)

        session = Mock()
        session.get.side_effect = request
        with patch.object(http, "_session", return_value=session), ThreadPoolExecutor(3) as pool:
            jobs = [pool.submit(http.get_response, URL) for _ in range(3)]
            try:
                self.assertTrue(both_started.wait(timeout=2))
            finally:
                release.set()
            for job in jobs:
                self.assertEqual(job.result(timeout=2).status_code, 200)
        self.assertEqual(peak, 2)


if __name__ == "__main__":
    unittest.main()
