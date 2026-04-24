# filename: backend/captcha_solver.py
import requests
import time
import os
from typing import Optional

class CaptchaSolver:
    def __init__(self, api_key: str, service_url: str = "https://2captcha.com/in.php"):
        self.api_key = api_key
        self.service_url = service_url
        self.result_url = "https://2captcha.com/res.php"

    def solve_recaptcha_v2(self, site_key: str, page_url: str, proxy: Optional[str] = None, session_id: str = "default") -> Optional[str]:
        """Solves reCAPTCHA v2 with proxy support."""
        if not self.api_key or self.api_key == "YOUR_2CAPTCHA_API_KEY":
            print(f"[{session_id}] CAPTCHA_API_KEY is not set. Cannot solve CAPTCHA.")
            return None

        payload = {
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1
        }
        
        # Parse proxy string (http://user:pass@ip:port) for 2Captcha format
        if proxy:
            try:
                proto, rest = proxy.split('://')
                if '@' in rest:
                    auth, host_port = rest.split('@')
                    user, password = auth.split(':')
                    ip, port = host_port.split(':')
                    payload.update({
                        "proxy": f"{ip}:{port}",
                        "proxytype": proto.upper(),
                        "proxyuser": user,
                        "proxypass": password
                    })
                else:
                    ip, port = rest.split(':')
                    payload.update({
                        "proxy": f"{ip}:{port}",
                        "proxytype": proto.upper()
                    })
            except Exception as e:
                print(f"[{session_id}] Failed to parse proxy for 2Captcha: {e}. Proceeding without proxy for captcha.")

        try:
            response = requests.post(self.service_url, data=payload, timeout=30).json()
            if response["status"] == 1:
                request_id = response["request"]
                print(f"[{session_id}] Captcha submitted, request ID: {request_id}. Waiting for result...")
                for _ in range(30): # Poll for up to 150 seconds (30 * 5s)
                    time.sleep(5)
                    result_payload = {
                        "key": self.api_key,
                        "action": "get",
                        "id": request_id,
                        "json": 1
                    }
                    result_response = requests.get(self.result_url, params=result_payload, timeout=30).json()
                    if result_response["status"] == 1:
                        print(f"[{session_id}] Captcha solved!")
                        return result_response["request"]
                    elif result_response["request"] == "CAPCHA_NOT_READY":
                        continue
                    else:
                        print(f"[{session_id}] Captcha error from 2Captcha: {result_response['request']}")
                        return None
                print(f"[{session_id}] Captcha polling timed out.")
                return None
            else:
                print(f"[{session_id}] Error submitting captcha to 2Captcha: {response['request']}")
                return None
        except Exception as e:
            print(f"[{session_id}] Captcha solver error: {e}")
            return None