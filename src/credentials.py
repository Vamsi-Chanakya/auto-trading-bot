"""
Secure Credential Manager using macOS Keychain

This module handles all sensitive credentials securely:
- Webull credentials (email, password, trading PIN)
- Twilio credentials (account SID, auth token)
- User phone number

NO credentials are ever stored in plaintext files or code.
All credentials are encrypted at rest using macOS Keychain.
"""

import keyring
import getpass
import sys
from typing import Optional

# Service name for keyring (identifies our app in Keychain)
SERVICE_NAME = "AutoTradingForVamsi"

# Credential keys
class CredentialKeys:
    WEBULL_EMAIL = "webull_email"
    WEBULL_PASSWORD = "webull_password"
    WEBULL_TRADING_PIN = "webull_trading_pin"
    WEBULL_DEVICE_ID = "webull_device_id"
    TWILIO_ACCOUNT_SID = "twilio_account_sid"
    TWILIO_AUTH_TOKEN = "twilio_auth_token"
    TWILIO_PHONE_NUMBER = "twilio_phone_number"
    USER_PHONE_NUMBER = "user_phone_number"


class CredentialManager:
    """Manages secure storage and retrieval of credentials using macOS Keychain."""

    def __init__(self):
        self.service = SERVICE_NAME

    def _get(self, key: str) -> Optional[str]:
        """Retrieve a credential from Keychain."""
        try:
            return keyring.get_password(self.service, key)
        except Exception as e:
            print(f"Error retrieving {key}: {e}")
            return None

    def _set(self, key: str, value: str) -> bool:
        """Store a credential in Keychain."""
        try:
            keyring.set_password(self.service, key, value)
            return True
        except Exception as e:
            print(f"Error storing {key}: {e}")
            return False

    def _delete(self, key: str) -> bool:
        """Delete a credential from Keychain."""
        try:
            keyring.delete_password(self.service, key)
            return True
        except keyring.errors.PasswordDeleteError:
            return True  # Already deleted
        except Exception as e:
            print(f"Error deleting {key}: {e}")
            return False

    # Webull Credentials
    @property
    def webull_email(self) -> Optional[str]:
        return self._get(CredentialKeys.WEBULL_EMAIL)

    @property
    def webull_password(self) -> Optional[str]:
        return self._get(CredentialKeys.WEBULL_PASSWORD)

    @property
    def webull_trading_pin(self) -> Optional[str]:
        return self._get(CredentialKeys.WEBULL_TRADING_PIN)

    @property
    def webull_device_id(self) -> Optional[str]:
        return self._get(CredentialKeys.WEBULL_DEVICE_ID)

    # Twilio Credentials
    @property
    def twilio_account_sid(self) -> Optional[str]:
        return self._get(CredentialKeys.TWILIO_ACCOUNT_SID)

    @property
    def twilio_auth_token(self) -> Optional[str]:
        return self._get(CredentialKeys.TWILIO_AUTH_TOKEN)

    @property
    def twilio_phone_number(self) -> Optional[str]:
        return self._get(CredentialKeys.TWILIO_PHONE_NUMBER)

    @property
    def user_phone_number(self) -> Optional[str]:
        return self._get(CredentialKeys.USER_PHONE_NUMBER)

    def is_webull_configured(self) -> bool:
        """Check if Webull credentials are configured."""
        return all([
            self.webull_email,
            self.webull_password,
            self.webull_trading_pin
        ])

    def is_twilio_configured(self) -> bool:
        """Check if Twilio credentials are configured."""
        return all([
            self.twilio_account_sid,
            self.twilio_auth_token,
            self.twilio_phone_number,
            self.user_phone_number
        ])

    def is_fully_configured(self) -> bool:
        """Check if all credentials are configured."""
        return self.is_webull_configured() and self.is_twilio_configured()

    def setup_webull(self):
        """Interactive setup for Webull credentials."""
        print("\n=== Webull Credential Setup ===")
        print("Your credentials will be stored securely in macOS Keychain.")
        print("They will NEVER be saved in plaintext files.\n")

        email = input("Webull email: ").strip()
        password = getpass.getpass("Webull password: ")
        trading_pin = getpass.getpass("Webull trading PIN (6 digits): ")

        if len(trading_pin) != 6 or not trading_pin.isdigit():
            print("Error: Trading PIN must be exactly 6 digits")
            return False

        self._set(CredentialKeys.WEBULL_EMAIL, email)
        self._set(CredentialKeys.WEBULL_PASSWORD, password)
        self._set(CredentialKeys.WEBULL_TRADING_PIN, trading_pin)

        print("\n[OK] Webull credentials stored securely in Keychain")
        return True

    def setup_twilio(self):
        """Interactive setup for Twilio credentials."""
        print("\n=== Twilio Credential Setup ===")
        print("Get your credentials from: https://console.twilio.com/")
        print("They will NEVER be saved in plaintext files.\n")

        account_sid = input("Twilio Account SID: ").strip()
        auth_token = getpass.getpass("Twilio Auth Token: ")
        twilio_phone = input("Twilio Phone Number (e.g., +1234567890): ").strip()
        user_phone = input("Your Phone Number (e.g., +1234567890): ").strip()

        # Basic validation
        if not account_sid.startswith("AC"):
            print("Warning: Account SID usually starts with 'AC'")

        if not twilio_phone.startswith("+"):
            print("Warning: Phone numbers should start with '+' and country code")

        self._set(CredentialKeys.TWILIO_ACCOUNT_SID, account_sid)
        self._set(CredentialKeys.TWILIO_AUTH_TOKEN, auth_token)
        self._set(CredentialKeys.TWILIO_PHONE_NUMBER, twilio_phone)
        self._set(CredentialKeys.USER_PHONE_NUMBER, user_phone)

        print("\n[OK] Twilio credentials stored securely in Keychain")
        return True

    def setup_device_id(self, device_id: str):
        """Store the Webull device ID (generated after first login)."""
        self._set(CredentialKeys.WEBULL_DEVICE_ID, device_id)

    def clear_all(self):
        """Clear all stored credentials (use with caution)."""
        print("\nClearing all stored credentials...")
        for key in [
            CredentialKeys.WEBULL_EMAIL,
            CredentialKeys.WEBULL_PASSWORD,
            CredentialKeys.WEBULL_TRADING_PIN,
            CredentialKeys.WEBULL_DEVICE_ID,
            CredentialKeys.TWILIO_ACCOUNT_SID,
            CredentialKeys.TWILIO_AUTH_TOKEN,
            CredentialKeys.TWILIO_PHONE_NUMBER,
            CredentialKeys.USER_PHONE_NUMBER,
        ]:
            self._delete(key)
        print("[OK] All credentials cleared from Keychain")

    def status(self):
        """Print credential configuration status."""
        print("\n=== Credential Status ===")
        print(f"Webull Email:      {'[OK]' if self.webull_email else '[NOT SET]'}")
        print(f"Webull Password:   {'[OK]' if self.webull_password else '[NOT SET]'}")
        print(f"Webull PIN:        {'[OK]' if self.webull_trading_pin else '[NOT SET]'}")
        print(f"Webull Device ID:  {'[OK]' if self.webull_device_id else '[NOT SET]'}")
        print(f"Twilio SID:        {'[OK]' if self.twilio_account_sid else '[NOT SET]'}")
        print(f"Twilio Token:      {'[OK]' if self.twilio_auth_token else '[NOT SET]'}")
        print(f"Twilio Phone:      {'[OK]' if self.twilio_phone_number else '[NOT SET]'}")
        print(f"Your Phone:        {'[OK]' if self.user_phone_number else '[NOT SET]'}")
        print(f"\nFully Configured:  {'YES' if self.is_fully_configured() else 'NO'}")


def main():
    """CLI interface for credential management."""
    creds = CredentialManager()

    if len(sys.argv) < 2:
        print("Usage: python credentials.py [--setup | --status | --clear]")
        print("\nOptions:")
        print("  --setup   Set up all credentials interactively")
        print("  --status  Show credential configuration status")
        print("  --clear   Clear all stored credentials")
        sys.exit(1)

    command = sys.argv[1]

    if command == "--setup":
        creds.setup_webull()
        creds.setup_twilio()
        print("\n=== Setup Complete ===")
        creds.status()

    elif command == "--status":
        creds.status()

    elif command == "--clear":
        confirm = input("Are you sure you want to clear all credentials? (yes/no): ")
        if confirm.lower() == "yes":
            creds.clear_all()
        else:
            print("Cancelled")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
