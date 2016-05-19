from datetime import datetime, timedelta
from collections import namedtuple, OrderedDict
from functools import partial

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import _ResultItem
from multiprocessing import Process

from requests import Session
from urllib import urlencode

import time
import sys
import Queue
import uuid
import xmltodict

import re
initiator_re = re.compile(r"initiator/[^/]+$")


def _process_worker(call_queue, result_queue, connection_args, logger):
    """Evaluates calls from call_queue and places the results in result_queue.

    This worker is run in a separate process.

    Args:
        call_queue: A multiprocessing.Queue of _CallItems that will be read and
            evaluated by the worker.
        result_queue: A multiprocessing.Queue of _ResultItems that will written
            to by the worker.
        shutdown: A multiprocessing.Event that will be set as a signal to the
            worker that it should exit when call_queue is empty.
    """

    vmem_process = None
    while True:
        try:
            call_item = call_queue.get(block=True, timeout=0.5)
        except Queue.Empty:
            continue

        if call_item is None:
            # Wake up queue management thread
            if vmem_process:
                vmem_process.connection.logout()
            result_queue.put(None)
            return

        if vmem_process is None:
            vmem_process = ViolinAPI(connection_args, logger)

        try:
            function = getattr(vmem_process, call_item.fn)
            r = function(*call_item.args, **call_item.kwargs)
        except BaseException:
            e = sys.exc_info()[1]
            result_queue.put(_ResultItem(call_item.work_id,
                                         exception=e))
        else:
            result_queue.put(_ResultItem(call_item.work_id,
                                         result=r))


class ViolinManager(ProcessPoolExecutor):
    """Violin container API process manager."""

    WORKERS = 1
    """Worker count per container."""

    def __init__(self, args, logger):
        super(ViolinManager, self).__init__(self.WORKERS)
        self.__vmem_args = args
        self.logger = logger

    def __getattr__(self, key):
        self.logger.debug(
            "Sumbit function '%s' to processing. Pending functions: %s",
            key, self._pending_work_items
        )
        return partial(self.submit, key)

    def _adjust_process_count(self):
        if len(self._processes) == 1:
            return
        p = Process(
            target=_process_worker,
            args=(self._call_queue, self._result_queue, self.__vmem_args, self.logger)
        )
        p.start()
        self._processes.add(p)

    def shutdown(self, wait=True):
        self.logger.debug("Stop Violin container process manager.")
        self._call_queue.put(None)
        super(ViolinManager, self).shutdown(wait)


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


class ViolinAPI(object):
    """Violin container API helper."""

    def __init__(self, args, logger=None):
        self.__connection = ViolinSession(args, logger)
        self.__container = self.__connection.container_name
        self.logger = self.__connection.logger

    @property
    def container(self):
        return self.__container

    @property
    def connection(self):
        return self.__connection

    def get_container_name(self):
        """Returns container name."""

        return self.container

    def get_container_stats(self):
        """Get all container stats."""

        req = GET_CONTAINER_STATS_XML.format(self.container)
        resp = self.connection.post(req)

        result = {}
        for el in resp.query_response_node:
            result[el["name"].split("/")[-1]] = int(el["value"])
        result["free_bytes"] = result["total_bytes"] - result["alloc_bytes"]

        return result

    def get_container_free_space(self):
        """Get container current free space."""

        path = "/vshare/state/local/container/{0}/free_bytes".format(self.container)
        result = self.connection.get(path)

        return int(result.query_response_value)

    def get_container_total_space(self):
        """Get container total space."""

        path = "/vshare/state/local/container/{0}/total_bytes".format(self.container)
        result = self.connection.get(path)

        return long(result.query_response_value)

    def get_container_lun_num(self):
        """Returns container LUN's count."""

        stats = self.get_container_stats()
        return int(stats["num_luns"])

    def get_lun(self, lun_name):
        """Get specified lun."""

        path = "/vshare/state/local/container/{0}/lun/{1}/*".format(
            self.container, lun_name)
        result = self.connection.get(path)
        try:
            result.query_response_node
        except KeyError:
            raise ViolinLunNotFound(self.container, lun_name)

        return result

    def get_lun_size(self, lun_name):
        """Returns current LUN size."""

        path = "/vshare/state/local/container/{0}/lun/{1}/size".format(
            self.container, lun_name)
        result = self.connection.get(path)

        return int(result.query_response_value)

    def get_lun_id(self, lun_name):
        """Returns LUN id."""

        path = "/vshare/config/export/container/{container}/lun/{lun_name}/target/**".format(
            container=self.container, lun_name=lun_name)

        result = self.connection.get(path)
        try:
            nodes = result.query_response_node
        except KeyError:
            raise ViolinExportNotFound(self.container, self.name)

        lun_ids = set()
        for node in nodes:
            if node["name"].split("/")[-1] == "lun_id":
                lun_ids.add(int(node["value"]))

        if len(lun_ids) > 1:
            raise ViolinError(
                "Unable to get lun_id: multiple lun_id found.",
                lun_name
            )

        return list(lun_ids)[0]

    def get_lun_export(self, lun_name):
        """Returns LUN export config."""

        lun_model = ViolinLUN(self, lun_name)
        return lun_model.get_export()

    def get_lun_serial(self, lun_name):
        """Returns LUN serial."""

        lun_model = ViolinLUN(self, lun_name)
        return lun_model.get_serial()

    def get_snapshot_export(self, snapshot_name, lun_name):
        """Returns Snapshot export config of specified LUN."""

        snap_model = ViolinLUNSnapshot(self, snapshot_name, lun_name)
        return snap_model.get_export()

    def get_snapshot_serial(self, snapshot_name, lun_name):
        """Returns Snapshot serial of specified LUN."""

        snap_model = ViolinLUNSnapshot(self, snapshot_name, lun_name)
        return snap_model.get_serial()

    def get_snapshots(self, lun_name):
        """Returns snapshots list for specified LUN."""

        snapshots = []

        path = "/vshare/state/snapshot/container/{container}/lun/{lun_name}/snap/*".format(
            container=self.container, lun_name=lun_name)

        result = self.connection.get(path)
        try:
            nodes = result.query_response_node
        except KeyError:
            return snapshots

        for node in nodes:
            snapshots.append(node["name"].split("/")[-1])

        return snapshots

    def get_luns(self):
        """Returns LUNs list on container."""

        luns = []

        path = "/vshare/state/local/container/{container}/lun/*".format(
            container=self.container)

        result = self.connection.get(path)
        try:
            nodes = result.query_response_node
        except KeyError:
            return luns

        for node in nodes:
            luns.append(node["name"].split("/")[-1])

        return luns

    def create_lun(self, lun_name, size):
        """Create LUN."""

        req = CREATE_LUN_XML.format(
            container=self.container, lun_name=lun_name, size=size)

        retries = 0
        resp = None
        while retries < 3:
            try:
                resp = self.connection.post(req)
            except ViolinSystemIsBusy as e:
                resp = e
                # TODO: determine best timeout
                time.sleep(5)
                retries += 1
                continue
            except ViolinError as e:
                if e.code == 512:
                    # We get this error code (512) empirically
                    # TODO: double check error code and create support case
                    raise ViolinNoSpaceLeft(self.container, lun_name)
                else:
                    raise
            else:
                break

        if resp is None:
            raise ViolinError(
                "Violin action: 'create_lun': name='{0}' failed.", lun_name
            )
        elif isinstance(resp, ViolinSystemIsBusy):
            raise resp

        self.logger.debug("Violin action: 'create_lun': name='%s', status=(%s, %s)",
            lun_name, resp.return_code, resp.return_msg)

    def _await_serial(self, model, timeout=15):
        """Wait and returns serial_id.

        :param model: container object model
        :param timeout: serial wait time
        """

        # We need to sleep 1.5-2 seconds before polling
        time.sleep(2)

        serial = None
        stime = datetime.now()
        # Serial await timeout
        delta = timedelta(0, timeout)

        while not serial:
            if datetime.now() - stime >= delta:
                raise RuntimeError()

            try:
                serial = model.get_serial()
            except ViolinLunNotFound:
                # TODO: use POLLING_INTERVAL * 20 from c2.config
                time.sleep(0.1 * 20)
                continue

            if not serial:
                # TODO: use POLLING_INTERVAL * 20 from c2.config
                time.sleep(0.1 * 20)
                continue

        return serial

    def _await_export_config(self, model, initiators, timeout=15):
        """Wait and returns export config.

        :param model: container object model
        :param timeout: config wait time
        """

        config = None
        stime = datetime.now()
        delta = timedelta(0, timeout)

        while not config:
            if datetime.now() - stime >= delta:
                raise RuntimeError()
            try:
                config = model.get_export()
            except ViolinExportNotFound:
                time.sleep(0.1 * 10)
                continue
            else:
                if set(initiators) - set(config["initiators"]):
                    time.sleep(0.1 * 20)
                    config = None
                    continue
                else:
                    break

        return config

    def __export_common(self, model, lun_id, initiators=[], retries=5):
        """Performs export action and waits for success state.

        :param model: container object model
        :param lun_id: assigned lun id
        :param initiators: export addresses
        """

        initiators = map(c2.ibutils.hexnum_to_guid, initiators)

        retry = 0
        serial = None
        config = None
        while retry < retries:
            try:
                model.export_unexport_action(lun_id, initiators=initiators)
            except ViolinSystemIsBusy:
                # TODO: determine best timeout
                time.sleep(5)
                retry += 1
                continue
            except ViolinError as e:
                model.on_export_error(e, retries, retry)
                retry += 1
                continue

            try:
                serial = self._await_serial(model)
            except RuntimeError:
                retry += 1
                continue

            try:
                config = self._await_export_config(model, initiators)
            except RuntimeError:
                retry += 1
                continue
            else:
                break

        if not serial or not config:
            raise ViolinExportNotFound(self.container, model.name)

        return serial

    def _unexport_all(self, model, timeout=30):
        """Unexport from all initiators."""

        exported = True
        stime = datetime.now()
        delta = timedelta(0, timeout)
        while exported:
            if datetime.now() - stime >= delta:
                raise RuntimeError()

            serial = model.get_serial()
            if serial is None:
                exported = False
            else:
                time.sleep(0.1 * 30)
                continue

    def _unexport_initiators(self, model, initiators, timeout=30):
        """Unexport from specified initiators."""

        exported = True
        stime = datetime.now()
        delta = timedelta(0, timeout)
        while exported:
            if datetime.now() - stime >= delta:
                raise RuntimeError()

            config = model.get_export()
            if not set(initiators).intersection(
                set(config["initiators"])
            ):
                exported = False
            else:
                time.sleep(0.1 * 30)
                continue

    def __unexport_common(self, model, lun_id, initiators=[]):
        """Performs unexport action and waits for success state.

        :param model: container object model
        :param lun_id: assigned lun id
        :param initiators: export addresses
        """

        initiators = map(c2.ibutils.hexnum_to_guid, initiators)

        retries = 0
        while retries < 3:
            try:
                model.export_unexport_action(lun_id,
                    initiators=initiators, unexport=True)
            except ViolinSystemIsBusy:
                # TODO: determine best timeout
                time.sleep(5)
                retries += 1
                continue
            except ViolinError as e:
                if e.code == 14004:
                    break
                else:
                    raise
            try:
                if not initiators:
                    self._unexport_all(model)
                else:
                    self._unexport_initiators(model, initiators)
            except RuntimeError:
                retries += 1
                continue
            else:
                break

        return True

    def export_lun(self, lun_name, lun_id, initiators=[]):
        """Performs LUN export."""

        lun_model = ViolinLUN(self, lun_name)
        return self.__export_common(lun_model, lun_id, initiators=initiators)

    def unexport_lun(self, lun_name, lun_id, initiators=[]):
        """Performs LUN unexport."""

        lun_model = ViolinLUN(self, lun_name)
        return self.__unexport_common(lun_model, lun_id, initiators=initiators)

    def _export_unexport_lun(self, lun_name, lun_id, initiators=[], unexport=False):
        """Send request for export/unexport action for specified LUN.

        Attention: Used only in unittest!
        """

        lun_model = ViolinLUN(self, lun_name)
        return lun_model.export_unexport_action(lun_id, initiators, unexport)

    def resize_lun(self, lun_name, size):
        """Resize LUN."""

        current_size = self.get_lun_size(lun_name)
        if current_size == size:
            self.logger.debug("Resize lun '%s': current lun size is equal to new size: %s == %s",
                lun_name, current_size, size)
            return

        new_size = size / constants.GIGABYTE
        request = RESIZE_LUN_XML.format(
            container=self.container, lun_name=lun_name, new_size=new_size)

        resp = None
        try:
            resp = self.connection.post(request)
        except ViolinError as e:
            if e.code == 512:
                # We get this error code (512) empirically
                # TODO: double check error code and create support case
                raise ViolinNoSpaceLeft(self.container, lun_name)
            else:
                raise
        else:
            self.logger.debug("Violin action: 'resize_lun': name=%s, size=%s, status=(%s, %s)",
                lun_name, new_size, resp.return_code, resp.return_msg)

    def delete_lun(self, lun_name):
        """Delete LUN."""

        request = DELETE_LUN_XML.format(
            container=self.container, lun_name=lun_name)
        resp = None
        try:
            resp = self.connection.post(request)
        except ViolinError as e:
            if e.code == 14004:
                pass
            else:
                raise
        else:
            self.logger.debug("Violin action: 'delete_lun': name='%s' status=(%s, %s)",
                lun_name, resp.return_code, resp.return_msg)

    def get_snapshot_status(self, lun_name, snap_name):
        """Returns snapshot status."""

        path = "/vshare/state/snapshot/container/{0}/lun/{1}/snap/{2}/status".format(
            self.container, lun_name, snap_name)
        resp = self.connection.get(path)

        status = None
        try:
            status = resp.query_response_value
        except KeyError:
            return None

        self.logger.debug("Violin query: 'snapshot_status': lun='%s', snapshot='%s', status='%s",
            lun_name, snap_name, status)

        return status

    def _await_snapshot(self, lun_name, snap_name):
        """Awaits for snapshot creation."""

        stime = datetime.now()
        delta = timedelta(0, 30)

        created = False
        while not created:
            if datetime.now() - stime >= delta:
                raise RuntimeError()

            status = self.get_snapshot_status(lun_name, snap_name)
            if status is None:
                # TODO: determine best timeout
                time.sleep(0.1 * 20)
                continue
            else:
                created = True

        return created

    def create_lun_snapshot(self, lun_name, snap_name, description="", await=True):
        """Creates snapshot for specified LUN."""

        request = CREATE_LUN_SNAPHOT_XML.format(container=self.container,
            lun_name=lun_name, snap_name=snap_name, desc=description, rw="false")

        retries = 0
        resp = None
        while retries < 3:
            try:
                resp = self.connection.post(request)
            except ViolinSystemIsBusy as e:
                resp = e
                # TODO: determine best timeout
                time.sleep(5)
                retries += 1
                continue
            else:
                break

        if resp is None:
            raise ViolinError(
                "Violin action: 'create_snapshot': lun='{0}, 'name='{0}' failed.",
                lun_name, snap_name
            )
        elif isinstance(resp, ViolinSystemIsBusy):
            raise resp

        if await:
            created = self._await_snapshot(lun_name, snap_name)
            if not created:
                raise ViolinError(
                    "Violin action: 'create_snapshot': snapshot {0} not available.",
                    snap_name
                )
        self.logger.debug(
            "Violin action: 'create_snapshot': lun='%s', snapshot='%s'",
            lun_name, snap_name
        )

    def delete_lun_snapshot(self, lun_name, snap_name):
        """Delete lun snapshot."""

        request = DELETE_LUN_SNAPHOT_XML.format(container=self.container,
            lun_name=lun_name, snap_name=snap_name)

        retries = 0
        resp = None
        while retries < 3:
            try:
                resp = self.connection.post(request)
            except ViolinSystemIsBusy as e:
                resp = e
                # TODO: determine best timeout
                time.sleep(5)
                retries += 1
                continue
            except ViolinError as e:
                if e.code == 14004:
                    break
                else:
                    raise

        if resp is None:
            raise ViolinError(
                "Violin action: 'delete_snapshot': lun='{0}, 'name='{0}' failed.",
                lun_name, snap_name
            )
        elif isinstance(resp, ViolinSystemIsBusy):
            raise resp

        self.logger.debug("Violin action: 'delete_snapshot': name='%s' status=(%s, %s)",
            snap_name, resp.return_code, resp.return_msg)

    def export_snapshot(self, lun_name, snap_name, snap_lun_id, initiators=[]):
        """Preforms LUN Snapshot export."""

        snapshot_model = ViolinLUNSnapshot(self, lun_name, snap_name, rw=False)
        return self.__export_common(snapshot_model, snap_lun_id, initiators=initiators)

    def unexport_snapshot(self, lun_name, snap_name, snap_lun_id, initiators=[]):
        """Performs LUN Snapshot unexport."""

        snapshot_model = ViolinLUNSnapshot(self, lun_name, snap_name, rw=False)
        return self.__unexport_common(snapshot_model, snap_lun_id, initiators=initiators)

    def _export_unexport_snapshot(self, lun_name, snap_name, snap_lun_id, initiators=[], unexport=False):
        """Send request for export/unexport action for specified LUN Snapshot.

        Attention: Used only in unittest!
        """

        snap_model = ViolinLUNSnapshot(self, lun_name, snap_name)
        return snap_model.export_unexport_action(snap_lun_id, initiators, unexport)

    def get_current_lun_id(self):
        """Returns current lun id."""

        temp_name = str(uuid.uuid4())

        self.create_lun(temp_name, 1)
        self.export_lun(temp_name, lun_id=-1)

        lun_id = self.get_lun_id(temp_name)

        self.unexport_lun(temp_name, -1)
        self.delete_lun(temp_name)

        return lun_id

    def commit_changes(self):
        """Commit changes on violin container."""

        req = COMMIT_CHANGES_XML
        self.connection.post(req)

        self.logger.debug("Violin action: 'commit_changes': container='%s'",
            self.container)


CREATE_LUN_XML = """\
<?xml version="1.0" encoding="utf8"?>
<!-- Response options: Only false -->
<xg-request>
    <action-request>
    <action-name>/vshare/actions/lun/create</action-name>
        <nodes>
            <node>
                 <name>container</name>
                 <type>string</type>
                 <value>{container}</value>
            </node>
            <node>
                <name>name</name>
                <type>string</type>
                <value>{lun_name}</value>
            </node>
            <node>
                <name>size</name>
                <type>string</type>
                <value>{size}</value>
            </node>
            <node>
                <name>quantity</name>
                <type>uint64</type>
                <value>1</value>
            </node>
            <node>
                <name>nozero</name>
                <type>string</type>
                <value>0</value>
            </node>
            <node>
                <name>thin</name>
                <type>string</type>
                <value>0</value>
            </node>
            <node>
                <name>readonly</name>
                <type>string</type>
                <value>w</value>
            </node>
            <node>
                <name>action</name>
                <type>string</type>
                <value>c</value>
            </node>
            <node>
                <name>startnum</name>
                <type>uint64</type>
                <value>1</value>
            </node>
            <node>
                <name>blksize</name>
                <type>uint32</type>
                <value>512</value>
            </node>
        </nodes>
    </action-request>
</xg-request>
"""

DELETE_LUN_XML = """\
<?xml version="1.0" encoding="utf8"?>
<!-- Response options: Only false -->
<xg-request>
    <action-request>
        <action-name>/vshare/actions/lun/create</action-name>
        <nodes>
            <node>
                <name>container</name>
                <type>string</type>
                <value>{container}</value>
            </node>
            <node>
                <name>name</name>
                <type>string</type>
                <value>{lun_name}</value>
            </node>
            <node>
                <name>size</name>
                <type>string</type>
                <value>0</value>
            </node>
            <node>
                <name>quantity</name>
                <type>uint64</type>
                <value>1</value>
            </node>
            <node>
                <name>nozero</name>
                <type>string</type>
                <value>1</value>
            </node>
            <node>
                <name>thin</name>
                <type>string</type>
                <value>0</value>
            </node>
            <node>
                <name>readonly</name>
                <type>string</type>
                <value>w</value>
            </node>
            <node>
                <name>action</name>
                <type>string</type>
                <value>d</value>
            </node>
            <node>
                <name>startnum</name>
                <type>uint64</type>
                <value>1</value>
            </node>
            <node>
                <name>blksize</name>
                <type>uint32</type>
                <value>512</value>
            </node>
        </nodes>
    </action-request>
</xg-request>
"""

RESIZE_LUN_XML = """\
<?xml version="1.0" encoding="utf8"?>
<!-- Response options: Only false -->
<xg-request>
    <action-request>
        <action-name>/vshare/actions/lun/resize</action-name>
        <nodes>
            <node>
                <name>container</name>
                <type>string</type>
                <value>{container}</value>
            </node>
            <node>
                <name>lun</name>
                <type>string</type>
                <value>{lun_name}</value>
            </node>
            <node>
                <name>lun_new_size</name>
                <type>string</type>
                <value>{new_size}</value>
            </node>
        </nodes>
    </action-request>
</xg-request>
"""

EXPORT_UNEXPORT_LUN_XML = """\
<?xml version="1.0" encoding="utf8"?>
<nodes>
    <node>
        <name>container</name>
        <type>string</type>
        <value>{container}</value>
    </node>
    <node>
        <name>names/{lun_name}</name>
        <type>string</type>
        <value>{lun_name}</value>
    </node>
    <node>
        <name>ports/*</name>
        <type>string</type>
        <value>all</value>
    </node>
    <node>
        <name>lun_id</name>
        <type>int16</type>
        <value>{lun_id}</value>
    </node>
    <node>
        <name>unexport</name>
        <type>bool</type>
        <value>{unexport}</value>
    </node>
</nodes>
"""

EXPORT_UNEXPORT_LUN_SNAPSHOT_XML = """\
<?xml version="1.0" encoding="utf8"?>
<nodes>
    <node>
        <name>container</name>
        <type>string</type>
        <value>{container}</value>
    </node>
    <node>
        <name>lun</name>
        <type>string</type>
        <value>{lun_name}</value>
    </node>
    <node>
        <name>names/{snap_name}</name>
        <type>string</type>
        <value>{snap_name}</value>
    </node>
    <node>
        <name>ports/all</name>
        <type>string</type>
        <value>all</value>
    </node>
    <node>
        <name>lun_id</name>
        <type>string</type>
        <value>{lun_id}</value>
    </node>
    <node>
        <name>unexport</name>
        <type>bool</type>
        <value>{unexport}</value>
    </node>
</nodes>
"""

CREATE_LUN_SNAPHOT_XML = """\
<?xml version="1.0" encoding="utf8"?>
<!-- Response options: Only false -->
<xg-request>
    <action-request>
        <action-name>/vshare/actions/vdm/snapshot/create</action-name>
        <nodes>
            <node>
                <name>container</name>
                <type>string</type>
                <value>{container}</value>
            </node>
            <node>
                <name>lun</name>
                <type>string</type>
                <value>{lun_name}</value>
            </node>
            <node>
                <name>name</name>
                <type>string</type>
                <value>{snap_name}</value>
            </node>
            <node>
                <name>action</name>
                <type>string</type>
                <value>create</value>
            </node>
            <node>
                <name>description</name>
                <type>string</type>
                <value>{desc}</value>
            </node>
            <node>
                <name>readwrite</name>
                <type>bool</type>
                <value>{rw}</value>
            </node>
            <node>
                <name>snap_protect</name>
                <type>bool</type>
                <value>true</value>
            </node>
        </nodes>
    </action-request>
</xg-request>
"""

DELETE_LUN_SNAPHOT_XML = """\
<?xml version="1.0" encoding="utf8"?>
<!-- Response options: Only false -->
<xg-request>
    <action-request>
        <action-name>/vshare/actions/vdm/snapshot/create</action-name>
        <nodes>
            <node>
                <name>container</name>
                <type>string</type>
                <value>{container}</value>
            </node>
            <node>
                <name>lun</name>
                <type>string</type>
                <value>{lun_name}</value>
            </node>
            <node>
                <name>name</name>
                <type>string</type>
                <value>{snap_name}</value>
            </node>
            <node>
                <name>action</name>
                <type>string</type>
                <value>delete</value>
            </node>
        </nodes>
    </action-request>
</xg-request>
"""

COMMIT_CHANGES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<xg-request>
    <action-request>
        <action-name>/mgmtd/db/save</action-name>
    </action-request>
</xg-request>
"""

GET_CONTAINER_STATS_XML = """\
<?xml version="1.0" encoding="utf8"?>
<!-- Response options: Only false -->
<xg-request>
    <query-request>
        <nodes>
            <node>
                <subop>iterate</subop>
                    <flags>
                        <flag>subtree</flag>
                        <flag>include-self</flag>
                    </flags>
                <name>/vshare/state/local/container/{0}/total_bytes</name>
            </node>
            <node>
                <subop>iterate</subop>
                    <flags>
                        <flag>subtree</flag>
                        <flag>include-self</flag>
                    </flags>
                <name>/vshare/state/local/container/{0}/alloc_bytes</name>
            </node>
            <node>
                <subop>iterate</subop>
                    <flags>
                        <flag>subtree</flag>
                        <flag>include-self</flag>
                    </flags>
                <name>/vshare/state/local/container/{0}/num_luns</name>
            </node>
        </nodes>
    </query-request>
</xg-request>
"""
