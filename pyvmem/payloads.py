from __future__ import unicode_literals


CREATE_LUN_XML = """\
<?xml version="1.0" encoding="utf8"?>
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
"""
"""ViolinActionRequest("/vshare/actions/lun/create")"""


DELETE_LUN_XML = """\
<?xml version="1.0" encoding="utf8"?>
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
"""
"""ViolinActionRequest("/vshare/actions/lun/create")"""


RESIZE_LUN_XML = """\
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
        <name>lun_new_size</name>
        <type>string</type>
        <value>{new_size}</value>
    </node>
</nodes>
"""
"""ViolinActionRequest("/vshare/actions/lun/resize")"""


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
"""
"""ViolinActionRequest("/vshare/actions/vdm/snapshot/create")"""


DELETE_LUN_SNAPHOT_XML = """\
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
"""
"""ViolinActionRequest("/vshare/actions/vdm/snapshot/create")"""


COMMIT_CHANGES_XML = """"""
"""ViolinActionRequest("/mgmtd/db/save")"""
