from copy import deepcopy

import tenacity
from DrissionPage import ChromiumOptions, SessionOptions, WebPage
from DrissionPage.errors import ElementNotFoundError
from fake_useragent import UserAgent
from loguru import logger

from .account import Account
from .gmail import GmailCredentials
from .imap import imap_login
from .login import LoginConfig


class PageLoadError(Exception):
    pass

# TODO: create a exception handler to kill the page
@tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_fixed(5))
def login_with_drissionpage(
        username: str,
        password: str,
        email: str,
        email_password: str,
        gmail_credentials: GmailCredentials | None = None,
        base_data_path: str = "drission"
) -> tuple[dict, dict] | tuple[None, None]:
    # element constants
    LOGIN_SPAN_TEXT = "Phone, email, or username"
    NEXT_BUTTON_TEXT = "Next"
    EMAIL_OR_PHONE_TEXT = "Phone or email"
    PASSWORD_TEXT = "Password"
    WHAT_IS_HAPPENING_TEXT = "What is happening?!"

    # element selectors
    PASSWORD_SELECTOR = "tag:input@type=password"
    LOGIN_BUTTON_SELECTOR = "tag:button@data-testid=LoginForm_Login_Button"

    # urls
    LOGIN_URL = "https://x.com/i/flow/login"


    co = ChromiumOptions()
    co.headless(True)
    co.set_user_data_path(f"{base_data_path}/{username}")
    co._arguments.append("--disable-gpu")
    co._arguments.append("--disable-dev-shm-usage")
    co._arguments.append("--window-size=1024,768")

    co.set_user_agent(UserAgent().chrome)
    # co.set_load_mode("eager")

    so = SessionOptions()
    page = WebPage(chromium_options=co, session_or_options=so)


    page.get(LOGIN_URL)

    # Get "Sign in with Apple" span element
    logger.info("waiting for the page to load")
    try:
        login_elem = page.ele(LOGIN_SPAN_TEXT, timeout=30)
        login_elem.click()
    except ElementNotFoundError:
        page.quit()
        logger.error("Failed to load the login page")
        raise PageLoadError("Failed to load the login page")


    login_elem.input(username)

    logger.info("Clicking on the next button")
    page.ele(NEXT_BUTTON_TEXT).click()

    # TODO: add a section to handle the email-based login

    # check if they are asking for email
    try:
        email_elem = page.ele(EMAIL_OR_PHONE_TEXT, timeout=5)
        email_elem.click()
        email_elem.input(email)
        page.ele(NEXT_BUTTON_TEXT).click()
    except ElementNotFoundError:
        logger.trace("They are not asking for email")

    # wait for the Password input
    password_elem = page.ele(PASSWORD_TEXT, timeout=10)
    password_elem.click()
    password_elem.input(password)

    # Find all button elements
    logger.trace("waiting for the login button")
    login_button = page.ele(LOGIN_BUTTON_SELECTOR, timeout=10)
    login_button.hover()
    login_button.click()

    # TODO: check if password is incorrect

    # wait for What is happening?!
    logger.trace("waiting for What is happening?!")
    try:
        page.ele(WHAT_IS_HAPPENING_TEXT, timeout=30)
    except ElementNotFoundError:
        logger.error("The main page is not loaded")
        # TODO: add some logs about the page state
        page.quit()
        return None, None

    # copy the cookies and headers
    cookies = deepcopy(page.cookies(as_dict=True, all_info=True))
    headers = deepcopy(page._headers)

    page.quit()

    return cookies, headers


async def login_alternative(acc: Account, cfg: LoginConfig | None = None, base_data_path: str = "drission") -> Account:
    log_id = f"{acc.username} - {acc.email}"
    if acc.active:
        logger.info(f"account already active {log_id}")
        return acc

    cfg, imap, gmail_creds = cfg or LoginConfig(), None, None
    if cfg.email_first and not cfg.manual:
        imap = await imap_login(acc.email, acc.email_password)
    if cfg.gmail and acc.gmail_credentials:
        acc.gmail_credentials

    # run drissionpage script
    cookies, headers = login_with_drissionpage(
        username=acc.username,
        password=acc.password,
        email=acc.email,
        email_password=acc.email_password,
        gmail_credentials=acc.gmail_credentials,
        base_data_path=base_data_path
    )

    acc.active = True
    acc.headers = {k: v for k, v in headers.items()}
    acc.cookies = {k: v for k, v in cookies.items()}
    return acc
