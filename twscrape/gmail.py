import base64
import email as emaillib
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message as EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .imap import EmailLoginError
from .logger import logger

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

@dataclass(kw_only=True)
class GmailCredentials:
    token: str
    refresh_token: str
    client_id: str
    client_secret: str
    scopes: list[str] = field(default_factory=lambda: SCOPES) # NOTE: this actually should be a copied list
    token_uri: str = "https://oauth2.googleapis.com/token"
    universe_domain: str = "googleapis.com"
    account: str = ""
    expiry: str = ""


def oauth2_login(authorized_info: GmailCredentials) -> Credentials:
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.

    creds = Credentials.from_authorized_user_info(info=authorized_info, scopes=SCOPES)
   
    if not creds or not creds.valid:
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

def _parse_code(email_message: EmailMessage) -> str | None:
    # NOTE: consider reading just the snippet of the email
    msg_time = email_message.get("Date", "").split("(")[0].strip()
    msg_time = datetime.strptime(msg_time, "%a, %d %b %Y %H:%M:%S %z")

    msg_subj = email_message.get("Subject", "").lower()
    msg_from = email_message.get("From", "").lower()

    logger.trace("email's subject: {}", email_message["Subject"])
    logger.trace("email's from: {}", email_message["From"])
    
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
        # eg. Your Twitter confirmation code is XXX
        return msg_subj.split(" ")[-1].strip()
    return None

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
    for retry in range(num_retries):
        logger.debug(f"Attempt {retry + 1}/{num_retries}")
        try:
            search_id = (
                service.users().messages().list(userId="me", labelIds="UNREAD", maxResults=5).execute()
            )
            number_result = search_id["resultSizeEstimate"]
            logger.trace(f"Number of emails: {number_result}")

        except HttpError:
            logger.exception("An error occurred while trying to get emails")
            return None

        if number_result > 0:
            message_ids = search_id["messages"]

            for msg_id in message_ids:
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
