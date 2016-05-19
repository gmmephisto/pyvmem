from __future__ import unicode_literals


class VMEMLunBase(object):
    """Base klass for VMEM LUNs."""

    @classmethod
    def create(cls, *args, **kwargs):
        """Creates and returns instance of VMEM LUN."""

        raise NotImplementedError()

    @classmethod
    def one(cls, *args, **kwargs):
        """Returns instance of specified VMEM LUN."""

        raise NotImplementedError()

    @classmethod
    def all(cls, *args, **kwargs):
        """Returns list of instances of VMEM LUNs."""

        raise NotImplementedError()

    def __init__(self, client, name, **kwargs):
        self._client = client
        self.name = name

    def export(cls, *args, **kwargs):
        """Exports VMEM LUN to specified initiators."""

        raise NotImplementedError()

    def unexport(cls, *args, **kwargs):
        """Unexports VMEM LUN from specified initiators."""

        raise NotImplementedError()

    def delete(cls, *args, **kwargs):
        """Deletes VMEM LUN from container."""

        raise NotImplementedError()



class ViolinLUNBase(object):
    """Base class for Violin objects."""

    def __init__(self, client, name, *args, **kwargs):
        self.container = client.container
        self.connection = client.connection
        self.logger = client.logger

        self.name = name

    def _parse_export_config(self, path):
        """Returns parsed export config."""

        result = self.connection.get(path)
        try:
            nodes = result.query_response_node
        except KeyError:
            raise ViolinExportNotFound(self.container, self.name)

        config = {}
        for node in nodes:
            if bool(initiator_re.search(node["name"])):
                config.setdefault("initiators", set()).add(node["value"])
        config["initiators"] = list(config["initiators"])

        return config

    def _parse_export_serial(self, path):
        """Returns parsed serial_id."""

        response = self.connection.get(path)
        try:
            serial = response.query_response_value
        except KeyError:
            raise ViolinLunNotFound(self.container, self.name)

        try:
            parsed_serial = c2.ibutils.parse_hexnum(serial)
        except ValueError:
            return None
        except Exception as e:
            self.logger.error(
                "We got an unexpected error while parsing lun serial '%s': %s",
                serial, e)
            raise e
        else:
            return "3{0}".format(parsed_serial)

    def _export_unexport(self, request, template, **kwargs):
        """Common method for export/unexport lun."""

        lun_id = kwargs.get("lun_id")
        initiators = kwargs.get("initiators", [])
        unexport = kwargs.get("unexport", False)

        kwargs["unexport"] = "true" if unexport else "false"
        nodes = xmltodict.parse(template.format(
            container=self.container, **kwargs))["nodes"]["node"]
        for node in nodes:
            request.add_node(node)

        request.add_initiators(initiators)

        resp = self.connection.post(request.to_xml())
        self.logger.debug(
            "Violin action: '%s_lun': name='%s', id='%s', initiators=%s, status=(%s, %s)",
            "export" if not unexport else "unexport", self.name, lun_id, initiators,
            resp.return_code, resp.return_msg
        )
        return resp.return_code

    def _export_error(self, exc):
        """Common method for handle export errors."""

        assert isinstance(exc, ViolinError) is True

        if exc.code == 1 and "LUN ID conflict" in exc.message:
            raise ViolinLunIDConflict(exc.code, exc.message)


class ViolinLUN(ViolinLUNBase):
    """Represents Violin LUN."""

    def __init__(self, client, name, size=None, *args, **kwargs):
        super(ViolinLUN, self).__init__(client, name)
        self.size = size

    def get_export(self):
        """Returns LUN export config."""

        path = "/vshare/config/export/container/{0}/lun/{1}/target/**".format(
            self.container, self.name)
        return self._parse_export_config(path)

    def get_serial(self):
        """Returns serial_id (naa_id) of exported LUN."""

        path = "/vshare/state/local/container/{0}/lun/{1}/naa_id".format(
            self.container, self.name)
        return self._parse_export_serial(path)

    def export_unexport_action(self, lun_id, initiators=[], unexport=False):
        """Common method for export/unexport lun."""

        request = ViolinActionRequest("/vshare/actions/lun/export")

        return self._export_unexport(request, EXPORT_UNEXPORT_LUN_XML,
            lun_name=self.name, lun_id=lun_id, initiators=initiators, unexport=unexport
        )

    def on_export_error(self, exc, retries, retry):
        """Handle errors on export."""

        super(ViolinLUN, self)._export_error(exc)
        if (
            exc.code == 14004 and
            retry < retries - 1
        ):
            # TODO: determine best timeout
            self.logger.warning("LUN not found on export, retry.")
            time.sleep(0.1 * 10)
        else:
            raise


class ViolinLUNSnapshot(ViolinLUNBase):
    """Represents Violin LUN Snapshot."""

    def __init__(self, client, name, lun_name, rw=False, *args, **kwargs):
        super(ViolinLUNSnapshot, self).__init__(client, name)
        self.lun_name = lun_name
        self.__rw = rw

    @property
    def rw(self):
        return "true" if self.__rw else "false"

    def get_export(self):
        """Returns LUN Snapshot export config."""

        path = "/vshare/config/export/snapshot/container/{0}/lun/{1}/snap/{2}/target/**".format(
            self.container, self.name, self.lun_name)
        return self._parse_export_config(path)

    def get_serial(self):
        """Returns serial_id (naa_id) of exported LUN snapshot."""

        path = "/vshare/state/snapshot/container/{0}/lun/{1}/snap/{2}/naa_id".format(
            self.container, self.name, self.lun_name)
        return self._parse_export_serial(path)

    def export_unexport_action(self, lun_id, initiators=[], unexport=False):
        """Common method for export/unexport lun."""

        request = ViolinActionRequest("/vshare/actions/vdm/snapshot/export")

        return self._export_unexport(request, EXPORT_UNEXPORT_LUN_SNAPSHOT_XML,
            snap_name=self.lun_name, lun_name=self.name, lun_id=lun_id,
            initiators=initiators, unexport=unexport
        )

    def on_export_error(self, exc, retries, retry):
        """Handle errors on export."""

        super(ViolinLUNSnapshot, self)._export_error(exc)
        if (
            exc.code == 14004 and "inconsistent" in exc.message and
            retry < retries - 1
        ):
            # We got 14004 'inconsistent' error empirically
            # TODO: determine best timeout
            self.logger.warning("Snapshot LUN inconsistent on export.")
            time.sleep(0.1 * 20)
        else:
            raise
