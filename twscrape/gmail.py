import base64
import email as emaillib
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message as EmailMessage

import tenacity
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .imap import EmailLoginError
from .logger import logger
from .models import JSONTrait

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

@dataclass(kw_only=True)
class GmailCredentials(JSONTrait):
    token: str
    refresh_token: str
    client_id: str
    client_secret: str
    scopes: list[str] = field(default_factory=lambda: SCOPES) # NOTE: this actually should be a copied list
    token_uri: str = "https://oauth2.googleapis.com/token"
    universe_domain: str = "googleapis.com"
    account: str = ""
    expiry: str = ""

    def keys(self):
        return self.__dict__.keys()

    def get(self, key: str, default: object | None = None):
        return self.__dict__.get(key, default)
    

class NoEmailFoundError(Exception):
    pass


def oauth2_login(authorized_info: GmailCredentials) -> Credentials:
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.

    creds = Credentials.from_authorized_user_info(info=authorized_info, scopes=SCOPES)
   
    if not creds or not creds.valid:
        logger.debug("Credentials are invalid")
        logger.debug("expired: {}", creds.expired)
        logger.debug("refresh token: {}", creds.refresh_token)

        if creds and creds.expired and creds.refresh_token:
            logger.debug("Refreshing credentials")
            creds.refresh(Request())
            logger.debug("Credentials refreshed")
        else:
            raise Exception("Credentials can't be authorized automatically")
        
        # TODO: implement persistent storage for the credentials
        # # Save the credentials for the next run
        # with open(AUTHED_FILE, "w") as token:
        #     token.write(creds.to_json())
    return creds

def _parse_time(time_str: str) -> datetime | None:
    # follows the format: 'Thu, 15 Aug 2024 23:40:30 GMT'
    pattern_1 = "%a, %d %b %Y %H:%M:%S %Z"
    # follows the format: 'Thu, 15 Aug 2024 23:40:30 +0000'
    pattern_2 = "%a, %d %b %Y %H:%M:%S %z"
    if not time_str:
        return None

    for pattern in (pattern_1, pattern_2):
        try:
            return datetime.strptime(time_str, pattern)
        except ValueError:
            pass
    logger.trace("Couldn't parse the time: {}", time_str)
    return None


def _parse_code(email_message: EmailMessage) -> str | None:
    # NOTE: consider reading just the snippet of the email
    msg_time = email_message.get("Date", "").split("(")[0].strip()
    # follows the format: 'Thu, 15 Aug 2024 23:40:30 GMT'
    msg_time = _parse_time(msg_time)

    msg_subj = email_message.get("Subject", "").lower()
    msg_from = email_message.get("From", "").lower()

    logger.trace("email's subject: {}", email_message["Subject"])
    logger.trace("email's from: {}", email_message["From"])
    logger.trace("email's time: {}", msg_time)
    
    # content_types = email_message.get_content_maintype()
    # TODO: return this part if subject is not the code
    # getting the email body
    # email_text = None
    # if content_types == "multipart":
    #     logger.trace("This is a multipart message")

    #     text_part, _ = email_message.get_payload()
    #     email_text = text_part.get_payload()

    # else:
    #     logger.trace("This is the message body plain text")
    #     email_text = email_message.get_payload()
    
    if "info@x.com" in msg_from and "confirmation code is" in msg_subj:
        logger.trace("Email is from x.com and contains the confirmation code")
        # eg. Your Twitter confirmation code is XXX
        return msg_subj.split(" ")[-1].strip()
    return None

@tenacity.retry(
    retry=tenacity.retry_if_exception_type(HttpError),
    wait=tenacity.wait_full_jitter(max=20),
    stop=tenacity.stop_after_attempt(5),
)
def _read_message(service, msg_id: str) -> EmailMessage:
    message_list = (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="raw")
        .execute()
    )

    msg_raw = base64.urlsafe_b64decode(message_list["raw"].encode("ASCII"))
    email_message = emaillib.message_from_bytes(msg_raw)

    return email_message

def get_emails(service, num_retries: int = 5) -> str | None:
    number_result = 0

    for retry in tenacity.Retrying(
        retry=tenacity.retry_if_exception_type((HttpError, NoEmailFoundError)),
        wait=tenacity.wait_full_jitter(max=20),
        stop=tenacity.stop_after_attempt(num_retries),
        before=tenacity.before_log(logger, logger.level("TRACE").no),
    ):
        with retry:
            search_id = (
                service.users().messages().list(userId="me", labelIds="UNREAD", maxResults=5).execute()
            )
            number_result = search_id["resultSizeEstimate"]
            logger.trace(f"Number of emails: {number_result}")
            if number_result == 0:
                logger.trace("No emails in the inbox")
                raise NoEmailFoundError("No emails found")

    if number_result > 0:
        message_ids = search_id["messages"]

        for msg_id in message_ids:
            logger.trace("reading email: {}", msg_id["id"])
            email_message = _read_message(service, msg_id["id"])

            if code := _parse_code(email_message):
                return code

    
    return None

def get_service(credentials: Credentials):
    service = None
    try:
        service = build("gmail", "v1", credentials=credentials)
    except HttpError as error:
        logger.exception("An error occurred while trying to build the service")
    finally:
        return service

    
def gmail_get_email_code(authorized_info: GmailCredentials) -> str:
    service  =  None

    if credentials := oauth2_login(authorized_info):
        pass
    else:
        logger.error("Credentials couldn't be authorized")
        raise EmailLoginError("Credentials couldn't be authorized")

    if service := get_service(credentials):
        return get_emails(service)
    else:
        logger.error("Service couldn't be built")
        raise EmailLoginError("Gmail Service couldn't be built")
