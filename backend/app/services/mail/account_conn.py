"""Builds fully-resolved IMAP/SMTP connection params for an Account,
bridging the auth-mechanism split between password accounts (LOGIN with the
stored, Fernet-encrypted password) and OAuth accounts (XOAUTH2 with a
short-lived bearer token, refreshed here via oauth_token.get_access_token
if needed). Every module that opens an IMAP or SMTP connection goes through
this rather than reading Account.imap_password/smtp_password directly, so
neither auth mechanism has to be special-cased at each call site.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from services.mail.oauth_token import get_access_token
from services.mail.probe import ImapParams, SmtpParams


async def imap_params(db: AsyncSession, account: Account) -> ImapParams:
    if account.auth_type == "oauth_outlook":
        token = await get_access_token(db, account)
        return ImapParams(
            host=account.imap_host, port=account.imap_port, security=account.imap_security,
            username=account.imap_username, password=token, verify_ssl=account.verify_ssl,
            auth_type="oauth_outlook",
        )
    return ImapParams(
        host=account.imap_host, port=account.imap_port, security=account.imap_security,
        username=account.imap_username, password=account.imap_password, verify_ssl=account.verify_ssl,
    )


async def smtp_params(db: AsyncSession, account: Account) -> SmtpParams:
    if account.auth_type == "oauth_outlook":
        token = await get_access_token(db, account)
        return SmtpParams(
            host=account.smtp_host, port=account.smtp_port, security=account.smtp_security,
            username=account.smtp_username, password=token, verify_ssl=account.verify_ssl,
            auth_type="oauth_outlook",
        )
    return SmtpParams(
        host=account.smtp_host, port=account.smtp_port, security=account.smtp_security,
        username=account.smtp_username, password=account.smtp_password, verify_ssl=account.verify_ssl,
    )
