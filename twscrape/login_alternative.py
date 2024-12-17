import asyncio
from copy import deepcopy
from imaplib import IMAP4_SSL

import pyotp
import tenacity
from DrissionPage import ChromiumOptions, SessionOptions, WebPage
from DrissionPage.errors import ElementNotFoundError
from loguru import logger

from .account import Account
from .gmail import GmailCredentials, gmail_get_email_code
from .imap import imap_get_email_code, imap_login
from .login import LoginConfig


class PageLoadError(Exception):
    pass


class ElementLoadError(Exception):
    pass


def get_email_code(
    username: str,
    gmail_credentials: GmailCredentials | None = None,
    imap: IMAP4_SSL | None = None,
    email: str | None = None,
) -> str | None:

    if gmail_credentials:
        logger.trace(f"Getting email code for {username} through Gmail")
        code = gmail_get_email_code(gmail_credentials)
        logger.trace(f"The code for {username} is {code}")
    elif imap and email:
        logger.trace(f"Getting email code for {username} through IMAP")
        code = asyncio.run(imap_get_email_code(imap, email))
        logger.trace(f"The code for {username} is {code}")
    else:
        return None

    return code


def return_none_anyway(retry_state: tenacity.RetryCallState) -> tuple[None, None]:
    logger.warning(
        "Failed after {} retries, with exception: {}",
        retry_state.attempt_number,
        retry_state.outcome._exception,
    )
    # TODO: figure out how to close the page from here

    return None, None


# TODO: create a exception handler to kill the page
@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_fixed(5),
    retry=tenacity.retry_if_exception_type((PageLoadError, ElementLoadError)),
    retry_error_callback=return_none_anyway,
)
def login_with_drissionpage(
    username: str,
    password: str,
    email: str | None,
    mfa_code: str | None,
    user_agent: str | None = None,
    imap: IMAP4_SSL | None = None,
    gmail_credentials: GmailCredentials | None = None,
    base_data_path: str = "drission",
) -> tuple[dict, dict] | tuple[None, None]:
    # element constants
    LOGIN_SPAN_TEXT = "Phone, email, or username"
    NEXT_BUTTON_TEXT = "Next"
    # EMAIL_OR_PHONE_TEXT = "Phone or email"
    NAVIGATION_BAR_SELECTOR = "tag:nav@role=navigation"

    # element selectors
    PASSWORD_SELECTOR = "tag:input@type=password"
    CODEINPUT_SELECTOR = "tag:input@data-testid=ocfEnterTextTextInput@type=text"
    EMAILINPUT_SELECTOR = "tag:input@data-testid=ocfEnterTextTextInput@type=email"
    LOGIN_BUTTON_SELECTOR = "tag:button@data-testid=LoginForm_Login_Button"
    MFA_CODE_SELECTOR = "tag:input@data-testid=ocfEnterTextTextInput@inputmode=numeric@type=text"

    # urls
    LOGIN_URL = "https://x.com/i/flow/login"

    logger.trace("Setting up the drission page")
    # setup the page
    co = ChromiumOptions()
    co.headless(True)
    co.set_user_data_path(f"{base_data_path}/{username}")
    co._arguments.append("--disable-gpu")
    co._arguments.append("--no-sandbox")
    co._arguments.append("--disable-dev-shm-usage")
    co._arguments.append("--window-size=1024,768")

    if user_agent:
        co.set_user_agent(user_agent)
    # co.set_load_mode("eager")
    so = SessionOptions()
    page = WebPage(chromium_options=co, session_or_options=so)

    # The main part
    logger.trace("Loading the login page")
    page.get(LOGIN_URL)

    logger.trace("waiting for the page to load")
    try:
        login_elem = page.ele(LOGIN_SPAN_TEXT, timeout=30)
        login_elem.click()
        logger.trace("Inserting the username")
        login_elem.input(username)
    except ElementNotFoundError:
        page.quit()
        logger.error("Failed to load the login page")
        raise PageLoadError("Failed to load the login page")

    logger.trace("Clicking on the next button")
    page.ele(NEXT_BUTTON_TEXT).click()

    try:
        code_elem = page.ele(CODEINPUT_SELECTOR, timeout=5)
        code_elem.hover()
        code_elem.click()

        # get the code from email
        code = None
        try:
            if code := get_email_code(
                username=username,
                gmail_credentials=gmail_credentials,
                imap=imap,
                email=email,
            ):
                logger.trace("Inserting the code")
                code_elem.input(code)
            else:
                logger.error("Failed to get the email code")
                page.quit()
                return None, None
        except Exception:
            logger.exception("Failed to get the email code")
            page.quit()
            return None, None

        # click on the next button
        page.ele(NEXT_BUTTON_TEXT).click()

    except ElementNotFoundError:
        logger.trace("No element with 'Confirmation code' before the password")

    # check if they are asking for email
    try:
        email_elem = page.ele(EMAILINPUT_SELECTOR, timeout=5)
        email_elem.click()
        email_elem.input(email)
        page.ele(NEXT_BUTTON_TEXT).click()
    except ElementNotFoundError:
        logger.trace("They are not asking for email before the password")

    # wait for the Password input
    logger.trace("waiting for the password input")
    try:
        password_elem = page.ele(PASSWORD_SELECTOR, timeout=10)
        password_elem.click()
        password_elem.input(password)
    except ElementNotFoundError:
        logger.error("Password input element not found")
        page.get_screenshot("logs/login_password_error.png")
        logger.debug("html: {}", page.html)
        logger.debug("session: {}", page.session)
        raise ElementLoadError("Password input element not found")

    logger.trace("waiting for the login button")
    try:
        login_button = page.ele(LOGIN_BUTTON_SELECTOR, timeout=10)
        login_button.hover()
        login_button.click()
    except ElementNotFoundError:
        logger.error("Login button not found")
        raise ElementLoadError("Login button not found")

    # check if email code is asked, after the password
    try:
        code_elem = page.ele(CODEINPUT_SELECTOR, timeout=5)
        code_elem.hover()
        code_elem.click()

        # get the code from email
        code = None
        try:
            if code := get_email_code(
                username=username,
                gmail_credentials=gmail_credentials,
                imap=imap,
                email=email,
            ):
                logger.trace("Inserting the code")
                code_elem.input(code)
            else:
                logger.error("Failed to get the email code")
                page.quit()
                return None, None
        except Exception:
            logger.exception("Failed to get the email code")
            page.quit()
            return None, None

        # click on the next button
        page.ele(NEXT_BUTTON_TEXT).click()

    except ElementNotFoundError:
        logger.trace("No element with 'Confirmation code' after the password")

    # check if they are asking for email after the password
    try:
        email_elem = page.ele(EMAILINPUT_SELECTOR, timeout=5)
        email_elem.click()
        email_elem.input(email)
        page.ele(NEXT_BUTTON_TEXT).click()
    except ElementNotFoundError:
        logger.trace("They are not asking for email after the password")

    # check if they are asking for the MFA code
    try:
        mfa_elem = page.ele(MFA_CODE_SELECTOR, timeout=5)
        mfa_elem.hover()
        mfa_elem.click()

        if not mfa_code:
            logger.error("MFA code is required")
            page.quit()
            return None, None

        totp = pyotp.TOTP(mfa_code)

        mfa_elem.input(totp.now())
        page.ele(NEXT_BUTTON_TEXT).click()
    except ElementNotFoundError:
        page.get_screenshot("logs/mfa_stage.png")
        logger.debug("html: {}", page.html)
        logger.debug("session: {}", page.session)
        logger.trace("They are not asking for MFA code")


    # wait for What is happening?!
    logger.trace("waiting for the navigation bar to appear")
    try:
        page.ele(NAVIGATION_BAR_SELECTOR, timeout=30)
    except ElementNotFoundError:
        page.get_screenshot("logs/login_error.png")
        logger.error("The main page is not loaded")
        logger.debug("html: {}", page.html)
        logger.debug("session: {}", page.session)
        page.quit()
        return None, None

    # copy the cookies and headers
    cookies = deepcopy(page.cookies(as_dict=True, all_info=True))
    headers = deepcopy(page._headers)

    page.quit()

    return cookies, headers


def login_alternative(
    acc: Account, cfg: LoginConfig | None = None, base_data_path: str = "drission"
) -> Account:
    log_id = f"{acc.username} - {acc.email}"
    if acc.active:
        logger.info(f"account already active {log_id}")
        return acc

    cfg, imap, gmail_creds = cfg or LoginConfig(), None, None
    if cfg.email_first and not cfg.manual and not imap:
        imap = asyncio.run(imap_login(acc.email, acc.email_password))
    if cfg.gmail and acc.gmail_credentials and not gmail_creds:
        gmail_creds = acc.gmail_credentials

    # run drissionpage script
    cookies, headers = login_with_drissionpage(
        username=acc.username,
        password=acc.password,
        email=acc.email,
        mfa_code=acc.mfa_code,
        user_agent=acc.user_agent,
        gmail_credentials=gmail_creds,
        base_data_path=base_data_path,
    )

    if cookies and headers:
        acc.active = True
        acc.headers = {k: v for k, v in headers.items()}
        acc.cookies = {k: v for k, v in cookies.items()}
    else:
        acc.active = False

    return acc
