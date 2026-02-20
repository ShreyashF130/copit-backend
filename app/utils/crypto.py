import os
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger("drop_bot")

# Load the Master Key
MASTER_KEY = os.getenv("ENCRYPTION_MASTER_KEY")

if not MASTER_KEY:
    logger.warning("🔥 CRITICAL: ENCRYPTION_MASTER_KEY is missing! Keys will not be encrypted.")
    cipher_suite = None
else:
    cipher_suite = Fernet(MASTER_KEY.encode())

def encrypt_data(plain_text: str) -> str:
    """Encrypts a string. Returns the encrypted string, or original if no key is set."""
    if not plain_text or not cipher_suite:
        return plain_text
    return cipher_suite.encrypt(plain_text.encode()).decode()

def decrypt_data(cipher_text: str) -> str:
    """Decrypts a string. Returns the plain text, or original if decryption fails."""
    if not cipher_text or not cipher_suite:
        return cipher_text
    try:
        return cipher_suite.decrypt(cipher_text.encode()).decode()
    except Exception as e:
        logger.error(f"Decryption failed (Key changed or corrupt data): {e}")
        return cipher_text # Fallback (useful if you have old unencrypted keys in DB)