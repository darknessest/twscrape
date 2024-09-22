import asyncio
from copy import deepcopy
from imaplib import IMAP4_SSL

import tenacity
from DrissionPage import ChromiumOptions, SessionOptions, WebPage
from DrissionPage.errors import ElementNotFoundError
from fake_useragent import UserAgent
from loguru import logger

from .account import Account
from .gmail import GmailCredentials, gmail_get_email_code
from .imap import imap_get_email_code, imap_login
from .login import LoginConfig


class PageLoadError(Exception):
    pass


# TODO: create a exception handler to kill the page
@tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_fixed(5))
def login_with_drissionpage(
    username: str,
    password: str,
    email: str | None,
    imap: IMAP4_SSL | None = None,
    gmail_credentials: GmailCredentials | None = None,
    base_data_path: str = "drission",
) -> tuple[dict, dict] | tuple[None, None]:
    # element constants
    LOGIN_SPAN_TEXT = "Phone, email, or username"
    NEXT_BUTTON_TEXT = "Next"
    EMAIL_OR_PHONE_TEXT = "Phone or email"
    WHAT_IS_HAPPENING_TEXT = "What is happening?!"

    # element selectors
    PASSWORD_SELECTOR = "tag:input@type=password"
    CODEINPUT_SELECTOR = "tag:input@data-testid=ocfEnterTextTextInput"
    LOGIN_BUTTON_SELECTOR = "tag:button@data-testid=LoginForm_Login_Button"

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

    co.set_user_agent(UserAgent().chrome)
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
        logger.trace(f"Getting email code for {username} through Gmail")
        if gmail_credentials:
            code = gmail_get_email_code(gmail_credentials)
        elif imap and email:
            code = asyncio.run(imap_get_email_code(imap, email))
        else:
            logger.error("No gmail or imap provided. Can't get the code")
            page.quit()
            return None, None

        code_elem.input(code)
    except ElementNotFoundError:
        logger.debug("No element with 'Confirmation code'")

    # check if they are asking for email
    try:
        email_elem = page.ele(EMAIL_OR_PHONE_TEXT, timeout=5)
        email_elem.click()
        email_elem.input(email)
        page.ele(NEXT_BUTTON_TEXT).click()
    except ElementNotFoundError:
        logger.trace("They are not asking for email")

    # wait for the Password input
    logger.trace("waiting for the password input")
    try:
        password_elem = page.ele(PASSWORD_SELECTOR, timeout=10)
        password_elem.click()
        password_elem.input(password)
    except ElementNotFoundError:
        logger.error("Password input element not found")
        page.quit()
        return None, None

    # Find all button elements
    logger.trace("waiting for the login button")
    try:
        login_button = page.ele(LOGIN_BUTTON_SELECTOR, timeout=10)
        login_button.hover()
        login_button.click()
    except ElementNotFoundError:
        logger.error("Login button not found")
        page.quit()
        return None, None

    try:
        # find an element with "Wrong password"
        logger.trace("looking for Wrong password element")
        page.get_screenshot("logs/possibly_wrong_password_1.png")
        page.ele("Wrong password", timeout=30)
        page.get_screenshot("logs/possibly_wrong_password_2.png")
        logger.error(f"Wrong password for {username}")
        page.quit()
        return None, None
    except ElementNotFoundError:
        logger.trace("No element with 'Wrong password'. Login is probably successful")

    # wait for What is happening?!
    logger.trace("waiting for What is happening?!")
    try:
        page.ele(WHAT_IS_HAPPENING_TEXT, timeout=30)
    except ElementNotFoundError:
        logger.error("The main page is not loaded")
        logger.debug("html: {}", page.html)
        logger.debug("session: {}", page.session)
        # logger.debug("cookies: {}", page.cookies(as_dict=True, all_info=True))
        # logger.debug("headers: {}", page._headers)
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
