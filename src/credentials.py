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
    TELEGRAM_BOT_TOKEN = "telegram_bot_token"
    TELEGRAM_CHAT_ID = "telegram_chat_id"


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

    # Telegram Credentials
    @property
    def telegram_bot_token(self) -> Optional[str]:
        return self._get(CredentialKeys.TELEGRAM_BOT_TOKEN)

    @property
    def telegram_chat_id(self) -> Optional[str]:
        return self._get(CredentialKeys.TELEGRAM_CHAT_ID)

    def is_webull_configured(self) -> bool:
        """Check if Webull credentials are configured."""
        return all([
            self.webull_email,
            self.webull_password,
            self.webull_trading_pin
        ])

    def is_telegram_configured(self) -> bool:
        """Check if Telegram credentials are configured."""
        return all([
            self.telegram_bot_token,
            self.telegram_chat_id
        ])

    def is_fully_configured(self) -> bool:
        """Check if all credentials are configured."""
        return self.is_webull_configured() and self.is_telegram_configured()

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

    def setup_telegram(self):
        """Interactive setup for Telegram credentials."""
        print("\n=== Telegram Bot Setup ===")
        print("To create a Telegram bot:")
        print("1. Open Telegram and message @BotFather")
        print("2. Send /newbot and follow the prompts")
        print("3. Copy the bot token you receive")
        print("4. Message your new bot, then visit:")
        print("   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates")
        print("5. Find your chat_id in the response")
        print("\nCredentials will NEVER be saved in plaintext files.\n")

        bot_token = getpass.getpass("Telegram Bot Token: ")
        chat_id = input("Your Telegram Chat ID: ").strip()

        # Basic validation
        if ":" not in bot_token:
            print("Warning: Bot token usually contains a colon (:)")

        if not chat_id.lstrip("-").isdigit():
            print("Warning: Chat ID should be a number")

        self._set(CredentialKeys.TELEGRAM_BOT_TOKEN, bot_token)
        self._set(CredentialKeys.TELEGRAM_CHAT_ID, chat_id)

        print("\n[OK] Telegram credentials stored securely in Keychain")
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
            CredentialKeys.TELEGRAM_BOT_TOKEN,
            CredentialKeys.TELEGRAM_CHAT_ID,
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
        print(f"Telegram Token:    {'[OK]' if self.telegram_bot_token else '[NOT SET]'}")
        print(f"Telegram Chat ID:  {'[OK]' if self.telegram_chat_id else '[NOT SET]'}")
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
        creds.setup_telegram()
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
