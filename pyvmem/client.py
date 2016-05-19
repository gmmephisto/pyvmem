from __future__ import unicode_literals

from collections import OrderedDict, Mapping, namedtuple
from six.moves.urllib.parse import urljoin

import logging
import requests
import uuid
import xmltodict

from pyvmem import exceptions

log = logging.getLogger(__name__)
"""Logger instance."""


class VMEMActionRequest(object):
    """Represents a VMEM action request."""

    def __init__(self, name):
        self.name = name
        self._request = OrderedDict([(
            "xg-request", OrderedDict([(
                "action-request", OrderedDict([
                    ("action-name", name),
                    ("nodes", OrderedDict([
                        ("node", [])
                    ]))
                ])
            )])
        )])

    def to_xml(self, pretty=True):
        """Returns XML request message."""

        return xmltodict.unparse(self._request, pretty=pretty)

    @property
    def root(self):
        return self._request["xg-request"]

    @property
    def action(self):
        return self.root["action-request"]

    def add_node(self, node):
        """Adds nodes to request object."""

        if not isinstance(node, OrderedDict):
            raise TypeError()

        self.action["nodes"]["node"].append(node)

    def add_initiators(self, initiators=None):
        """Adds initiators to request object."""

        if not initiators:
            self.add_node(OrderedDict([
                ("name", "initiators/all"),
                ("type", "string"),
                ("value", "all")
            ]))
        else:
            for guid in initiators:
                self.add_node(OrderedDict([
                    ("name", "initiators/{0}".format(guid)),
                    ("type", "string"),
                    ("value", "{0}".format(guid))
                ]))


VMEMResponseStatus = namedtuple("status", ("code", "message"))
"""Represents a VMEM response status."""


class VMEMResponse(Mapping):
    """Represents a VMEM response."""

    def __init__(self, data):
        self._status = None
        self._return_status = None

        self._response_data = data
        try:
            self._response = xmltodict.parse(data)
        except xmltodict.expat.ExpatError:
            raise exceptions.VMEMMalformedResponse()

    def __getitem__(self, key):
        return self._response[key]

    def __len__(self):
        return len(self._response)

    def __iter__(self):
        return iter(self._response)

    @property
    def text(self):
        return self._response_data

    @property
    def root(self):
        return self["xg-response"]

    @property
    def is_query(self):
        return "query-response" in self.root

    @property
    def is_action(self):
        return "action-response" in self.root

    @property
    def query(self):
        return self.root["query-response"] if self.is_query else None

    @property
    def action(self):
        return self.root["action-response"] if self.is_action else None

    @property
    def status(self):
        if not self._status and "xg-status" in self.root:
            self._status = VMEMResponseStatus(
                int(self.root["xg-status"]["status-code"]),
                self.root["xg-status"].get("status-msg", "")
            )
        return self._status

    @property
    def return_status(self):
        if not self._return_status:
            status = None
            if self.is_query:
                status = self.query["return-status"]
            elif self.is_action:
                status = self.action["return-status"]

            self._return_status = VMEMResponseStatus(
                int(status["return-code"]), status.get("return-msg", "")
            )
        return self._return_status

    @property
    def content(self):
        return self.query["nodes"].get("node", {}) if self.is_query else {}

    def raise_for_status(self):
        """Raises VMEM specific error if response has error status."""

        if self.status and self.status.code >= exceptions.EX_ERROR:
            code, message = self.status
            if message == "Not authenticated":
                raise exceptions.VMEMAuthError()
            else:
                raise exceptions.VMEMError(code, message)

        if self.return_status and self.return_status.code >= exceptions.EX_ERROR:
            code, message = self.return_status
            if code == exceptions.EX_BUSY:
                raise exceptions.VMEMSystemIsBusy(code, message)
            else:
                raise exceptions.VMEMError(code, message)


class VMEMSession(object):
    """VMEM session base class."""

    __session = None
    """VMEM session instance."""

    __endpoint = "{scheme}://{host}/admin/launch/"
    """VMEM HTTP endpoint."""

    __xtree = "{scheme}://{host}/xtree/"
    """VMEM XG endpoint."""

    def __init__(self, host, user, passwd, is_secure=False,
                 retries=3, timeout=30):
        self.host = host
        self.scheme = "https" if is_secure else "http"

        self.user = user
        self.passwd = passwd

        self.timeout = timeout
        self.retries = retries

        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        self.__session = requests.Session()
        self.__session.headers.update(self.headers)

    @property
    def endpoint(self):
        return self.__endpoint.format(
            scheme=self.scheme, host=self.host)

    @property
    def xtree(self):
        return self.__xtree.format(
            scheme=self.scheme, host=self.host)

    def login(self):
        """Login to VMEM container."""

        self.__session.cookies.clear_session_cookies()

        # Another form data for valid request
        data = {
            "d_user_id": "user_id",
            "t_user_id": "string",
            "c_user_id": "string",
            "e_user_id": "true",
            "Login": "Login"
        }
        # Actual login data
        data.update({
            "f_user_id": self.user,
            "f_password": self.passwd,
        })
        # Login request params
        params = {
            "script": "rh",
            "action": "login",
            "template": "login",
        }
        self.__session.post(
            url=self.endpoint, data=data, params=params,
            timeout=self.timeout, allow_redirects=False, verify=False)

    def logout(self):
        """Logout from VMEM container."""

        # No data to send
        data = ""

        # Logout request params
        params = {
            "action": "logout",
            "template": "logout",
            "script": "rh"
        }
        self.__session.post(
            url=self.endpoint, data=data, params=params,
            timeout=self.timeout, allow_redirects=False, verify=False)
        self.__session.cookies.clear_session_cookies()

    def _send_request(self, method, url, data=None, headers=None):
        """Base method for sending requests."""

        headers = headers or {}
        retries = self.retries

        request_uuid = str(uuid.uuid4())
        log.debug("VMEM request %s: method='%s', url='%s', data='%s'",
            request_uuid, method, url, data)

        vresponse = None
        while retries >= 0:
            log.debug("VMEM request %s: retries left (%s)", request_uuid, retries)
            response = self.__session.request(
                method=method, url=url, data=data,
                timeout=self.timeout, headers=headers,
                allow_redirects=False, verify=False
            )
            response.raise_for_status()
            try:
                vresponse = VMEMResponse(response.text)
            except exceptions.VMEMMalformedResponse:
                if not retries:
                    raise
                retries -= 1
                continue

            log.debug("VMEM response for request '%s': %s",
                request_uuid, vresponse.text)

            try:
                vresponse.raise_for_status()
            except exceptions.VMEMAuthError:
                if not retries:
                    raise
                retries -= 1
                self.login()
                continue
            else:
                return vresponse

    def get(self, path):
        """Sends HTTP GET request to VMEM."""

        return self._send_request(
            method="get", url=urljoin(self.xtree, path))

    def post(self, data):
        """Sends HTTP POST request to VMEM."""

        return self._send_request(
            method="post", url=self.xtree, data=data, headers=self.headers)


class VMEMClient(object):
    """Client to VMEM XG API."""

    @classmethod
    def from_args(cls, *args, **kwargs):
        """Initialize VMEM client from specified arguments."""

        return cls()

    def __init__(self, session):
        if not isinstance(session, VMEMSession):
            raise exceptions.Error(
                "VMEM Client must be initialize with VMEMSession instance.")

        self._session = session

    @property
    def session(self):
        return self._session

    def commit(self):
        """Commits database changes on VMEM container."""

        return self.session.post(VMEMActionRequest("/mgmtd/db/save").to_xml())

    def get_container_name(self):
        """Returns VMEM container name."""

        return self.session.get("vshare/state/local/container/*").content["value"]
