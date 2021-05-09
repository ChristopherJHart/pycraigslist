"""
pycraigslist.models.sessions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Handles requests and constructs BeautifulSoup objects.
"""

import cchardet
import concurrent.futures
import lxml
import tenacity
import requests
from bs4 import BeautifulSoup, SoupStrainer
from pycraigslist.exceptions import MaximumRequestsError

HEADERS = {"headers": {"User-Agent": "Mozilla/5.0"}}
# Retry 10 times, starting with 0.01 second and doubling the delay every time
_RETRY_ARGS = {
    "wait": tenacity.wait.wait_random_exponential(multiplier=0.01, exp_base=2),
    "stop": tenacity.stop.stop_after_attempt(12),
}


def yield_html(url, **kwargs):
    """Yields HTML content(s) to caller."""
    session = requests.Session()
    strainer = get_cl_strainer()
    try:
        # Single request: a url string
        if isinstance(url, str):
            yield get_html(get_request(session, url, **parse_kwargs(kwargs)).text, strainer)
        # Single request: a single url in a list or tuple
        elif isinstance(url, (list, tuple)) and len(url) == 1:
            yield get_html(get_request(session, url[0], **parse_kwargs(kwargs)).text, strainer)
        # Multiple requests
        else:
            # Build iterables of session and strainer objects equal in length to url tuple
            sessions = make_iterable(session, len(url))
            strainers = make_iterable(strainer, len(url))
            yield from map(
                get_html,
                (
                    response.text
                    for response in threaded_get_request(sessions, url, **parse_kwargs(kwargs))
                ),
                strainers,
            )
    except tenacity.RetryError:
        raise MaximumRequestsError("Maximum requests attempted - check network connection.")


def get_cl_strainer():
    """Gets bs4.SoupStrainer object, targeting relevant sections of the Craigslist page."""

    def target_elem_attrs(elem, attrs):
        """Gets desired elements and attributes from Craigslist HTML document."""
        # For pycraigslist.models.search_detail
        if elem == "section" and attrs.get("class") == "userbody":
            return True
        # For pycraigslist.models.search
        elif elem == "script" and attrs.get("type") == "text/javascript":
            return True
        # Whitespace after 'search-attribute' (index 0) is necessary
        elif elem == "div" and attrs.get("class") in [
            "search-attribute ",
            "search-attribute hide-list",
        ]:
            return True
        elif elem == "span" and attrs.get("class") == "totalcount":
            return True
        elif elem == "ul" and attrs.get("class") == "rows":
            return True

    return SoupStrainer(target_elem_attrs)


def get_html(text, strainer):
    """Gets bs4.BeautifulSoup object from response text."""
    return BeautifulSoup(text, "lxml", parse_only=strainer)


@tenacity.retry(**_RETRY_ARGS)
def get_request(requests_session, url, params=None):
    """Gets requests.models.Response object using requests.get.
    Retry request if request fails, with number of attempts and
    wait time specified in _RETRY_ARGS."""
    if params is None:
        params = HEADERS
    # Don't add headers if params is {}
    elif params != {}:
        params.update(HEADERS)
    return requests_session.get(url, params=params, timeout=5)


def threaded_get_request(sessions, urls, **kwargs):
    """Yields requests from get_request concurrently."""
    yield from iter(
        concurrency(
            concurrent.futures.ThreadPoolExecutor,
            lambda args: get_request(*args),
            sessions,
            urls,
            **kwargs
        )
    )


def concurrency(PoolExecutor, map_func, *args, **kwargs):
    """General concurrency procedure for thread pools and process
    pools that submits map-able functions to arguments."""
    # Zip args and kwarg values to make tuple of args
    zipped_args = zip(*args, *kwargs.values())
    with PoolExecutor(max_workers=5) as executor:
        futures = {
            # Func must accept all positional arguments (kwargs assumed by args OK)
            executor.submit(map_func, arg_tuple)
            for arg_tuple in zipped_args
        }
        for future in concurrent.futures.as_completed(futures):
            yield future.result()


def parse_kwargs(kwargs):
    """Removes first kwarg value from list or tuple wrapper if wrapped and
    is the only value."""
    for key, value in kwargs.copy().items():
        if isinstance(value, (list, tuple)) and len(value) == 1:
            kwargs[key] = value[0]
    return kwargs


def make_iterable(target, count):
    """Returns iterable of target object equal in length to count."""
    return (target for _ in range(count))
