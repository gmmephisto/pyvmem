from __future__ import unicode_literals

from psys import Error


EX_OK = 0
"""VMEM success response status."""

EX_ERROR = 1
"""VMEM error response status."""

EX_NOFND = 14004
"""VMEM object not found response status."""

EX_BUSY = 14032
"""VMEM system busy response status."""

EX_NOSPC = 512
"""VMEM no space left response status.

Attention: We get this error code empirically!
TODO: double check error code and create support case
"""


class VMEMError(Error):
    """Base exception for VMEM error."""

    code = EX_OK
    """VMEM error code."""

    message = ""
    """VMEM error message."""

    def __init__(self, code, message):
        super(VMEMError, self).__init__(code, message)
        self.code = code
        self.message = message

    def __str__(self):
        return "VMEM Error: {code} {message}".format(
            code=self.code, message=self.message)


class VMEMAuthError(VMEMError):
    def __init__(self):
        super(VMEMAuthError, self).__init__(1, "Not Authenticated")


class VMEMLunNotFound(VMEMError):
    def __init__(self, container, lun):
        super(VMEMLunNotFound, self).__init__(
            EX_NOFND, "Lun with name '{0}' not found on container '{1}'.".format(lun, container))


class VMEMExportNotFound(VMEMError):
    def __init__(self, container, lun):
        super(VMEMExportNotFound, self).__init__(
            EX_NOFND, "Export for lun '{0}' not found on container '{1}'.".format(lun, container))


class VMEMLunIDConflict(VMEMError):
    def __init__(self, code, msg):
        super(VMEMLunIDConflict, self).__init__(code, msg)


class VMEMNoSpaceLeft(VMEMError):
    def __init__(self, container, lun):
        super(VMEMNoSpaceLeft, self).__init__(
            EX_NOSPC, "No space left on container '{0}' when resize lun '{1}'.".format(container, lun))


class VMEMSystemIsBusy(VMEMError):
    def __init__(self, code, msg):
        """Meaning - The system is busy, and will not attempt 'action'.

        Action - Wait anywhere from 10 to 15 seconds and then attempt 'action' again.
        """
        super(VMEMSystemIsBusy, self).__init__(code, msg)


class VMEMMalformedResponse(VMEMError):
    def __init__(self):
        super(VMEMMalformedResponse, self).__init__(
            EX_ERROR, "Got a malformed reply from the VMEM container.")
